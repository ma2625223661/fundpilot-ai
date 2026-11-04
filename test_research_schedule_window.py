"""Clock-controlled engine checks; no network or real credential store."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_auto_ai import enrich_auto_report
from research_data import CHINA
from research_schedule import DEFAULT_SCHEDULE, schedule_signature
from test_research_auto_ai import evidence_report, response_for


class Clock(datetime):
    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    @classmethod
    def set(cls, value):
        cls.current = datetime.fromisoformat(value)


class ScheduleWindowEngineTests(unittest.TestCase):
    def setUp(self):
        Clock.set('2026-10-30T14:00:00+08:00')
        clock = patch('research_auto.datetime', Clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.config = {
            'enabled': True, 'key': 'synthetic-window-only', 'revision': 'window-test',
            'schedule': {**DEFAULT_SCHEDULE, 'mode': 'scheduled_interval',
                         'daily_time': '09:30', 'end_time': '15:00', 'interval_minutes': 7},
        }

    def engine(self, **kwargs):
        engine = AutoResearchEngine(config_provider=lambda: copy.deepcopy(self.config),
                                    runner=lambda **_: evidence_report(), **kwargs)
        self.addCleanup(engine.close)
        return engine

    def make_due(self, engine, value):
        engine._ai_schedule_state = {'signature': schedule_signature(self.config),
                                     'next_run_at': value}

    def run_once(self, engine):
        engine._run(None, False, copy.deepcopy(self.config))
        self.assertEqual(engine._state['status'], 'ready', engine._state.get('error'))
        return engine._state['report']['ai_research']

    def test_expired_slot_outside_window_advances_durably_without_provider(self):
        Clock.set('2026-10-30T15:00:00+08:00')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = self.engine(state_path=path)
            self.make_due(engine, '2026-10-30T14:59:00+08:00')
            with patch('research_auto_ai.provider_json') as paid:
                meta = self.run_once(engine)
            paid.assert_not_called()
            expected = '2026-10-31T09:30:00+08:00'
            self.assertEqual(meta['status'], 'scheduled')
            self.assertEqual(meta['next_run_at'], expected)
            self.assertTrue(meta['configuration_enabled'])
            self.assertEqual(json.loads(path.with_suffix('.schedule.json').read_text())['next_run_at'], expected)
            restored = self.engine(state_path=path)
            self.assertEqual(restored._ai_due(self.config).isoformat(), expected)

    def test_public_collection_crossing_stop_cannot_start_ai(self):
        Clock.set('2026-10-30T14:59:00+08:00')
        engine = self.engine()
        self.make_due(engine, Clock.now(CHINA).isoformat())
        def collect(**_):
            Clock.set('2026-10-30T15:00:00+08:00')
            return evidence_report()
        engine.runner = collect
        with patch('research_auto_ai.provider_json') as paid:
            meta = self.run_once(engine)
        paid.assert_not_called()
        self.assertEqual(meta['status'], 'scheduled')
        self.assertEqual(meta['next_run_at'], '2026-10-31T09:30:00+08:00')
        self.assertFalse(engine._state['report']['automatic']['paid_api_calls'])

    def test_custom_seven_minute_interval_runs_once_without_catch_up(self):
        calls = []
        def requester(_, codes, config):
            calls.append(codes)
            Clock.set('2026-10-30T14:02:00+08:00')
            return response_for(codes)
        engine = self.engine(ai_runner=lambda report, **kwargs: enrich_auto_report(
            report, requester=requester, **kwargs))
        meta = self.run_once(engine)
        self.assertEqual(meta['status'], 'completed')
        self.assertEqual(meta['request_count'], 1)
        self.assertEqual(engine._ai_due(self.config).isoformat(), '2026-10-30T14:09:00+08:00')
        self.assertEqual(self.run_once(engine)['status'], 'scheduled')
        self.assertEqual(len(calls), 1)

    def test_schedule_only_save_in_open_window_waits_full_interval(self):
        engine = self.engine()
        engine.start = lambda: None
        with patch('research_auto_ai.provider_json') as paid:
            self.assertTrue(engine.config_changed(schedule_only=True))
            due = engine._ai_due(self.config)
            meta = self.run_once(engine)
        paid.assert_not_called()
        self.assertEqual(due, Clock.now(CHINA) + timedelta(minutes=7))
        self.assertEqual(meta['status'], 'scheduled')
        self.assertTrue(self.config['enabled'])
        self.assertEqual(self.config['schedule']['end_time'], '15:00')

    def test_schedule_only_save_near_stop_waits_next_daily_start(self):
        Clock.set('2026-10-30T14:58:00+08:00')
        engine = self.engine()
        engine.start = lambda: None
        self.assertTrue(engine.config_changed(schedule_only=True))
        self.assertEqual(engine._ai_due(self.config).isoformat(), '2026-10-31T09:30:00+08:00')

    def test_overnight_window_keeps_sent_result_and_stops_remaining_batches(self):
        self.config['schedule'].update(daily_time='23:00', end_time='01:00')
        Clock.set('2026-10-31T00:59:00+08:00')
        calls = []
        def requester(_, codes, config):
            calls.append(codes)
            Clock.set('2026-10-31T01:00:00+08:00')
            return response_for(codes)
        engine = self.engine(ai_runner=lambda report, **kwargs: enrich_auto_report(
            report, requester=requester, **kwargs))
        engine.runner = lambda **_: evidence_report(24)
        meta = self.run_once(engine)
        self.assertEqual(meta['status'], 'window_closed')
        self.assertTrue(meta['stopped_for_schedule'])
        self.assertFalse(meta['terminal_error'])
        self.assertGreaterEqual(len(calls), 1)
        self.assertLessEqual(len(calls), 2)
        self.assertEqual(meta['request_count'], len(calls))
        self.assertEqual(meta['analyzed_count'], 8 * len(calls))
        self.assertEqual(meta['usage']['total_tokens'], 150 * len(calls))
        self.assertEqual(engine._ai_due(self.config).isoformat(), '2026-10-31T23:00:00+08:00')
        self.assertEqual(engine._blocked_ai_revision, None)

    def test_old_batch_remains_closed_when_in_flight_request_returns_next_window(self):
        Clock.set('2026-10-30T14:59:00+08:00')
        allowed = []
        def ai_runner(report, config, can_start_request, **_):
            allowed.append(can_start_request())
            Clock.set('2026-10-30T15:00:00+08:00')
            allowed.append(can_start_request())
            Clock.set('2026-10-31T09:31:00+08:00')
            allowed.append(can_start_request())
            result = copy.deepcopy(report)
            result['ai_research'] = {'status': 'window_closed', 'stopped_for_schedule': True}
            return result
        engine = self.engine(ai_runner=ai_runner)
        self.run_once(engine)
        self.assertEqual(allowed, [True, False, False])
        self.assertEqual(engine._ai_due(self.config).isoformat(), '2026-10-31T09:38:00+08:00')

    def test_daily_plan_does_not_replay_missed_slot_after_stop(self):
        self.config['schedule']['mode'] = 'daily'
        Clock.set('2026-10-30T15:01:00+08:00')
        engine = self.engine()
        self.make_due(engine, '2026-10-30T09:30:00+08:00')
        with patch('research_auto_ai.provider_json') as paid:
            meta = self.run_once(engine)
        paid.assert_not_called()
        self.assertEqual(meta['status'], 'scheduled')
        self.assertEqual(meta['next_run_at'], '2026-10-31T09:30:00+08:00')

    def test_blocked_credentials_outside_window_keep_report_without_missing_due(self):
        Clock.set('2026-10-30T15:01:00+08:00')
        engine = self.engine()
        engine._blocked_ai_revision = self.config['revision']
        with patch('research_auto_ai.provider_json') as paid:
            meta = self.run_once(engine)
        paid.assert_not_called()
        self.assertEqual(meta['status'], 'error')
        self.assertTrue(meta['terminal_error'])
        self.assertTrue(meta['blocked_until_config_change'])
        self.assertIsNone(engine._ai_due(self.config))


if __name__ == '__main__':
    unittest.main()
