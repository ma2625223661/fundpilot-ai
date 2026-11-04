from test_holdings_fixtures import portfolio
import copy
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from research_strategy import build_strategy, rolling_holding_evidence


def fixture(changes=(1, .6, .3, .8), now='2026-10-29T16:00:00+08:00', quote='2026-10-29T15:00:00+08:00'):
    end = date.fromisoformat(now[:10])
    dates, cursor = [], end
    while len(dates) < 121:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    dates.reverse()
    history = [{'date': day.isoformat(), 'nav': 1, 'return_pct': .1} for day in dates]
    snapshot = {'as_of': now, 'market': [{'code': str(i), 'name': '指数' + str(i), 'change_pct': value, 'as_of': quote} for i, value in enumerate(changes)],
                'funds': [{'code': '110020', 'name': '测试权益基金', 'history': history, 'fund_type': '股票型', 'holdings': portfolio(['软件开发'])}], 'news': []}
    quant = [{'code': '110020', 'name': '测试权益基金', 'score': 85, 'action': '分批配置候选', 'quality': 'ok', 'asset_class': 'equity_mixed', 'invalidation': '趋势转弱时复核'}]
    return snapshot, quant


class StrategyTests(unittest.TestCase):
    def test_theme_name_without_disclosed_holdings_never_becomes_candidate(self):
        snapshot, quant = fixture()
        snapshot['funds'][0].pop('holdings')
        snapshot['funds'][0].update(name='测试白酒股票A', fund_type='股票型')
        original = copy.deepcopy((snapshot, quant))
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['regime']['mode'], 'risk_on')
        self.assertEqual(result['candidates'], [])
        exclusion = result['excluded_candidates'][0]
        self.assertEqual(exclusion['board_match']['board_id'], 'holdings_unclassified')
        self.assertEqual(exclusion['board_match']['status'], 'unknown')
        self.assertIn('持仓核验', exclusion['reason'])
        self.assertEqual((snapshot, quant), original)

    def test_matching_disclosed_stock_weights_unlock_only_conditional_candidate(self):
        snapshot, quant = fixture()
        snapshot['funds'][0].update(name='测试白酒股票A', fund_type='股票型', holdings={
            'status': 'ok', 'report_date': '2026-09-30',
            'source_id': 'holdings:110020', 'source_url': 'https://example.test/disclosure/110020',
            'rows': [{'code': f'60000{index}', 'name': f'合成白酒企业{index}',
                      'weight_pct': 10, 'instrument_type': 'stock', 'tag_status': 'ok', 'tags': ['白酒'],
                      'tag_source_url': f'https://example.test/classification/60000{index}'}
                     for index in range(1, 4)]})
        result = build_strategy(snapshot, quant)
        self.assertEqual(len(result['candidates']), 1)
        candidate = result['candidates'][0]
        self.assertEqual(candidate['board_match']['status'], 'matched')
        self.assertEqual(candidate['board_match']['matched_weight_pct'], 30)
        self.assertEqual(candidate['board_match']['report_date'], '2026-09-30')
        self.assertFalse(candidate['execution_eligible'])
        self.assertFalse(candidate['verified_buyable'])
        self.assertEqual(candidate['score'], quant[0]['score'])

        # Full, known holdings in an unrelated sector cannot pass on the name.
        for holding in snapshot['funds'][0]['holdings']['rows']:
            holding['tags'] = ['银行']
        mismatched = build_strategy(snapshot, quant)
        self.assertEqual(mismatched['candidates'][0]['board_match']['board_id'], 'sector_banking')

    @patch('research_holdings.verify_board', return_value={'status': 'matched', 'reason': 'synthetic holdings fixture'})
    def test_hugangshen_equity_cannot_bypass_overseas_evidence_gate(self, matched):
        snapshot,quant=fixture()
        snapshot['funds'][0].update(name='显示标识',fund_type='QDII-混合')
        result=build_strategy(snapshot,quant)
        self.assertEqual(result['regime']['mode'],'risk_on')
        self.assertEqual(result['candidates'],[])
        self.assertTrue(any('海外市场' in f['reason'] for f in result['excluded_candidates']))

    def test_low_pressure_produces_only_conditional_research_candidate(self):
        snapshot, quant = fixture()
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['regime']['mode'], 'risk_on')
        self.assertEqual(len(result['candidates']), 1)
        candidate = result['candidates'][0]
        self.assertFalse(candidate['verified_buyable'])
        self.assertEqual(candidate['holding_plan']['minimum_calendar_days'], 7)
        self.assertIn('不是基金合同', candidate['holding_plan']['intended_holding'])
        self.assertIn('免赎回费', result['horizon']['notice'])

    def test_synchronized_drop_switches_to_defense(self):
        snapshot, quant = fixture((-3, -2.8, -3.2, -2.5))
        result = build_strategy(snapshot, quant)
        self.assertGreaterEqual(result['panic']['score'], 70)
        self.assertEqual(result['regime']['mode'], 'defensive')
        self.assertEqual(result['candidates'], [])
        self.assertIn('不是VIX', result['panic']['method'])

    def test_defensive_hysteresis_requires_new_quotes_and_two_step_recovery(self):
        snapshot, quant = fixture((-3, -3, -3, -3))
        previous = build_strategy(snapshot, quant)
        unchanged_time, quant = fixture((.5, .5, .5, .5), now='2026-10-29T16:01:00+08:00')
        held = build_strategy(unchanged_time, quant, previous=previous)
        self.assertEqual(held['regime']['mode'], 'defensive')
        nextday, quant = fixture((.5, .5, .5, .5), now='2026-10-30T16:00:00+08:00', quote='2026-10-30T15:00:00+08:00')
        recovery = build_strategy(nextday, quant, previous=previous)
        self.assertEqual(recovery['regime']['mode'], 'cautious')
        self.assertNotIn('可继续筛选', recovery['panic']['summary'])
        self.assertIn('保持谨慎', recovery['panic']['summary'])
        subsequent, quant = fixture((.5, .5, .5, .5), now='2026-11-02T15:30:00+08:00', quote='2026-11-02T15:00:00+08:00')
        restored = build_strategy(subsequent, quant, previous=recovery)
        self.assertEqual(restored['regime']['mode'], 'risk_on')

    def test_cautious_mode_holds_until_below_30(self):
        snapshot, quant = fixture((-1, -1, -1, -1))
        cautious = build_strategy(snapshot, quant)
        self.assertEqual(cautious['regime']['mode'], 'cautious')
        nextday, quant = fixture((-.1, -.1, -.1, -.1), now='2026-10-30T16:00:00+08:00', quote='2026-10-30T15:00:00+08:00')
        result = build_strategy(nextday, quant, previous=cautious)
        self.assertLess(result['panic']['score'], 40)
        self.assertGreaterEqual(result['panic']['score'], 30)
        self.assertEqual(result['regime']['mode'], 'cautious')

    def test_missing_stale_future_or_sparse_market_blocks_candidates(self):
        for quote in (None, '2026-01-01T15:00:00+08:00', '2027-01-01T15:00:00+08:00', '2026-10-29'):
            snapshot, quant = fixture(quote=quote)
            result = build_strategy(snapshot, quant)
            self.assertEqual(result['regime']['mode'], 'unknown')
            self.assertIsNone(result['panic']['score'])
            self.assertEqual(result['candidates'], [])
        snapshot, quant = fixture(changes=(1, 1))
        self.assertEqual(build_strategy(snapshot, quant)['regime']['mode'], 'unknown')

    def test_pressure_uses_latest_known_session_over_long_holiday_and_fails_closed_without_calendar(self):
        from research_strategy import _pressure
        snapshot, _ = fixture(now='2026-10-08T09:10:00+08:00', quote='2026-09-30T15:00:00+08:00')
        self.assertIsNotNone(_pressure(snapshot)['score'])
        self.assertEqual(_pressure(snapshot)['coverage']['fresh_indices'], 4)
        self.assertEqual(_pressure(snapshot)['calculated_at'], '2026-10-08T09:10:00+08:00')
        self.assertEqual(_pressure(snapshot)['quote_as_of'], '2026-09-30T15:00:00+08:00')
        for as_of in ('2026-10-08T14:30:00+08:00', '2026-10-08T16:00:00+08:00', '2027-01-04T09:10:00+08:00'):
            snapshot['as_of'] = as_of
            self.assertIsNone(_pressure(snapshot)['score'])

    def test_same_verified_close_does_not_release_cautious_state_after_long_holiday(self):
        from research_strategy import _pressure, _regime, SCHEMA_VERSION
        snapshot, _ = fixture(now='2026-10-08T09:10:00+08:00', quote='2026-09-30T15:00:00+08:00')
        previous = {'schema_version': SCHEMA_VERSION, 'regime': {'mode': 'cautious'},
                    'panic': {'score': 10, 'as_of': '2026-09-30T16:00:00+08:00',
                              'latest_market_as_of': '2026-09-30T15:00:00+08:00'}}
        result = _regime(_pressure(snapshot), previous)
        self.assertEqual(result['mode'], 'cautious')
        self.assertTrue(result['hysteresis_applied'])

    def test_rolling_calendar_windows_ignore_future_and_use_source_returns(self):
        snapshot, _ = fixture()
        fund = snapshot['funds'][0]
        base = rolling_holding_evidence(fund, snapshot['as_of'])
        self.assertGreaterEqual(base['sample_count'], 30)
        self.assertAlmostEqual(base['median_return_pct'], ((1.001 ** 5) - 1) * 100, places=3)
        self.assertEqual(base['actual_days_range'], [7, 7])
        self.assertEqual(base['negative_frequency_pct'], 0)
        self.assertEqual(base['last_window_end'], '2026-10-29')
        self.assertFalse(base['costs_included'])
        self.assertTrue(base['overlapping_windows'])
        fund['history'].append({'date': '2026-12-01', 'nav': 20, 'return_pct': 90})
        amended = rolling_holding_evidence(fund, snapshot['as_of'])
        self.assertEqual(amended['median_return_pct'], base['median_return_pct'])
        self.assertEqual(amended['sample_count'], base['sample_count'])
        self.assertEqual(amended['excluded_future_rows'], 1)

    def test_missing_returns_and_short_history_block_7_day_evidence(self):
        snapshot, quant = fixture()
        snapshot['funds'][0]['history'] = snapshot['funds'][0]['history'][-20:]
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['holding_evidence']['110020']['status'], 'insufficient')
        for row in snapshot['funds'][0]['history']:
            row['return_pct'] = None
        evidence = rolling_holding_evidence(snapshot['funds'][0], snapshot['as_of'])
        self.assertEqual(evidence['sample_count'], 0)

    def test_bank_stock_is_never_labeled_a_low_risk_defensive_option(self):
        snapshot, quant = fixture()
        universe = [{'code': '161121', 'name': '某银行指数ETF联接'}, {'code': 'x', 'name': '某货币基金'}, {'code': 'y', 'name': '某1-3年国债基金'}, {'code': 'z', 'name': '某信用短债基金'}]
        universe[0].update(fund_type='指数型-股票', holdings=portfolio(['银行']))
        universe[1]['fund_type'] = '货币型'
        options = build_strategy(snapshot, quant, universe=universe)['defensive_options']
        by_category = {option['category']: option for option in options}
        self.assertEqual(by_category['excluded_bank_equity']['examples'][0]['code'], '161121')
        for category in ('bank_deposit', 'money_market', 'short_government_debt'):
            self.assertFalse(any(row['code'] == '161121' for row in by_category[category]['examples']))
        self.assertFalse(by_category['short_government_debt']['supported_by_current_catalog'])
        self.assertFalse(any(row['code'] == 'z' for row in by_category['short_government_debt']['examples']))
        self.assertTrue(any('银行理财产品不等于银行存款' in note for note in by_category['bank_deposit']['limitations']))

    def test_quant_quality_and_category_gates_remain_effective(self):
        snapshot, quant = fixture()
        for field, value in (('quality', 'stale'), ('quality', 'insufficient'), ('action', '继续观察'), ('asset_class', 'short_bond')):
            modified = copy.deepcopy(quant)
            modified[0][field] = value
            self.assertEqual(build_strategy(snapshot, modified)['candidates'], [])

    def test_valid_noncandidate_still_has_7_day_holding_evidence(self):
        snapshot, quant = fixture()
        quant[0]['action'] = '暂缓新增'
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['candidates'], [])
        self.assertIn('110020', result['holding_evidence'])
        evidence = result['holding_evidence']['110020']
        self.assertGreaterEqual(evidence['sample_count'], 30)
        self.assertIsNotNone(evidence['median_return_pct'])
        self.assertTrue(evidence['suitability']['checks'])
        self.assertIn('已计算至少7天', result['excluded_candidates'][0]['reason'])

    def test_old_or_wrong_schema_previous_does_not_latch_defense(self):
        snapshot, quant = fixture((-3, -3, -3, -3))
        previous = build_strategy(snapshot, quant)
        previous['schema_version'] = 999
        recovery, quant = fixture()
        self.assertEqual(build_strategy(recovery, quant, previous=previous)['regime']['mode'], 'risk_on')

    @patch('research_holdings.verify_board', return_value={'status': 'matched', 'reason': 'synthetic holdings fixture'})
    def test_qdii_requires_matched_overseas_market_and_fx_evidence(self, matched):
        snapshot, quant = fixture()
        snapshot['funds'][0]['fund_type'] = 'QDII-股票'
        blocked = build_strategy(snapshot, quant)
        self.assertEqual(blocked['candidates'], [])
        self.assertIn('A股指数压力不能替代', blocked['excluded_candidates'][0]['reason'])
        row = {'fund_code': '110020', 'as_of': '2026-10-29T15:00:00+08:00', 'source_url': 'https://data.example/observed', 'change_pct': 0.5}
        snapshot['overseas_market'] = [row]
        self.assertEqual(build_strategy(snapshot, quant)['candidates'], [])
        snapshot['fx'] = [row]
        supported = build_strategy(snapshot, quant)
        self.assertEqual(len(supported['candidates']), 1)
        self.assertFalse(supported['candidates'][0]['execution_eligible'])
        self.assertTrue(supported['candidates'][0]['verification_blockers'])

    def test_minus_two_point_three_sample_enters_defense(self):
        snapshot, quant = fixture((-2.3, -2.3, -2.3, -2.3))
        self.assertGreaterEqual(build_strategy(snapshot, quant)['panic']['score'], 70)

    def test_severe_market_override_is_explicit_without_faking_score(self):
        snapshot, quant = fixture((-.82, -1.03, -2.92, -4.45))
        result = build_strategy(snapshot, quant)
        self.assertLess(result['panic']['score'], 70)
        self.assertEqual(result['regime']['mode'], 'defensive')
        self.assertTrue(result['panic']['stress_override']['active'])
        self.assertIn('平均 -2.31%', result['panic']['summary'])
        self.assertIn('4 个下跌', result['panic']['summary'])
        self.assertIn('指数3 -4.45%', result['panic']['summary'])
        self.assertIn('同步大跌保护', result['regime']['reason'])
        self.assertEqual(result['candidates'], [])

    def test_7_day_historical_suitability_rejects_losses_and_tail_risk(self):
        snapshot, quant = fixture()
        for row in snapshot['funds'][0]['history']:
            row['return_pct'] = -.1
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['candidates'], [])
        self.assertFalse(result['holding_evidence']['110020']['suitability']['eligible'])
        self.assertIn('中位收益', result['excluded_candidates'][0]['reason'])
        snapshot, quant = fixture()
        snapshot['funds'][0]['history'][-1]['return_pct'] = -10
        result = build_strategy(snapshot, quant)
        self.assertEqual(result['candidates'], [])
        checks = result['holding_evidence']['110020']['suitability']['checks']
        self.assertTrue(checks[1]['passed'])
        self.assertFalse(checks[3]['passed'])

    def test_defensive_examples_are_capped_and_unavailable_rows_excluded(self):
        snapshot, quant = fixture()
        universe = [{'code': 'locked', 'name': '锁定货币基金', 'is_locked': True},
                    {'code': 'old', 'name': '旧货币基金', 'nav_date': '2026-01-01'},
                    {'code': 'paused', 'name': '暂停货币基金', 'purchase_status': '暂停申购'}]
        universe += [{'code': str(i), 'name': '样本货币基金' + str(i)} for i in range(100)]
        for value in universe:
            value['fund_type'] = '货币型'
        result = build_strategy(snapshot, quant, universe=universe)
        money = next(option for option in result['defensive_options'] if option['category'] == 'money_market')
        self.assertEqual(len(money['examples']), 5)
        self.assertFalse({'locked', 'old', 'paused'} & {row['code'] for row in money['examples']})
        self.assertEqual(money['verification_status'], 'source_unavailable')

    def test_market_news_pressure_ignores_neutral_fund_announcements(self):
        snapshot, quant = fixture()
        snapshot['news'] = [{'title': '市场大跌，资金净流出', 'published_at': '2026-10-29', 'category': '财经新闻'}]
        baseline = build_strategy(snapshot, quant)['panic']
        snapshot['news'] += [{'title': '基金招募说明书更新', 'published_at': '2026-10-29', 'category': '基金公告'} for _ in range(30)]
        snapshot['news'].append({'title': '监管部门例行发布', 'published_at': '2026-10-29', 'category': '监管发布'})
        actual = build_strategy(snapshot, quant)['panic']
        self.assertEqual(actual['score'], baseline['score'])
        news_component = actual['components'][-1]
        self.assertEqual(news_component['sample_count'], 1)
        self.assertEqual(news_component['points'], 5)
        self.assertEqual(news_component['excluded_category_count'], 31)


if __name__ == '__main__':
    unittest.main()
