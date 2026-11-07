import copy
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from research_leader_index import (build_indicator, parse_history, apply_indicator,
    refresh_custom_scores, last_close_day, collect_leader_histories)
from research_sectors import analyze_sector
from research_trading_calendar import is_trading_day

NOW = '2026-10-31T04:00:00+08:00'
BOARD = {'id': 'sector_test', 'title': '测试行业', 'group': 'industry'}


def days(count=80):
    end, result = date(2026, 10, 30), []
    while len(result) < count:
        if is_trading_day(end):
            result.append(end.isoformat())
        end -= timedelta(days=1)
    return list(reversed(result))


def member(code='600000.SH', daily=.001, **changes):
    row = {'ts_code': code, 'name': code, 'as_of': '2026-10-30T15:00:00+08:00',
        'source_ids': ['members', 'quote', 'finance'],
        'membership_evidence': {'l1_name': '测试官方成分', 'snapshot_date': '2026-10-30'},
        'quote': {'close': 10, 'pct_chg': daily*100, 'is_intraday': False},
        'financials': {'ann_date': '2026-10-30', 'end_date': '2026-09-30', 'tr_yoy': 10, 'netprofit_yoy': 20, 'eps': 1},
        'history': [{'date': day, 'close': 10*(1+daily)**i} for i, day in enumerate(days())]}
    row.update(changes)
    return row


