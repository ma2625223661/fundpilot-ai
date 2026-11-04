import json
import multiprocessing
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from research_ai_cost import AICostGuard, CHINA, CostLimitError, MAX_INPUT_BYTES, IMPORTED_UNKNOWN_RESERVATION


PAYLOAD = {'model': 'test-model', 'max_tokens': 100, 'messages': [{'role': 'user', 'content': '核验真实证据'}]}
CONFIG = {'key': 'private-unit-test-key', 'cost_controls': {'daily_request_limit': 28, 'daily_token_limit': 8_000_000}}
NOW = datetime(2026, 10, 31, 22, 30, tzinfo=CHINA)


def response(prompt=20, completion=10, **extra):
    return {'usage': {'prompt_tokens': prompt, 'completion_tokens': completion,
                      'total_tokens': prompt + completion, **extra}, 'choices': []}


def _first_process_attempt(path, barrier, results):
    """Spawn-safe worker: every process races its first ledger transaction."""
    try:
        guard = AICostGuard(path, clock=lambda: NOW)
        barrier.wait(timeout=20)
        guard.invoke('sector', PAYLOAD,
                     {'cost_controls': {'daily_request_limit': 3}}, lambda: response())
        results.put('sent')
    except CostLimitError as error:
        results.put(error.code)
    except BaseException as error:
        results.put(type(error).__name__)


class AICostGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.now = NOW
        self.guard = AICostGuard(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_usage_releases_conservative_difference_and_records_kind(self):
        result = response(prompt_cache_hit_tokens=7, prompt_cache_miss_tokens=13)
        observed = {}
        def send():
            before = self.guard.summary(CONFIG)
            observed.update(before)
            self.assertEqual(before['requests'], 1)
            self.assertEqual(before['unknown_requests'], 1)
            self.assertEqual(before['in_flight_requests'], 1)
            self.assertGreater(before['tokens_reserved'], 30)
            return result
        self.assertIs(self.guard.invoke('sector', PAYLOAD, CONFIG, send), result)
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['usage']['total_tokens'], 30)
        self.assertEqual(summary['tokens_reserved'], 30)
        self.assertEqual(summary['tokens_unsettled'], 0)
        self.assertEqual(summary['unknown_requests'], 0)
        self.assertEqual(summary['prompt_cache_hit_tokens'], 7)
        self.assertEqual(summary['by_kind']['sector']['requests'], 1)
        self.assertEqual(summary['by_kind']['events']['requests'], 0)
        self.assertEqual(summary['limits']['daily_request_limit'], 28)
        self.assertTrue(summary['limits']['reuse_enabled'])

    def test_missing_invalid_and_timeout_usage_keep_full_reservation_and_attempt_count(self):
        size = len(json.dumps(PAYLOAD, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + PAYLOAD['max_tokens']
        for value in ({}, {'usage': {}}, {'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 99}}):
            self.guard.invoke('events', PAYLOAD, CONFIG, lambda value=value: value)
        with self.assertRaisesRegex(TimeoutError, 'private timeout body'):
            self.guard.invoke('sector', PAYLOAD, CONFIG, Mock(side_effect=TimeoutError('private timeout body')))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['requests'], 4)
        self.assertEqual(summary['unknown_requests'], 4)
        self.assertEqual(summary['tokens_reserved'], size * 4)
        self.assertEqual(summary['tokens_unsettled'], size * 4)
        self.assertFalse(summary['usage_complete'])
        self.assertEqual(summary['usage']['total_tokens'], 0)
        self.assertEqual(summary['by_kind']['events']['unknown_requests'], 3)
        self.assertEqual(summary['in_flight_requests'], 0)

    def test_restart_preserves_requests_and_unknown_reservations(self):
        with self.assertRaises(TimeoutError):
            self.guard.invoke('sector', PAYLOAD, CONFIG, Mock(side_effect=TimeoutError()))
        prior = self.guard.summary(CONFIG)
        restarted = AICostGuard(self.path, clock=lambda: NOW)
        self.assertEqual(restarted.summary(CONFIG), prior)
        limit = {'cost_controls': {'daily_request_limit': 1, 'daily_token_limit': 8_000_000}}
        send = Mock()
        with self.assertRaises(CostLimitError) as error:
            restarted.invoke('sector', PAYLOAD, limit, send)
        self.assertEqual(error.exception.code, 'request_limit')
        send.assert_not_called()

    def test_atomic_parallel_admission_cannot_exceed_request_limit(self):
        # Initialize once, then use independent guards/connections like workers
        # in separate processes would, with the SQLite writer transaction lock.
        self.guard.summary(CONFIG)
        limit = {'cost_controls': {'daily_request_limit': 3, 'daily_token_limit': 8_000_000}}
        sent = []
        lock = threading.Lock()
        def attempt(index):
            guard = AICostGuard(self.path, clock=lambda: NOW)
            def send():
                with lock:
                    sent.append(index)
                return response()
            try:
                guard.invoke('sector', PAYLOAD, limit, send)
                return 'sent'
            except CostLimitError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(results.count('sent'), 3)
        self.assertEqual(results.count('request_limit'), 9)
        self.assertEqual(len(sent), 3)
        self.assertEqual(self.guard.summary(CONFIG)['requests'], 3)

    def test_first_transaction_parallel_creation_stress_thirty_rounds(self):
        limit = {'cost_controls': {'daily_request_limit': 3}}
        for trial in range(30):
            path = Path(self.temp.name) / ('first-race-' + str(trial) + '.sqlite3')
            guard = AICostGuard(path, clock=lambda: NOW)
            barrier = threading.Barrier(8)
            def attempt(_):
                # Exercise both a shared runtime guard and independently
                # created guards pointing at the same initially absent file.
                current = guard if trial % 2 == 0 else AICostGuard(path, clock=lambda: NOW)
                barrier.wait(timeout=10)
                try:
                    current.invoke('sector', PAYLOAD, limit, lambda: response())
                    return 'sent'
                except CostLimitError as error:
                    return error.code
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(attempt, range(8)))
            with self.subTest(trial=trial):
                self.assertEqual(results.count('sent'), 3, results)
                self.assertEqual(results.count('request_limit'), 5, results)
                summary = guard.summary(CONFIG)
                self.assertFalse(summary['blocked'])
                self.assertEqual(summary['requests'], 3)
                self.assertEqual(summary['usage']['total_tokens'], 90)
                self.assertEqual(summary['unknown_requests'], 0)

    def test_first_transaction_creation_is_safe_across_spawned_processes(self):
        context = multiprocessing.get_context('spawn')
        barrier = context.Barrier(6)
        results = context.Queue()
        processes = [context.Process(target=_first_process_attempt,
                                     args=(str(self.path), barrier, results)) for _ in range(6)]
        try:
            for process in processes:
                process.start()
            outcomes = [results.get(timeout=30) for _ in processes]
            for process in processes:
                process.join(timeout=10)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(outcomes.count('sent'), 3, outcomes)
            self.assertEqual(outcomes.count('request_limit'), 3, outcomes)
            summary = self.guard.summary(CONFIG)
            self.assertFalse(summary['blocked'])
            self.assertEqual(summary['requests'], 3)
            self.assertEqual(summary['usage']['total_tokens'], 90)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            results.close()
            results.join_thread()

    def test_atomic_parallel_token_reservation_cannot_exceed_budget(self):
        self.guard.summary(CONFIG)
        reservation = len(json.dumps(PAYLOAD, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 100
        limit = {'cost_controls': {'daily_request_limit': 100, 'daily_token_limit': reservation * 2}}
        def attempt(_):
            try:
                self.guard.invoke('events', PAYLOAD, limit, lambda: {})
                return True
            except CostLimitError as error:
                self.assertEqual(error.code, 'token_limit')
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(self.guard.summary(CONFIG)['tokens_reserved'], reservation * 2)

    def test_beijing_midnight_resets_daily_admission_not_old_request_attribution(self):
        self.now = datetime(2026, 10, 31, 15, 59, 59, tzinfo=timezone.utc)
        limit = {'cost_controls': {'daily_request_limit': 1}}
        def slow_send():
            self.now += timedelta(seconds=2)
            return response()
        self.guard.invoke('events', PAYLOAD, limit, slow_send)
        today = self.guard.summary(limit)
        self.assertEqual(today['beijing_day'], '2026-11-01')
        self.assertEqual(today['requests'], 0)
        self.guard.invoke('sector', PAYLOAD, limit, lambda: response())
        self.assertEqual(self.guard.summary(limit)['requests'], 1)
        self.now = datetime(2026, 10, 31, 23, 59, 59, tzinfo=CHINA)
        prior = self.guard.summary(limit)
        self.assertEqual(prior['requests'], 1)
        self.assertEqual(prior['by_kind']['events']['usage']['total_tokens'], 30)

    def test_damaged_existing_database_fails_closed_and_hides_diagnostics(self):
        self.path.write_bytes(b'private database error with private-unit-test-key')
        send = Mock()
        with self.assertRaises(CostLimitError) as error:
            self.guard.invoke('sector', PAYLOAD, CONFIG, send)
        self.assertEqual(error.exception.code, 'ledger_unavailable')
        self.assertNotIn('private', str(error.exception))
        send.assert_not_called()
        summary = self.guard.summary(CONFIG)
        self.assertTrue(summary['blocked'])
        self.assertIsNone(summary['tokens_reserved'])
        self.assertIsNone(summary['requests'])

    def test_existing_empty_or_wrong_schema_database_is_never_reset(self):
        self.path.touch()
        with self.assertRaises(CostLimitError):
            self.guard.invoke('sector', PAYLOAD, CONFIG, Mock())
        alternate = Path(self.temp.name) / 'wrong.sqlite3'
        with sqlite3.connect(alternate) as db:
            db.execute('CREATE TABLE ledger_meta (version INTEGER)')
            db.execute('INSERT INTO ledger_meta VALUES (999)')
        db.close()
        guard = AICostGuard(alternate)
        self.assertTrue(guard.summary(CONFIG)['blocked'])

    def test_reservation_write_failure_prevents_send(self):
        self.guard.summary(CONFIG)
        send = Mock()
        with patch('research_ai_cost.sqlite3.connect', side_effect=sqlite3.OperationalError('private-key disk error')):
            with self.assertRaises(CostLimitError) as error:
                self.guard.invoke('sector', PAYLOAD, CONFIG, send)
        send.assert_not_called()
        self.assertNotIn('private-key', error.exception.reason)
        self.assertTrue(self.guard.summary(CONFIG)['blocked'])

    def test_settlement_failure_retains_reservation_and_blocks_new_calls(self):
        def send():
            self.guard._block()
            return response()
        with self.assertRaises(CostLimitError) as error:
            self.guard.invoke('sector', PAYLOAD, CONFIG, send)
        self.assertIn('保留预算预留', error.exception.reason)
        again = Mock()
        with self.assertRaises(CostLimitError):
            self.guard.invoke('sector', PAYLOAD, CONFIG, again)
        again.assert_not_called()
        recovered = AICostGuard(self.path, clock=lambda: NOW).summary(CONFIG)
        self.assertEqual(recovered['requests'], 1)
        self.assertEqual(recovered['unknown_requests'], 1)
        self.assertGreater(recovered['tokens_reserved'], 30)

    def test_input_cap_invalid_controls_and_zero_limits_prevent_all_io(self):
        cases = [(PAYLOAD | {'messages': [{'role': 'user', 'content': '中' * MAX_INPUT_BYTES}]}, CONFIG, 'input_limit'),
                 (PAYLOAD | {'max_tokens': True}, CONFIG, 'invalid_payload'),
                 (PAYLOAD | {'max_tokens': 0}, CONFIG, 'invalid_payload'),
                 (PAYLOAD, {'cost_controls': {'daily_request_limit': -1}}, 'invalid_limits'),
                 (PAYLOAD, {'cost_controls': {'daily_request_limit': True}}, 'invalid_limits'),
                 (PAYLOAD, {'cost_controls': {'daily_request_limit': 0}}, 'request_limit'),
                 (PAYLOAD, {'cost_controls': {'daily_token_limit': 0}}, 'token_limit')]
        for payload, config, code in cases:
            with self.subTest(code=code):
                send = Mock()
                with self.assertRaises(CostLimitError) as error:
                    self.guard.invoke('sector', payload, config, send)
                self.assertEqual(error.exception.code, code)
                send.assert_not_called()
        self.assertEqual(self.guard.summary(CONFIG)['requests'], 0)

    def test_cache_usage_details_and_actual_excess_are_accounted_without_secret_storage(self):
        self.guard.invoke('sector', PAYLOAD, CONFIG, lambda: response(prompt_tokens_details={'cached_tokens': 5}))
        self.guard.invoke('events', PAYLOAD, CONFIG, lambda: response(300, 200, prompt_cache_hit_tokens=4, prompt_cache_miss_tokens=296))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['tokens_reserved'], 530)
        self.assertEqual(summary['prompt_cache_hit_tokens'], 9)
        self.assertEqual(summary['prompt_cache_miss_tokens'], 311)
        self.assertEqual(summary['by_kind']['events']['usage']['total_tokens'], 500)
        serial = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn(CONFIG['key'], serial)
        self.assertNotIn(CONFIG['key'].encode(), self.path.read_bytes())
        self.assertNotIn('核验真实证据'.encode(), self.path.read_bytes())
        self.assertNotIn(b'test-model', self.path.read_bytes())

    def test_import_usage_counts_requests_and_is_idempotent_per_record_and_kind(self):
        usage = response(200, 40, prompt_cache_hit_tokens=120)['usage']
        self.assertTrue(self.guard.import_usage('private-archive-id', 'sector', usage, 13, NOW.isoformat()))
        self.assertFalse(self.guard.import_usage('private-archive-id', 'sector', usage, 13, NOW.isoformat()))
        self.assertTrue(self.guard.import_usage('private-archive-id', 'events', usage, 1, NOW.timestamp()))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['requests'], 14)
        self.assertEqual(summary['by_kind']['sector']['requests'], 13)
        self.assertEqual(summary['by_kind']['events']['requests'], 1)
        self.assertEqual(summary['tokens_reserved'], 480)
        self.assertEqual(summary['tokens_unsettled'], 0)
        self.assertEqual(summary['unknown_requests'], 0)
        self.assertEqual(summary['prompt_cache_hit_tokens'], 240)
        self.assertNotIn(b'private-archive-id', self.path.read_bytes())
        restarted = AICostGuard(self.path, clock=lambda: NOW)
        self.assertFalse(restarted.import_usage('private-archive-id', 'sector', usage, 13, NOW))
        self.assertEqual(restarted.summary(CONFIG)['requests'], 14)

    def test_import_incomplete_usage_preserves_known_tokens_and_unknown_reservation(self):
        self.assertTrue(self.guard.import_usage('incomplete', 'sector', response(500, 20)['usage'], 13, NOW, False))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['usage']['total_tokens'], 520)
        self.assertEqual(summary['tokens_reserved'], 520 + IMPORTED_UNKNOWN_RESERVATION)
        self.assertEqual(summary['tokens_unsettled'], IMPORTED_UNKNOWN_RESERVATION)
        self.assertEqual(summary['requests'], 13)
        self.assertEqual(summary['unknown_requests'], 1)
        self.assertEqual(summary['in_flight_requests'], 0)
        self.assertFalse(summary['usage_complete'])
        self.assertTrue(self.guard.import_usage('empty-usage', 'events', response(0, 0)['usage'], 1, NOW, False))
        self.assertEqual(self.guard.summary(CONFIG)['tokens_unsettled'], 2 * IMPORTED_UNKNOWN_RESERVATION)

    def test_import_is_today_only_and_rejects_invalid_inputs(self):
        usage = response()['usage']
        # This UTC instant is the current Beijing date.
        self.assertTrue(self.guard.import_usage('utc', 'events', usage, 1, '2026-10-30T17:00:00Z'))
        cases = [('', 'events', usage, 1, NOW, True),
                 ('old', 'events', usage, 1, NOW - timedelta(days=1), True),
                 ('future', 'events', usage, 1, NOW + timedelta(days=1), True),
                 ('bad-time', 'events', usage, 1, 'private-not-a-date', True),
                 ('bad-kind', 'other', usage, 1, NOW, True),
                 ('bad-count', 'events', usage, True, NOW, True),
                 ('zero-count', 'events', usage, 0, NOW, True),
                 ('bad-usage', 'events', {'prompt_tokens': -1}, 1, NOW, True),
                 ('inconsistent', 'events', usage | {'total_tokens': 999}, 1, NOW, False),
                 ('bad-complete', 'events', usage, 1, NOW, 1)]
        for args in cases:
            with self.subTest(record=args[0]):
                self.assertFalse(self.guard.import_usage(*args))
        self.assertEqual(self.guard.summary(CONFIG)['requests'], 1)

    def test_imported_actual_spend_can_exceed_limits_and_prevent_next_send(self):
        self.assertTrue(self.guard.import_usage('spent', 'sector', response(9_000_000, 50)['usage'], 40, NOW))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['remaining_requests'], 0)
        self.assertEqual(summary['remaining_tokens'], 0)
        send = Mock()
        with self.assertRaises(CostLimitError) as error:
            self.guard.invoke('sector', PAYLOAD, CONFIG, send)
        self.assertEqual(error.exception.code, 'request_limit')
        send.assert_not_called()

    def test_import_zero_token_complete_attempt_is_still_counted(self):
        self.assertTrue(self.guard.import_usage('zero', 'events', response(0, 0)['usage'], 1, NOW))
        summary = self.guard.summary(CONFIG)
        self.assertEqual(summary['requests'], 1)
        self.assertEqual(summary['tokens_reserved'], 0)
        self.assertTrue(summary['usage_complete'])


if __name__ == '__main__':
    unittest.main()
