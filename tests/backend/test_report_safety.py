"""Issue #5: a round with no data must not replace a valid report, and a report
that cannot be saved says so instead of silently disappearing after a restart."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_auto
from research_auto import AutoResearchEngine, usable_sector_count
from test_sector_engine import sector_report


def empty_report():
    report = sector_report()
    # Every source failed: directions are listed but carry no change and no score.
    report['sector_analysis'] = [{'id': 'sector_test', 'status': 'missing', 'score': None, 'change_pct': None}]
    return report


class ReportSafetyTests(unittest.TestCase):
    def engine(self, runner, path):
        engine = AutoResearchEngine(research_scope='sectors', runner=runner,
                                    ai_runner=lambda report, **_: report, state_path=path)
        self.addCleanup(engine.close)
        return engine

    def scan(self, engine):
        engine.request_scan()
        engine._worker.join(5)

    def test_an_empty_round_keeps_the_previous_valid_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sector-report.json'
            reports = iter([sector_report(), empty_report()])
            engine = self.engine(lambda **_: next(reports), path)
            self.scan(engine)
            first = engine._state['report']
            self.assertEqual(usable_sector_count(first), 1)
            self.scan(engine)
            self.assertIs(engine._state['report'], first)
            self.assertEqual(engine._state['status'], 'error')
            self.assertIn('保留上一份', engine._state['stage'])
            self.assertIn('避免空报告覆盖', engine._state['error'])
            saved = json.loads(path.read_text(encoding='utf-8'))['report']
            self.assertEqual(saved['sector_analysis'][0]['score'], 70)

    def test_an_empty_first_round_is_still_published(self):
        # With nothing to protect, an empty report is shown (it explains the gaps).
        engine = self.engine(lambda **_: empty_report(), None)
        self.scan(engine)
        self.assertEqual(engine._state['status'], 'ready')
        self.assertEqual(usable_sector_count(engine._state['report']), 0)

    def test_a_report_over_the_limit_explains_the_restart_consequence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sector-report.json'
            engine = self.engine(lambda **_: sector_report(), path)
            with patch.object(research_auto, 'MAX_REPORT_BYTES', 10), patch('builtins.print') as printed:
                self.scan(engine)
            warnings = engine._state['report']['snapshot']['warnings']
            self.assertTrue(any('重启后会回到上一份已保存的报告' in item for item in warnings), warnings)
            self.assertTrue(any('未能保存到磁盘' in str(call) for call in printed.call_args_list))
            self.assertFalse(path.exists())

    def test_the_limit_leaves_room_for_a_complete_report(self):
        self.assertGreaterEqual(research_auto.MAX_REPORT_BYTES, 64_000_000)


if __name__ == '__main__':
    unittest.main()
