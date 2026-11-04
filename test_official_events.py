"""Offline provenance, body extraction and time-window checks for public events."""
import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import research_official_events as module
from research_data import CHINA


REFERENCE = datetime(2026, 10, 31, 9, 10, tzinfo=CHINA)


def announcement(title='关于重大合同签订的公告', code='600001', when=None, identity='12345'):
    return {'secCode': code, 'secName': '测试股份', 'announcementTitle': title,
            'announcementTime': (when or REFERENCE - timedelta(days=1)).timestamp() * 1000,
            'announcementId': identity, 'adjunctUrl': f'finalpage/2026-10-30/{identity}.PDF'}


def listing(day='20261030'):
    return f'<ul class="u-list"><li><a href="./202610/t{day}_12345.html">促进储能产业发展的通知</a><span>2026-10-30</span></li></ul>'


def article(day='2026-10-30 11:10:00'):
    return f'<meta name="PubDate" content="{day}"><div class="article_con"><p>{"政策正文包含实际执行范围和支持条件。" * 12}</p><div>明确实施时点。</div><script>ignore me</script></div><div>不属于正文的导航</div>'


class OfficialEventTests(unittest.TestCase):
    def setUp(self):
        module._cache.clear()
        self.addCleanup(module._cache.clear)

    def test_company_listing_excludes_funds_routine_old_future_and_unknown_dates(self):
        records = [announcement(), announcement('某基金份额净值公告', '510300'),
                   announcement('关于召开股东大会的通知', identity='2'),
                   announcement('关于召开业绩说明会的公告', identity='3'),
                   announcement(when=REFERENCE + timedelta(minutes=1), identity='4'),
                   announcement(when=REFERENCE - timedelta(days=8), identity='5')]
        rows = module._cninfo_rows({'announcements': records}, REFERENCE, {'600001'})
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['leader_related'])
        self.assertFalse(rows[0]['evidence_complete'])
        self.assertEqual(rows[0]['sector_ids'], [])
        self.assertEqual(rows[0]['stock_codes'], ['600001'])

    def test_disclosure_url_does_not_follow_arbitrary_attachments(self):
        row = announcement()
        row['adjunctUrl'] = 'https://unrelated.example/doc.pdf'
        self.assertEqual(module._cninfo_rows({'announcements': [row]}, REFERENCE, set()), [])

    def test_missing_body_never_claims_evidence_complete(self):
        row = module._cninfo_rows({'announcements': [announcement()]}, REFERENCE, set())[0]
        with patch.object(module, '_read', side_effect=ValueError('not a pdf')):
            result = module._document_evidence(row, 999999)
        self.assertFalse(result['evidence_complete'])
        self.assertEqual(result['summary'], '')
        self.assertIn('不作影响评分', result['content_scope'])

    def test_successful_pdf_excerpt_is_marked_as_excerpt_not_fulltext(self):
        row = module._cninfo_rows({'announcements': [announcement()]}, REFERENCE, set())[0]
        with patch.object(module, '_read', return_value=b'%PDF-sample'), \
                patch.object(module, '_pdf_excerpt', return_value='公告正文' * 100):
            result = module._document_evidence(row, 999999)
        self.assertTrue(result['evidence_complete'])
        self.assertIn('非全文', result['content_scope'])
        self.assertEqual(len(result['body_excerpt']), 400)

    def test_non_pdf_or_image_only_pdf_cannot_be_assessed(self):
        with self.assertRaises(ValueError):
            module._pdf_excerpt(b'<html>not pdf</html>')

    def test_policy_body_uses_only_article_and_actual_metadata_time(self):
        responses = [listing().encode(), article().encode()]
        with patch.object(module, '_read', side_effect=responses):
            result = module._collect_policy('policy_test', '官方政策', module.POLICY_SOURCES[0][2], REFERENCE, 999999)
        row = result['events'][0]
        self.assertTrue(row['evidence_complete'])
        self.assertEqual(row['published_at'], '2026-10-30T11:10:00+08:00')
        self.assertNotIn('导航', row['summary'])
        self.assertNotIn('ignore', row['summary'])
        self.assertEqual(result['sources'][0]['status'], 'ok')

    def test_future_policy_metadata_excludes_whole_event(self):
        with patch.object(module, '_read', side_effect=[listing().encode(), article('2026-11-01 01:00:00').encode()]):
            result = module._collect_policy('policy_test', '官方政策', module.POLICY_SOURCES[0][2], REFERENCE, 999999)
        self.assertEqual(result['events'], [])

    def test_successful_old_listing_is_empty_window_not_source_failure(self):
        with patch.object(module, '_read', return_value=listing('20260820').encode()):
            result = module._collect_policy('policy_test', '官方政策', module.POLICY_SOURCES[0][2], REFERENCE, 999999)
        self.assertEqual(result['events'], [])
        self.assertEqual(result['sources'][0]['status'], 'ok')
        self.assertTrue(result['sources'][0]['empty_window'])
        self.assertEqual(result['warnings'], [])

    def test_failed_source_is_explicit_and_not_successful_empty_window(self):
        with patch.object(module, '_read', side_effect=TimeoutError()):
            result = module._collect_policy('policy_test', '官方政策', module.POLICY_SOURCES[0][2], REFERENCE, 999999)
        self.assertEqual(result['sources'][0]['status'], 'error')
        self.assertFalse(result['sources'][0]['empty_window'])
        self.assertTrue(result['warnings'])

    def test_company_dedup_prioritizes_known_leader_and_limits_documents(self):
        records = [announcement(code='600001', identity=str(index)) for index in range(16)]
        records += [announcement(code='600002', identity='leader')]
        seen = []
        def document(event, deadline):
            seen.append(event['id'])
            return dict(event, evidence_complete=True, summary='正文'*100, body_excerpt='正文'*100)
        with patch.object(module, '_read', return_value=json.dumps({'announcements': records}).encode()), \
                patch.object(module, '_document_evidence', side_effect=document):
            result = module._collect_announcements(REFERENCE, {'600002'}, time.monotonic() + 60)
        self.assertEqual(len(result['events']), 12)
        self.assertEqual(len(set(seen)), 12)
        self.assertIn('cninfo:leader', seen)
        self.assertEqual(result['sources'][0]['listing_count'], 17)

    def test_cache_is_detached_and_does_not_trigger_repeated_source_calls(self):
        empty = {'events': [], 'sources': [{'id': 'sample', 'status': 'ok', 'count': 0}], 'warnings': []}
        with patch.object(module, '_collect_announcements', return_value=empty) as announcements, \
                patch.object(module, '_collect_policy', return_value=empty) as policies:
            first = module.collect_official_events([], as_of=REFERENCE)
            first['sources'].clear()
            second = module.collect_official_events([], as_of=REFERENCE)
        self.assertTrue(second['cache_hit'])
        self.assertEqual(len(second['sources']), 3)
        announcements.assert_called_once()
        self.assertEqual(policies.call_count, 2)

    def test_leader_code_extraction_does_not_infer_from_free_text(self):
        self.assertEqual(module._leader_codes({'sector_a': [{'ts_code': '600001.SH'}, {'code': '300001'}],
                                               'summary': '510300 and 600002 are not authoritative membership'}),
                         {'600001', '300001'})


if __name__ == '__main__':
    unittest.main()
