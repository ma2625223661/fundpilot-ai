from test_holdings_fixtures import portfolio
import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_data import CHINA, now_iso
from research_auto import AutoResearchEngine, apply_board_holdings_gate, enforce_strategy, run_auto_research


def sample_report(mode='risk_on'):
    timestamp = now_iso()
    return {'snapshot': {'as_of': timestamp, 'warnings': [], 'funds': [
                {'code': '000001', 'name': '测试成长A', 'fund_type': '股票型', 'nav_date': timestamp[:10], 'holdings': portfolio(['软件开发'])}]},
            'quant': [{'code': '000001', 'name': '测试成长A', 'quality': 'ok', 'nav_date': timestamp[:10],
                       'score': 80, 'action': '分批配置候选', 'asset_class': 'equity_mixed',
                       'metrics': {'return_20d': 3, 'return_60d': 6, 'volatility_annual': 10, 'max_drawdown': -3},
                       'thresholds': {'annual_volatility_limit': 15, 'drawdown_limit': 8}}],
            'analysis': {'summary': '', 'market_view': '', 'risks': [], 'next_steps': [],
            'funds': [{'code': '000001', 'action': '分批配置候选', 'reason': '趋势',
                       'operation_plan': {'new_position': '买入', 'steps': ['第一批买入'],
                                          'existing_position': '未达到计划时评估分批新增',
                                          'entry_conditions': ['通过原条件即可新增']}}]},
            'strategy': {'schema_version': 1, 'as_of': timestamp, 'panic': {'score': 10, 'as_of': timestamp},
                         'regime': {'mode': mode, 'label': mode},
                         'candidates': [{'code': '000001', 'reason': '7天窗口'}]}}


