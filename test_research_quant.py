import math
import unittest
from datetime import date, timedelta

from research_quant import build_analysis, build_quant, build_sentiment, _rsi

TODAY = date(2026, 10, 29)
PREFS = {'risk': '稳健增强', 'pos': 25, 'min': 72}


def snapshot(returns, dateshift=0, dividend_at=None, missing_returns=False):
    end = TODAY - timedelta(days=dateshift)
    days = []
    cursor = end
    while len(days) < len(returns) + 1:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    nav = 1.0
    history = [{'date': days[0].isoformat(), 'nav': nav, 'return_pct': 0}]
    for i, change in enumerate(returns):
        nav *= 1 + change / 100
        if dividend_at == i:
            nav *= .8
        history.append({'date': days[i + 1].isoformat(), 'nav': nav, 'return_pct': None if missing_returns else change})
    return {'as_of': TODAY.isoformat() + 'T16:00:00+08:00', 'funds': [{'code': '000001', 'name': '测试基金', 'nav': nav, 'nav_date': days[-1].isoformat(), 'history': history, 'source_url': 'https://example.com/fund'}], 'market': [], 'news': [], 'sources': [], 'warnings': []}


class QuantTests(unittest.TestCase):
    def test_constant_return_math_and_overheating_guard(self):
        result = build_quant(snapshot([.2] * 80), PREFS)[0]
        self.assertEqual(result['quality'], 'ok')
        self.assertAlmostEqual(result['metrics']['return_20d'], (1.002 ** 20 - 1) * 100, places=2)
        self.assertAlmostEqual(result['metrics']['return_60d'], (1.002 ** 60 - 1) * 100, places=2)
        self.assertEqual(result['metrics']['volatility_annual'], 0)
        self.assertEqual(result['metrics']['max_drawdown'], 0)
        self.assertEqual(result['metrics']['rsi14'], 100)
        self.assertNotEqual(result['action'], '分批配置候选')

    def test_falling_series_triggers_reassessment_not_buying(self):
        result = build_quant(snapshot([-.3] * 80), PREFS)[0]
        self.assertEqual(result['action'], '考虑减仓（如持有）')
        self.assertLess(result['metrics']['return_60d'], -10)
        self.assertEqual(result['metrics']['rsi14'], 0)

    def test_flat_series_is_neutral_not_division_by_zero(self):
        result = build_quant(snapshot([0] * 80), PREFS)[0]
        self.assertEqual(result['metrics']['rsi14'], 50)
        self.assertEqual(result['score'], 50)
        self.assertEqual(result['action'], '继续观察')

    def test_dividend_adjustment_uses_published_return(self):
        normal = build_quant(snapshot([.1] * 80), PREFS)[0]
        dividend = build_quant(snapshot([.1] * 80, dividend_at=55), PREFS)[0]
        self.assertEqual(normal['metrics'], dividend['metrics'])
        self.assertEqual(dividend['metrics']['max_drawdown'], 0)

    def test_missing_adjustment_does_not_create_configuration_candidate(self):
        result = build_quant(snapshot([.5] * 80, missing_returns=True, dividend_at=55), PREFS)[0]
        self.assertEqual(result['quality'], 'insufficient')
        self.assertEqual(result['action'], '数据不足')
        self.assertIsNone(result['score'])
        self.assertTrue(any('单位净值' in reason for reason in result['reasons']))

    def test_stale_future_and_short_data_are_blocked(self):
        stale = build_quant(snapshot([.1] * 80, dateshift=14), PREFS)[0]
        self.assertEqual(stale['quality'], 'stale')
        self.assertEqual(stale['action'], '数据不足')
        future_data = snapshot([.1] * 80)
        future_data['funds'][0]['nav_date'] = '2027-01-01'
        self.assertEqual(build_quant(future_data, PREFS)[0]['quality'], 'insufficient')
        self.assertEqual(build_quant(snapshot([.1] * 20), PREFS)[0]['quality'], 'insufficient')

    def test_invalid_returns_and_large_history_gaps_are_blocked(self):
        data = snapshot([.1] * 80)
        data['funds'][0]['history'][40]['return_pct'] = -100
        self.assertEqual(build_quant(data, PREFS)[0]['action'], '数据不足')
        data = snapshot([.1] * 100)
        del data['funds'][0]['history'][30:60]
        self.assertEqual(build_quant(data, PREFS)[0]['quality'], 'insufficient')

    def test_wilder_rsi_known_fixture(self):
        prices = [44.34,44.09,44.15,43.61,44.33,44.83,45.1,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28]
        self.assertAlmostEqual(_rsi(prices), 70.4641, places=3)

    def test_sample_volatility_and_risk_guard(self):
        result = build_quant(snapshot([3, -2] * 40), {'risk': '稳健增强', 'pos': 25, 'min': 0})[0]
        self.assertGreater(result['metrics']['volatility_annual'], 30)
        self.assertEqual(result['action'], '暂缓新增')
        self.assertEqual(result['thresholds']['annual_volatility_limit'], 15)

    def test_position_is_a_cap_not_invented_weights(self):
        data = snapshot([.1] * 80)
        quant = build_quant(data, PREFS)
        analysis = build_analysis(data, quant, PREFS)
        self.assertIn('上限 25%', analysis['funds'][0]['allocation'])
        self.assertIn('暂不生成组合权重', analysis['funds'][0]['allocation'])
        self.assertEqual(analysis['funds'][0]['evidence_ids'], ['nav:000001'])
        self.assertTrue(any('未经' in item or '尚未做历史收益回测' in item for item in analysis['risks']))

    def test_sentiment_does_not_relabel_index_sample_as_whole_market(self):
        data = snapshot([.1] * 80)
        data['market'] = [{'name': 'A', 'change_pct': 1.0, 'as_of': '2026-10-29T15:00:00+08:00'}, {'name': 'B', 'change_pct': -1, 'as_of': '2026-10-29T15:00:00+08:00'}, {'name': 'old', 'change_pct': 9, 'as_of': '2026-01-01'}]
        data['news'] = [{'title': '公司利润增长', 'published_at': '2026-10-29'}, {'title': '业绩下滑', 'published_at': None}]
        result = build_sentiment(data)
        self.assertEqual(result['score'], 50)
        self.assertEqual(result['coverage']['indices'], 2)
        self.assertEqual(result['coverage']['recent_headlines'], 1)
        self.assertIn('不是全市场', result['method'])
        self.assertEqual(build_sentiment(snapshot([0] * 80))['score'], None)

    def test_good_candidate_has_conditional_thirds_not_forced_target_weight(self):
        data = snapshot([1.2, -.5] * 60)
        quant = build_quant(data, PREFS)
        self.assertEqual(quant[0]['action'], '分批配置候选')
        fund = build_analysis(data, quant, PREFS)['funds'][0]
        self.assertEqual(fund['score'], quant[0]['score'])
        self.assertIsNone(fund['recommendation_index'])
        self.assertIn('历史研究分为', fund['score_explanation'])
        self.assertIn('推荐指数另由市场、风险及板块持仓核验结果约束', fund['score_explanation'])
        self.assertIn('历史研究分不低于 72', fund['operation_plan']['entry_conditions'][0])
        self.assertIn('1/3', fund['operation_plan']['new_position'])
        self.assertIn('每一批执行前', fund['operation_plan']['new_position'])
        self.assertIn('合计不得超过总资产 100%', fund['operation_plan']['position_limit'])
        self.assertTrue(any('总收益曲线' in line for line in fund['operation_plan']['entry_conditions']))

    def test_insufficient_stale_and_waiting_plans_have_no_positive_entry_steps(self):
        for data in (snapshot([.1] * 20), snapshot([.1] * 80, dateshift=14), snapshot([0] * 80)):
            quant = build_quant(data, PREFS)
            plan = build_analysis(data, quant, PREFS)['funds'][0]['operation_plan']
            self.assertFalse(any('第一批' in step or '第二批' in step or '第三批' in step for step in plan['steps']))
            self.assertNotIn('1/3', plan['new_position'])
            self.assertTrue(plan['fee_checks'])

    def test_short_bond_monotonic_growth_is_not_equity_overheating(self):
        data = snapshot([.008] * 100)
        data['funds'][0]['name'] = '嘉实超短债C'
        data['funds'][0]['fund_type'] = '债券型-短债'
        result = build_quant(data, PREFS)[0]
        self.assertEqual(result['asset_class'], 'short_bond')
        self.assertEqual(result['metrics']['rsi14'], 100)
        self.assertEqual(result['score_components']['rsi_penalty'], 0)
        self.assertFalse(result['thresholds']['uses_rsi_gate'])
        self.assertLess(result['thresholds']['annual_volatility_limit'], 2)
        self.assertGreaterEqual(result['score'], 72)
        self.assertEqual(result['action'], '继续观察')
        self.assertEqual(result['configuration_scope'], 'trend_observation_only')
        analysis = build_analysis(data, [result], PREFS)['funds'][0]
        self.assertIn('信用', analysis['operation_plan']['new_position'])
        self.assertNotIn('第一批', ''.join(analysis['operation_plan']['steps']))
        self.assertNotIn('RSI14 小于 80', ''.join(analysis['operation_plan']['entry_conditions']))

    def test_declared_money_type_uses_class_rules_and_gold_is_separate(self):
        data = snapshot([.005] * 100)
        data['funds'][0]['fund_type'] = '货币型'
        result = build_quant(data, PREFS)[0]
        self.assertEqual(result['asset_class'], 'money')
        self.assertEqual(result['score_components']['rsi_penalty'], 0)
        self.assertIn('数据源类型', result['category_basis'])
        gold = snapshot([1.2, -.5] * 60)
        gold['funds'][0]['name'] = '华安黄金易ETF联接A'
        gold['funds'][0]['fund_type'] = '黄金商品型'
        gold_result = build_quant(gold, PREFS)[0]
        self.assertEqual(gold_result['asset_class'], 'gold')
        self.assertTrue(any('不代表黄金相对股票/债券' in r for r in gold_result['reasons']))

    def test_convertible_bond_does_not_get_pure_bond_rule(self):
        data = snapshot([1.2, -.5] * 60)
        data['funds'][0]['name'] = '测试可转债债券基金'
        self.assertEqual(build_quant(data, PREFS)[0]['asset_class'], 'equity_mixed')

    def test_guarded_action_invalidation_means_recovery_not_already_triggered_drop(self):
        data = snapshot([-.3] * 80)
        result = build_quant(data, PREFS)[0]
        self.assertEqual(result['action'], '考虑减仓（如持有）')
        self.assertIn('恢复为正', result['invalidation'])
        self.assertNotIn('20 日总收益≤0', result['invalidation'])
        plan = build_analysis(data, [result], PREFS)['funds'][0]['operation_plan']
        self.assertTrue(any('已经触发' in condition for condition in plan['exit_conditions']))


if __name__ == '__main__':
    unittest.main()
