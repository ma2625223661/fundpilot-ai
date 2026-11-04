import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_data import CHINA
from research_schedule import (DEFAULT_SCHEDULE, scheduled_time, schedule_settings,
                               schedule_signature, schedule_allows_run, schedule_stop_time)
from test_research_auto import sample_report


class ScheduleTests(unittest.TestCase):
    def config(self, mode='daily', daily_time='15:30', interval_minutes=60):
        return {'key': 'synthetic-test-only', 'enabled': True, 'revision': 'test-plan',
                'schedule': {**DEFAULT_SCHEDULE, 'mode': mode, 'daily_time': daily_time,
                             'interval_minutes': interval_minutes}}

    def test_daily_next_day_and_beijing_timezone(self):
        setting = self.config()['schedule']
        before = datetime.fromisoformat('2026-10-30T07:00:00+00:00')
        self.assertEqual(scheduled_time(setting, before).isoformat(), '2026-10-30T15:30:00+08:00')
        after = datetime.fromisoformat('2026-10-30T15:31:00+08:00')
        self.assertEqual(scheduled_time(setting, after).isoformat(), '2026-10-31T15:30:00+08:00')

    def test_interval_and_scheduled_interval_have_distinct_first_start(self):
        now = datetime.fromisoformat('2026-10-30T14:00:00+08:00')
        interval = self.config('interval')['schedule']
        combined = self.config('scheduled_interval')['schedule']
        self.assertEqual(scheduled_time(interval, now), now)
        self.assertEqual(scheduled_time(combined, now).hour, 15)
        complete = now.replace(hour=16, minute=5)
        self.assertEqual(scheduled_time(combined, complete, after_run=True), complete + timedelta(hours=1))

    def run_once(self, engine):
        self.assertTrue(engine.request_scan())
        engine._worker.join(2)
        self.assertFalse(engine._worker.is_alive())
        self.assertEqual(engine.status()['status'], 'ready')

    def test_future_daily_scan_and_manual_refresh_never_call_provider(self):
        setting = (datetime.now(CHINA) + timedelta(hours=1)).strftime('%H:%M')
        config = self.config(daily_time=setting)
        engine = AutoResearchEngine(runner=lambda **_: sample_report(), config_provider=lambda: config)
        try:
            with patch('research_auto_ai.provider_json') as provider:
                self.run_once(engine)
                self.run_once(engine)
            provider.assert_not_called()
            state = engine.status()
            self.assertEqual(state['report']['ai_research']['status'], 'scheduled')
            self.assertTrue(state['report']['ai_research']['configuration_enabled'])
            self.assertIsNotNone(state['ai_next_run_at'])
        finally:
            engine.close()

    def test_due_plan_runs_once_then_waits_full_interval_and_survives_restart(self):
        config = self.config('scheduled_interval')
        calls = []
        def ai_runner(report, config, **kwargs):
            if config.get('enabled'):
                calls.append(True)
            result = copy.deepcopy(report)
            result['ai_research'] = {'status': 'completed' if config.get('enabled') else 'disabled',
                'revision': config['revision'], 'configuration_enabled': config.get('enabled')}
            return result
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = AutoResearchEngine(path, runner=lambda **_: sample_report(),
                                        config_provider=lambda: config, ai_runner=ai_runner)
            try:
                engine._ai_due(config)
                engine._ai_schedule_state['next_run_at'] = (datetime.now(CHINA) - timedelta(seconds=1)).isoformat()
                self.run_once(engine)
                self.assertEqual(len(calls), 1)
                due = engine.status()['ai_next_run_at']
                self.run_once(engine)
                self.assertEqual(len(calls), 1)
                self.assertEqual(engine.status()['ai_next_run_at'], due)
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertNotIn(config['key'], json.dumps(saved))
                restored = AutoResearchEngine(path, config_provider=lambda: config)
                try:
                    self.assertEqual(restored.status()['ai_next_run_at'], due)
                finally:
                    restored.close()
            finally:
                engine.close()

    def test_disabling_clears_next_run_and_status_never_starts_threads(self):
        config = self.config()
        engine = AutoResearchEngine(config_provider=lambda: config)
        try:
            self.assertIsNotNone(engine.status()['ai_next_run_at'])
            config.update(enabled=False, revision='disabled')
            self.assertIsNone(engine.status()['ai_next_run_at'])
            self.assertIsNone(engine._worker)
            self.assertIsNone(engine._scheduler)
        finally:
            engine.close()

    def test_schedule_save_during_active_scan_cannot_be_reset_by_old_config(self):
        config = self.config('interval')
        entered, release = threading.Event(), threading.Event()
        calls = []
        def runner(**kwargs):
            entered.set()
            release.wait(2)
            return sample_report()
        def ai_runner(report, config, **kwargs):
            calls.append(bool(config.get('enabled')))
            result = copy.deepcopy(report)
            result['ai_research'] = {'status': 'disabled', 'revision': config['revision']}
            return result
        engine = AutoResearchEngine(runner=runner, config_provider=lambda: dict(config), ai_runner=ai_runner)
        engine.start = lambda: None
        try:
            self.assertTrue(engine.request_scan())
            self.assertTrue(entered.wait(1))
            config.update(revision='future-new-plan')
            engine.config_changed(schedule_only=True)
            due = engine._ai_due(config)
            release.set()
            engine._worker.join(2)
            self.assertEqual(engine._ai_due(config), due)
            self.run_once(engine)
            self.assertEqual(calls, [False, False])
            self.assertGreater((due - datetime.now(CHINA)).total_seconds(), 50 * 60)
        finally:
            release.set()
            engine.close()

    def test_schedule_only_save_is_restored_even_before_any_public_report(self):
        config = self.config('interval')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = AutoResearchEngine(path, config_provider=lambda: config)
            engine.start = lambda: None
            try:
                engine.config_changed(schedule_only=True)
                due = engine.status()['ai_next_run_at']
                self.assertFalse(path.exists())
                self.assertTrue(path.with_suffix('.schedule.json').exists())
                restored = AutoResearchEngine(path, config_provider=lambda: config)
                try:
                    self.assertEqual(restored.status()['ai_next_run_at'], due)
                    self.assertGreater((restored._ai_due(config) - datetime.now(CHINA)).total_seconds(), 50 * 60)
                finally:
                    restored.close()
            finally:
                engine.close()


