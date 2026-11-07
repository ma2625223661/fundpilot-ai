"""Regression cases discovered while verifying the user-supplied fund list."""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from research_holdings import HOLDINGS_RULE_VERSION, verify_board
from research_universe import CHINA, classify, plan_research_codes


def stock(code, name, weight, tags):
    return {'code': code, 'name': name, 'weight_pct': weight,
            'instrument_type': 'stock', 'tag_status': 'ok', 'tags': tags,
            'tag_source_url': 'https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SH' + code}


class ScreenshotEvidenceRules(unittest.TestCase):
    def fund(self):
        # 002605's 2026-09-30 disclosed ten-stock weights. These are fixed
        # regression data, never injected into production collection.
        rows = [stock(code, name, weight, tags) for code, name, weight, tags in [
            ('600519', '贵州茅台', 8.92, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('003010', '若羽臣', 7.19, ['商贸零售', '互联网电商']),
            ('603919', '金徽酒', 6.57, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('600809', '山西汾酒', 6.49, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('603369', '今世缘', 6.39, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('603198', '迎驾贡酒', 6.38, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('000568', '泸州老窖', 6.15, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('601888', '中国中免', 5.95, ['商贸零售']),
            ('000596', '古井贡酒', 5.41, ['食品饮料', '白酒Ⅱ', '白酒']),
            ('601579', '会稽山', 5.24, ['食品饮料', '非白酒', '其他酒类', '酿酒概念', '白酒']),
        ]]
        return {'code': '002605', 'name': '融通新消费灵活配置混合',
                'holdings': {'status': 'ok', 'report_date': '2026-09-30', 'rows': rows}}

    def test_non_liquor_industry_overrides_concept_without_dropping_denominator_or_evidence(self):
        fund = self.fund()
        before = copy.deepcopy(fund)
        result = verify_board(fund, 'sector_liquor', '2026-10-30')
        self.assertEqual(result['rule_version'], HOLDINGS_RULE_VERSION)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['disclosed_weight_pct'], 64.69)
        self.assertEqual(result['matched_weight_pct'], 46.31)
        self.assertAlmostEqual(result['matched_disclosed_pct'], 71.58757149482146)
        self.assertNotIn('会稽山', result['matched_names'])
        wine = next(row for row in result['stock_evidence'] if row['code'] == '601579')
        self.assertFalse(wine['matched'])
        self.assertTrue(wine['classification_known'])
        self.assertEqual(wine['excluded_by_industry_tags'], ['其他酒类', '非白酒'])
        self.assertIn('行业分类优先', wine['match_exclusion_reason'])
        self.assertEqual(fund, before)
        self.assertEqual(verify_board(fund, 'sector_consumer', '2026-10-30')['matched_disclosed_pct'], 100)
        self.assertGreater(verify_board(fund, 'sector_food_beverage', '2026-10-30')['matched_weight_pct'], 46.31)

    def test_each_explicit_non_liquor_tag_blocks_a_concept_match(self):
        for industry in ['非白酒', '其他酒类']:
            fund = self.fund()
            fund['holdings']['rows'] = [stock('601579', '名称不参与分类', 8, [industry, '白酒'])]
            result = verify_board(fund, 'sector_liquor', '2026-10-30')
            self.assertEqual(result['status'], 'mismatch', industry)
            self.assertEqual(result['matched_weight_pct'], 0, industry)
            self.assertEqual(result['disclosed_weight_pct'], 8, industry)

    def test_name_and_unknown_tags_cannot_exclude_or_create_industry_evidence(self):
        fund = self.fund()
        fund['holdings']['rows'] = [stock('600519', '非白酒或其他酒类', 8, ['白酒Ⅱ'])]
        self.assertEqual(verify_board(fund, 'sector_liquor', '2026-10-30')['matched_disclosed_pct'], 100)
        fund['holdings']['rows'][0].update(tag_status='unknown', tags=['非白酒', '白酒'])
        self.assertEqual(verify_board(fund, 'sector_liquor', '2026-10-30')['status'], 'unknown')

    def index_lof(self, **updates):
        row = {'code': '012414', 'name': '招商中证白酒指数(LOF)C',
               'fund_type': '指数型-股票', 'provider_purchase_flag': '1',
               'nav_date': datetime.now(CHINA).date().isoformat(), 'return_1m': 1,
               'alipay_available': 'unverified', 'redemption_terms': '完整规则待核验'}
        row.update(updates)
        return row

    def test_equity_index_lof_is_researchable_without_claiming_platform_sale(self):
        row = self.index_lof()
        result = classify(row)
        self.assertTrue(result['eligible'])
        self.assertEqual(row['alipay_available'], 'unverified')
        self.assertFalse(result['holding_rule_verified'])
        self.assertEqual(result['board_id'], 'holdings_unclassified')

    def test_lof_relaxation_preserves_type_and_transaction_gates(self):
        cases = [
            {'fund_type': '混合型-偏股'},
            {'fund_type': '指数型-股票-QDII'},
            {'fund_type': ''},
            {'provider_purchase_flag': '0'},
            {'nav_date': '2020-01-01'},
            {'name': '封闭三年持有指数(LOF)C'},
            {'name': '场内指数(LOF)C'},
            {'name': '测试ETF(LOF)C'},
            {'name': '测试REIT指数(LOF)C'},
        ]
        for updates in cases:
            self.assertFalse(classify(self.index_lof(**updates))['eligible'], updates)

    def ranking_row(self, code, ratio, reference_board=None, source_kind='user_reference'):
        row = {'code': code, 'name': '独立基金' + code, 'fund_type': '混合型-偏股', '_test_ratio': ratio}
        if reference_board:
            row['reference_candidate'] = {'source_kind': source_kind, 'requested_board_id': reference_board}
        return row

    def rank_plan(self, rows):
        # Isolate allocation from board assignment; requested-board overrides
        # are verified by the category integration tests owned by the caller.
        def board(fund, *_args, **_kwargs):
            return [{'id': 'sector_liquor', 'board_match': {'matched_disclosed_pct': fund['_test_ratio']}}]
        with patch('research_universe.boards_for', side_effect=board):
            return plan_research_codes([row['code'] for row in rows], rows, '2026-10-30')

    def test_three_source_list_members_precede_other_higher_ratio_candidates(self):
        rows = [self.ranking_row('001001', 100),
                self.ranking_row('009941', 100, 'sector_liquor'),
                self.ranking_row('012414', 100, 'sector_liquor', 'yangjibao'),
                self.ranking_row('002605', 71.5876, 'sector_liquor')]
        result = self.rank_plan(rows)
        self.assertEqual(result['board_targets']['sector_liquor'], ['009941', '012414', '002605'])
        self.assertEqual(result['selected_codes'], ['009941', '012414', '002605'])

    def test_reference_for_another_board_or_non_user_source_has_no_priority(self):
        rows = [self.ranking_row('002605', 71.5876, 'sector_consumer'),
                self.ranking_row('009941', 90, 'sector_liquor', 'web_search'),
                self.ranking_row('001001', 100), self.ranking_row('001002', 99),
                self.ranking_row('001003', 98)]
        result = self.rank_plan(rows)
        self.assertEqual(result['board_targets']['sector_liquor'], ['001001', '001002', '001003'])


if __name__ == '__main__':
    unittest.main()
