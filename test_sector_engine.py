"""Sector mode must not invoke or recreate the retired fund pipeline."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

from research_auto import AutoResearchEngine, REPORT_VERSION
from research_data import now_iso, CHINA


def sector_report():
    return {'research_scope': 'sectors', 'as_of': now_iso(),
            'snapshot': {'as_of': now_iso(), 'market': [], 'news': [], 'sources': [], 'warnings': []},
            'strategy': {'panic': {'score': 20}, 'regime': {'mode': 'risk_on'}},
            'sector_analysis': [{'id': 'sector_test', 'score': 70, 'recommendation_index': 70,
                                 'status': 'available', 'reason': '独立板块行情'}]}


class SectorEngineTests(unittest.TestCase):
    def make_engine(self, **options):
        options.setdefault('runner', lambda **_: sector_report())
        options.setdefault('ai_runner', lambda report, **_: report)
        engine = AutoResearchEngine(research_scope='sectors', **options)
        self.addCleanup(engine.close)
        return engine

    def test_scan_never_calls_fund_gates_or_adds_members(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sector-report.json'
            engine = self.make_engine(state_path=path)
            with patch('research_auto.build_sections', side_effect=AssertionError('fund pipeline')), \
                    patch('research_auto.apply_board_holdings_gate', side_effect=AssertionError('holdings gate')), \
                    patch('research_auto.enrich_board_diagnostics', side_effect=AssertionError('fund diagnostics')):
                engine.request_scan()
                engine._worker.join(3)
                self.assertEqual(engine._state['status'], 'ready')
                report = engine.status()['report']
            for key in ('sections', 'candidate_references', 'holdings_index', 'holdings_check_ledger'):
                self.assertNotIn(key, report)
            self.assertNotIn('funds', report['snapshot'])
            saved = json.loads(path.read_text(encoding='utf-8'))['report']
            self.assertEqual(saved, engine._state['report'])

    def test_old_fund_report_is_not_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.json'
            path.write_text(json.dumps({'version': REPORT_VERSION, 'report': {'strategy': {},
                             'snapshot': {'funds': [{'code': '000001'}]}}}), encoding='utf-8')
            engine = self.make_engine(state_path=path)
            self.assertIsNone(engine._state['report'])

    def test_misconfigured_runner_cannot_publish_a_legacy_fund_report(self):
        engine = self.make_engine(runner=lambda **_: {'strategy': {}, 'snapshot': {'funds': [{'code': '000001'}]}})
        engine.request_scan()
        engine._worker.join(3)
        self.assertEqual(engine._state['status'], 'error')
        self.assertIsNone(engine.status()['report'])

    def test_stale_sector_scores_are_unknown_and_do_not_reintroduce_funds(self):
        engine = self.make_engine()
        report = sector_report()
        engine._state.update(status='ready', report=copy.deepcopy(report),
                             completed_at=(datetime.now(CHINA) - timedelta(hours=3)).isoformat())
        result = engine.status()
        self.assertTrue(result['report_stale'])
        self.assertIsNone(result['report']['sector_analysis'][0]['recommendation_index'])
        self.assertIsNone(result['report']['strategy']['panic']['score'])
        self.assertNotIn('sections', result['report'])
        self.assertEqual(engine._state['report'], report)

    def test_configuration_change_removes_previous_sector_ai_narrative(self):
        engine = self.make_engine(config_provider=lambda: {'revision': 'new', 'enabled': False})
        report = sector_report()
        report['ai_research'] = {'revision': 'old', 'configuration_enabled': True, 'status': 'completed'}
        report['sector_analysis'][0].update(ai_reason='旧模型解读', ai_risks=['旧风险'],
                                            ai_invalidation='旧条件', ai_research_status='completed')
        engine._state.update(status='ready', report=report, completed_at=now_iso())
        public = engine.status()['report']
        self.assertNotIn('ai_reason', public['sector_analysis'][0])
        self.assertEqual(public['ai_research']['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
