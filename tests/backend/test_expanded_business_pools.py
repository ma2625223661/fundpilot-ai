"""Expanded evidence keeps company scope and complete market-cap universes."""
import copy
import math
import unittest
from unittest.mock import patch

import research_theme_memberships as theme
from test_research_theme_memberships import workbook

NOW = '2026-10-31T13:30:00+08:00'


class CompleteAllAUniverse(unittest.TestCase):
    def setUp(self):
        self.ref = copy.deepcopy(theme.CNI_REFERENCES['style_microcap'])
        self.ref['minimum_universe_size'] = 3
        self.header = ['日期', '样本代码', '样本简称', '所属行业', '总市值(亿元)']
        self.rows = [self.header,
                     ['2026-09-30', '000987', '越秀资本', '金融', '300'],
                     ['2026-09-30', '600390', '五矿资本', '金融', '200'],
                     ['2026-09-30', '920493', '并行科技', '信息技术', '100']]

    def test_full_snapshot_has_explicit_cap_date_without_creating_a_live_quote(self):
        rows = theme.parse_cni_members(workbook(self.rows), self.ref, NOW)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]['ts_code'], '920493.BJ')
        for row in rows:
            self.assertEqual(row['member_date'], '2026-09-30')
            self.assertEqual(row['membership_market_cap_date'], '2026-09-30')
            self.assertGreater(row['membership_market_cap'], 0)
            self.assertNotIn('quote_time', row)
            self.assertNotIn('total_mv', row)

    def test_truncated_duplicate_invalid_or_mixed_date_universe_is_rejected(self):
        duplicate = copy.deepcopy(self.rows)
        duplicate[-1] = duplicate[-2]
        invalid = copy.deepcopy(self.rows)
        invalid[-1][1] = '00700'
        mixed = copy.deepcopy(self.rows)
        mixed[-1][0] = '2026-10-01'
        old = copy.deepcopy(self.rows)
        old[-1][0] = '2026-01-01'
        for rows in (self.rows[:-1], duplicate, invalid, mixed, old):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                theme.parse_cni_members(workbook(rows), self.ref, NOW)

    def test_missing_or_nonfinite_snapshot_cap_never_becomes_a_zero_or_live_cap(self):
        rows = copy.deepcopy(self.rows)
        for row, value in zip(rows[1:], ('', 'nan', 'inf')):
            row[4] = value
        result = theme.parse_cni_members(workbook(rows), self.ref, NOW)
        self.assertTrue(all('membership_market_cap' not in row for row in result))

    def test_partial_cached_universe_is_refetched(self):
        partial = [{'ts_code': '600390.SH', 'member_date': '2026-09-30'}]
        identity = {'code': 200, 'data': {'indexcode': '399317',
                    'indexfullcname': self.ref['title'], 'indexname': '国证A指'}}
        import json
        detail = {'code': 200, 'total': 3, 'data': {'rows': [{'dateStr': '2026-09-30'}]}}
        with patch('research_public_data._get', return_value=partial), \
             patch('research_public_data._remember', side_effect=lambda key, rows, ttl: rows), \
             patch.object(theme, '_download', side_effect=[json.dumps(identity).encode(), json.dumps(detail).encode(), workbook(self.rows)]) as download:
            rows = theme.fetch_cni_members(self.ref, NOW)
        self.assertEqual(len(rows), 3)
        self.assertEqual(download.call_count, 3)


class ExpandedBusinessScope(unittest.TestCase):
    def test_pcb_additions_do_not_confuse_copper_clad_material_with_board_manufacture(self):
        rows = theme.BUSINESS_EVIDENCE['sector_pcb']
        codes = {row['ts_code'] for row in rows}
        self.assertTrue({'002463.SZ', '603228.SH', '688183.SH', '002436.SZ'} <= codes)
        self.assertNotIn('600183.SH', codes)
        self.assertEqual(len(codes), len(rows))

    def test_new_car_and_finance_pools_require_visible_business_facts(self):
        for sector in ('sector_auto_vehicle', 'sector_diversified_finance'):
            self.assertGreaterEqual(len(theme.BUSINESS_EVIDENCE[sector]), 3)
            for evidence in theme.BUSINESS_EVIDENCE[sector]:
                missing = evidence['required'][-1]
                body = ' '.join(evidence['required'][:-1])
                with self.subTest(code=evidence['ts_code']), self.assertRaises(ValueError):
                    theme.parse_business_evidence(body + '<!--' + missing + '-->', evidence,
                        theme.BUSINESS_REFERENCES[sector], NOW, NOW)

    def test_research_link_does_not_turn_into_verified_theme_income(self):
        evidence = next(row for row in theme.BUSINESS_EVIDENCE['sector_brain_computer']
                        if row['ts_code'] == '002925.SZ')
        row = theme.parse_business_evidence(' '.join(evidence['required']), evidence,
            theme.BUSINESS_REFERENCES['sector_brain_computer'], NOW, NOW)
        self.assertIn('教学研究关联', row['role'])
        self.assertIn('非主题收入', row['role'])
        self.assertEqual(row['published_date'], '2025-06-12')

    def test_copied_resource_business_evidence_is_independent(self):
        original = next(row for row in theme.BUSINESS_EVIDENCE['gold'] if row['ts_code'] == '600988.SH')
        resource = next(row for row in theme.BUSINESS_EVIDENCE['commodities'] if row['ts_code'] == '600988.SH')
        self.assertEqual(resource, original)
        self.assertIsNot(resource, original)
        self.assertIsNot(resource['required'], original['required'])

    def test_new_storage_business_still_requires_current_official_membership(self):
        additions = {'688123.SH', '688525.SH'}
        self.assertTrue(additions <= {row['ts_code'] for row in theme.CNI_BUSINESS_FILTERS['sector_memory_chip']})
        current = [{'ts_code': '688123.SH', 'name': '聚辰股份', 'member_date': '2026-09-30'}]
        def member(evidence, reference, as_of):
            return theme.parse_business_evidence(' '.join(evidence['required']), evidence, reference, as_of, NOW)
        with patch.object(theme, 'fetch_cni_members', return_value=current), \
             patch.object(theme, 'fetch_business_member', side_effect=member), \
             patch('research_public_data._save'):
            result = theme.fetch_theme_memberships([{'id': 'sector_memory_chip'}], NOW)
        rows = result['memberships']['sector_memory_chip'][0]
        self.assertEqual([row['ts_code'] for row in rows], ['688123.SH'])
        self.assertEqual(rows[0]['evidence_type'], 'official_index_business')


if __name__ == '__main__':
    unittest.main()
