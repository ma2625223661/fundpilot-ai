import unittest.mock
import copy
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import research_sectors as sectors


AS_OF = '2026-10-30T18:00:00+08:00'


def quote(**changes):
    return {'code': 'BKTEST', 'name': '白酒', 'change_pct': 2.0, 'last': 1000,
            'up_count': 8, 'down_count': 2, 'as_of': '2026-10-30T15:00:00+08:00',
            'source_id': 'sector_quotes_concept', 'source_url': 'https://example.com/sector',
            'history_secid': '90.BKTEST', **changes}


def history():
    end = datetime(2026, 10, 30)
    days = []
    while len(days) < 80:
        if end.weekday() < 5:
            days.append(end.date().isoformat())
        end -= timedelta(days=1)
    return [{'date': day, 'close': 100 + index * .3, 'return_pct': .3}
            for index, day in enumerate(reversed(days))]


class SectorResearchTests(unittest.TestCase):
    def setUp(self):
        from test_helpers.isolated_public_cache import isolate_public_cache
        isolate_public_cache(self)

    def test_catalog_has_no_product_types_or_portfolio_queue(self):
        catalog = sectors.sector_catalog()
        ids = {row['id'] for row in catalog}
        for identity in ('holdings_unclassified', 'unclassified', 'equity_active',
                         'equity_index', 'overseas_mixed', 'fixed_income_plus'):
            self.assertNotIn(identity, ids)
        self.assertTrue(all(not row['id'].endswith('_mixed') for row in catalog))
        self.assertTrue(all('基金' not in row['title'] and '持仓' not in row['description'] for row in catalog))
        self.assertEqual(next(row['title'] for row in catalog if row['id'] == 'money'), '货币市场')

    def test_quote_parser_keeps_real_breadth_and_timestamp(self):
        rows = sectors.parse_sector_quotes({'data': {'diff': [
            {'f12': 'BK1234', 'f14': '白酒', 'f2': 1000.5, 'f3': 2.3,
             'f104': 8, 'f105': 2, 'f124': 1793343600},
            {'f12': '000001', 'f14': '非板块'}]}}, 'sector_quotes_concept')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['up_count'], 8)
        self.assertEqual(rows[0]['down_count'], 2)
        self.assertEqual(rows[0]['change_pct'], 2.3)
        self.assertTrue(rows[0]['as_of'].startswith('2026-10-30'))

    def test_explicit_alias_mapping_does_not_substitute_nearby_sector(self):
        catalog = [{'id': 'sector_cpo', 'title': 'CPO'}, {'id': 'sector_liquor', 'title': '白酒'}]
        matched = sectors.match_sector_quotes(catalog, [quote(name='通信')], [])
        self.assertEqual(matched, {})
        matched = sectors.match_sector_quotes(catalog, [quote(name='白酒Ⅲ')], [])
        self.assertEqual(set(matched), {'sector_liquor'})

    def test_verified_direct_sector_index_is_available_when_catalog_is_down(self):
        catalog = [{'id': 'sector_liquor', 'title': '白酒'}]
        direct = quote(code='sz399997', name='中证白酒', source_id='sector_indices_tencent')
        matched = sectors.match_sector_quotes(catalog, [], [direct])
        self.assertEqual(matched['sector_liquor']['code'], 'sz399997')
        self.assertEqual(matched['sector_liquor']['history_secid'], 'tencent:sz399997')
        self.assertEqual(sectors.match_sector_quotes(catalog, [], [dict(direct, name='其他指数')]), {})

    def test_tencent_direct_history_preserves_index_prices_and_rejects_future(self):
        payload = {'data': {'sz399997': {'day': [
            ['2026-10-29', '100', '101', '102', '99', '10'],
            ['2026-10-30', '101', '103', '104', '100', '10'],
            ['2026-10-31', '103', '109', '110', '100', '10']]}}}
        rows = sectors.parse_tencent_history(payload, 'sz399997', AS_OF)
        self.assertEqual([row['date'] for row in rows], ['2026-10-29', '2026-10-30'])
        self.assertEqual(rows[-1]['close'], 103)
        self.assertAlmostEqual(rows[-1]['return_pct'], (103 / 101 - 1) * 100)
        self.assertIn('web.ifzq.gtimg.cn', sectors._history_url('tencent:sz399997'))

    def test_missing_sector_has_unknown_score_and_no_proxy_quote(self):
        row = sectors.analyze_sector({'id': 'sector_cpo', 'title': 'CPO'}, None, [], [], [], AS_OF, {'mode': 'risk_on'})
        self.assertEqual(row['status'], 'missing')
        self.assertIsNone(row['score'])
        self.assertIsNone(row['recommendation_index'])
        self.assertIsNone(row['quote'])

    def test_stale_and_future_quotes_are_not_scored(self):
        for stamp in ('2026-10-20T15:00:00+08:00', '2026-10-31T15:00:00+08:00', None):
            row = sectors.analyze_sector({'id': 'sector_liquor', 'title': '白酒'}, quote(as_of=stamp), history(), [], [], AS_OF, {'mode': 'risk_on'})
            self.assertEqual(row['status'], 'stale')
            self.assertIsNone(row['recommendation_index'])

    def test_direct_day_quote_is_partial_and_has_no_composite_score_without_history(self):
        row = sectors.analyze_sector({'id': 'sector_liquor', 'title': '白酒'}, quote(change_pct=10), [], [], [], AS_OF, {'mode': 'risk_on'})
        self.assertEqual(row['status'], 'partial')
        self.assertIsNone(row['recommendation_index'])
        self.assertIsNone(row['score'])
        self.assertIn('暂不评分', row['summary'])
        self.assertEqual(row['breadth_up_ratio'], 80)
        self.assertIsNone(row['metrics']['return_20d'])

    def test_historical_metrics_are_prices_and_market_risk_is_independent(self):
        source = {'id': 'sector_quotes_concept', 'status': 'ok'}
        row = sectors.analyze_sector({'id': 'sector_liquor', 'title': '白酒'}, quote(), history(), [source], [], AS_OF,
                                     {'mode': 'defensive', 'label': '防御优先'})
        self.assertEqual(row['status'], 'ok')
        self.assertEqual(row['recommendation_index'], row['score'])
        self.assertGreater(row['recommendation_index'], 39)
        self.assertEqual(row['metrics']['sample_count'], 80)
        self.assertGreater(row['metrics']['return_20d'], 0)
        self.assertEqual(row['sources'], [source])

    def test_history_parser_excludes_future_dates_and_invalid_close(self):
        rows = sectors.parse_sector_history({'data': {'klines': [
            '2026-10-29,100,101,102,99,1,1,1,1,1,1',
            '2026-10-30,100,0,102,99,1,1,1,1,1,1',
            '2026-10-31,100,103,104,99,1,1,1,1,1,1']}}, AS_OF)
        self.assertEqual(rows, [{'date': '2026-10-29', 'close': 101.0, 'return_pct': 1.0}])

    def test_missing_data_and_defensive_market_do_not_invent_critical_risk(self):
        missing = sectors.analyze_sector({'id': 'test', 'title': '测试'}, None, [], [], [], AS_OF, {'mode': 'unknown'})
        defensive = sectors.analyze_sector({'id': 'test', 'title': '测试'}, quote(), history(), [], [], AS_OF, {'mode': 'defensive'})
        self.assertEqual((missing['severity'], missing['signal']), ('normal', 'neutral'))
        self.assertEqual((defensive['severity'], defensive['signal']), ('normal', 'neutral'))

    def test_severe_daily_drop_is_critical_but_stale_quote_cannot_signal(self):
        row = sectors.analyze_sector({'id': 'test', 'title': '测试'}, quote(change_pct=-5), history(), [], [], AS_OF, {'mode': 'risk_on'})
        self.assertEqual(row['severity'], 'critical')
        self.assertEqual(row['signal'], 'neutral')
        stale = sectors.analyze_sector({'id': 'test', 'title': '测试'}, quote(change_pct=-8, as_of='2026-10-01T15:00:00+08:00'), history(), [], [], AS_OF, {'mode': 'risk_on'})
        self.assertEqual(stale['severity'], 'normal')

    def test_excellent_trend_requires_complete_history_and_positive_momentum(self):
        row = sectors.analyze_sector({'id': 'test', 'title': '测试'}, quote(change_pct=3), history(), [], [], AS_OF, {'mode': 'risk_on'})
        self.assertGreaterEqual(row['recommendation_index'], 75)
        self.assertEqual(row['signal'], 'trend_excellent')
        partial = sectors.analyze_sector({'id': 'test', 'title': '测试'}, quote(change_pct=3), [], [], [], AS_OF, {'mode': 'risk_on'})
        self.assertEqual(partial['signal'], 'neutral')

    @patch('research_sectors.fetch_policy', return_value=[])
    @patch('research_sectors.fetch_text')
    def test_common_collection_never_calls_product_data(self, fetch, policy):
        def answer(url, encoding='utf-8-sig'):
            if url == sectors.MARKET_URL:
                return 'v_sh000001="1~上证指数~000001~3500~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~20261030150000~-1~-1";'
            return json.dumps({'result': {'data': []}})
        fetch.side_effect = answer
        snapshot = sectors.collect_sector_market()
        self.assertNotIn('funds', snapshot)
        self.assertEqual({row['id'] for row in snapshot['sources']}, {'market_tencent', 'policy_csrc'})
        self.assertTrue(all('sina' not in call.args[0] for call in fetch.call_args_list))
        for call in fetch.call_args_list:
            self.assertNotIn('fund.', call.args[0])
            self.assertNotIn('pingzhong', call.args[0])

    @patch('research_sectors.collect_sector_histories', return_value=({}, []))
    @patch('research_overseas.collect_overseas_references', lambda *_: ([], [], {}))
    @patch('research_reference_fallbacks.collect_money_reference', lambda *_: ([], [], {}))
    @patch('research_sectors.collect_macro_risk', lambda *_: ({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'}))
    @patch('research_sectors.collect_long_wave_evidence', lambda *_: ({}, []))
    @patch('research_sectors.collect_verified_references', lambda *_: ([], [], {}))
    @patch('research_sectors.fetch_text', return_value='')
    @patch('research_sectors.collect_sector_quotes', return_value=([], []))
    @patch('research_sectors.collect_sector_market')
    def test_complete_report_has_only_sector_scope(self, common, quotes, fetch, histories):
        common.return_value = {'as_of': AS_OF, 'market': [], 'news': [], 'sources': [], 'warnings': []}
        report = sectors.run_sector_research()
        self.assertEqual(report['research_scope'], 'sectors')
        for key in ('funds', 'quant', 'sections', 'holdings_index', 'candidate_references', 'universe'):
            self.assertNotIn(key, report)
        self.assertNotIn('funds', report['snapshot'])
        self.assertNotIn('funds', report['analysis'])
        self.assertTrue(report['sector_analysis'])
        self.assertTrue(all(row['recommendation_index'] is None for row in report['sector_analysis']))

    def test_reference_index_requires_all_declared_data_including_company_financials(self):
        board = {'id': 'sector_ai_application', 'title': 'AI应用', 'group': 'industry'}
        valid = {'ts_code': '600000.SH', 'financials': {
            'ann_date': '2026-10-29', 'end_date': '2026-09-30', 'tr_yoy': 10}, 'source_ids': []}
        for leaders, ready in (([], False), ([dict(valid, financials=None)], False),
                               ([dict(valid, financials={'ann_date': '2026-11-01', 'end_date': '2026-09-30', 'tr_yoy': 10})], False),
                               ([valid], True)):
            with self.subTest(leaders=leaders), \
                 patch.object(sectors, 'now_iso', return_value=AS_OF), \
                 patch.object(sectors, 'sector_catalog', return_value=[board]), \
                 patch.object(sectors, 'collect_sector_market', return_value={'market': [], 'news': [], 'sources': [], 'warnings': []}), \
                 patch.object(sectors, 'collect_sector_quotes', return_value=([], [])), \
                 patch.object(sectors, 'collect_verified_references', return_value=([], [], {})), \
                 patch.object(sectors, 'collect_macro_risk', return_value=({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'})), \
                 patch.object(sectors, 'collect_long_wave_evidence', return_value=({}, [])), \
             patch.object(sectors, 'fetch_text', return_value=''), \
                 patch.object(sectors, 'match_sector_quotes', return_value={board['id']: quote()}), \
                 patch.object(sectors, 'collect_sector_histories', return_value=({'90.BKTEST': history()}, [])), \
                 patch('research_tushare.gather_sector_company_evidence', return_value={'sector_leaders': {board['id']: leaders}, 'sources': [], 'warnings': []}), \
                 patch('research_leader_index.collect_leader_histories'), \
                 patch('research_leader_index.build_indicator', return_value=None):
                report = sectors.run_sector_research()
            row = report['sector_analysis'][0]
            self.assertEqual(all(r['status'] == 'ok' for r in row['requirements']), ready)
            self.assertEqual(row['recommendation_index'] is not None, ready)
            self.assertEqual(report['coverage']['scored_sector_count'], int(ready))
            self.assertEqual(report['coverage']['fully_ready_sector_count'], int(ready))
            if not ready:
                self.assertIsNone(row['score'])
                self.assertEqual(row['status'], 'partial')
                self.assertIn('score_requirements_unmet', [g['code'] for g in row['data_gaps']])

    def test_composite_gate_requires_each_named_requirement_and_preserves_real_parts(self):
        for blocked in ('data', 'mapping', 'model'):
            row = {'status': 'ok', 'score': 85, 'recommendation_index': 85, 'technical_score': 80,
                   'score_components': {'base': 50}, 'signal': 'trend_excellent', 'trend': '趋势偏强',
                   'requirements': [{'id': key, 'label': key, 'status': 'partial' if key == blocked else 'ok'}
                                    for key in ('data', 'mapping', 'model')]}
            self.assertFalse(sectors.enforce_score_requirements(row))
            self.assertIsNone(row['score'])
            self.assertIsNone(row['recommendation_index'])
            self.assertEqual(row['signal'], 'neutral')
            self.assertEqual(row['technical_score'], 80)
            self.assertEqual(row['score_components'], {'base': 50})

    def test_failed_public_membership_source_is_visible_without_selected_companies(self):
        catalog = [
            {'id': 'sector_memory_chip', 'title': '存储芯片', 'group': 'industry'},
            {'id': 'style_microcap', 'title': '微盘股', 'group': 'style'},
            {'id': 'sector_unrelated', 'title': '其他板块', 'group': 'industry'},
        ]
        failures = [{'id': 'public:members:' + board['id'], 'status': 'error',
                     'name': board['title'] + '官方成分', 'error': '成分下载返回非工作簿内容',
                     'url': 'https://www.cnindex.com.cn/sample-detail/download'}
                    for board in catalog[:2]]
        with patch.object(sectors, 'now_iso', return_value=AS_OF), \
             patch.object(sectors, 'sector_catalog', return_value=catalog), \
             patch.object(sectors, 'collect_sector_market', return_value={'market': [], 'news': [], 'sources': [], 'warnings': []}), \
             patch.object(sectors, 'collect_sector_quotes', return_value=([], [])), \
             patch.object(sectors, 'collect_verified_references', return_value=([], [], {})), \
             patch.object(sectors, 'collect_macro_risk', return_value=({'status': 'unavailable', 'risk_score': None}, {'id': 'macro:nbs_pmi', 'status': 'error'})), \
             patch.object(sectors, 'collect_long_wave_evidence', return_value=({}, [])), \
             patch.object(sectors, 'fetch_text', return_value=''), \
             patch.object(sectors, 'collect_sector_histories', return_value=({}, [])), \
             patch('research_tushare.gather_sector_company_evidence', return_value={'sector_leaders': {}, 'sources': failures, 'warnings': []}), \
             patch('research_leader_index.collect_leader_histories'), \
             patch('research_leader_index.build_indicator', return_value=None):
            report = sectors.run_sector_research()
        for board, row in zip(catalog, report['sector_analysis']):
            with self.subTest(board=board['id']):
                gaps = [gap for gap in row['data_gaps'] if gap['code'] == 'company_membership_unavailable']
                own_sources = [source for source in row['sources'] if source['id'].startswith('public:members:')]
                if board['id'] == 'sector_unrelated':
                    self.assertEqual(gaps, [])
                    self.assertEqual(own_sources, [])
                else:
                    self.assertEqual(len(gaps), 1)
                    self.assertEqual(gaps[0]['source_ids'], ['public:members:' + board['id']])
                    self.assertEqual([source['id'] for source in own_sources], gaps[0]['source_ids'])
                    self.assertEqual(own_sources[0]['error'], '成分下载返回非工作簿内容')
                self.assertIsNone(row['recommendation_index'])
                self.assertIsNone(row['quote'])


class IndexHistoryTests(unittest.TestCase):
    """Daily closes for the four market index cards (small trend lines)."""

    def market(self):
        return {'market': [
            {'code': 'sh000001', 'name': '上证指数', 'last': 3900, 'as_of': '2026-11-04T15:00:00+08:00'},
            {'code': 'sz399006', 'name': '创业板指', 'last': 2500, 'as_of': '2026-11-04T15:00:00+08:00'},
            {'code': 'hkHSI', 'name': '恒生指数', 'last': 26000, 'as_of': '2026-11-04T16:00:00+08:00'}]}

    def test_requests_cover_only_the_four_a_share_indices_on_the_tencent_day_line(self):
        requests = sectors.index_history_requests(self.market())
        self.assertEqual(sorted(requests), ['market:sh000001', 'market:sz399006'])
        self.assertEqual(requests['market:sh000001']['history_secid'], 'tencent:sh000001')
        self.assertEqual(requests['market:sh000001']['name'], '上证指数')

    def test_last_sixty_closes_are_attached_with_dates_only(self):
        snapshot = self.market()
        rows = [{'date': f'2026-{8 + i // 28:02d}-{i % 28 + 1:02d}', 'close': 3000 + i, 'return_pct': 0.1}
                for i in range(80)]
        sectors.attach_index_histories(snapshot, {'tencent:sh000001': rows})
        history = snapshot['market'][0]['history']
        self.assertEqual(len(history), sectors.INDEX_HISTORY_DAYS)
        self.assertEqual(history[-1], {'date': rows[-1]['date'], 'close': rows[-1]['close']})
        self.assertNotIn('history', snapshot['market'][1])

    def test_missing_or_too_short_history_leaves_the_field_out(self):
        snapshot = self.market()
        snapshot['market'][0]['history'] = [{'date': '2026-10-01', 'close': 1}]
        sectors.attach_index_histories(snapshot, {'tencent:sh000001': [{'date': '2026-11-04', 'close': 3900}]})
        self.assertNotIn('history', snapshot['market'][0])


if __name__ == '__main__':
    unittest.main()


class BroadIndexReferenceTests(unittest.TestCase):
    def test_broad_indices_use_complete_official_series_and_industries_keep_samples(self):
        from research_sectors import prefer_company_indicator
        ready = {'meta': {'ready': True}}
        with unittest.mock.patch('research_sectors._company_financial_ready', return_value=True):
            for board_id in ('index_csi300', 'index_csi500', 'index_star', 'index_sse50'):
                self.assertFalse(prefer_company_indicator({'id': board_id, 'group': 'broad'}, ready, [{}], True, None))
                # Without a complete official series the sample is still the fallback.
                self.assertTrue(prefer_company_indicator({'id': board_id, 'group': 'broad'}, ready, [{}], False, None))
            self.assertTrue(prefer_company_indicator({'id': 'sector_semiconductor', 'group': 'industry'}, ready, [{}], True, None))
            self.assertFalse(prefer_company_indicator({'id': 'sector_semiconductor', 'group': 'industry'},
                                                      {'meta': {'ready': False}}, [{}], True, None))


class PublisherDailyFreshnessTests(unittest.TestCase):
    def test_official_end_of_day_series_keep_previous_close_until_evening_publication(self):
        from research_sectors import _quote_fresh
        quote = {'code': 'H11001', 'as_of': '2026-11-03', 'as_of_precision': 'date', 'data_frequency': 'daily',
                 'history_secid': 'official:csindex:H11001', 'change_pct': 0.09}
        self.assertTrue(_quote_fresh(quote, '2026-11-04T10:00:00+08:00'))
        self.assertTrue(_quote_fresh(quote, '2026-11-04T15:12:00+08:00'))
        self.assertFalse(_quote_fresh(quote, '2026-11-04T21:00:00+08:00'))
        self.assertTrue(_quote_fresh({**quote, 'as_of': '2026-11-04'}, '2026-11-04T21:00:00+08:00'))
        # Live-sourced daily series still need today's close right after 15:00.
        tencent = {**quote, 'history_secid': 'tencent:sh000300'}
        self.assertFalse(_quote_fresh(tencent, '2026-11-04T15:12:00+08:00'))
