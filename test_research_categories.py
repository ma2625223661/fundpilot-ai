"""Portfolio classification, independent memberships and coverage diagnostics."""
import copy
import unittest
from unittest.mock import patch
from research_categories import BOARDS, REFERENCE_ORDER, SCHEMA_VERSION, board_for, boards_for, board_matches_for, build_board_coverage
from research_holdings import BOARD_TAGS, verify_board
from research_selection import _classify
from test_holdings_fixtures import portfolio

STAMP = '2026-10-30T16:00:00+08:00'


def fund(code='000001', name='随意展示名称', tags=('软件开发',)):
    return {'code': code, 'name': name, 'fund_type': '股票型', 'holdings': portfolio(tags),
            'nav_date': STAMP[:10], 'eligible': True}


class BoardTests(unittest.TestCase):
    def test_reference_boards_and_aliases_are_preserved(self):
        self.assertEqual(SCHEMA_VERSION, 9)
        self.assertEqual(len(REFERENCE_ORDER), 83)
        self.assertEqual(len([b for b in BOARDS.values() if not b.get('dynamic')]), 120)
        self.assertEqual(len(set(REFERENCE_ORDER)), 83)
        self.assertTrue(all(isinstance(board['aliases'], list) for board in BOARDS.values()))

    def test_renaming_cannot_change_any_membership_or_primary_board(self):
        value = fund(tags=['银行'])
        expected = boards_for(value, 'equity_active', STAMP)
        for name in ('白酒精选A', '半导体科技C', '红利低波', '沪深300', '黄金', '', '任意文字'):
            with self.subTest(name=name):
                value['name'] = name
                self.assertEqual(boards_for(value, 'equity_active', STAMP), expected)
                self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'sector_banking')

    def test_all_supported_themes_use_explicit_stock_tags(self):
        for identity, tags in BOARD_TAGS.items():
            with self.subTest(board=identity):
                value = fund(tags=[sorted(tags)[0]])
                boards = {item['id']: item for item in board_matches_for(value, 'equity_active', STAMP)}
                self.assertIn(identity, boards)
                self.assertEqual(boards[identity]['board_match']['matched_disclosed_pct'], 100)

    def test_parent_and_child_memberships_are_verified_independently(self):
        value = fund(tags=['软件开发', 'CPO'])
        ids = {board['id'] for board in board_matches_for(value, 'equity_active', STAMP)}
        self.assertIn('sector_technology', ids)
        self.assertIn('sector_cpo', ids)
        self.assertNotIn('sector_pcb', ids)
        self.assertNotIn('sector_semiconductor', ids)
        self.assertEqual([b['id'] for b in boards_for(value, 'equity_active', STAMP)], ['sector_cpo'])
        value['holdings'] = portfolio(['CPO'])
        self.assertEqual({b['id'] for b in boards_for(value, 'equity_active', STAMP)}, {'sector_cpo'})

    def test_each_board_has_independent_numerator_and_common_denominator(self):
        value = fund(tags=['银行'])
        value['holdings']['rows'] = [dict(portfolio(['银行'])['rows'][0], weight_pct=40),
            dict(portfolio(['银行', '电力'])['rows'][1], weight_pct=10),
            dict(portfolio(['电力'])['rows'][0], code='600003', weight_pct=5)]
        banks = verify_board(value, 'sector_banking', STAMP)
        power = verify_board(value, 'sector_power', STAMP)
        self.assertAlmostEqual(banks['matched_disclosed_pct'], 50 / 55 * 100)
        self.assertAlmostEqual(power['matched_disclosed_pct'], 15 / 55 * 100)
        self.assertEqual(banks['status'], 'matched')
        self.assertEqual(power['status'], 'mismatch')

    def test_majority_without_rounding_or_nav_floor(self):
        value = fund(tags=['银行'])
        value['holdings']['rows'] = [dict(portfolio(['银行'])['rows'][0], weight_pct=.75),
            dict(portfolio(['电力'])['rows'][1], weight_pct=.25)]
        self.assertIn('sector_banking', {b['id'] for b in boards_for(value, 'equity_active', STAMP)})
        value['holdings']['rows'][0]['weight_pct'] = .25
        self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'holdings_unclassified')
        value['holdings']['rows'][0]['weight_pct'] = .250001
        self.assertIn('sector_banking', {b['id'] for b in boards_for(value, 'equity_active', STAMP)})

    def test_unknown_tags_stay_in_denominator(self):
        value = fund(tags=['银行'])
        value['holdings']['rows'][1].update(weight_pct=8, tag_status='unknown', tags=[])
        self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'holdings_unclassified')

    def test_invalid_duplicate_future_stale_rows_do_not_pass(self):
        for mode in ('missing', 'duplicate', 'future', 'stale', 'invalid', 'unknown_identity'):
            value = fund(tags=['银行'])
            if mode == 'missing':
                value.pop('holdings')
            elif mode == 'duplicate':
                value['holdings']['rows'][1]['code'] = value['holdings']['rows'][0]['code']
            elif mode in ('future', 'stale'):
                value['holdings']['report_date'] = '2026-12-31' if mode == 'future' else '2025-01-01'
            elif mode == 'invalid':
                value['holdings']['invalid_row_count'] = 1
            else:
                value['holdings']['rows'][1].pop('instrument_type')
            with self.subTest(mode=mode):
                self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'holdings_unclassified')

    def test_index_style_region_titles_never_prove_exposure(self):
        value = fund(name='沪深300红利低波港股创新药')
        self.assertEqual({b['id'] for b in boards_for(value, 'equity_active', STAMP)}, {'sector_technology'})
        for identity in ('index_csi300', 'style_dividend_low_volatility', 'overseas_hk_innovative_drug'):
            self.assertEqual(verify_board(value, identity, STAMP)['status'], 'unknown')

    def test_mainland_consumer_holdings_never_claim_cross_market_exposure(self):
        value = fund(tags=['商贸零售'])
        self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'sector_consumer')
        match = verify_board(value, 'overseas_hugangshen_consumer', STAMP)
        self.assertEqual(match['status'], 'unknown')
        self.assertEqual(match['matched_disclosed_pct'], 100)

    def test_explicit_nonstock_source_types_stay_separate(self):
        for kind, expected in [('货币型', 'money'), ('债券型-短债', 'short_bond'),
                               ('债券型-长债', 'bond'), ('黄金商品型', 'gold')]:
            value = fund(name='白酒银行半导体', tags=['银行'])
            value['fund_type'] = kind
            self.assertEqual(board_for(value, _classify(value, {})[0], STAMP)['id'], expected)

    def test_no_source_type_never_infers_from_title(self):
        for name in ('货币基金', '黄金', '银行', '国债', '海外科技'):
            self.assertEqual(_classify({'name': name}, {})[0], 'unclassified')

    def test_fake_matched_status_without_strict_ratio_cannot_unlock(self):
        value = fund(tags=['银行'])
        for match in ({'status': 'matched'}, {'status': 'matched', 'matched_weight_pct': 75, 'disclosed_weight_pct': 100},
                      {'status':'matched','matched_weight_pct':100,'disclosed_weight_pct':100,'rule_version':'disclosed_stock_gt75_v1'}):
            with patch('research_holdings.verify_board', return_value=match):
                self.assertEqual(board_for(value, 'equity_active', STAMP)['id'], 'holdings_unclassified')

    def test_coverage_counts_memberships_and_deduplicates_codes(self):
        value = fund(tags=['软件开发', 'CPO'])
        snapshot = {'as_of': STAMP, 'funds': [value]}
        quant = [{'code': value['code'], 'quality': 'ok', 'nav_date': STAMP[:10]}]
        original = copy.deepcopy((value, snapshot, quant))
        coverage = build_board_coverage({'funds': [value, value]}, [value['code'], value['code']], snapshot, quant, [])
        by_id = {board['id']: board for board in coverage}
        self.assertEqual(by_id['sector_cpo']['screened_count'], 1)
        self.assertEqual(by_id['sector_cpo']['deep_count'], 1)
        self.assertEqual(by_id['sector_cpo']['matched_holdings_count'], 1)
        self.assertEqual(by_id['sector_technology']['screened_count'], 0)
        self.assertEqual(by_id['sector_technology']['deep_count'], 0)
        self.assertEqual(by_id['sector_banking']['deep_count'], 0)
        self.assertEqual((value, snapshot, quant), original)

    def test_missing_holdings_not_counted_under_named_theme(self):
        value = fund(name='银行精选')
        value.pop('holdings')
        coverage = build_board_coverage({'funds': [value]}, [value['code']], {'as_of': STAMP, 'funds': [value]}, [], [])
        by_id = {board['id']: board for board in coverage}
        self.assertEqual(by_id['sector_banking']['screened_count'], 0)
        self.assertEqual(by_id['holdings_unclassified']['screened_count'], 1)
        self.assertEqual(by_id['holdings_unclassified']['deep_count'], 1)
        self.assertEqual(by_id['holdings_unclassified']['research_gap']['examples'][0]['code'], value['code'])

    def test_stale_quant_is_not_verified_research(self):
        value = fund(tags=['银行'])
        coverage = build_board_coverage({'funds': [value]}, [value['code']], {'as_of': STAMP, 'funds': [value]},
            [{'code': value['code'], 'quality': 'ok', 'nav_date': '2026-01-01'}], [])
        board = next(b for b in coverage if b['id'] == 'sector_banking')
        self.assertEqual(board['valid_quant_count'], 0)
        self.assertEqual(board['research_gap']['category'], 'stale_data')


if __name__ == '__main__':
    unittest.main()
