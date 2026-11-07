import threading
import time
import unittest
from unittest.mock import patch

from research_free_config import FreeDataConfigStore


class FreeConfigTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ('provider_status', {'provider': 'baostock', 'status': 'available'}),
            ('capability_snapshot', {}),
        ):
            mock = patch('research_free_config.' + name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_verify_is_async_and_repeated_click_does_not_start_another_worker(self):
        release = threading.Event()
        calls = []
        completed = threading.Event()

        def probe():
            calls.append(True)
            release.wait(2)
            return {'verification': 'partial', 'capabilities': {
                'industry': {'status': 'available', 'count': 2, 'checked_at': '2026-10-31'}}}

        store = FreeDataConfigStore(probe=probe, on_complete=completed.set)
        started = time.monotonic()
        try:
            initial = store.verify()
            self.assertLess(time.monotonic() - started, .3)
            self.assertEqual(initial['verification'], 'checking')
            self.assertEqual(store.verify()['verification'], 'checking')
        finally:
            release.set()
        self.assertTrue(completed.wait(2))
        self.assertEqual(len(calls), 1)
        result = store.status()
        self.assertTrue(result['installed'])
        self.assertTrue(result['configured'])
        self.assertEqual(result['verification'], 'partial')
        statuses = {r['id']: r['status'] for r in result['capabilities']}
        self.assertEqual(statuses, {'industry': 'available', 'daily': 'unverified', 'financial': 'unverified'})

    def test_installed_timeout_does_not_claim_package_missing(self):
        store = FreeDataConfigStore(probe=lambda: {'verification': 'timeout', 'error': '超时'})
        store.verify()
        store._worker.join(1)
        result = store.status()
        self.assertTrue(result['installed'])
        self.assertFalse(result['configured'])
        self.assertEqual(result['verification'], 'timeout')
        self.assertEqual(result['capabilities'][0]['status'], 'timeout')
        self.assertEqual(result['capabilities'][1]['status'], 'unverified')

    def test_package_missing_does_not_call_probe(self):
        store = FreeDataConfigStore(probe=lambda: self.fail('must not probe absent package'))
        with patch('research_free_config.provider_status', return_value={'status': 'not_installed'}):
            result = store.verify()
        self.assertFalse(result['installed'])
        self.assertEqual(result['verification'], 'not_installed')

    def test_unverified_calendar_remains_unverified_instead_of_connection_failure(self):
        store = FreeDataConfigStore(probe=lambda: {'verification': 'unverified',
            'error': '交易日历未经核验', 'capabilities': {'daily': {'status': 'unverified'}}})
        store.verify()
        store._worker.join(1)
        self.assertEqual(store.status()['verification'], 'unverified')

    def test_clearing_ignores_completion_of_previous_check(self):
        release = threading.Event()
        def probe():
            release.wait(1)
            return {'verification': 'partial'}
        store = FreeDataConfigStore(probe=probe)
        store.verify()
        store.clear()
        release.set()
        store._worker.join(1)
        self.assertEqual(store.status()['verification'], 'unverified')


if __name__ == '__main__':
    unittest.main()
