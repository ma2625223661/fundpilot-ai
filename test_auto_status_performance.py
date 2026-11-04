"""Offline regressions for a responsive heartbeat while large reports render."""
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_data import CHINA, now_iso
from test_research_auto import sample_report


class NeverCopy:
    def __deepcopy__(self, memo):
        raise AssertionError('heartbeat must not traverse portfolio evidence')


class StatusPerformanceTests(unittest.TestCase):
    def test_review_histories_are_internal_dated_and_isolated(self):
        engine=self.make_engine()
        engine._state['report']['as_of']='2026-11-01T20:00:00+08:00'
        stamp=engine._state['report']['as_of']
        engine._state['report']['_quote_histories']={'test':{'rows':[{'date':'2026-10-30','close':100}]}}
        self.assertIsNone(engine.review_histories('old-report'))
        history=engine.review_histories(stamp)
        history['test']['rows'][0]['close']=999
        self.assertEqual(engine.review_histories(stamp)['test']['rows'][0]['close'],100)
        self.assertNotIn('_quote_histories',engine.status()['report'])

    def make_engine(self, config=None):
        engine = AutoResearchEngine(config_provider=lambda: config or {})
        self.addCleanup(engine.close)
        engine._state.update(status='ready', report=sample_report(), completed_at=now_iso())
        return engine

    def test_summary_never_copies_portfolios_or_runs_classification(self):
        engine = self.make_engine()
        engine._state['report']['snapshot']['large_evidence'] = NeverCopy()
        engine._state['report']['holdings_index'] = NeverCopy()
        with patch('research_auto.board_catalog_scope', side_effect=AssertionError('catalog lock')):
            first = engine.status(include_report=False)
            second = engine.status(include_report=False)
        self.assertIsNone(first['report'])
        self.assertTrue(first['has_report'])
        self.assertEqual(first['report_version'], second['report_version'])
        self.assertLess(len(str(first)), 2000)

    def test_large_internal_index_is_removed_before_public_copy(self):
        engine = self.make_engine()
        engine._state['report']['holdings_index'] = NeverCopy()
        engine._state['report']['holdings_check_ledger'] = NeverCopy()
        state = engine.status()
        self.assertNotIn('holdings_index', state['report'])
        self.assertNotIn('holdings_check_ledger', state['report'])

    def test_cached_view_is_reused_but_caller_mutations_do_not_leak(self):
        engine = self.make_engine()
        with patch.object(engine, '_render_status', wraps=engine._render_status) as render:
            first = engine.status()
            first['report']['analysis']['summary'] = 'caller mutation'
            engine._progress('继续扫描', {'deep_done': 1})
            second = engine.status()
        self.assertEqual(render.call_count, 1)
        self.assertNotEqual(second['report']['analysis']['summary'], 'caller mutation')
        self.assertEqual(second['stage'], '继续扫描')

    def test_heartbeat_remains_available_during_slow_report_render(self):
        engine = self.make_engine()
        entered, release = threading.Event(), threading.Event()
        render = engine._render_status
        errors = []

        def slow_render(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError('heartbeat was blocked by report rendering')
            return render(*args)

        def request_report():
            try:
                engine.status()
            except Exception as error:
                errors.append(error)

        with patch.object(engine, '_render_status', side_effect=slow_render):
            worker = threading.Thread(target=request_report)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(engine.status(include_report=False)['status'], 'ready')
                self.assertTrue(worker.is_alive())
            finally:
                release.set()
                worker.join(3)
        self.assertEqual(errors, [])

    def test_freshness_and_configuration_changes_invalidate_cached_version(self):
        config = {'revision': 'one', 'enabled': False}
        engine = self.make_engine(config)
        first = engine.status()
        config['revision'] = 'two'
        second = engine.status()
        self.assertNotEqual(first['report_version'], second['report_version'])
        engine._state['completed_at'] = (datetime.now(CHINA) - timedelta(hours=3)).isoformat()
        stale = engine.status()
        self.assertNotEqual(second['report_version'], stale['report_version'])
        self.assertTrue(stale['report_stale'])
        self.assertIsNone(stale['report']['strategy']['panic']['score'])
        self.assertEqual(stale['report']['strategy']['candidates'], [])
        self.assertEqual(stale['report_version'], engine.status(include_report=False)['report_version'])


if __name__ == '__main__':
    unittest.main()
