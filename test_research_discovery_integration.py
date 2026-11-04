"""Offline contracts for public discovery joining the automatic research flow."""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import Mock, patch

import research_auto as ra
import research_universe as ru
from research_categories import build_board_coverage


STAMP = '2026-10-30T10:30:00+08:00'
OLD_STAMP = '2026-10-29T10:30:00+08:00'


def universe_row(code, name='测试半导体混合C', eligible=True, score=5,
                 fund_type='混合型-偏股', **changes):
    row = {'code': code, 'name': name, 'fund_type': fund_type,
           'eligible': eligible, 'exclusion_reasons': [] if eligible else ['最短持有期限未通过'],
           'universe_bucket': 'medium_high', 'screen_group': '混合',
           'nav': 1.2, 'nav_date': STAMP[:10], 'return_1w': score,
           'return_1m': score, 'return_3m': score,
           'source_url': f'https://fund.eastmoney.com/{code}.html'}
    row.update(changes)
    return row


def hit(code, name='测试半导体混合C', fund_type='混合型-偏股', **changes):
    candidate = {'code': code, 'name': name, 'fund_type': fund_type,
                 'source_url': f'https://fund.eastmoney.com/{code}.html',
                 'search_url': 'https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=test',
                 'search_title': name, 'search_provider': 'eastmoney_search',
                 'searched_at': STAMP, 'status': 'discovery_only'}
    candidate.update(changes)
    return candidate


def search_board(candidates, identity='sector_semiconductor', **changes):
    board = {'board_id': identity, 'label': ru.BOARDS[identity]['label'],
             'query': ru.BOARDS[identity]['label'] + ' 基金', 'status': 'ok',
             'attempted': True, 'attempted_this_run': True, 'success': bool(candidates),
             'searched_at': STAMP, 'cache_hit': False, 'candidates': candidates, 'attempts': []}
    board.update(changes)
    return board


def discovery(boards):
    return {'as_of': STAMP, 'boards': boards,
            'sources': [{'id': 'discovery:offline-search', 'status': 'ok', 'fetched_at': STAMP}],
            'warnings': []}


def gap(identity='sector_semiconductor', status='no_match', **changes):
    row = {'id': identity, 'status': status, 'deep_count': 0, 'displayed_count': 0,
           'candidate_count': 0, 'valid_quant_count': 0, 'eligible_count': 0}
    row.update(changes)
    return row


class DiscoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        # An unexpected request must fail locally before any network is reached.
        network = patch('urllib.request.urlopen', side_effect=AssertionError('offline integration test'))
        self.network = network.start()
        self.addCleanup(network.stop)
        paid = patch('research_auto.enrich_auto_report', side_effect=AssertionError('paid AI must not run'))
        self.paid_ai = paid.start()
        self.addCleanup(paid.stop)

    def test_only_current_eligible_discoveries_are_preferred_and_other_hits_remain_discovery(self):
        universe = {'as_of': STAMP, 'funds': [universe_row('000001'), universe_row('000002', eligible=False)]}
        previous = [gap()]
        original = copy.deepcopy((universe, previous))
        found = discovery([search_board([hit('000001'), hit('000002'), hit('000003')])])
        progress = Mock()
        with patch.object(ra, 'discover_public_candidates', return_value=found) as search:
            result, preferred = ra._search_unresolved_boards(universe, previous, True, progress)
        search.assert_called_once_with(previous, limit_boards=3, max_per_board=3, refresh=True)
        self.assertEqual(preferred, ['000001'])
        by_code = {item['code']: item for item in result['boards'][0]['candidates']}
        self.assertEqual(by_code['000001']['status'], 'screened')
        self.assertEqual(by_code['000002']['status'], 'excluded')
        self.assertIn('最短持有期限未通过', by_code['000002']['screening_reason'])
        self.assertEqual(by_code['000003']['status'], 'not_in_current_ranking')
        self.assertTrue(all(item['screened_at'] == STAMP for item in by_code.values()))
        self.assertIn('仍须', by_code['000001']['screening_reason'])
        self.assertEqual((universe, previous), original)
        progress.assert_called_once()
        self.network.assert_not_called()
        self.paid_ai.assert_not_called()

    def test_absent_unresolved_directions_never_trigger_search(self):
        for previous in (None, {}, [], [gap(status='candidate')],
                         [gap(status='not_researched')], [gap(displayed_count=1)]):
            with self.subTest(previous=previous):
                progress = Mock()
                with patch.object(ra, 'discover_public_candidates') as search:
                    result, preferred = ra._search_unresolved_boards({'funds': []}, previous, False, progress)
                self.assertEqual(result['boards'], [])
                self.assertEqual(preferred, [])
                search.assert_not_called()
                progress.assert_not_called()

    def test_duplicate_discoveries_do_not_duplicate_preferred_codes(self):
        found = discovery([search_board([hit('000001')]),
                           search_board([hit('000001')], 'sector_cpo')])
        with patch.object(ra, 'discover_public_candidates', return_value=found):
            result, preferred = ra._search_unresolved_boards({'funds': [universe_row('000001')]},
                                                           [gap(), gap('sector_cpo')], False, Mock())
        self.assertEqual(preferred, ['000001'])
        self.assertTrue(all(board['candidates'][0]['status'] == 'screened' for board in result['boards']))

    def test_code_match_with_conflicting_product_name_or_type_cannot_be_preferred(self):
        for candidate in (hit('000001', name='另一只白酒混合C'),
                          hit('000001', fund_type='债券型-长债'),
                          hit('000001', name='')):
            with self.subTest(candidate=candidate):
                found = discovery([search_board([candidate])])
                with patch.object(ra, 'discover_public_candidates', return_value=found):
                    result, preferred = ra._search_unresolved_boards({'funds': [universe_row('000001')]},
                                                                   [gap()], False, Mock())
                self.assertEqual(preferred, [])
                item = result['boards'][0]['candidates'][0]
                self.assertEqual(item['status'], 'identity_conflict')
                self.assertTrue(item['screening_reason'])

    def test_product_identity_tolerates_width_case_and_spaces_and_missing_optional_type(self):
        row = universe_row('000001', name='测试半导体ETF联接C', fund_type='指数型-股票')
        for candidate in (hit('000001', name=' 测试 半导体etf联接Ｃ ', fund_type=' 指数型-股票 '),
                          hit('000001', name='测试半导体ETF联接C', fund_type='')):
            with self.subTest(candidate=candidate):
                with patch.object(ra, 'discover_public_candidates',
                                  return_value=discovery([search_board([candidate])])):
                    result, preferred = ra._search_unresolved_boards({'funds': [row]}, [gap()], False, Mock())
                self.assertEqual(preferred, ['000001'])
                self.assertEqual(result['boards'][0]['candidates'][0]['status'], 'screened')

    def test_public_search_exception_is_isolated_and_original_inputs_survive(self):
        universe, previous = {'funds': [universe_row('000001')]}, [gap()]
        before = copy.deepcopy((universe, previous))
        with patch.object(ra, 'discover_public_candidates', side_effect=TimeoutError('public source unavailable')):
            result, preferred = ra._search_unresolved_boards(universe, previous, False, Mock())
        self.assertEqual(preferred, [])
        self.assertEqual(result['boards'], [])
        self.assertTrue(result['warnings'])
        self.assertEqual((universe, previous), before)

    def test_attaching_selection_changes_only_discovery_status_and_preserves_measured_counts(self):
        coverage = [gap(deep_count=2, eligible_count=8, valid_quant_count=1),
                    gap('sector_cpo', status='holdings_pending', deep_count=3)]
        found = discovery([search_board([
            hit('000001', status='screened'), hit('000002', status='screened'),
            hit('000003', status='excluded'), hit('000004', status='not_in_current_ranking')])])
        original_coverage, original_found = copy.deepcopy((coverage, found))
        ra._attach_web_discovery(coverage, found, [], ['000001', '000003', '000004'])
        self.assertEqual([{key: value for key, value in row.items() if key != 'web_search'}
                          for row in coverage], original_coverage)
        statuses = {item['code']: item['status'] for item in coverage[0]['web_search']['candidates']}
        self.assertEqual(statuses, {'000001': 'research_selected', '000002': 'screened',
                                    '000003': 'excluded', '000004': 'not_in_current_ranking'})
        self.assertNotIn('web_search', coverage[1])
        self.assertEqual(found, original_found)

    def test_historical_search_evidence_retains_its_time_and_is_marked_previous_run(self):
        old_search = search_board([hit('000001', status='screened', searched_at=OLD_STAMP)],
                                  searched_at=OLD_STAMP)
        previous = [gap(web_search=old_search)]
        before = copy.deepcopy(previous)
        coverage = [gap(status='insufficient', deep_count=1)]
        with patch.object(ra, 'discover_public_candidates') as search:
            ra._attach_web_discovery(coverage, discovery([]), previous, [])
        attached = coverage[0]['web_search']
        self.assertTrue(attached['from_previous_run'])
        self.assertFalse(attached['attempted_this_run'])
        self.assertEqual(attached['searched_at'], OLD_STAMP)
        self.assertEqual(attached['candidates'][0]['searched_at'], OLD_STAMP)
        self.assertEqual(attached['candidates'][0]['status'], 'discovery_only')
        self.assertEqual(attached['candidates'][0]['previous_screening_status'], 'screened')
        self.assertEqual(coverage[0]['deep_count'], 1)
        self.assertEqual(previous, before)
        search.assert_not_called()

    def test_historical_screening_and_selection_are_not_reused_as_current_research(self):
        historical_statuses = ('research_selected', 'screened', 'excluded',
                               'not_in_current_ranking', 'identity_conflict')
        candidates = [hit(f'{index:06d}', status=status, searched_at=OLD_STAMP,
                          screened_at=OLD_STAMP, screening_reason=f'上次结果：{status}')
                      for index, status in enumerate(historical_statuses, 1)]
        previous = [gap(web_search=search_board(candidates, searched_at=OLD_STAMP))]
        before = copy.deepcopy(previous)
        coverage = [gap(status='insufficient')]
        # Current selection elsewhere must not upgrade unrefreshed old evidence.
        selected_codes = [item['code'] for item in candidates]
        ra._attach_web_discovery(coverage, discovery([]), previous, selected_codes)
        attached = coverage[0]['web_search']
        self.assertTrue(attached['from_previous_run'])
        self.assertFalse(attached['attempted_this_run'])
        self.assertEqual(attached['searched_at'], OLD_STAMP)
        for candidate, old in zip(attached['candidates'], candidates):
            with self.subTest(previous_status=old['status']):
                self.assertEqual(candidate['status'], 'discovery_only')
                self.assertEqual(candidate['previous_screening_status'], old['status'])
                self.assertEqual(candidate['previous_screening_reason'], old['screening_reason'])
                self.assertEqual(candidate['searched_at'], OLD_STAMP)
                self.assertEqual(candidate['screened_at'], OLD_STAMP)
                self.assertIn('本轮', candidate['screening_reason'])
                self.assertIn('未', candidate['screening_reason'])
                self.assertNotIn('已纳入本轮深研', candidate['screening_reason'])
        self.assertEqual(coverage[0]['deep_count'], 0)
        self.assertEqual(coverage[0]['candidate_count'], 0)
        self.assertEqual(previous, before)

    def test_current_search_overrides_history_without_mutating_either_source(self):
        previous = [gap(web_search=search_board([hit('000001')], searched_at=OLD_STAMP))]
        found = discovery([search_board([hit('000002', status='screened')])])
        before = copy.deepcopy((previous, found))
        coverage = [gap()]
        ra._attach_web_discovery(coverage, found, previous, ['000002'])
        self.assertEqual(coverage[0]['web_search']['searched_at'], STAMP)
        self.assertFalse(coverage[0]['web_search'].get('from_previous_run', False))
        self.assertEqual(coverage[0]['web_search']['candidates'][0]['status'], 'research_selected')
        self.assertEqual((previous, found), before)

    def test_preferred_picker_still_caps_three_deduplicates_family_and_rejects_excluded_rows(self):
        rows = [universe_row('000001', '白酒甲A', score=90),
                universe_row('000002', '白酒甲C', score=89),
                universe_row('000003', '白酒乙C', score=80),
                universe_row('000004', '白酒丙C', score=70),
                universe_row('000005', '白酒丁C', score=1),
                universe_row('000006', '白酒戊C', eligible=False, score=99)]
        universe = {'as_of': STAMP, 'funds': rows}
        before = copy.deepcopy(universe)
        chosen = ru.pick_research_codes(universe, preferred_codes=['000002', '000005', '000006', '999999'])
        self.assertEqual(len(chosen), 4)
        self.assertIn('000002', chosen)
        self.assertIn('000005', chosen)
        self.assertNotIn('000001', chosen)
        self.assertNotIn('000006', chosen)
        self.assertNotIn('999999', chosen)
        selected = [row for row in rows if row['code'] in chosen]
        self.assertEqual(len({ru._family(row) for row in selected}), len(selected))
        self.assertEqual(universe, before)

    def test_preferred_candidate_must_still_be_eligible_at_pick_time(self):
        universe = {'funds': [universe_row('000001'), universe_row('000002', name='另一半导体混合C')]}
        with patch.object(ra, 'discover_public_candidates', return_value=discovery([search_board([hit('000001')])])):
            _, preferred = ra._search_unresolved_boards(universe, [gap()], False, Mock())
        self.assertEqual(preferred, ['000001'])
        universe['funds'][0]['eligible'] = False
        self.assertEqual(ru.pick_research_codes(universe, preferred_codes=preferred), ['000002'])

    def test_preferred_codes_do_not_override_board_diversity_or_total_budget(self):
        rows = [universe_row(f'{index:06d}', f'白酒{label}C', score=index)
                for index, label in enumerate(('甲', '乙', '丙'), 1)]
        rows += [universe_row('000010', '半导体甲C'), universe_row('000011', '半导体乙C')]
        chosen = ru.pick_research_codes({'funds': rows}, limit=2,
                                        preferred_codes=['000001', '000002', '000003'])
        self.assertEqual(len(chosen), 2)
        self.assertEqual(sum(code in {'000001', '000002', '000003'} for code in chosen), 2)
        self.assertEqual(sum(code in {'000010', '000011'} for code in chosen), 0)

    def test_query_direction_never_relabels_a_fund_or_fills_the_wrong_boards_deep_count(self):
        row = universe_row('000001', '白酒甲C')
        universe = {'as_of': STAMP, 'funds': [row]}
        with patch.object(ra, 'discover_public_candidates',
                          return_value=discovery([search_board([hit('000001', name='白酒甲C')], 'sector_cpo')])):
            found, preferred = ra._search_unresolved_boards(universe, [gap('sector_cpo')], False, Mock())
        selected = ru.pick_research_codes(universe, preferred_codes=preferred)
        coverage = build_board_coverage(universe, selected, {'as_of': STAMP, 'funds': []}, [], [])
        ra._attach_web_discovery(coverage, found, [], selected)
        by_id = {board['id']: board for board in coverage}
        self.assertEqual(by_id['sector_liquor']['deep_count'], 0)
        self.assertEqual(by_id['holdings_unclassified']['deep_count'], 1)
        self.assertEqual(by_id['sector_cpo']['deep_count'], 0)
        self.assertEqual(by_id['sector_cpo']['candidate_count'], 0)
        self.assertEqual(by_id['sector_cpo']['status'], 'no_match')
        self.assertEqual(by_id['sector_cpo']['web_search']['candidates'][0]['status'], 'research_selected')
        self.assertNotIn('board_id', row)

    def test_scan_runs_only_eligible_discovery_and_keeps_search_evidence_separate_from_deep_counts(self):
        rows = [universe_row('000001'), universe_row('000002', eligible=False)]
        universe = {'as_of': STAMP, 'funds': rows, 'sources': [], 'warnings': [],
                    'coverage': {'catalog_count': 2, 'screened_count': 2}}
        found = discovery([search_board([hit('000001'), hit('000002'), hit('000003')])])
        found['warnings'] = ['公开搜索部分结果仍待核验']
        snapshot = {'as_of': STAMP, 'funds': [copy.deepcopy(rows[0])],
                    'market': [], 'news': [], 'sources': [], 'warnings': []}
        with ExitStack() as stack:
            stack.enter_context(patch.object(ra, 'collect_universe', return_value=universe))
            stack.enter_context(patch.object(ra, 'discover_public_candidates', return_value=found))
            holdings = stack.enter_context(patch.object(ra, 'collect_holdings',
                side_effect=lambda basic, **kwargs: copy.deepcopy(basic)))
            collect = stack.enter_context(patch.object(ra, 'collect_research', return_value=snapshot))
            stack.enter_context(patch.object(ra, 'build_sentiment', return_value={}))
            stack.enter_context(patch.object(ra, 'build_quant', return_value=[]))
            stack.enter_context(patch.object(ra, 'build_strategy', return_value={'candidates': []}))
            stack.enter_context(patch.object(ra, 'build_analysis', return_value={'funds': []}))
            stack.enter_context(patch.object(ra, 'build_sections', return_value=[]))
            stack.enter_context(patch.object(ra, 'build_market_overview', return_value={}))
            result = ra.run_auto_research(previous={'board_coverage': [gap()]}, refresh=False)
        collect.assert_called_once_with(['000001'], refresh=False, include_common=True)
        self.assertTrue(holdings.call_args.kwargs['preflight'])
        self.assertEqual(result['universe']['selected_codes'], ['000001'])
        self.assertEqual(result['universe']['coverage']['deep_count'], 1)
        self.assertEqual(result['universe']['coverage']['deep_requested_count'], 1)
        self.assertEqual(result['universe']['coverage']['deep_data_count'], 1)
        board = next(board for board in result['board_coverage'] if board['id'] == 'sector_semiconductor')
        self.assertEqual(board['deep_count'], 0)
        self.assertEqual([item['status'] for item in board['web_search']['candidates']],
                         ['research_selected', 'excluded', 'not_in_current_ranking'])
        self.assertEqual(board['candidate_count'], 0)
        self.assertEqual(result['sections'], [])
        self.assertIn('公开搜索部分结果仍待核验', result['snapshot']['warnings'])
        self.assertTrue(any(source['id'] == 'discovery:offline-search' for source in result['snapshot']['sources']))
        self.network.assert_not_called()
        self.paid_ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