class AutoResearchTests(unittest.TestCase):
    def setUp(self):
        # Every network boundary is mocked in automatic orchestration tests.
        # Published-holdings parsing/collection has its own isolated test suite.
        collector = patch('research_auto.collect_holdings', side_effect=lambda snapshot, **kwargs: copy.deepcopy(snapshot))
        self.collect_holdings = collector.start()
        self.addCleanup(collector.stop)

    def test_holdings_gate_removes_old_theme_candidate_and_buy_plan_without_changing_quant(self):
        report = sample_report()
        report['snapshot']['funds'][0].pop('holdings')
        report['snapshot']['funds'][0]['name'] = '测试白酒股票A'
        report['analysis']['funds'][0]['action'] = '7 天以上研究候选'
        measured = copy.deepcopy(report['quant'])
        with patch('research_holdings.fetch_holdings') as fetch:
            apply_board_holdings_gate(report['snapshot'], report['quant'], report['analysis'], report['strategy'])
        fetch.assert_not_called()
        self.assertEqual(report['strategy']['candidates'], [])
        fund = report['analysis']['funds'][0]
        self.assertEqual(fund['action'], '继续观察')
        self.assertEqual(fund['board_match']['status'], 'unknown')
        self.assertIsNone(fund['recommendation_index'])
        self.assertNotIn('第一批买入', fund['operation_plan']['steps'])
        self.assertNotIn('分批新增', fund['operation_plan']['existing_position'])
        self.assertNotIn('通过原条件即可新增', fund['operation_plan']['entry_conditions'])
        self.assertIn('持仓', fund['operation_plan']['new_position'])
        self.assertEqual(report['quant'], measured)

    def test_holdings_gate_preserves_matched_theme_candidate_with_published_weight_evidence(self):
        report = sample_report()
        timestamp = report['snapshot']['as_of']
        report['snapshot']['funds'][0].update(name='测试白酒股票A', holdings={
            'status': 'ok', 'report_date': timestamp[:10],
            'source_id': 'holdings:000001', 'source_url': 'https://example.test/disclosure/000001',
            'rows': [{'code': f'60000{index}', 'name': f'合成白酒企业{index}', 'weight_pct': 10,
                      'instrument_type': 'stock', 'tag_status': 'ok', 'tags': ['白酒']}
                     for index in range(1, 4)]})
        measured = copy.deepcopy(report['quant'])
        original_plan = copy.deepcopy(report['analysis']['funds'][0]['operation_plan'])
        apply_board_holdings_gate(report['snapshot'], report['quant'], report['analysis'], report['strategy'])
        self.assertEqual(len(report['strategy']['candidates']), 1)
        self.assertEqual(report['analysis']['funds'][0]['board_match']['status'], 'matched')
        self.assertEqual(report['analysis']['funds'][0]['recommendation_index'], 80)
        self.assertEqual(report['analysis']['funds'][0]['operation_plan'], original_plan)
        self.assertEqual(report['quant'], measured)

    def test_restored_theme_report_rechecks_missing_holdings_without_network_or_losing_metrics(self):
        report = sample_report()
        report['snapshot']['funds'][0].pop('holdings')
        report['snapshot']['funds'][0]['name'] = '测试白酒股票A'
        report['analysis'] = enforce_strategy(report['analysis'], report['strategy'])
        measured = copy.deepcopy(report['quant'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            writer = AutoResearchEngine(path)
            writer._persist(report, now_iso())
            writer.close()
            restored = AutoResearchEngine(path)
            self.addCleanup(restored.close)
            with patch('research_holdings.fetch_holdings') as fetch:
                state = restored.status()
            fetch.assert_not_called()
        self.assertTrue(state['report_stale'])
        self.assertEqual(state['report']['strategy']['candidates'], [])
        self.assertEqual(state['report']['sections'], [])
        fund = state['report']['analysis']['funds'][0]
        self.assertNotIn(fund['action'], ('分批配置候选', '7 天以上研究候选'))
        self.assertEqual(fund['board_match']['status'], 'unknown')
        self.assertNotIn('第一批买入', fund['operation_plan']['steps'])
        self.assertEqual(state['report']['quant'], measured)

    def test_defensive_mode_removes_buy_steps_from_detailed_cards(self):
        report = sample_report('defensive')
        report['strategy']['candidates'] = []
        output = enforce_strategy(report['analysis'], report['strategy'])
        fund = output['funds'][0]
        self.assertEqual(fund['action'], '防御期暂停新增')
        self.assertFalse(fund['execution_eligible'])
        self.assertNotIn('第一批买入', fund['operation_plan']['steps'])
        self.assertIn('暂停', fund['operation_plan']['new_position'])
        self.assertNotIn('分批新增', fund['operation_plan']['existing_position'])
        self.assertNotIn('通过原条件即可新增', fund['operation_plan']['entry_conditions'])
        self.assertEqual(report['analysis']['funds'][0]['action'], '分批配置候选')

    def test_candidate_remains_research_without_verified_platform_or_terms(self):
        report = sample_report()
        output = enforce_strategy(report['analysis'], report['strategy'])
        self.assertEqual(output['funds'][0]['action'], '7 天以上研究候选')
        self.assertFalse(output['funds'][0]['execution_eligible'])
        self.assertEqual(output['funds'][0]['alipay_available'], 'unverified')

    def test_concurrent_requests_share_single_scan_and_persist_without_credentials(self):
        gate, entered = threading.Event(), threading.Event()
        calls = []
        def runner(**kwargs):
            calls.append(kwargs)
            entered.set()
            gate.wait(2)
            return sample_report()
        with tempfile.TemporaryDirectory() as directory:
            engine = AutoResearchEngine(Path(directory) / 'report.json', runner=runner)
            self.assertTrue(engine.request_scan())
            self.assertTrue(entered.wait(1))
            self.assertFalse(engine.request_scan())
            self.assertEqual(engine.status()['status'], 'running')
            gate.set()
            engine._worker.join(2)
            self.assertEqual(len(calls), 1)
            self.assertEqual(engine.status()['status'], 'ready')
            saved = json.loads((Path(directory) / 'report.json').read_text(encoding='utf-8'))
            self.assertNotIn('key', saved)
            restored = AutoResearchEngine(Path(directory) / 'report.json', runner=runner)
            state = restored.status()
            self.assertTrue(state['report_stale'])
            self.assertIsNone(state['report']['strategy']['panic']['score'])
            self.assertEqual(state['report']['strategy']['candidates'], [])
            engine.close()
            restored.close()

    def test_stale_and_failed_results_never_leave_actionable_candidates(self):
        engine = AutoResearchEngine()
        report = sample_report()
        report['analysis'] = enforce_strategy(report['analysis'], report['strategy'])
        engine._state.update(status='ready', report=report,
                             completed_at=(datetime.now(CHINA) - timedelta(hours=3)).isoformat())
        state = engine.status()
        self.assertTrue(state['report_stale'])
        self.assertEqual(state['report']['strategy']['regime']['mode'], 'unknown')
        self.assertEqual(state['report']['analysis']['funds'][0]['action'], '暂缓新增')
        section_fund = state['report']['sections'][0]['funds'][0]
        self.assertEqual(section_fund['role'], 'observation')
        self.assertEqual(section_fund['action'], '暂缓新增')
        self.assertIn('暂不安排', section_fund['operation_plan']['new_position'])
        self.assertNotIn('分批新增', section_fund['operation_plan']['existing_position'])
        self.assertEqual(engine._state['report']['strategy']['panic']['score'], 10)
        engine.runner = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('unexpected source content'))
        engine.request_scan()
        engine._worker.join(2)
        state = engine.status()
        self.assertEqual(state['status'], 'error')
        self.assertIsNone(state['report']['strategy']['panic']['score'])
        engine.close()

    def test_status_adds_boards_to_old_report_without_dropping_full_research(self):
        engine = AutoResearchEngine()
        report = sample_report()
        report['analysis'] = enforce_strategy(report['analysis'], report['strategy'])
        engine._state.update(status='ready', report=report, completed_at=now_iso())
        state = engine.status()
        self.assertFalse(state['report_stale'])
        self.assertEqual(state['report']['sections'][0]['funds'][0]['role'], 'candidate')
        self.assertEqual(state['report']['analysis']['funds'][0]['recommendation_index'],
                         state['report']['sections'][0]['funds'][0]['recommendation_index'])
        self.assertEqual(len(state['report']['analysis']['funds']), 1)
        self.assertNotIn('sections', engine._state['report'])
        engine.close()

    @patch('research_auto.collect_research')
    @patch('research_auto.pick_holdings_preflight_codes')
    @patch('research_auto.collect_universe')
    def test_auto_boards_limit_each_class_and_preserve_all_deep_data(self, universe, pick, collect):
        report = sample_report()
        codes = [f'{i:06}' for i in range(1, 4)]
        funds, quants, analyses = [], [], []
        for index, code in enumerate(codes):
            fund = dict(report['snapshot']['funds'][0], code=code, name=f'独立策略{index}A')
            funds.append(fund)
            quants.append(dict(report['quant'][0], code=code, score=80 + index))
            analyses.append(dict(report['analysis']['funds'][0], code=code, name=fund['name']))
        collect.return_value = dict(report['snapshot'], funds=funds, sources=[], market=[], news=[])
        pick.side_effect = [codes, []]
        universe.return_value = {'funds': funds, 'coverage': {}, 'sources': [], 'warnings': []}
        strategy = copy.deepcopy(report['strategy'])
        strategy['candidates'] = [{'code': code, 'reason': '7天窗口'} for code in codes]
        with patch('research_auto.build_quant', return_value=quants), \
                patch('research_auto.build_analysis', return_value=dict(report['analysis'], funds=analyses)), \
                patch('research_auto.build_strategy', return_value=strategy), \
                patch('research_auto.load_candidate_references', return_value=[]):
            result = run_auto_research()
        self.assertEqual(len(result['snapshot']['funds']), 3)
        self.assertEqual(len(result['quant']), 3)
        self.assertEqual(len(result['analysis']['funds']), 3)
        self.assertEqual(len(result['sections']), 1)
        self.assertEqual([f['code'] for f in result['sections'][0]['funds']], ['000003', '000002', '000001'])
        self.assertTrue(all(f['role'] == 'candidate' for f in result['sections'][0]['funds']))
        self.assertEqual(result['automatic']['per_board_deep_limit'], 3)
        self.assertEqual(result['automatic']['per_board_display_limit'], 3)

    def test_next_scan_receives_isolated_coverage_context_without_altering_saved_strategy(self):
        report = sample_report()
        report['board_coverage'] = [{'id': 'sector_cxo', 'status': 'not_researched',
                                    'eligible_count': 5, 'deep_count': 0}]
        before = copy.deepcopy(report)
        seen = []
        def runner(previous, **_):
            seen.append(copy.deepcopy(previous))
            previous['board_coverage'][0]['deep_count'] = 99
            return sample_report()
        engine = AutoResearchEngine(runner=runner)
        engine._state.update(report=report, completed_at=now_iso())
        try:
            self.assertTrue(engine.request_scan())
            engine._worker.join(2)
            self.assertEqual(engine._state['status'], 'ready')
            carried = seen[0]['board_coverage'][0]
            self.assertEqual(carried['id'], before['board_coverage'][0]['id'])
            self.assertEqual(carried['deep_count'], 0)
            self.assertEqual(carried['eligible_count'], 5)
            self.assertEqual(carried['research_gap']['category'], 'not_researched')
            self.assertEqual(seen[0]['regime'], before['strategy']['regime'])
            self.assertEqual(report, before)
        finally:
            engine.close()

    @patch('research_auto.collect_research')
    @patch('research_auto.pick_holdings_preflight_codes', return_value=[])
    @patch('research_auto.collect_universe')
    def test_research_uses_separate_bounded_portfolio_discovery(self, universe, pick, collect):
        universe.return_value = {'funds': [], 'coverage': {}, 'warnings': [], 'sources': []}
        collect.return_value = {'as_of': now_iso(), 'funds': [], 'market': [], 'news': [],
                                'warnings': [], 'sources': []}
        coverage = [{'id': 'sector_cxo', 'status': 'not_researched', 'deep_count': 0}]
        run_auto_research(previous={'board_coverage': coverage})
        self.assertEqual(pick.call_args.kwargs['preferred_codes'], [])
        self.assertEqual(pick.call_args.kwargs['limit'], 96)

    @patch('research_auto.collect_research')
    @patch('research_auto.pick_holdings_preflight_codes', return_value=[])
    @patch('research_auto.collect_universe')
    def test_empty_universe_does_not_silently_substitute_default_funds(self, universe, pick, collect):
        universe.return_value = {'funds': [], 'coverage': {'screened_count': 0}, 'warnings': [], 'sources': []}
        collect.return_value = {'as_of': now_iso(), 'funds': [], 'market': [], 'news': [], 'warnings': [], 'sources': []}
        with patch('research_service.provider_json') as paid:
            result = run_auto_research()
        collect.assert_called_once_with(refresh=False, market_only=True)
        self.assertEqual(result['strategy']['regime']['mode'], 'unknown')
        self.assertEqual(result['strategy']['candidates'], [])
        paid.assert_not_called()

    @patch('research_auto.collect_research')
    @patch('research_auto.pick_holdings_preflight_codes')
    @patch('research_auto.cap_research_codes')
    @patch('research_auto.collect_universe')
    def test_deep_research_batches_and_accounts_for_missing_funds(self, universe, cap, pick, collect):
        codes = [f'{i:06}' for i in range(24)]
        pick.side_effect = [codes, []]
        cap.return_value = codes
        universe.return_value = {'funds': [{'code': c, 'name': c, 'fund_type': '混合型'} for c in codes],
                                 'coverage': {'screened_count': 20000}, 'sources': [], 'warnings': []}
        collect.return_value = {'as_of': now_iso(), 'funds': [], 'market': [], 'news': [], 'warnings': [], 'sources': []}
        result = run_auto_research()
        self.assertEqual(collect.call_count, 3)
        self.assertTrue(all(len(call.args[0]) <= 8 for call in collect.call_args_list))
        self.assertEqual([call.kwargs['include_common'] for call in collect.call_args_list], [True, False, False])
        self.assertEqual(len(result['quant']), 24)
        self.assertEqual(result['universe']['coverage']['deep_count'], 24)
        self.assertEqual(result['universe']['coverage']['deep_data_count'], 0)
        self.assertTrue(all(q['score'] is None for q in result['quant']))


if __name__ == '__main__':
    unittest.main()
