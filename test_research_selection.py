from test_holdings_fixtures import portfolio
import copy
import unittest
from unittest.mock import patch

from research_selection import (_classify, _family, build_sections, recommendation_index,
                                MAX_RESEARCH_PER_BOARD, MAX_DISPLAY_PER_BOARD)

NOW = '2026-10-30T16:00:00+08:00'


def make(code, name, kind='股票型', score=80, action='继续观察', vol=10, dd=-3, vol_limit=15, dd_limit=8, asset='equity_mixed'):
    fund = {'code': code, 'name': name, 'fund_type': kind, 'nav_date': '2026-10-29', 'source_url': 'https://example.com/' + code}
    fund['holdings'] = portfolio(['软件开发'])
    quant = {'code': code, 'name': name, 'quality': 'ok', 'nav_date': '2026-10-29', 'score': score, 'action': action,
             'asset_class': asset, 'metrics': {'volatility_annual': vol, 'max_drawdown': dd, 'return_20d': 3, 'return_60d': 6},
             'thresholds': {'annual_volatility_limit': vol_limit, 'drawdown_limit': dd_limit}, 'reasons': ['完整理由保留'], 'invalidation': '风险变化后复核'}
    analysis = {'code': code, 'name': name, 'score': score, 'action': action, 'reason': '原始完整分析理由',
                'operation_plan': {'steps': ['既有步骤'], 'position_limit': '上限25%，不是目标仓位'}}
    return fund, quant, analysis


def run(rows, strategy=None, limit=MAX_DISPLAY_PER_BOARD):
    snapshot = {'as_of': NOW, 'funds': [row[0] for row in rows]}
    return build_sections(snapshot, [row[1] for row in rows], {'funds': [row[2] for row in rows]}, strategy, limit)


def regime(mode='risk_on', codes=()):
    return {'as_of': NOW, 'regime': {'mode': mode}, 'candidates': [{'code': code, 'holding_plan': {'minimum_calendar_days': 7}} for code in codes]}


