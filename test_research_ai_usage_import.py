import copy
import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from research_ai_cost import AICostGuard, CHINA, CostLimitError
from research_ai_usage_import import bootstrap_usage, IMPORT_ERROR


NOW = datetime(2026, 10, 31, 23, 50, tzinfo=CHINA)
PAYLOAD = {'max_tokens': 10, 'messages': []}


def usage(prompt=2000, completion=20):
    return {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': prompt + completion}


def report(at=NOW, requests=14, complete=True):
    return {'as_of': at.isoformat(), 'ai_research': {'revision': 'test-revision',
            'request_count': requests, 'usage': usage(), 'usage_complete': complete},
            'event_analysis': {'as_of': at.isoformat(), 'revision': 'test-revision',
            'request_count': 1, 'usage': usage(200, 10), 'usage_complete': True},
            'summary': 'private-report-text-not-for-ledger'}


class BootstrapUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.state = self.folder / 'sector-report.json'
        self.archive = self.folder / 'accounts.sqlite3'
        self.guard = AICostGuard(self.folder / 'cost.sqlite3', clock=lambda: NOW)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, value):
        self.state.write_text(json.dumps({'report': value}, ensure_ascii=False), encoding='utf-8')

    def archives(self, values):
        db = sqlite3.connect(self.archive)
        try:
            db.executescript('''CREATE TABLE reports(id TEXT PRIMARY KEY,payload BLOB NOT NULL,
                summary TEXT NOT NULL,sectors INTEGER NOT NULL,created REAL NOT NULL);
                CREATE TABLE users(secret TEXT); CREATE TABLE sessions(secret TEXT);
                CREATE TABLE credentials(secret TEXT);
                INSERT INTO users VALUES ('private-account-secret');''')
            for index, value in enumerate(values):
                blob = gzip.compress(json.dumps(value, ensure_ascii=False).encode())
                db.execute('INSERT INTO reports VALUES (?,?,?,?,?)',
                           ('different-archive-id-' + str(index), blob, '', 100, NOW.timestamp() - index))
            db.commit()
        finally:
            db.close()

    def assert_blocked(self):
        result = bootstrap_usage(self.guard, self.state)
        self.assertEqual(result, {'status': 'error', 'error': IMPORT_ERROR})
        self.assertTrue(self.guard.summary()['blocked'])
        send = Mock()
        with self.assertRaises(CostLimitError):
            self.guard.invoke('sector', PAYLOAD, {}, send)
        send.assert_not_called()

    def test_fresh_install_without_sources_does_not_create_account_database(self):
        self.assertIsNone(bootstrap_usage(self.guard, None))
        self.assertIsNone(bootstrap_usage(self.guard, self.state))
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.guard.path.exists())

    def test_archive_and_current_are_deduplicated_and_events_are_subtracted(self):
        value = report()
        self.archives([value, value])
        self.save(value)
        result = bootstrap_usage(self.guard, self.state)
        self.assertEqual(result, {'status': 'ok', 'reports_examined': 3, 'records_imported': 2})
        summary = self.guard.summary()
        self.assertEqual(summary['requests'], 14)
        self.assertEqual(summary['usage'], usage())
        self.assertEqual(summary['by_kind']['sector']['requests'], 13)
        self.assertEqual(summary['by_kind']['sector']['usage'], usage(1800, 10))
        self.assertEqual(summary['by_kind']['events']['requests'], 1)
        self.assertEqual(summary['by_kind']['events']['usage'], usage(200, 10))
        self.assertEqual(bootstrap_usage(self.guard, self.state)['records_imported'], 0)
        ledger = self.guard.path.read_bytes()
        self.assertNotIn(b'private-report-text', ledger)
        self.assertNotIn(b'private-account-secret', ledger)
        self.assertNotIn(b'different-archive-id', ledger)

    def test_only_reports_table_is_read_with_sqlite_read_only_mode(self):
        self.archives([report()])
        connection = sqlite3.connect
        queries, uris = [], []
        def connect(location, **kwargs):
            uris.append(location)
            db = connection(location, **kwargs)
            db.set_trace_callback(queries.append)
            return db
        with patch('research_ai_usage_import.sqlite3.connect', side_effect=connect):
            self.assertEqual(bootstrap_usage(self.guard, self.state)['status'], 'ok')
        # The same sqlite3 module is also used by the guard, whose writes are
        # expected. Inspect the archive-specific connection URI and reads.
        self.assertTrue(any(str(uri).endswith('accounts.sqlite3?mode=ro') for uri in uris))
        selects = [query.lower() for query in queries if query.lstrip().lower().startswith('select')]
        self.assertFalse(any('from users' in query or 'from sessions' in query or 'from credentials' in query
                             for query in selects))

    def test_missing_usage_with_request_count_is_reserved_conservatively(self):
        value = report(requests=3)
        value['ai_research'].pop('usage')
        value['event_analysis'].pop('usage')
        self.save(value)
        self.assertEqual(bootstrap_usage(self.guard, self.state)['records_imported'], 2)
        summary = self.guard.summary()
        self.assertEqual(summary['requests'], 3)
        self.assertEqual(summary['usage']['total_tokens'], 0)
        self.assertEqual(summary['unknown_requests'], 2)
        self.assertEqual(summary['tokens_unsettled'], 13000)

    def test_known_incomplete_round_preserves_actual_and_one_unknown_sector_request(self):
        self.save(report(complete=False))
        self.assertEqual(bootstrap_usage(self.guard, self.state)['status'], 'ok')
        summary = self.guard.summary()
        self.assertEqual(summary['usage'], usage())
        self.assertEqual(summary['unknown_requests'], 1)
        self.assertEqual(summary['tokens_reserved'], 2020 + 6500)

    def test_previous_day_is_ignored_by_guard(self):
        self.save(report(at=NOW - timedelta(days=1)))
        self.assertEqual(bootstrap_usage(self.guard, self.state)['records_imported'], 0)
        self.assertEqual(self.guard.summary()['requests'], 0)

    def test_new_guard_recorded_round_is_not_imported_again(self):
        value = report()
        value['ai_research']['cost_ledger_recorded'] = True
        self.guard.invoke('sector', PAYLOAD, {}, lambda: {'usage': usage()})
        self.archives([value])
        self.save(value)
        self.assertEqual(bootstrap_usage(self.guard, self.state)['records_imported'], 0)
        self.assertEqual(self.guard.summary()['requests'], 1)

    def test_missing_or_empty_ledger_cannot_silently_skip_recorded_paid_reports(self):
        value = report()
        value['ai_research']['cost_ledger_recorded'] = True
        self.save(value)
        self.assert_blocked()
        # A valid schema with zero rows is also insufficient evidence of paid
        # work recorded today. This covers a hand-created or replaced ledger.
        self.guard = AICostGuard(self.folder / 'empty.sqlite3', clock=lambda: NOW)
        self.assertEqual(self.guard.summary()['requests'], 0)
        self.assert_blocked()

    def test_missing_ledger_ignores_previous_day_marker_and_zero_request_round(self):
        old = report(at=NOW - timedelta(days=1))
        old['ai_research']['cost_ledger_recorded'] = True
        current = report(requests=0)
        current['ai_research'].update(cost_ledger_recorded=True, usage=usage(0, 0))
        current['event_analysis']['retained'] = True
        self.archives([old])
        self.save(current)
        self.assertEqual(bootstrap_usage(self.guard, self.state)['status'], 'ok')
        self.assertEqual(self.guard.summary()['requests'], 0)

    def test_bootstrap_validates_all_sources_before_any_usage_import(self):
        self.archives([report()])
        self.state.write_bytes(b'private-invalid-json')
        self.assert_blocked()
        recovered = AICostGuard(self.guard.path, clock=lambda: NOW)
        self.assertEqual(recovered.summary()['requests'], 0)

    def test_retained_event_is_not_duplicated_or_subtracted_from_new_sector_work(self):
        original = report(requests=2)
        later = copy.deepcopy(original)
        later['as_of'] = (NOW + timedelta(minutes=1)).isoformat()
        later['ai_research'].update(request_count=1, usage=usage(100, 5))
        later['event_analysis']['retained'] = True
        self.archives([original, later])
        self.save(later)
        self.assertEqual(bootstrap_usage(self.guard, self.state)['records_imported'], 3)
        summary = self.guard.summary()
        self.assertEqual(summary['requests'], 3)
        self.assertEqual(summary['by_kind']['events']['requests'], 1)
        self.assertEqual(summary['usage'], usage(2100, 25))

    def test_bounded_archive_reads_only_the_latest_forty_records(self):
        values = []
        for index in range(42):
            value = report(at=NOW - timedelta(seconds=index))
            value['event_analysis']['request_count'] = 0
            value['event_analysis']['usage'] = usage(0, 0)
            value['ai_research']['request_count'] = 1
            values.append(value)
        self.archives(values)
        result = bootstrap_usage(self.guard, self.state)
        self.assertEqual(result['reports_examined'], 40)
        self.assertEqual(result['records_imported'], 40)
        self.assertEqual(self.guard.summary()['requests'], 40)

    def test_corrupt_existing_archive_is_observable_and_blocks_new_spend(self):
        self.archive.write_bytes(b'private-database-error')
        self.assert_blocked()

    def test_missing_or_wrong_reports_table_blocks_new_spend(self):
        db = sqlite3.connect(self.archive)
        db.execute('CREATE TABLE users(secret TEXT)')
        db.close()
        self.assert_blocked()

    def test_corrupt_gzip_blocks_new_spend(self):
        self.archives([report()])
        db = sqlite3.connect(self.archive)
        db.execute('UPDATE reports SET payload=?', (b'private-corrupt-gzip',))
        db.commit()
        db.close()
        self.assert_blocked()

    def test_decompression_bomb_and_oversized_state_are_bounded_and_blocked(self):
        self.archives([report()])
        with patch('research_ai_usage_import.MAX_REPORT_BYTES', 100):
            self.assert_blocked()
        self.archive.unlink()
        self.guard = AICostGuard(self.folder / 'second-ledger.sqlite3', clock=lambda: NOW)
        self.save(report())
        with patch('research_ai_usage_import.MAX_REPORT_BYTES', 100):
            self.assert_blocked()

    def test_oversized_compressed_blob_is_rejected_before_materialization(self):
        self.archives([report()])
        with patch('research_ai_usage_import.MAX_COMPRESSED_BYTES', 10):
            self.assert_blocked()

    def test_invalid_current_json_or_paid_metadata_blocks_instead_of_losing_usage(self):
        self.state.write_bytes(b'{private-invalid-json')
        self.assert_blocked()
        for index, mutate in enumerate((
                lambda value: value.update(as_of='private-invalid-date'),
                lambda value: value['ai_research'].update(usage=usage() | {'total_tokens': 999}),
                lambda value: value['ai_research'].update(request_count=0),
                lambda value: value['event_analysis'].update(request_count=100))):
            self.guard = AICostGuard(self.folder / ('invalid-' + str(index) + '.sqlite3'), clock=lambda: NOW)
            value = report()
            mutate(value)
            self.save(value)
            self.assert_blocked()

    def test_unknown_block_reason_never_leaks_arbitrary_diagnostics(self):
        self.guard.block('private-key-or-database-diagnostic')
        serial = json.dumps(self.guard.summary(), ensure_ascii=False)
        self.assertNotIn('private-key', serial)


if __name__ == '__main__':
    unittest.main()
