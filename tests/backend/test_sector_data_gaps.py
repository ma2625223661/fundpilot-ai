"""Data failures must remain distinguishable from absent reference mappings."""
import unittest
from unittest.mock import patch

import research_sectors as sectors
from test_research_sectors import history


AS_OF = '2026-10-31T02:00:00+08:00'


class SectorDataGapTests(unittest.TestCase):
    def analyze(self, identity, sources=(), quote=None, history=()):
        return sectors.analyze_sector({'id': identity, 'title': identity}, quote,
            list(history), list(sources), [], AS_OF, {'mode': 'risk_on'})

    def test_catalog_failure_is_attached_to_a_mapped_sector(self):
        source = {'id': 'sector_quotes_concept', 'status': 'error',
                  'error': 'connection closed', 'fetched_at': AS_OF}
        row = self.analyze('sector_brain_computer', [source])
        self.assertEqual(row['data_gaps'][0]['code'], 'quote_source_failed')
        self.assertEqual(row['sources'], [source])
        self.assertIn('脑机接口', row['reference_expected'])
        self.assertIsNone(row['score'])
        self.assertEqual(row['severity'], 'normal')

    def test_unmapped_sector_is_not_misreported_as_source_failure(self):
        row = self.analyze('sector_test_unmapped', [
            {'id': 'sector_quotes_industry', 'status': 'error'}])
        self.assertEqual(row['data_gaps'][0]['code'], 'quote_mapping_missing')
        self.assertEqual(row['sources'], [])

    def test_supported_source_without_a_quote_has_its_own_reason(self):
        row = self.analyze('sector_brain_computer', [
            {'id': 'sector_quotes_concept', 'status': 'ok', 'count': 20}])
        self.assertEqual(row['data_gaps'][0]['code'], 'quote_not_returned')

    def test_unconnected_asset_does_not_blame_the_stock_catalog(self):
        for identity in ('money',):
            with self.subTest(identity=identity):
                row = self.analyze(identity, [{'id': 'sector_quotes_industry', 'status': 'error'}])
                self.assertEqual(row['data_gaps'][0]['code'], 'asset_source_missing')
                self.assertFalse(row['sources'])
                self.assertIsNone(row['recommendation_index'])

    def test_resource_equity_failure_does_not_request_commodity_prices(self):
        source = {'id': 'public:business:601899.SH:commodities', 'status': 'error', 'error': 'timeout'}
        row = self.analyze('commodities', [source])
        self.assertEqual(row['data_gaps'][0]['code'], 'company_evidence_unavailable')
        self.assertEqual(row['sources'], [source])
        self.assertIn('资源企业股票', row['reference_expected'])
        self.assertNotIn('专属资产行情', row['data_status_summary'])
        self.assertIsNone(row['recommendation_index'])

    def test_quote_failure_and_history_failure_are_distinct(self):
        quote = {'code': 'TEST', 'name': 'test index', 'change_pct': 0,
                 'as_of': '2026-10-30T15:00:00+08:00',
                 'source_id': 'quote', 'history_secid': 'test'}
        sources = [{'id': 'quote', 'status': 'ok'},
                   {'id': 'sector_history:test', 'status': 'error'}]
        row = self.analyze('sector_test', sources, quote)
        self.assertEqual(row['data_gaps'][0]['code'], 'history_source_failed')
        self.assertEqual(row['change_pct'], 0)
        self.assertIsNone(row['recommendation_index'])
        self.assertIn('quote', {s['id'] for s in row['sources']})
        stale = self.analyze('sector_test', sources, dict(quote, as_of='2026-10-01T15:00:00+08:00'))
        self.assertEqual(stale['data_gaps'][0]['code'], 'quote_stale')
        self.assertIsNone(stale['recommendation_index'])

    def test_bond_reference_keeps_real_returns_without_using_stock_scores(self):
        quote = {'code': 'H11001', 'name': '中证全债指数', 'change_pct': .02,
                 'as_of': '2026-10-30', 'source_id': 'official_bond',
                 'history_secid': 'official:bond', 'asset_type': 'bond',
                 'return_type': 'full_price_with_coupon', 'scope_note': '含应计利息及派息'}
        row = self.analyze('bond', [{'id': 'official_bond', 'status': 'ok'}], quote, history())
        self.assertEqual(row['change_pct'], .02)
        self.assertTrue(row['history_complete'])
        self.assertIsInstance(row['recommendation_index'], int)
        self.assertEqual(row['score_model'], 'bond_trend_v1')
        self.assertFalse(any(g['code'] == 'score_model_unavailable' for g in row['data_gaps']))
        self.assertIn('含息及派息', row['summary'])
        self.assertEqual(row['severity'], 'normal')
        self.assertEqual(row['signal'], 'trend_excellent')
        self.assertTrue(any('利息再投资系列' in text for text in row['risks']))

    def test_official_reference_fallback_checks_identity(self):
        identity = 'sector_cloud_computing'
        reference = sectors.VERIFIED_REFERENCES[identity]
        catalog = [{'id': identity, 'title': '云计算'}]
        quote = {'board_id': identity, 'code': reference['code'], 'name': reference['name'],
                 'source_id': 'sector_reference:' + identity}
        self.assertEqual(sectors.match_sector_quotes(catalog, [], [], [quote])[identity], dict(quote, asset_type='equity_index'))
        for invalid in (dict(quote, code='000000'), dict(quote, name='其他方向'),
                        dict(quote, source_id='unverified')):
            self.assertEqual(sectors.match_sector_quotes(catalog, [], [], [invalid]), {})

    def test_official_history_is_reused_without_a_second_provider_request(self):
        identity = 'sector_cloud_computing'
        reference = sectors.VERIFIED_REFERENCES[identity]
        history_id = 'official:csindex:' + reference['code']
        quote = {'board_id': identity, 'code': reference['code'], 'name': reference['name'],
                 'source_id': 'sector_reference:' + identity, 'history_secid': history_id,
                 'as_of': '2026-10-30', 'change_pct': 1.0}
        source = {'id': quote['source_id'], 'status': 'ok', 'as_of': '2026-10-30'}
        snapshot = {'market': [], 'news': [], 'sources': [], 'warnings': []}
        with patch.object(sectors, 'collect_verified_references', return_value=([quote], [source], {history_id: history()})), \
             patch('research_overseas.collect_overseas_references', return_value=([], [], {})), \
             patch('research_reference_fallbacks.collect_money_reference', return_value=([], [], {})), \
             patch.object(sectors, 'collect_sector_market', return_value=snapshot), \
             patch.object(sectors, 'collect_sector_quotes', return_value=([], [])), \
             patch.object(sectors, 'collect_macro_risk', return_value=({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'})), \
             patch.object(sectors, 'fetch_text', return_value=''), \
             patch.object(sectors, 'now_iso', return_value=AS_OF), \
             patch.object(sectors, 'collect_sector_histories', return_value=({}, [])) as collect:
            report = sectors.run_sector_research()
        self.assertNotIn(identity, collect.call_args.args[0])
        row = next(row for row in report['sector_analysis'] if row['id'] == identity)
        self.assertEqual(row['metrics']['sample_count'], 80)
        self.assertIsNone(row['recommendation_index'])
        self.assertEqual(row['requirements'][0]['status'], 'partial')
        self.assertIn(source, row['sources'])

    def test_daily_reference_freshness_respects_weekends_and_holidays(self):
        quote = {'as_of': '2026-10-30', 'as_of_precision': 'date', 'data_frequency': 'daily'}
        self.assertTrue(sectors._quote_fresh(quote, '2026-11-02T14:30:00+08:00'))
        self.assertFalse(sectors._quote_fresh(quote, '2026-11-02T15:30:00+08:00'))
        holiday_quote = dict(quote, as_of='2026-09-30')
        self.assertTrue(sectors._quote_fresh(holiday_quote, '2026-10-08T09:10:00+08:00'))
        self.assertFalse(sectors._quote_fresh(holiday_quote, '2026-10-08T16:00:00+08:00'))
        self.assertFalse(sectors._quote_fresh(dict(quote, as_of='2027-01-04'), '2027-01-05T09:10:00+08:00'))

    def test_hk_reference_and_cross_market_reference_use_native_sessions(self):
        hk = {'reference_market_daily': True, 'market':'HK', 'currency':'HKD',
              'score_scope':'reference_trend', 'trade_date':'2026-10-16', 'as_of':'2026-10-16'}
        # Oct 19 is a HK holiday and an ordinary mainland session.
        now='2026-10-19T17:00:00+08:00'
        self.assertTrue(sectors._quote_fresh(hk,now))
        self.assertTrue(sectors._history_fresh([{'date':'2026-10-16'}],hk,now))
        cross=dict(hk,market='CN_HK',currency='CNY',trade_date='2026-10-19',as_of='2026-10-19')
        self.assertTrue(sectors._quote_fresh(cross,now))
        self.assertFalse(sectors._history_fresh([{'date':'2026-10-16'}],cross,now))
        self.assertFalse(sectors._quote_fresh(dict(cross,currency='HKD'),now))
        # HK-only sessions during the mainland national holiday also count.
        cross.update(trade_date='2026-10-08',as_of='2026-10-08')
        self.assertTrue(sectors._quote_fresh(cross,'2026-10-08T16:30:00+08:00'))
        self.assertFalse(sectors._quote_fresh(cross,'2026-10-08T16:00:00+08:00'))


if __name__ == '__main__':
    unittest.main()
