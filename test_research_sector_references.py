import json
import time
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import research_sector_references as refs


AS_OF = '2026-10-31T02:00:00+08:00'


def csi_payload(reference, **changes):
    item = {'indexCode': reference['code'], 'indexNameCnAll': reference['title'],
            'tradeDate': '20261030', 'close': 269.02, 'changePct': -0.17}
    item.update(changes)
    return {'code': '200', 'data': [item]}


class VerifiedReferenceTests(unittest.TestCase):
    def test_verified_references_have_publisher_identity_and_explicit_scope(self):
        self.assertGreaterEqual(len(refs.VERIFIED_REFERENCES), 16)
        for reference in refs.VERIFIED_REFERENCES.values():
            self.assertTrue(reference['official_url'].startswith(('https://www.csindex.com.cn/',
                                                                 'https://www.cnindex.com.cn/')))
            self.assertTrue(reference['scope_note'])
        self.assertEqual(refs.VERIFIED_REFERENCES['sector_ai_application']['code'], '980112')
        self.assertEqual(refs.VERIFIED_REFERENCES['sector_nonbank']['code'], '931479')

    def test_bond_scope_does_not_claim_reinvestment_or_all_long_bonds(self):
        for board_id in ('bond', 'long_bond'):
            self.assertEqual(refs.VERIFIED_REFERENCES[board_id]['asset_type'], 'bond')
            self.assertEqual(refs.VERIFIED_REFERENCES[board_id]['return_type'], 'full_price_with_coupon')
            self.assertIn('派息', refs.VERIFIED_REFERENCES[board_id]['scope_note'])
        self.assertIn('6.5年以上', refs.VERIFIED_REFERENCES['long_bond']['scope_note'])
        self.assertIn('不覆盖所有中长债', refs.VERIFIED_REFERENCES['long_bond']['scope_note'])

    def test_csi_percent_is_not_multiplied_and_future_invalid_prices_excluded(self):
        reference = refs.VERIFIED_REFERENCES['bond']
        first = csi_payload(reference)['data'][0]
        data = {'code': '200', 'data': [dict(first, tradeDate='20261029', close=269.48), first,
            dict(first, tradeDate='20261102', close=300), dict(first, tradeDate='20261028', close=0)]}
        rows = refs.parse_csindex_history(data, reference, AS_OF)
        self.assertEqual([row['date'] for row in rows], ['2026-10-29', '2026-10-30'])
        self.assertEqual(rows[-1]['return_pct'], -0.17)

    def test_csi_rejects_wrong_index_name_or_code(self):
        reference = refs.VERIFIED_REFERENCES['sector_cloud_computing']
        for changes in ({'indexCode': '000300'}, {'indexNameCnAll': '中证人工智能主题指数'}):
            with self.assertRaisesRegex(ValueError, '代码或名称'):
                refs.parse_csindex_history(csi_payload(reference, **changes), reference, AS_OF)

    def test_intraday_run_uses_completed_daily_data_only(self):
        reference = refs.VERIFIED_REFERENCES['bond']
        latest = csi_payload(reference)['data'][0]
        data = {'code': '200', 'data': [dict(latest, tradeDate='20261029'), latest]}
        rows = refs.parse_csindex_history(data, reference, '2026-10-30T14:30:00+08:00')
        self.assertEqual([row['date'] for row in rows], ['2026-10-29'])

    def test_cni_columns_are_named_and_fractional_percent_is_converted(self):
        data = {'code': 200, 'data': {'indexCode': '980112', 'indexName': 'AI应用',
            'item': ['percent', 'close', 'timestamp'],
            'data': [[-0.0511658455, 1171.0662, 1793289600000]]}}
        rows = refs.parse_cnindex_history(data, refs.VERIFIED_REFERENCES['sector_ai_application'], AS_OF)
        self.assertEqual(rows[0]['date'], '2026-10-30')
        self.assertAlmostEqual(rows[0]['return_pct'], -5.11658455)
        self.assertEqual(rows[0]['close'], 1171.0662)

    def test_errors_and_empty_official_data_are_not_zero_market_observations(self):
        reference = refs.VERIFIED_REFERENCES['bond']
        for data in ({'code': '500', 'data': []}, {'code': '200', 'data': []}):
            with self.assertRaises(ValueError):
                refs.parse_csindex_history(data, reference, AS_OF)

    @patch('research_sector_references.fetch_text')
    def test_collection_keeps_date_precision_and_no_invented_breadth(self, fetch):
        reference = refs.VERIFIED_REFERENCES['bond']
        fetch.return_value = json.dumps(csi_payload(reference))
        with patch.object(refs, 'VERIFIED_REFERENCES', {'bond': reference}):
            quotes, sources, histories = refs.collect_verified_references(AS_OF)
        self.assertEqual(quotes[0]['as_of'], '2026-10-30')
        self.assertEqual(quotes[0]['as_of_precision'], 'date')
        self.assertIsNone(quotes[0]['up_count'])
        self.assertEqual(len(histories[quotes[0]['history_secid']]), 1)
        self.assertEqual({s['id'] for s in sources}, {'sector_reference:bond',
                         'sector_history:official:csindex:H11001'})
        self.assertTrue(all(s['status'] == 'partial' for s in sources))

    @patch('research_sector_references.fetch_text', side_effect=OSError('offline'))
    def test_failed_collection_preserves_board_specific_errors(self, fetch):
        quotes, sources, histories = refs.collect_verified_references(AS_OF)
        self.assertEqual(quotes, [])
        self.assertEqual(histories, {})
        self.assertEqual(len(sources), len(refs.VERIFIED_REFERENCES))
        self.assertTrue(all(s['status'] == 'error' and s['board_id'] for s in sources))

    @patch('research_sector_references.fetch_text')
    def test_http_status_remains_visible_in_failed_source(self, fetch):
        error=urllib.error.HTTPError('https://example.test/',403,'private response',{},None)
        fetch.side_effect=error
        _,sources,_=refs.collect_verified_references(AS_OF,board_ids=['bond'])
        self.assertEqual(sources[0]['error'],'HTTP 403：官方指数日线未取得')
        self.assertNotIn('private response',sources[0]['error'])
        error.close()

    def test_budget_rotation_persists_and_later_references_get_a_turn(self):
        references={key:refs.VERIFIED_REFERENCES[key] for key in ['bond','long_bond','short_bond']}
        started=[]
        def slow(board,*_):
            started.append(board)
            time.sleep(.2)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(refs,'CACHE_PATH',Path(folder)/'cache.json'), \
             patch.object(refs,'VERIFIED_REFERENCES',references), \
             patch.object(refs,'MAX_WORKERS',1), \
             patch.object(refs,'_collect_one',side_effect=slow):
            refs.collect_cached_references(AS_OF,budget_seconds=.02)
            self.assertEqual(started,['bond'])
            refs.collect_cached_references(AS_OF,budget_seconds=.02)
            self.assertEqual(started,['bond','long_bond'])
            self.assertEqual(refs.load_record(refs.CACHE_PATH,'collection_cursor')['next_board_id'],'short_bond')

    @patch('research_sector_references._collect_one')
    def test_global_budget_returns_without_waiting_for_slow_provider(self, collect):
        collect.side_effect = lambda *args: time.sleep(0.2)
        start = time.monotonic()
        quotes, sources, histories = refs.collect_verified_references(AS_OF, budget_seconds=0.01)
        self.assertLess(time.monotonic() - start, 0.15)
        self.assertEqual(quotes, [])
        self.assertEqual(histories, {})
        self.assertEqual(len(sources), len(refs.VERIFIED_REFERENCES))
        self.assertTrue(all('预算' in s['error'] for s in sources))


if __name__ == '__main__':
    unittest.main()