class LeaderIndexTests(unittest.TestCase):
    def test_microcap_uses_small_cap_sample_labels_and_preserves_selection_scope(self):
        board = {'id': 'style_microcap', 'title': '微盘股', 'group': 'style'}
        rows = [member('920414.BJ'), member('920149.BJ')]
        out = build_indicator(board, rows, NOW)
        self.assertTrue(out['meta']['ready'])
        self.assertEqual(out['meta']['name'], '微盘股 · 小市值样本指标')
        self.assertIn('自建小市值样本指标 v1', out['meta']['method'])
        self.assertIn('优先保留4家小市值代表', out['meta']['method'])
        self.assertIn('按市值从小到大取12家候选', out['meta']['scope'])
        self.assertIn('不是官方微盘指数', out['meta']['scope'])
        sector = analyze_sector(board, out['quote'], out['history'], [out['source']], [], NOW, {'mode': 'risk_on'})
        apply_indicator(sector, out, rows, NOW)
        refresh_custom_scores({'sector_analysis': [sector], 'as_of': NOW})
        self.assertIn('小市值样本分析', sector['summary'])
        self.assertIn('自建小市值样本指标', sector['data_status_summary'])
        self.assertTrue(any('小市值样本指标' in reason for reason in sector['reasons']))
        self.assertNotIn('龙头', sector['summary'] + sector['data_status_summary'] + out['meta']['method'])

    def test_resource_equity_is_an_equity_basket_with_limited_coverage(self):
        from research_sectors import sector_catalog
        board = next(b for b in sector_catalog() if b['id'] == 'commodities')
        self.assertEqual(board['group'], 'industry')
        self.assertIn('大宗商品', board['aliases'])
        rows = [member('601899.SH'), member('600938.SH')]
        for row in rows:
            row['membership_evidence']['evidence_type'] = 'public_business'
        out = build_indicator(board, rows, NOW)
        self.assertTrue(out['meta']['ready'])
        self.assertIn('资源企业股票样本指标', out['meta']['name'])
        self.assertIn('上市公司整体财务', out['meta']['scope'])
        self.assertIn('不是商品现货或期货价格', out['meta']['scope'])
        self.assertIn('不代表煤炭、农产品', out['meta']['scope'])
        self.assertEqual(out['quote']['asset_type'], 'equity')
        self.assertIn('非商品价格指数', out['quote']['mapping_basis'])

    def test_brain_computer_research_link_does_not_claim_theme_revenue_leadership(self):
        board = {'id': 'sector_brain_computer', 'title': '脑机接口', 'group': 'industry'}
        rows = [member('688626.SH'), member('301293.SZ')]
        for row in rows:
            row['membership_evidence']['evidence_type'] = 'public_business'
        out = build_indicator(board, rows, NOW)
        self.assertTrue(out['meta']['ready'])
        self.assertEqual(out['meta']['name'], '脑机接口 · 研究关联样本指标')
        self.assertIn('上市公司整体财务', out['meta']['scope'])
        self.assertIn('不是脑机接口业务分部财务', out['meta']['scope'])
        self.assertIn('不等同现有规模产品收入', out['meta']['scope'])
        self.assertIn('非主题收入排名', out['quote']['mapping_basis'])
        sector = analyze_sector(board, out['quote'], out['history'], [out['source']], [], NOW, {'mode': 'risk_on'})
        apply_indicator(sector, out, rows, NOW)
        refresh_custom_scores({'sector_analysis': [sector], 'as_of': NOW})
        self.assertIn('研究关联样本分析', sector['summary'])
        self.assertIn('自建研究关联样本指标', sector['data_status_summary'])

    def test_brain_computer_still_requires_two_complete_samples(self):
        board = {'id': 'sector_brain_computer', 'title': '脑机接口', 'group': 'industry'}
        for rows in ([member('688626.SH')], [member('688626.SH'), member('301293.SZ', history=[])]):
            self.assertFalse(build_indicator(board, rows, NOW)['meta']['ready'])

    def test_equal_weight_returns_are_compounded_not_average_price_levels(self):
        rows = [member(daily=.01), member('000001.SZ', daily=-.005)]
        before = copy.deepcopy(rows)
        out = build_indicator(BOARD, rows, NOW)
        self.assertTrue(out['meta']['ready'])
        self.assertEqual([r['weight_pct'] for r in out['meta']['constituents']], [50, 50])
        self.assertAlmostEqual(out['meta']['value'], round(100*1.0025**79, 4))
        self.assertAlmostEqual(out['quote']['change_pct'], .25)
        self.assertEqual(rows, before)
        self.assertIn('不是历史龙头组合', out['meta']['method'])

    def test_missing_or_future_membership_and_duplicate_or_stale_price_do_not_score(self):
        for bad in [member(membership_evidence={}), member(membership_evidence={'l1_name':'x','snapshot_date':'2026-11-01'}),
                    member(as_of='2026-10-29T15:00:00+08:00'), member(as_of='2026-11-02T15:00:00+08:00')]:
            self.assertIsNone(build_indicator(BOARD, [bad], NOW))
        out=build_indicator(BOARD,[member(),member()],NOW)
        self.assertFalse(out['meta']['ready'])
        self.assertEqual(out['meta']['sample_count'],1)

    def test_previous_verified_fixed_samples_do_not_claim_current_complete_membership_ranking(self):
        rows = [member(), member('000001.SZ')]
        for row in rows:
            row['membership_evidence']['evidence_type'] = 'official_fixed_sample'
        out = build_indicator(BOARD, rows, NOW)
        self.assertTrue(out['meta']['ready'])
        self.assertIn('本轮完整成分名单未取得', out['meta']['scope'])
        self.assertIn('固定有限样本', out['meta']['method'])
        self.assertNotIn('当前板块成分内按总市值筛选', out['meta']['method'])
        self.assertIn('本轮完整成分未取得', out['quote']['mapping_basis'])

    def test_no_history_or_one_sample_exposes_data_without_fabricated_score(self):
        for rows in ([member()], [member(), member('000001.SZ', history=[])],
                     [member(history=member()['history'][:-1]),member('000001.SZ')]):
            out=build_indicator(BOARD,rows,NOW)
            self.assertFalse(out['meta']['ready'])
            sector=analyze_sector(BOARD,out['quote'],out['history'],[out['source']],[],NOW,{'mode':'risk_on'})
            apply_indicator(sector,out,rows,NOW)
            refresh_custom_scores({'sector_analysis':[sector],'as_of':NOW})
            self.assertIsNone(sector['recommendation_index'])
            self.assertEqual(sector['status'],'partial')

    def test_missing_a_recent_trading_day_cannot_be_hidden_by_a_long_history(self):
        rows=[member(),member('000001.SZ')]
        rows[0]['history'].pop(-10)
        bundle=build_indicator(BOARD,rows,NOW)
        self.assertGreater(bundle['meta']['history_count'],61)
        self.assertFalse(bundle['meta']['ready'])

    def test_history_prefers_adjusted_series_omits_intraday_future_and_wrong_symbol(self):
        payload={'data':{'sh600000':{'day':[['2026-10-29','0','99']],
            'qfqday':[['2026-10-29','0','10'],['2026-10-30','0','11'],['2026-11-02','0','12']]}}}
        rows=parse_history(payload,'600000.SH','2026-10-30T14:30:00+08:00')
        self.assertEqual(rows,[{'date':'2026-10-29','close':10}])
        with self.assertRaises(ValueError):parse_history(payload,'000001.SZ',NOW)
        self.assertEqual(last_close_day('2026-11-02T09:10:00+08:00'),'2026-10-30')

    def test_live_basket_uses_common_session_and_keeps_intraday_out_of_history(self):
        rows=[member(),member('000001.SZ')]
        for row in rows:
            row['as_of']='2026-10-30T14:29:59+08:00'
            row['quote']['is_intraday']=True
            row['history']=row['history'][:-1]
        out=build_indicator(BOARD,rows,'2026-10-30T14:30:00+08:00')
        self.assertTrue(out['meta']['ready'])
        self.assertEqual(out['meta']['history_end'],'2026-10-29')
        self.assertAlmostEqual(out['meta']['value'],round(out['history'][-1]['close']*1.001,4))
        rows[1]['quote']['is_intraday']=False
        self.assertFalse(build_indicator(BOARD,rows,'2026-10-30T14:30:00+08:00')['meta']['ready'])
        rows[1]['as_of']='2026-10-29T15:00:00+08:00'
        self.assertIsNone(build_indicator(BOARD,rows,'2026-10-30T14:30:00+08:00'))

    def test_composite_is_idempotent_has_no_market_cap_and_requires_official_assessed_event(self):
        rows=[member(),member('000001.SZ')]
        bundle=build_indicator(BOARD,rows,NOW)
        sector=analyze_sector(BOARD,bundle['quote'],bundle['history'],[bundle['source']],[],NOW,{'mode':'risk_on'})
        apply_indicator(sector,bundle,rows,NOW)
        report={'sector_analysis':[sector],'as_of':NOW,'strategy':{'regime':{'mode':'cautious'}},
            'event_analysis':{'status':'completed','events':[{'sector_ids':[BOARD['id']], 'impact_score':-80,
                'direction':'negative','published_at':'2026-10-30T18:00:00+08:00','source_ids':['official_cninfo']}]}}
        # Use the actual allowlisted source identity, not a generic headline.
        from research_event_ai import OFFICIAL_EVENT_SOURCES
        report['event_analysis']['events'][0]['source_ids']=[next(iter(OFFICIAL_EVENT_SOURCES))]
        refresh_custom_scores(report)
        self.assertEqual(sector['score_breakdown']['fundamentals']['points'],28)
        self.assertEqual(sector['score_components']['catalyst_points'],-24)
        self.assertNotIn('score_cap',sector)
        self.assertEqual(sector['score'],sector['recommendation_index'])
        before=copy.deepcopy(report)
        refresh_custom_scores(report)
        self.assertEqual(report,before)
        report['event_analysis']['events'][0]['source_ids']=['random_blog']
        refresh_custom_scores(report)
        self.assertEqual(sector['score_components']['catalyst_points'],0)
        report['event_analysis']['status']='pending'
        refresh_custom_scores(report)
        self.assertEqual(sector['event_score_status'],'unassessed')

    def test_unknown_or_future_financial_values_are_excluded_from_adjustment(self):
        rows=[member(financials={'ann_date':'2026-11-01','end_date':'2026-09-30','tr_yoy':999}),
              member('000001.SZ',financials=None)]
        bundle=build_indicator(BOARD,rows,NOW)
        sector=analyze_sector(BOARD,bundle['quote'],bundle['history'],[bundle['source']],[],NOW,{'mode':'risk_on'})
        apply_indicator(sector,bundle,rows,NOW)
        refresh_custom_scores({'sector_analysis':[sector],'as_of':NOW})
        self.assertIsNone(sector['recommendation_index'])
        self.assertIsNone(sector['research_score'])
        self.assertEqual(sector['score_status'],'unavailable')

    def test_event_refresh_cannot_restore_composite_when_data_requirements_are_partial(self):
        rows = [member(), member('000001.SZ', financials=None)]
        bundle = build_indicator(BOARD, rows, NOW)
        sector = analyze_sector(BOARD, bundle['quote'], bundle['history'], [bundle['source']], [], NOW, {'mode': 'risk_on'})
        apply_indicator(sector, bundle, rows, NOW)
        sector['requirements'] = [{'id': key, 'label': key, 'status': 'partial' if key == 'data' else 'ok'}
                                  for key in ('data', 'mapping', 'model')]
        report = {'sector_analysis': [sector], 'as_of': NOW, 'event_analysis': {'status': 'completed', 'events': []}}
        refresh_custom_scores(report)
        refresh_custom_scores(report)
        self.assertIsNone(sector['recommendation_index'])
        self.assertIsNone(sector['score'])
        self.assertIsNone(sector['research_score'])
        self.assertEqual(sector['research_tier']['id'],'pending')
        self.assertEqual(len([g for g in sector['data_gaps'] if g['code'] == 'score_requirements_unmet']), 1)

    def test_trend_star_is_recomputed_from_final_composite_and_risk_gates(self):
        from research_event_ai import OFFICIAL_EVENT_SOURCES
        rows = [member(daily=.01), member('000001.SZ',daily=.01)]
        for row in rows:row['financials'].update(tr_yoy=100,netprofit_yoy=200)
        bundle = build_indicator(BOARD, rows, NOW)
        sector = analyze_sector(BOARD, bundle['quote'], bundle['history'], [bundle['source']], [], NOW, {'mode': 'risk_on'})
        apply_indicator(sector, bundle, rows, NOW)
        sector['requirements'] = [{'id': key, 'status': 'ok'} for key in ('data', 'mapping', 'model')]
        money={'id':'money','status':'ok','score_scope':'money_liquidity','recommendation_index':90,'as_of':'2026-10-30'}
        report = {'sector_analysis': [sector,money], 'as_of': NOW, 'strategy': {'regime': {'mode': 'risk_on'},
            'panic':{'score':10,'quote_as_of':'2026-10-30T15:00:00+08:00'},'macro_evidence':{'status':'ok','risk_score':10,'published_at':'2026-10-30'}},
            'event_analysis':{'status':'completed','events':[]}}
        refresh_custom_scores(report)
        self.assertGreaterEqual(sector['recommendation_index'],65)
        self.assertEqual(sector['signal'], 'trend_excellent')
        base=sector['score']
        report['event_analysis'] = {'status': 'completed', 'events': [{'sector_ids': [BOARD['id']],
            'impact_score': 80, 'direction': 'positive', 'published_at': '2026-10-30T18:00:00+08:00',
            'source_ids': [next(iter(OFFICIAL_EVENT_SOURCES))]}]}
        refresh_custom_scores(report)
        self.assertEqual(sector['signal'], 'trend_excellent')
        sector['severity'] = 'critical'
        refresh_custom_scores(report)
        self.assertEqual(sector['signal'], 'neutral')
        sector['severity'] = 'normal'
        report['strategy']['regime']['mode'] = 'cautious'
        refresh_custom_scores(report)
        self.assertEqual(sector['signal'], 'neutral')
        self.assertGreater(sector['score'],59)
        report['strategy']['regime']['mode'] = 'risk_on'
        report['event_analysis']['events'] = []
        refresh_custom_scores(report)
        self.assertEqual(sector['recommendation_index'],base)
        self.assertEqual(sector['signal'], 'trend_excellent')
        report['event_analysis']['status']='scheduled'
        refresh_custom_scores(report)
        self.assertEqual(sector['signal'], 'neutral')

    def test_last_verified_close_survives_long_holiday_but_not_reopening_close(self):
        rows = [member(), member('000001.SZ')]
        for row in rows:
            row['as_of'] = '2026-09-30T15:00:00+08:00'
            row['membership_evidence']['snapshot_date'] = '2026-09-30'
            day, points = date(2026, 9, 30), []
            while len(points) < 80:
                if is_trading_day(day):
                    points.append({'date': day.isoformat(), 'close': 100})
                day -= timedelta(days=1)
            row['history'] = list(reversed(points))
        self.assertTrue(build_indicator(BOARD, rows, '2026-10-08T09:10:00+08:00')['meta']['ready'])
        self.assertIsNone(build_indicator(BOARD, rows, '2026-10-08T16:00:00+08:00'))
        self.assertIsNone(build_indicator(BOARD, rows, '2027-01-04T09:10:00+08:00'))

    def test_unmapped_empty_and_nonequity_sectors_are_not_given_arbitrary_companies(self):
        self.assertIsNone(build_indicator(BOARD,[],NOW))
        self.assertIsNone(build_indicator({**BOARD,'group':'defensive'},[member()],NOW))
        company={'sector_leaders':{},'sources':[]}
        with patch('research_public_data._save'),patch('research_leader_index.fetch_text',side_effect=AssertionError('network')):
            collect_leader_histories(company,NOW)
        self.assertEqual(company['sources'],[])

    def test_history_fallback_replaces_the_entire_series_and_preserves_actual_provider(self):
        rows = member()['history']
        company = {'sector_leaders': {'x': [member()]}, 'sources': []}
        fallback = {'600000.SH': {'rows': rows, 'url': 'https://www.baostock.com',
            'fetched_at': NOW, 'error': ''}}
        with patch('research_public_data._get', return_value=None), patch('research_public_data._remember'), \
             patch('research_public_data._save'), patch('research_leader_index.fetch_text', side_effect=ValueError('primary unavailable')), \
             patch('research_leader_history_fallback.fetch_a_share_histories', return_value=fallback):
            collect_leader_histories(company, NOW)
        self.assertEqual(company['sector_leaders']['x'][0]['history'], rows)
        source = next(s for s in company['sources'] if s['id'] == 'leader_history:600000.SH')
        self.assertIn('BaoStock', source['name'])
        self.assertEqual(source['status'], 'ok')
        self.assertEqual(source['url'], fallback['600000.SH']['url'])

    def test_a_share_history_collector_keeps_overseas_history_and_sources(self):
        overseas = member('00700.HK')
        company = {'sector_leaders': {'x': [overseas]}, 'sources': []}
        before = copy.deepcopy(overseas)
        with patch('research_public_data._save'), patch('research_leader_index.fetch_text', side_effect=AssertionError('network')):
            collect_leader_histories(company, NOW)
        self.assertEqual(overseas, before)

    def test_history_fallback_covers_all_selected_companies_across_bounded_batches(self):
        codes = [str(600000+i) + '.SH' for i in range(61)]
        rows = member()['history']
        company = {'sector_leaders': {code: [member(code, history=[])] for code in codes}, 'sources': []}
        def fallback(batch, as_of):
            self.assertLessEqual(len(batch), 60)
            return {code: {'rows': rows, 'url': 'https://www.baostock.com',
                           'fetched_at': NOW, 'error': ''} for code in batch}
        with patch('research_public_data._get', return_value=None), patch('research_public_data._remember'), \
             patch('research_public_data._save'), patch('research_leader_index.fetch_text', side_effect=ValueError('primary unavailable')), \
             patch('research_leader_history_fallback.fetch_a_share_histories', side_effect=fallback) as fetch:
            collect_leader_histories(company, NOW)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(len(group[0]['history']) == 80 for group in company['sector_leaders'].values()))

    def test_custom_a_share_close_remains_valid_during_verified_exchange_holiday(self):
        from research_sectors import _quote_fresh, _history_fresh
        quote = {'is_custom': True, 'data_frequency': 'daily',
                 'as_of': '2026-09-30T15:00:00+08:00'}
        now = '2026-10-07T09:10:00+08:00'
        self.assertTrue(_quote_fresh(quote, now))
        self.assertTrue(_history_fresh([{'date': '2026-09-30', 'close': 100}], quote, now))
        self.assertFalse(_quote_fresh(quote, '2026-10-08T16:00:00+08:00'))


if __name__=='__main__':unittest.main()
