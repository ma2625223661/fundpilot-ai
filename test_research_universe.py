from test_holdings_fixtures import portfolio
from research_holdings import BOARD_TAGS
import json
import copy
import unittest
from datetime import datetime
from unittest.mock import patch
import research_universe as ru


def rank_text(page=1, total=2, pages=1, codes=('000001', '000002')):
    rows = []
    for code in codes:
        rows.append(','.join([code, '测试混合' + code, 'CS', datetime.now(ru.CHINA).date().isoformat(), '1.2', '1.3', '0.2', '1', '3', '5', '8', '12', '', '', '', '', '2020-01-01', '1']))
    return 'var rankData={datas:' + json.dumps(rows) + f',allRecords:{total},pageIndex:{page},pageNum:1000,allPages:{pages}' + '};'


class UniverseTests(unittest.TestCase):
    def setUp(self):
        ru._cache = None

    def row(self, code, name='测试成长混合A', kind='混合型-偏股', **kwargs):
        row = {'code': code, 'name': name, 'fund_type': kind, 'nav_date': datetime.now(ru.CHINA).date().isoformat(), 'provider_purchase_flag': '1', 'return_1w': 1, 'return_1m': 3, 'return_3m': 5}
        # Test scenarios explicitly supply synthetic portfolios; this fixture
        # shorthand is not used by any application classification code.
        scenario = next((key for key in sorted(BOARD_TAGS, key=lambda k: -len(ru.BOARDS[k]['label']))
                         if ru.BOARDS[key]['label'] in name), 'sector_technology')
        row['holdings'] = portfolio([sorted(BOARD_TAGS[scenario])[0]])
        row.update(kwargs); row.update(ru.classify(row)); return row

    def test_parse_returns_and_alipay_remains_unverified(self):
        result = ru.parse_rank_page(rank_text())
        self.assertEqual(result['allRecords'], 2)
        self.assertEqual(result['funds'][0]['return_1m'], 3)
        self.assertEqual(result['funds'][0]['return_1y'], 12)
        self.assertEqual(result['funds'][0]['alipay_available'], 'unverified')

    def test_catalog_is_data_only_and_deduplicated(self):
        catalog = ru.parse_catalog('var r = [["000001","TEST","测试","混合型"],["000001","TEST","测试","混合型"]];')
        self.assertEqual(len(catalog), 1)
        with self.assertRaises(ValueError):
            ru.parse_catalog('var r = evil();')

    def test_lockups_exchange_only_stale_and_unknown_purchase_excluded(self):
        for name in ['测试一年持有混合', '测试90天债券', '测试定开债券', '测试ETF', '测试LOF']:
            self.assertFalse(self.row('000001', name)['eligible'], name)
        self.assertTrue(self.row('000001', '测试ETF联接A', '指数型-股票')['eligible'])
        self.assertFalse(self.row('000001', '测试基金Y')['eligible'])
        self.assertTrue(self.row('000001', '测试养老产业指数A', '指数型-股票')['eligible'])
        self.assertFalse(self.row('000001', nav_date='2020-01-01')['eligible'])
        self.assertFalse(self.row('000001', provider_purchase_flag='0')['eligible'])

    def test_diverse_selection_deduplicates_share_classes_and_reserves_defensive(self):
        rows = [self.row('000001', '科技成长混合A'), self.row('000002', '科技成长混合C'),
                self.row('000003', '测试沪深300联接A', '指数型-股票'),
                self.row('000004', '测试超短债A', '债券型-短债'),
                self.row('000005', '测试黄金联接A', '指数型-股票'),
                self.row('000006', '医药创新股票A', '股票型')]
        codes = ru.pick_research_codes({'funds': rows}, 5)
        self.assertIn('000004', codes)
        self.assertFalse('000001' in codes and '000002' in codes)
        self.assertEqual(len(codes), 5)

    def test_partial_page_failure_is_not_claimed_complete(self):
        catalog = 'var r = [["000001","T","测试","混合型-偏股"]];'
        def fetch(url):
            if 'fundcode_search' in url:
                return catalog
            if 'pi=1&' in url:
                return rank_text(total=2000, pages=2, codes=('000001',))
            raise TimeoutError()
        with patch('research_universe.fetch_text', side_effect=fetch):
            result = ru.collect_universe()
        self.assertEqual(result['coverage']['failed_pages'], [2])
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['coverage']['alipay_verified_count'], 0)
        self.assertEqual(len(result['funds']), 1)
        self.assertTrue(ru.collect_universe()['cache_hit'])

    def test_each_board_researches_at_most_three_distinct_families(self):
        rows = [self.row(f'{index + 1:06d}', f'白酒{suffix}策略A')
                for index, suffix in enumerate(('甲', '乙', '丙', '丁', '戊', '己'))]
        rows += [self.row(f'{index + 101:06d}', f'半导体{suffix}策略A')
                 for index, suffix in enumerate(('甲', '乙', '丙', '丁', '戊', '己'))]
        codes = ru.pick_research_codes({'funds': rows}, 96)
        selected = [row for row in rows if row['code'] in codes]
        self.assertEqual(len(selected), 6)
        for identity in ('sector_liquor', 'sector_semiconductor'):
            self.assertEqual(sum(row['board_id'] == identity for row in selected), 3)
        self.assertEqual(ru.MAX_RESEARCH_PER_BOARD, 3)
        self.assertEqual(ru.MAX_DISPLAY_PER_BOARD, 3)

    def test_holdings_reclassification_caps_converging_boards_before_deep_research(self):
        rows = [self.row(f'{index + 1:06d}', f'科技{suffix}策略A')
                for index, suffix in enumerate(('甲', '乙', '丙', '丁'))]
        rows += [self.row(f'{index + 101:06d}', f'CPO{suffix}策略A')
                 for index, suffix in enumerate(('甲', '乙', '丙', '丁'))]
        codes = ru.pick_research_codes({'funds': rows}, 96)
        self.assertEqual(len(codes), 6)
        for fund in rows:
            fund['holdings'] = {'status': 'ok', 'report_date': '2026-09-30', 'rows': [
                {'code': f'{600001 + index}', 'name': f'合成持仓{index}', 'weight_pct': 10,
                 'tag_status': 'ok', 'instrument_type': 'stock', 'tags': ['CPO']}
                for index in range(4)]}
        before = copy.deepcopy((rows, codes))
        with patch('research_universe.fetch_text', side_effect=AssertionError('offline finalization')):
            finalized = ru.cap_research_codes(codes, rows, as_of='2026-10-30')
        self.assertEqual(len(finalized), 3)
        self.assertEqual(finalized, codes[:3])
        self.assertTrue(all(ru._theme(fund, as_of='2026-10-30') == 'sector_cpo' for fund in rows))
        self.assertEqual((rows, codes), before)

    def test_final_research_cap_preserves_separate_boards_and_deduplicates_inputs(self):
        rows = [self.row('000001', '科技甲策略A'), self.row('000002', '科技甲策略C'),
                self.row('000003', '科技乙策略A'), self.row('000004', '白酒甲策略A')]
        codes = ['000001', '000001', '999999', '000002', '000003', '000004']
        self.assertEqual(set(ru.cap_research_codes(codes, rows)), {'000001', '000003', '000004'})

    def test_research_board_finalization_uses_report_date_instead_of_wall_clock(self):
        rows = [self.row(f'{index + 1:06d}', f'科技{suffix}策略A')
                for index, suffix in enumerate(('甲', '乙', '丙', '丁'))]
        rows += [self.row(f'{index + 101:06d}', f'CPO{suffix}策略A')
                 for index, suffix in enumerate(('甲', '乙', '丙', '丁'))]
        for fund in rows:
            fund['holdings'] = {'status': 'ok', 'report_date': '2026-09-30', 'rows': [
                {'code': f'{600001 + index}', 'weight_pct': 10, 'instrument_type': 'stock',
                 'tag_status': 'ok', 'tags': ['CPO']}
                for index in range(4)]}
        codes = [fund['code'] for fund in rows]
        self.assertEqual(len(ru.cap_research_codes(codes, rows, as_of='2026-10-30')), 3)
        self.assertEqual(len(ru.cap_research_codes(codes, rows, as_of='2026-09-01')), 3)
        self.assertEqual(len(ru.pick_research_codes({'funds': rows, 'as_of': '2026-09-01'})), 8)
        self.assertEqual(len(ru.pick_research_codes({'funds': rows, 'as_of': '2026-10-30'})), 3)

    def test_unresearched_boards_rotate_across_small_budget_rounds(self):
        rows = [self.row(f'{index + 1:06d}', name) for index, name in enumerate(
                ('白酒精选A', '食品饮料精选A', 'CXO精选A', '油气精选A', '消费精选A'))]
        for value, tag in zip(rows, ('白酒', '食品加工', 'CRO', '油气开采', '商贸零售')):
            value['holdings'] = portfolio([tag])
            value.update(ru.classify(value))
        universe = {'funds': rows}
        previous, seen = None, set()
        before = copy.deepcopy(universe)
        rounds = []
        for _ in range(3):
            codes = ru.pick_research_codes(universe, limit=2, previous_coverage=previous)
            selected = {fund['board_id'] for fund in rows if fund['code'] in codes}
            rounds.append(selected)
            seen.update(selected)
            previous = [{'id': fund['board_id'], 'eligible_count': 1,
                         'deep_count': int(fund['code'] in codes),
                         'status': 'insufficient' if fund['code'] in codes else 'not_researched'}
                        for fund in rows]
        self.assertEqual(len(seen), 5)
        self.assertFalse(rounds[0].intersection(rounds[1]))
        self.assertEqual(universe, before)

    def test_rotation_preserves_total_budget_share_family_and_current_eligibility(self):
        labels = [ru.BOARDS[key]['label'] for key in ru.BOARDS if key.startswith('sector_')][:40]
        rows = [self.row(f'{board * 10 + variant + 1:06d}', label + suffix + 'A')
                for board, label in enumerate(labels) for variant, suffix in enumerate(('甲', '乙', '丙', '丁'))]
        rows += [self.row('900001', '白酒甲C'), self.row('900002', '无效一年持有A')]
        previous = [{'id': identity, 'deep_count': 0, 'eligible_count': 999,
                     'status': 'not_researched'} for identity in ru.BOARDS]
        codes = ru.pick_research_codes({'funds': rows}, limit=999, previous_coverage=previous)
        selected = [fund for fund in rows if fund['code'] in codes]
        self.assertEqual(len(codes), 96)
        self.assertEqual(len(set(map(ru._family, selected))), len(codes))
        self.assertNotIn('900002', codes)
        self.assertFalse('000001' in codes and '900001' in codes)
        counts = {}
        for fund in selected:
            counts[fund['board_id']] = counts.get(fund['board_id'], 0) + 1
        self.assertTrue(all(count <= 3 for count in counts.values()))

    def test_unresolved_board_tries_other_family_but_can_fall_back_to_old_samples(self):
        rows = [self.row('000001', '白酒甲A', return_1m=99), self.row('000002', '白酒甲C', return_1m=98),
                self.row('000003', '白酒乙A', return_1m=90), self.row('000004', '白酒丙A', return_1m=80),
                self.row('000005', '白酒丁A', return_1m=1)]
        examples = [{'code': '000001', 'name': '白酒甲A'}, {'code': '000003', 'name': '白酒乙A'},
                    {'code': '000004', 'name': '白酒丙A'}]
        for status in ('holdings_pending', 'holdings_mismatch', 'insufficient'):
            previous = [{'id': 'sector_liquor', 'deep_count': 3, 'status': status,
                         'research_gap': {'category': 'holdings', 'examples': examples}}]
            with self.subTest(status=status):
                codes = ru.pick_research_codes({'funds': rows}, limit=3, previous_coverage=previous)
                self.assertEqual(codes[0], '000005')
                self.assertEqual(len(codes), 3)
                self.assertFalse('000001' in codes and '000002' in codes)
                # Soft preference never removes all old legal candidates.
                self.assertEqual(len(ru.pick_research_codes({'funds': rows[:4]}, limit=3,
                                                         previous_coverage=previous)), 3)

    def test_resolved_boards_keep_rank_and_malformed_history_is_ignored(self):
        rows = [self.row('000001', '白酒甲A', return_1m=99), self.row('000002', '白酒乙A', return_1m=1)]
        baseline = ru.pick_research_codes({'funds': rows}, limit=1)
        previous = [{'id': 'sector_liquor', 'deep_count': 1, 'status': 'observation',
                     'research_gap': {'examples': [{'code': '000001', 'name': '白酒甲A'}]}}]
        self.assertEqual(ru.pick_research_codes({'funds': rows}, limit=1, previous_coverage=previous), baseline)
        for invalid in (None, {}, 'old report', [None, {}, {'id': 'unknown'}, {'id': []},
                        {'id': 'sector_liquor', 'deep_count': float('nan')}],
                        [{'id': 'sector_liquor', 'status': 'insufficient', 'research_gap': {'examples': [None, {'code': []}]}}]):
            self.assertEqual(ru.pick_research_codes({'funds': rows}, limit=1, previous_coverage=invalid), baseline)

    def test_duplicate_rows_make_incomplete_coverage(self):
        catalog = 'var r = [["000001","T","测试","混合型-偏股"]];'
        with patch('research_universe.fetch_text', side_effect=lambda url: catalog if 'fundcode_search' in url else rank_text(codes=('000001', '000001'))):
            result = ru.collect_universe()
        self.assertEqual(result['coverage']['duplicate_count'], 1)
        self.assertFalse(result['coverage']['complete'])


if __name__ == '__main__':
    unittest.main()