class SelectionTests(unittest.TestCase):
    def test_max_three_and_same_family_dedup(self):
        rows = [make('000001', '成长优选A', score=88), make('000002', '成长优选C', score=89), make('000003', '价值优选A', score=83), make('000004', '均衡优选A', score=80)]
        sections = run(rows, limit=99)
        self.assertEqual(len(sections[0]['funds']), 3)
        self.assertEqual([f['code'] for f in sections[0]['funds']], ['000002', '000003', '000004'])
        self.assertEqual(sections[0]['eligible_count'], 3)
        self.assertEqual(sections[0]['eligible_share_count'], 4)

    def test_family_dedup_preserves_currency_and_different_strategy(self):
        rows = [make('1', '某基金人民币A'), make('2', '某基金美元A'), make('3', '另基金A', score=79)]
        picks = run(rows)[0]['funds']
        self.assertEqual({f['code'] for f in picks}, {'1', '2', '3'})

    def test_real_strategy_candidate_prioritized_over_higher_observation_score(self):
        rows = [make('1', '候选基金A', score=75, action='分批配置候选'), make('2', '高分观察A', score=95), make('3', '另一观察A', score=90)]
        section = run(rows, regime(codes=['1']))[0]
        self.assertEqual(section['status'], 'candidate')
        self.assertEqual(section['funds'][0]['code'], '1')
        self.assertEqual(section['funds'][0]['role'], 'candidate')
        self.assertFalse(section['funds'][0]['execution_eligible'])

    def test_no_candidates_are_observation_not_recommendation(self):
        sections = run([make('1', '观察基金A')], regime())
        self.assertEqual(sections[0]['status'], 'observation')
        self.assertEqual(sections[0]['display_title'], '观察优选')
        self.assertEqual(sections[0]['funds'][0]['role'], 'observation')

    def test_unknown_stale_or_defensive_strategy_never_makes_active_cards(self):
        rows = [make('1', '候选基金A', action='分批配置候选')]
        for strategy in (None, regime('unknown', ['1']), regime('defensive', ['1']), {**regime(codes=['1']), 'as_of': '2026-10-29T16:00:00+08:00'}):
            pick = run(rows, strategy)[0]['funds'][0]
            self.assertEqual(pick['role'], 'observation')
            self.assertNotIn('配置候选', pick['action'])
            self.assertTrue(all('第一批' not in step for step in pick['operation_plan']['steps']))

    def test_observation_replaces_previous_existing_position_instructions(self):
        row = make('1', '候选基金A', action='分批配置候选')
        row[2]['operation_plan'].update({
            'existing_position': '已有配置满足计划时评估分批新增。',
            'entry_conditions': ['第一批买入三分之一'],
        })
        card = run([row])[0]['funds'][0]
        self.assertEqual(card['role'], 'observation')
        self.assertIn('不安排新增', card['operation_plan']['existing_position'])
        self.assertNotIn('评估分批新增', card['operation_plan']['existing_position'])
        self.assertNotIn('第一批买入', card['operation_plan']['entry_conditions'])

    def test_seven_day_candidate_label_is_downgraded_without_fresh_strategy(self):
        row = make('1', '候选基金A', action='7 天以上研究候选')
        card = run([row])[0]['funds'][0]
        self.assertEqual(card['role'], 'observation')
        self.assertNotIn('研究候选', card['action'])

    def test_declared_source_type_wins_over_theme_name(self):
        self.assertEqual(_classify({'fund_type': 'QDII-股票', 'name': '全球黄金矿业股票A'}, {})[0], 'overseas_equity')
        self.assertEqual(_classify({'fund_type': '债券型-长债', 'name': '稳利增强债券A'}, {})[0], 'bond')

    def test_same_currency_share_classes_deduplicate_before_currency_suffix(self):
        self.assertEqual(_family({'name': '全球债券A（人民币）'}), _family({'name': '全球债券C（人民币）'}))
        self.assertNotEqual(_family({'name': '全球债券A（人民币）'}), _family({'name': '全球债券C（美元）'}))

    def test_no_stale_future_or_insufficient_fake_picks(self):
        for quality, nav_date in (('stale', '2026-10-01'), ('insufficient', '2026-10-29'), ('ok', '2026-11-01'), ('ok', None)):
            row = make('1', '样本基金A')
            row[1]['quality'], row[1]['nav_date'], row[0]['nav_date'] = quality, nav_date, nav_date
            self.assertEqual(run([row]), [])
        self.assertEqual(run([]), [])

    def test_bond_subclasses_and_equity_index_are_separated(self):
        rows = [make('1', '名称随意', '债券型-短债'), make('2', '名称随意2', '债券型-纯债'),
                make('3', '名称随意3', '债券型-混合二级'), make('4', '名称随意4', '债券型-可转债'),
                make('5', '银行沪深300指数A', '指数型-股票'), make('6', '名称随意6', '货币型')]
        self.assertEqual({s['id'] for s in run(rows)},
                         {'short_bond', 'bond', 'secondary_bond', 'convertible_bond', 'sector_technology', 'money'})
        self.assertNotIn('index_csi300', {s['id'] for s in run(rows)})

    def test_overseas_bond_not_ranked_against_equity_and_gold_separate(self):
        rows = [make('1', '美国股票A', 'QDII-股票'), make('2', '全球债券A', 'QDII-债券'),
                make('3', '显示标识', '黄金商品型')]
        rows[0][0].pop('holdings')
        self.assertEqual({s['id'] for s in run(rows)}, {'overseas_bond', 'gold'})

    def test_gold_equity_company_theme_does_not_override_declared_stock_type(self):
        rows = [make('1', '独立甲A', '股票型'), make('2', '独立乙B', '指数型-股票')]
        for fund, _, _ in rows:
            fund['holdings'] = portfolio(['黄金'])
        result = run(rows)
        self.assertEqual({s['id'] for s in result}, {'sector_gold_equity'})
        self.assertEqual({f['asset_category'] for s in result for f in s['funds']}, {'equity_active', 'equity_index'})

    def test_theme_names_alone_never_fill_recommendations(self):
        rows = [make('000001', '白酒精选股票A', action='分批配置候选')]
        rows[0][0].pop('holdings')
        self.assertEqual(run(rows, regime(codes=['000001'])), [])
        rows[0][0]['holdings'] = portfolio(['银行'])
        cards = run(rows, regime(codes=['000001']))
        self.assertNotIn('sector_liquor', {s['id'] for s in cards})
        card = next(s for s in cards if s['id']=='sector_banking')['funds'][0]
        self.assertEqual(card['board_match']['matched_disclosed_pct'], 100)
        self.assertEqual(card['role'], 'candidate')
        self.assertEqual(card['recommendation_index'], 80)
        self.assertFalse(card['execution_eligible'])

    def test_numeric_recommendation_keeps_historical_score_and_risk_caps(self):
        self.assertEqual(recommendation_index(95, 'candidate', '7 天以上研究候选', 'risk_on', []), 95)
        self.assertEqual(recommendation_index(95, 'observation', '继续观察', 'risk_on', []), 71)
        self.assertEqual(recommendation_index(95, 'candidate', '暂缓新增', 'risk_on', []), 59)
        self.assertEqual(recommendation_index(95, 'candidate', '继续观察', 'defensive', []), 39)
        self.assertIsNone(recommendation_index(95, 'candidate', '继续观察', 'unknown', []))
        row = make('000001', '高分综合股票A', score=95, action='暂缓新增')
        card = run([row], regime())[0]['funds'][0]
        self.assertEqual(card['score'], 95)
        self.assertEqual(card['recommendation_index'], 59)

    def test_defensive_safety_before_score_and_high_score_risk_reason(self):
        risky = make('003121', '示例超短债C', '债券型-短债', score=92, action='暂缓新增', vol=1.56, vol_limit=1.5, dd=-.2, dd_limit=1, asset='short_bond')
        safe = make('000009', '其他超短债A', '债券型-短债', score=80, vol=.5, vol_limit=1.5, dd=-.1, dd_limit=1, asset='short_bond')
        section = run([risky, safe])[0]
        self.assertEqual(section['funds'][0]['code'], '000009')
        pick = section['funds'][1]
        self.assertEqual(pick['action'], '暂缓新增')
        self.assertIn('1.56%', pick['brief']['risk'])
        self.assertIn('1.5%', pick['brief']['risk'])
        self.assertIn('92', pick['brief']['reason'])
        self.assertIn('不能覆盖风险超限', pick['brief']['reason'])
        self.assertEqual(pick['role'], 'observation')

    def test_tie_breaking_lower_volatility_then_shallower_drawdown(self):
        rows = [make('3', '基金丙A', vol=9, dd=-4), make('1', '基金甲A', vol=8, dd=-4), make('2', '基金乙A', vol=8, dd=-2)]
        self.assertEqual([f['code'] for f in run(rows)[0]['funds']], ['2', '1', '3'])

    def test_default_and_invalid_limit_use_three_but_explicit_lower_limit_is_kept(self):
        rows = [make(str(index), f'不同策略{suffix}A', score=90 - index)
                for index, suffix in enumerate(('甲', '乙', '丙', '丁', '戊'), 1)]
        snapshot = {'as_of': NOW, 'funds': [row[0] for row in rows]}
        quant, analysis = [row[1] for row in rows], {'funds': [row[2] for row in rows]}
        self.assertEqual(MAX_RESEARCH_PER_BOARD, 3)
        self.assertEqual(MAX_DISPLAY_PER_BOARD, 3)
        self.assertEqual(len(build_sections(snapshot, quant, analysis)[0]['funds']), 3)
        for limit in (99, None, 'invalid', float('inf')):
            with self.subTest(limit=limit):
                self.assertEqual(len(run(rows, limit=limit)[0]['funds']), 3)
        self.assertEqual(len(run(rows, limit=1)[0]['funds']), 1)
        self.assertEqual(len(run(rows, limit=2)[0]['funds']), 2)
        self.assertIn('最多3只', run(rows)[0]['selection_method'])

    def test_low_score_risk_reason_does_not_claim_strong_trend(self):
        card = run([make('1', '低分样本股票A', score=0, action='暂缓新增', dd=-25)])[0]['funds'][0]
        self.assertIn('0 分', card['brief']['reason'])
        self.assertNotIn('较强', card['brief']['reason'])
        self.assertEqual(card['role'], 'observation')

    def test_blocked_quant_not_overridden_by_optimistic_analysis(self):
        row = make('1', '基金A', action='暂缓新增')
        row[2]['action'] = '买入'
        card = run([row], regime(codes=['1']))[0]['funds'][0]
        self.assertEqual(card['action'], '暂缓新增')
        self.assertEqual(card['role'], 'observation')

    def test_brief_lengths_and_input_immutability(self):
        row = make('1', '测试A', action='考虑减仓（如持有）')
        original = copy.deepcopy(row)
        card = run([row])[0]['funds'][0]
        self.assertEqual(row, original)
        self.assertEqual(card['reason'], '原始完整分析理由')
        self.assertEqual(card['action'], '考虑减仓（如持有）')
        self.assertTrue(all(len(value) <= 100 for value in card['brief'].values()))
        self.assertIn('不作新增推荐', card['brief']['headline'])

    def test_limit_zero_and_unscored_quality_are_honest(self):
        self.assertEqual(run([make('1', '测试A')], limit=0), [])
        card = run([make('1', '测试A', score=None)])[0]['funds'][0]
        self.assertIsNone(card['score'])
        self.assertEqual(card['brief']['score_label'], '研究分待核验')


if __name__ == '__main__':
    unittest.main()
