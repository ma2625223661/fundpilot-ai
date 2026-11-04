import copy
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from urllib.parse import urlsplit

import research_theme_memberships as theme

NOW = '2026-10-31T10:00:00+08:00'


def workbook(rows):
    data = []
    for number, row in enumerate(rows, 1):
        cells = ''.join('<c r="' + chr(65+i) + str(number) + '" t="inlineStr"><is><t>'
                        + escape(value) + '</t></is></c>' for i, value in enumerate(row))
        data.append('<row r="' + str(number) + '">' + cells + '</row>')
    sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(data) + '</sheetData></worksheet>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('xl/worksheets/sheet1.xml', sheet)
    return output.getvalue()


class PublisherMembers(unittest.TestCase):
    def setUp(self):
        self.ref = theme.CNI_REFERENCES['sector_memory_chip']

    def test_official_identity_requires_code_full_name_and_short_name(self):
        payload = {'code': 200, 'data': {'indexcode': '980138',
                   'indexfullcname': self.ref['title'], 'indexname': '存储芯片'}}
        theme.validate_cni_identity(payload, self.ref)
        for key in ('indexcode', 'indexfullcname', 'indexname'):
            wrong = copy.deepcopy(payload)
            wrong['data'][key] = 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError):
                theme.validate_cni_identity(wrong, self.ref)
        for wrong in (None, [], {'code': 200, 'data': []}):
            with self.assertRaises(ValueError):
                theme.validate_cni_identity(wrong, self.ref)

    def test_dated_mainland_members_and_duplicate_codes(self):
        rows = [['日期', '样本代码', '样本简称'],
                ['2026-09-30', '603986', '兆易创新'],
                ['2026-09-30', '688008', '澜起科技'],
                ['2026-09-30', '301308', '江波龙'],
                ['2026-09-30', '920522', '纳科诺尔'],
                ['2026-09-30', '603986', '兆易创新'],
                ['2026-09-30', '900901', 'B股'],
                ['2026-09-30', '00700', '港股']]
        result = theme.parse_cni_members(workbook(rows), self.ref, NOW)
        self.assertEqual({r['ts_code'] for r in result}, {'603986.SH', '688008.SH', '301308.SZ', '920522.BJ'})
        self.assertTrue(all(r['member_date'] == '2026-09-30' for r in result))

    def test_future_or_stale_members_never_pass(self):
        for day in ('2026-11-01', '2026-09-01'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                theme.parse_cni_members(workbook([['日期', '样本代码', '样本简称'], [day, '603986', '兆易创新']]), self.ref, NOW)

    def test_header_change_fails_closed(self):
        with self.assertRaises(ValueError):
            theme.parse_cni_members(workbook([['日期', '基金代码', '基金名称'], ['2026-10-30', '603986', 'invalid']]), self.ref, NOW)

    def test_current_official_xls_format_is_supported(self):
        content = (Path(__file__).parent / 'test_fixtures/cni-memory-20261030.xls').read_bytes()
        rows = theme.parse_cni_members(content, self.ref, NOW)
        self.assertEqual(len(rows), 42)
        self.assertEqual(rows[0]['ts_code'], '688008.SH')
        self.assertTrue(all(row['member_date'] == '2026-10-30' for row in rows))
        self.assertIn('603986.SH', {row['ts_code'] for row in rows})

    def test_non_workbook_response_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, '未返回有效 Excel 工作簿'):
            theme.parse_cni_members('暂无数据'.encode(), self.ref, NOW)

    def test_download_uses_verified_latest_month_across_month_boundary(self):
        identity = {'code': 200, 'data': {'indexcode': self.ref['code'],
                    'indexfullcname': self.ref['title'], 'indexname': '存储芯片'}}
        detail = {'code': 200, 'total': 2, 'data': {'rows': [
            {'dateStr': '2026-10-30', 'seccode': '603986', 'secname': '兆易创新'}]}}
        file = workbook([['日期', '样本代码', '样本简称'],
                         ['2026-10-30', '603986', '兆易创新'],
                         ['2026-10-30', '688008', '澜起科技']])
        with patch('research_public_data._get', return_value=None), \
             patch('research_public_data._remember', side_effect=lambda key, rows, ttl: rows), \
             patch.object(theme, '_download', side_effect=[json.dumps(identity).encode(), json.dumps(detail).encode(), file]) as download:
            rows = theme.fetch_cni_members(self.ref, '2026-11-01T03:00:00+08:00')
        self.assertEqual(len(rows), 2)
        self.assertIn('dateStr=2026-11', download.call_args_list[1].args[0])
        self.assertIn('dateStr=2026-10', download.call_args_list[2].args[0])
        self.assertIn('/sample-detail/download?', rows[0]['source_url'])

    def test_snapshot_details_future_mixed_stale_or_truncated_are_rejected(self):
        for payload in (
            {'code': 200, 'total': 1, 'data': {'rows': []}},
            {'code': 200, 'total': 1, 'data': {'rows': [{'dateStr': '2026-11-01'}]}},
            {'code': 200, 'total': 1, 'data': {'rows': [{'dateStr': '2026-09-01'}]}},
            {'code': 200, 'total': 2, 'data': {'rows': [{'dateStr': '2026-10-30'}, {'dateStr': '2026-10-29'}]}},
            {'code': 200, 'total': '42', 'data': {'rows': [{'dateStr': '2026-10-30'}]}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                theme.cni_sample_snapshot(payload, self.ref, NOW)

    def test_workbook_must_match_details_count_and_snapshot_date(self):
        identity = {'code': 200, 'data': {'indexcode': self.ref['code'],
                    'indexfullcname': self.ref['title'], 'indexname': '存储芯片'}}
        for total, day in ((2, '2026-10-30'), (1, '2026-10-29')):
            detail = {'code': 200, 'total': total, 'data': {'rows': [{'dateStr': '2026-10-30'}]}}
            file = workbook([['日期', '样本代码', '样本简称'], [day, '603986', '兆易创新']])
            with self.subTest(total=total, day=day), patch('research_public_data._get', return_value=None), \
                 patch('research_public_data._remember') as remember, \
                 patch.object(theme, '_download', side_effect=[json.dumps(identity).encode(), json.dumps(detail).encode(), file]):
                with self.assertRaisesRegex(ValueError, '数量或日期不一致'):
                    theme.fetch_cni_members(self.ref, NOW)
                remember.assert_not_called()

    def test_only_requested_csi_memberships_returned_and_no_alias_mutation(self):
        refs = theme.membership_references([{'id': 'sector_commercial_aerospace'}])
        refs['sector_commercial_aerospace']['aliases'].append('changed')
        self.assertNotIn('changed', theme.CSI_REFERENCES['sector_commercial_aerospace']['aliases'])
        self.assertEqual(theme.membership_references([{'id': 'sector_memory_chip'}]), {})


class BusinessEvidence(unittest.TestCase):
    def setUp(self):
        self.evidence = theme.BUSINESS_EVIDENCE['sector_nuclear_fusion'][0]
        self.ref = theme.BUSINESS_REFERENCES['sector_nuclear_fusion']
        self.body = '<html><body>' + ' '.join(self.evidence['required']) + '</body></html>'

    def test_observation_and_publication_are_separate(self):
        row = theme.parse_business_evidence(self.body, self.evidence, self.ref, NOW, NOW)
        self.assertEqual(row['member_date'], '2026-10-31')
        self.assertEqual(row['published_date'], '2026-04-23')
        self.assertEqual(row['evidence_type'], 'public_business')
        self.assertIn('有限样本池', row['role'])

    def test_missing_fact_or_script_only_fact_does_not_qualify(self):
        body = self.body.replace('主机线圈', '<script>主机线圈</script>')
        with self.assertRaises(ValueError):
            theme.parse_business_evidence(body, self.evidence, self.ref, NOW, NOW)

    def test_future_publication_or_observation_rejected(self):
        evidence = {**self.evidence, 'published_date': '2026-11-01'}
        with self.assertRaises(ValueError):
            theme.parse_business_evidence(self.body, evidence, self.ref, NOW, NOW)
        with self.assertRaises(ValueError):
            theme.parse_business_evidence(self.body, self.evidence, self.ref, NOW, '2026-11-01T10:00:00+08:00')

    def test_no_publication_date_stays_unknown(self):
        evidence = {**self.evidence, 'published_date': None}
        row = theme.parse_business_evidence(self.body, evidence, self.ref, NOW, NOW)
        self.assertIsNone(row['published_date'])

    def test_memory_requires_both_current_index_membership_and_product_facts(self):
        raw = [{'ts_code': '603986.SH', 'name': '兆易创新', 'member_date': '2026-09-30',
                'index_name': '国证存储芯片产业指数', 'index_code': '980138'},
               {'ts_code': '002371.SZ', 'name': '北方华创', 'member_date': '2026-09-30',
                'index_name': '国证存储芯片产业指数', 'index_code': '980138'}]
        def business(evidence, reference, as_of):
            text = ' '.join(evidence['required'])
            return theme.parse_business_evidence(text, evidence, reference, as_of, NOW)
        with patch.object(theme, 'fetch_cni_members', return_value=raw), \
             patch.object(theme, 'fetch_business_member', side_effect=business), \
             patch('research_public_data._save'):
            result = theme.fetch_theme_memberships([{'id': 'sector_memory_chip'}], NOW)
        rows = result['memberships']['sector_memory_chip'][0]
        self.assertEqual([r['ts_code'] for r in rows], ['603986.SH'])
        self.assertEqual(rows[0]['member_date'], '2026-09-30')
        self.assertEqual(rows[0]['evidence_type'], 'official_index_business')
        self.assertEqual(len(rows[0]['source_ids']), 2)

    def test_cctc_public_catalog_requires_exact_product_identity(self):
        evidence = theme.BUSINESS_EVIDENCE['sector_mlcc'][1]
        ref = theme.BUSINESS_REFERENCES['sector_mlcc']
        payload = [{'id': 46, 'name': '多层片式陶瓷电容器',
                    'nameEn': 'Multilayer Ceramic Chip Capacitor', 'brief': 'MLCC'}]
        row = theme.parse_business_evidence(json.dumps(payload, ensure_ascii=False), evidence, ref, NOW, NOW)
        self.assertEqual(row['ts_code'], '300408.SZ')
        payload[0]['id'] = 48
        with self.assertRaises(ValueError):
            theme.parse_business_evidence(json.dumps(payload, ensure_ascii=False), evidence, ref, NOW, NOW)

    def test_each_additional_direction_has_two_specific_public_facts(self):
        for identity in ('sector_cpo', 'sector_pcb', 'sector_mlcc', 'sector_compute_leasing', 'sector_rare_earth_magnet'):
            evidence = theme.BUSINESS_EVIDENCE[identity]
            self.assertGreaterEqual(len(evidence), 2)
            self.assertEqual(len({row['ts_code'] for row in evidence}), len(evidence))
            for row in evidence:
                source = urlsplit(row['url'])
                self.assertIn(source.scheme, ('http', 'https'))
                self.assertTrue(source.hostname)
                if source.scheme == 'http':
                    self.assertIn(source.hostname, {'www.torch.cn', 'www.atmcn.com', 'www.bohaileasing.com'})
                self.assertGreaterEqual(len(row['required']), 3)


if __name__ == '__main__':
    unittest.main()
