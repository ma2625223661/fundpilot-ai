"""Behavioral contracts for adopting an explicit software board classification."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_auto as auto
from research_candidates import (load_candidate_references, prepare_reference_candidates,
                                 build_reference_candidates)
from research_categories import board_for
from research_selection import build_sections
from test_holdings_fixtures import portfolio

STAMP = '2026-10-30T19:00:00+08:00'


def member(code, match=100, reference=True):
    holdings = portfolio(['白酒'], weights=(match, 100-match) if match < 100 else (100,))
    if match < 100:
        holdings['rows'][1]['tags'] = ['家用电器']
    row = {'code': code, 'name': '任意展示名称' + code, 'fund_type': '股票型',
           'eligible': True, 'universe_bucket': 'medium_high', 'screen_group': '股票',
           'holdings': holdings, 'nav': 1.2, 'nav_date': STAMP[:10], 'history': []}
    if reference:
        row['reference_candidate'] = {'code': code, 'requested_board_id': 'sector_liquor',
                                     'source_kind': 'user_reference',
                                     'source_label': '养基宝板块分类（用户提供）'}
    return row


def measured(code):
    return {'code': code, 'quality': 'ok', 'nav_date': STAMP[:10], 'score': 70,
            'action': '继续观察', 'metrics': {'volatility_annual': 10, 'max_drawdown': -2},
            'thresholds': {'annual_volatility_limit': 30, 'drawdown_limit': 18}}


class ReferenceBoardTests(unittest.TestCase):
    def test_forced_web_identity_displays_without_catalog_or_invented_metrics(self):
        reference = {'code': '022073', 'name': '公开页面基金名称', 'source_kind': 'web_discovery',
                     'forced_selection': True, 'direct_selection': True, 'requested_board_id': 'overseas_hk_dividend'}
        sections = build_sections({'as_of': STAMP, 'funds': []}, [], {'funds': []},
                                  references=[reference], reference_catalog=[])
        self.assertEqual(len(sections), 1)
        card = sections[0]['funds'][0]
        self.assertEqual(card['name'], reference['name'])
        self.assertIsNone(card['recommendation_index'])
        self.assertIsNone(card['board_match'].get('matched_disclosed_pct'))
        self.assertEqual(card['metrics'], {})
        self.assertFalse(card['execution_eligible'])
        references = build_reference_candidates([reference], {'funds': []}, {'as_of': STAMP, 'funds': []}, sections, [])
        self.assertEqual(references[0]['name'], reference['name'])
        self.assertEqual(references[0]['status'], 'forced_displayed')
        wrong_board = [{**sections[0], 'id': 'sector_liquor'}]
        self.assertEqual(build_reference_candidates([reference], {'funds': []}, {}, wrong_board, [])[0]['status'], 'forced_pending')

    def test_forced_member_has_a_main_card_under_the_three_fund_cap(self):
        rows = [member(code) for code in ('009941', '012414', '002605')]
        forced = {'code': '000999', 'name': '强制收录基金', 'source_kind': 'web_discovery', 'forced_selection': True,
                  'direct_selection': True, 'requested_board_id': 'sector_liquor'}
        refs = [row['reference_candidate'] for row in rows] + [forced]
        sections = build_sections({'as_of': STAMP, 'funds': rows}, [measured(row['code']) for row in rows], {'funds': []},
                                  references=refs, reference_catalog=rows)
        liquor = next(board for board in sections if board['id'] == 'sector_liquor')
        self.assertEqual(len(liquor['funds']), 3)
        self.assertEqual(liquor['funds'][0]['code'], forced['code'])
        self.assertIsNone(liquor['funds'][0]['recommendation_index'])

    def test_source_classification_keeps_member_while_ratio_remains_accurate(self):
        fund = member('002605', 72)
        original = copy.deepcopy(fund)
        board = board_for(fund, 'equity_active', STAMP)
        self.assertEqual(board['id'], 'sector_liquor')
        self.assertEqual(board['classification_method'], 'reference_board')
        self.assertEqual(board['board_match']['matched_disclosed_pct'], 72)
        self.assertEqual(board['board_comparison'][0]['id'], 'sector_consumer')
        self.assertEqual(board['board_comparison'][0]['matched_disclosed_pct'], 100)
        self.assertEqual(fund, original)
        del fund['reference_candidate']
        self.assertEqual(board_for(fund, 'equity_active', STAMP)['id'], 'sector_consumer')

    def test_three_explicit_members_are_displayed_without_fabricating_risk_or_purity(self):
        funds = [member('009941'), member('012414'), member('002605', 72), member('000001', reference=False)]
        sections = build_sections({'as_of': STAMP, 'funds': funds}, [measured(f['code']) for f in funds],
                                  {'funds': []}, {'as_of': STAMP, 'regime': {'mode': 'risk_on'}, 'candidates': []})
        liquor = next(s for s in sections if s['id'] == 'sector_liquor')
        self.assertEqual({f['code'] for f in liquor['funds']}, {'009941', '012414', '002605'})
        self.assertEqual(len(liquor['funds']), 3)
        for fund in liquor['funds']:
            self.assertEqual(fund['role'], 'observation')
            self.assertFalse(fund['execution_eligible'])
        self.assertEqual(next(f for f in liquor['funds'] if f['code'] == '002605')['board_match']['matched_disclosed_pct'], 72)

    def test_ineligible_or_missing_members_remain_explained_instead_of_forced_into_strategy(self):
        refs = [member(code)['reference_candidate'] for code in ('009941', '012414', '002605')]
        funds = [member('009941'), member('012414')]
        funds[1].update(eligible=False, exclusion_reasons=['净值资料过期'])
        universe = {'as_of': STAMP, 'funds': funds}
        self.assertEqual(prepare_reference_candidates(universe, refs), ['009941'])
        result = build_reference_candidates(refs, universe, {'as_of': STAMP, 'funds': []}, [], [])
        self.assertEqual([r['status'] for r in result], ['holdings_verified', 'excluded', 'not_in_catalog'])
        self.assertIn('净值资料过期', result[1]['reason'])
        self.assertIsNone(result[2]['matched_disclosed_pct'])

    def test_registry_rejects_invalid_or_unknown_origins_and_deduplicates(self):
        valid = member('009941')['reference_candidate']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'references.json'
            path.write_text(json.dumps({'candidates': [valid, valid, {**valid, 'code': 'bad'},
                                                        {**valid, 'code': '000002', 'source_kind': 'search_hit'}]}), encoding='utf-8')
            self.assertEqual(load_candidate_references(path), [valid])
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(load_candidate_references(path), [])

    def test_automatic_scan_preserves_reference_membership_through_research_and_coverage(self):
        codes = ['009941', '012414', '002605']
        funds = [member(code, 72 if code == '002605' else 100, reference=False) for code in codes]
        funds.append(member('000001', reference=False))
        universe = {'as_of': STAMP, 'funds': funds, 'coverage': {'catalog_count': 4}, 'sources': []}
        refs = [member(code)['reference_candidate'] for code in codes]
        def collect(selected=None, **kwargs):
            return {'as_of': STAMP, 'funds': [copy.deepcopy(f) for f in funds if f['code'] in selected],
                    'sources': [], 'warnings': [], 'market': [], 'news': []}
        analysis = {'summary': '', 'market_view': '', 'risks': [], 'next_steps': [], 'funds': [
            {'code': code, 'action': '继续观察', 'reason': '观察', 'operation_plan': {}} for code in codes]}
        with patch('urllib.request.urlopen', side_effect=AssertionError('offline test')), \
                patch.object(auto, 'collect_universe', return_value=universe), \
                patch.object(auto, 'load_candidate_references', return_value=refs), \
                patch.object(auto, 'collect_research', side_effect=collect), \
                patch.object(auto, 'collect_holdings', side_effect=AssertionError('complete portfolios should be reused')), \
                patch.object(auto, 'build_sentiment', return_value={}), \
                patch.object(auto, 'build_quant', side_effect=lambda snapshot, prefs: [measured(f['code']) for f in snapshot['funds']]), \
                patch.object(auto, 'build_analysis', return_value=analysis), \
                patch.object(auto, 'build_strategy', return_value={'as_of': STAMP, 'regime': {'mode': 'risk_on'}, 'candidates': []}), \
                patch.object(auto, 'build_market_overview', return_value={}):
            result = auto.run_auto_research()
        self.assertEqual(set(result['universe']['selected_codes']), set(codes))
        board = next(b for b in result['board_coverage'] if b['id'] == 'sector_liquor')
        self.assertEqual(board['displayed_count'], 3)
        self.assertEqual({c['status'] for c in board['reference_candidates']}, {'displayed'})
        self.assertTrue(all(f.get('reference_candidate') for f in result['snapshot']['funds']))

    def test_saved_report_keeps_reference_and_raw_holdings_without_duplicate_classification(self):
        fund = member('002605', 72)
        report = {'snapshot': {'as_of': STAMP, 'funds': [fund]},
                  'analysis': {'funds': [{'code': fund['code'], 'board_match': {'large': 'derived'},
                                          'board_matches': [{'large': 'derived'}],
                                          'board_comparison': [{'large': 'derived'}], 'reason': '保留原解读'}]},
                  'strategy': {}, 'candidate_references': [fund['reference_candidate']]}
        original = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = auto.AutoResearchEngine(path)
            engine._persist(report, STAMP)
            engine.close()
            saved = json.loads(path.read_text(encoding='utf-8'))['report']
        self.assertEqual(saved['snapshot']['funds'][0], fund)
        self.assertEqual(saved['candidate_references'], report['candidate_references'])
        self.assertEqual(saved['analysis']['funds'], [{'code': '002605', 'reason': '保留原解读'}])
        self.assertEqual(report, original)


if __name__ == '__main__':
    unittest.main()