class ScheduleWindowTests(unittest.TestCase):
    def setting(self, mode='scheduled_interval', start='09:00', end='15:00', interval=37):
        return {**DEFAULT_SCHEDULE, 'mode': mode, 'daily_time': start,
                'end_time': end, 'interval_minutes': interval}

    def timestamp(self, value):
        return datetime.fromisoformat(value + '+08:00')

    def test_same_day_window_start_inclusive_end_exclusive_and_next_opening(self):
        setting = self.setting()
        for instant, allowed, due in [
                ('2026-10-30T08:59:59', False, '2026-10-30T09:00:00'),
                ('2026-10-30T09:00:00', True, '2026-10-30T09:00:00'),
                ('2026-10-30T14:59:59', True, '2026-10-30T14:59:59'),
                ('2026-10-30T15:00:00', False, '2026-10-31T09:00:00'),
                ('2026-10-30T23:00:00', False, '2026-10-31T09:00:00')]:
            now = self.timestamp(instant)
            with self.subTest(now=instant):
                self.assertEqual(schedule_allows_run(setting, now), allowed)
                self.assertEqual(scheduled_time(setting, now), self.timestamp(due))
                self.assertEqual(schedule_stop_time(setting, now),
                                 self.timestamp('2026-10-30T15:00:00') if allowed else None)

    def test_interval_completion_at_or_beyond_end_skips_to_next_day_without_catchup(self):
        setting = self.setting(interval=30)
        before = self.timestamp('2026-10-30T14:29:59')
        self.assertEqual(scheduled_time(setting, before, after_run=True), self.timestamp('2026-10-30T14:59:59'))
        for instant in ('2026-10-30T14:30:00', '2026-10-30T14:59:00', '2026-10-30T15:20:00'):
            self.assertEqual(scheduled_time(setting, self.timestamp(instant), after_run=True),
                             self.timestamp('2026-10-31T09:00:00'))

    def test_overnight_window_uses_previous_start_until_exclusive_morning_end(self):
        setting = self.setting(start='22:00', end='06:00')
        for instant, allowed, end in [
                ('2026-10-30T21:59:59', False, None),
                ('2026-10-30T22:00:00', True, '2026-10-31T06:00:00'),
                ('2026-10-31T00:00:00', True, '2026-10-31T06:00:00'),
                ('2026-10-31T05:59:59', True, '2026-10-31T06:00:00'),
                ('2026-10-31T06:00:00', False, None)]:
            now = self.timestamp(instant)
            with self.subTest(now=instant):
                self.assertEqual(schedule_allows_run(setting, now), allowed)
                self.assertEqual(schedule_stop_time(setting, now), self.timestamp(end) if end else None)
        self.assertEqual(scheduled_time(setting, self.timestamp('2026-10-31T06:00:00')),
                         self.timestamp('2026-10-31T22:00:00'))
        self.assertEqual(scheduled_time(setting, self.timestamp('2026-10-30T23:45:00'), after_run=True),
                         self.timestamp('2026-10-31T00:22:00'))
        self.assertEqual(scheduled_time(setting, self.timestamp('2026-10-31T05:50:00'), after_run=True),
                         self.timestamp('2026-10-31T22:00:00'))

    def test_daily_still_plans_one_fixed_start_and_uses_end_only_as_request_gate(self):
        setting = self.setting(mode='daily')
        self.assertEqual(scheduled_time(setting, self.timestamp('2026-10-30T08:30:00')),
                         self.timestamp('2026-10-30T09:00:00'))
        now = self.timestamp('2026-10-30T10:00:00')
        self.assertTrue(schedule_allows_run(setting, now))
        self.assertEqual(scheduled_time(setting, now), self.timestamp('2026-10-31T09:00:00'))
        self.assertEqual(scheduled_time(setting, self.timestamp('2026-10-30T09:00:00'), after_run=True),
                         self.timestamp('2026-10-31T09:00:00'))
        self.assertFalse(schedule_allows_run(setting, self.timestamp('2026-10-30T15:00:00')))

    def test_interval_mode_ignores_saved_start_and_end(self):
        setting = self.setting(mode='interval', start='22:00', end='06:00', interval=17)
        now = self.timestamp('2026-10-30T12:00:00')
        self.assertTrue(schedule_allows_run(setting, now))
        self.assertIsNone(schedule_stop_time(setting, now))
        self.assertEqual(scheduled_time(setting, now), now)
        self.assertEqual(scheduled_time(setting, now, after_run=True), now + timedelta(minutes=17))

    def test_null_end_preserves_old_unbounded_scheduling_and_six_item_signature(self):
        legacy = {'revision': 'legacy-plan', 'enabled': True, 'key': 'synthetic-only',
                  'schedule': {'mode': 'scheduled_interval', 'daily_time': '09:00',
                               'interval_minutes': 45, 'timezone': 'Asia/Shanghai'}}
        expected = ['legacy-plan', True, 'scheduled_interval', 45, '09:00', 'Asia/Shanghai']
        self.assertEqual(schedule_signature(legacy), expected)
        explicit = copy.deepcopy(legacy)
        explicit['schedule']['end_time'] = None
        self.assertEqual(schedule_signature(explicit), expected)
        setting = schedule_settings(legacy)
        now = self.timestamp('2026-10-30T10:00:00')
        self.assertTrue(schedule_allows_run(setting, now))
        self.assertIsNone(schedule_stop_time(setting, now))
        self.assertEqual(scheduled_time(setting, now), self.timestamp('2026-10-31T09:00:00'))
        self.assertEqual(scheduled_time(setting, now, after_run=True), now + timedelta(minutes=45))
        explicit['schedule']['end_time'] = '15:00'
        self.assertEqual(schedule_signature(explicit), expected + ['15:00'])

    def test_legacy_six_item_sidecar_restart_preserves_reserved_future_slot(self):
        config = {'revision': 'legacy-plan', 'enabled': True, 'key': 'synthetic-only',
                  'schedule': {'mode': 'interval', 'daily_time': '09:00',
                               'interval_minutes': 45, 'timezone': 'Asia/Shanghai'}}
        due = datetime.now(CHINA) + timedelta(hours=3)
        saved = {'signature': ['legacy-plan', True, 'interval', 45, '09:00', 'Asia/Shanghai'],
                 'next_run_at': due.isoformat()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.with_suffix('.schedule.json').write_text(json.dumps(saved), encoding='utf-8')
            engine = AutoResearchEngine(path, config_provider=lambda: config)
            try:
                self.assertEqual(engine._ai_due(config), due)
                self.assertEqual(engine._ai_schedule_state, saved)
                self.assertIsNone(engine._worker)
            finally:
                engine.close()

    def test_window_time_converts_utc_and_does_not_mutate_setting(self):
        setting = self.setting()
        original = copy.deepcopy(setting)
        now = datetime.fromisoformat('2026-10-30T01:15:00+00:00')
        self.assertTrue(schedule_allows_run(setting, now))
        self.assertEqual(scheduled_time(setting, now).isoformat(), '2026-10-30T09:15:00+08:00')
        self.assertEqual(schedule_stop_time(setting, now).isoformat(), '2026-10-30T15:00:00+08:00')
        self.assertEqual(setting, original)


if __name__ == '__main__':
    unittest.main()
