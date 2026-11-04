"""Offline runtime wiring: every production sector request has cost protection."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_ai_cost import CostLimitError
from research_data import now_iso
from test_research_sector_ai import evidence, response, CONFIG
from research_sector_ai import enrich_sector_report


class AICostEngineTests(unittest.TestCase):
    def test_runtime_reuses_evidence_and_ledger_survives_restart(self):
        config = dict(CONFIG)
        calls = []

        def request(report, identities, settings):
            calls.append(list(identities))
            return response(identities)

        def run_ai(report, **kwargs):
            return enrich_sector_report(report, requester=request, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sector-report.json'
            engine = AutoResearchEngine(path, research_scope='sectors',
                config_provider=lambda: config,
                runner=lambda **kwargs: evidence(2), ai_runner=run_ai)
            self.addCleanup(engine.close)
            engine._run(None, False, config)
            self.assertEqual(engine._state['status'], 'ready')
            self.assertEqual(len(calls), 1)
            self.assertEqual(engine.status(False)['ai_cost']['requests'], 1)
            self.assertTrue(engine._state['report']['ai_research']['cost_ledger_recorded'])
            # Advance only the scheduler admission, never the provider evidence.
            engine._ai_schedule_state = {}
            engine._run(None, False, config)
            self.assertEqual(len(calls), 1)
            meta = engine._state['report']['ai_research']
            self.assertEqual(meta['reused_count'], 2)
            self.assertEqual(meta['usage']['total_tokens'], 0)
            self.assertEqual(engine.status(False)['ai_cost']['requests'], 1)
            raw = path.read_text(encoding='utf-8')
            self.assertNotIn(CONFIG['key'], raw)
            self.assertNotIn('_cost_guard', raw)
            engine.close()
            restored = AutoResearchEngine(path, research_scope='sectors',
                config_provider=lambda: config, ai_runner=run_ai)
            self.addCleanup(restored.close)
            # The saved report is already ledger-accounted, so no bootstrap double charge.
            self.assertEqual(restored.status(False)['ai_cost']['requests'], 1)

    def test_live_limit_change_reaches_each_request_without_config_revision(self):
        config = {**CONFIG, 'cost_controls': {'daily_request_limit': 0,
                  'daily_token_limit': 8_000_000, 'reuse_enabled': True}}
        got = {}

        def run_ai(report, config, **kwargs):
            got.update(config)
            return {**report, 'ai_research': {'status': 'disabled'}}

        with tempfile.TemporaryDirectory() as folder:
            engine = AutoResearchEngine(Path(folder) / 'sector-report.json',
                research_scope='sectors', config_provider=lambda: config,
                runner=lambda **kwargs: evidence(1), ai_runner=run_ai)
            self.addCleanup(engine.close)
            engine._run(None, False, dict(config))
            guard = got['_cost_guard']
            send = unittest.mock.Mock(return_value={'usage': {
                'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
            with self.assertRaises(CostLimitError):
                guard.invoke('sector', {'max_tokens': 10}, got['_cost_config_provider'](), send)
            send.assert_not_called()
            config['cost_controls'] = {**config['cost_controls'], 'daily_request_limit': 1}
            guard.invoke('sector', {'max_tokens': 10}, got['_cost_config_provider'](), send)
            self.assertEqual(send.call_count, 1)
            public = engine.status(False)
            self.assertEqual(public['ai_cost']['requests'], 1)
            self.assertNotIn(CONFIG['key'], json.dumps(public))


if __name__ == '__main__':
    unittest.main()
