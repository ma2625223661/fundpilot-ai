import unittest
from unittest.mock import patch
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import research_free_data as free
from research_free_data import (BaoStockAdapter, _financial, _quarters,
    gather_free_sector_company_evidence, provider_status)


class FakeAdapter:
    def __init__(self):
        self.logged = False
        self.logged_out = False

    def login(self):
        self.logged = True

    def logout(self):
        self.logged_out = True

    def stock_basic(self):
        return [{'code': 'sh.600000', 'code_name': '浦发银行'}]

    def stock_industry(self):
        return [{'code': 'sh.600000', 'code_name': '浦发银行', 'industry': '银行',
                 'industryClassification': '申万'}]

    def daily(self, code, start_date, end_date):
        self.daily_args = (code, start_date, end_date)
        return [{'date': '2026-10-30', 'code': code, 'close': '10.2', 'pctChg': '1.2',
                 'volume': '1000', 'amount': '200000'}]

    def profit(self, code, year, quarter):
        return [{'pubDate': '2026-10-29', 'statDate': '2026-09-30', 'roeAvg': '.082', 'epsTTM': '0.44'}]

    def growth(self, code, year, quarter):
        return [{'pubDate': '2026-10-29', 'statDate': '2026-09-30', 'YOYNI': '.051'}]

    def dupont(self, code, year, quarter):
        return []


class FreeDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patches = patch.multiple(free, _CACHE_PATH=Path(temporary.name) / 'cache.json',
                                 _datasets={}, _capabilities={}, _rotation=0, _session_lock=threading.Lock())
        patches.start()
        self.addCleanup(patches.stop)

    def test_missing_optional_package_is_explicit(self):
        with patch.dict(sys.modules, {'baostock': None}):
            result = gather_free_sector_company_evidence([], '2026-10-31T09:10:00+08:00', adapter=None)
        # The development environment does not install optional packages. A
        # real installation is tested through the injected fake below.
        self.assertIn(result['status'], {'not_installed', 'unavailable', 'partial'})

    def test_fake_provider_preserves_shared_evidence_schema(self):
        adapter = FakeAdapter()
        result = gather_free_sector_company_evidence(
            [{'id': 'sector_banking'}], '2026-10-31T09:10:00+08:00', adapter)
        self.assertEqual(result['status'], 'partial')
        row = result['sector_leaders']['sector_banking'][0]
        self.assertEqual(row['ts_code'], '600000.SH')
        self.assertEqual(row['quote']['close'], 10.2)
        self.assertAlmostEqual(row['financials']['roe'], 8.2)
        self.assertAlmostEqual(row['financials']['netprofit_yoy'], 5.1)
        self.assertEqual(adapter.daily_args[0], 'sh.600000')
        self.assertTrue(adapter.logged and adapter.logged_out)
        self.assertIn('baostock:stock_industry', row['source_ids'])
        self.assertTrue(set(row['source_ids']) <= {r['id'] for r in result['sources']})
        self.assertEqual(row['financials']['ann_date'], '2026-10-29')

    def test_status_does_not_contact_network(self):
        status = provider_status()
        self.assertEqual(status['provider'], 'baostock')
        self.assertIn(status['status'], {'available', 'not_installed'})

    def test_financials_use_actual_disclosure_and_reject_future_and_same_day(self):
        rows = [
            {'pubDate': '2026-10-29', 'statDate': '2026-09-30', 'roeAvg': '.1', 'gpMargin': '.25'},
            {'pubDate': '2026-10-31', 'statDate': '2026-09-30', 'roeAvg': '.9'},
            {'pubDate': '2026-11-01', 'statDate': '2026-09-30', 'YOYNI': '.9'},
            {'statDate': '2026-09-30', 'YOYNI': '.8'},
        ]
        result = _financial(rows, '600000.SH', '2026-10-31T09:10:00+08:00')
        self.assertEqual(result['ann_date'], '2026-10-29')
        self.assertEqual(result['roe'], 10)
        self.assertEqual(result['grossprofit_margin'], 25)
        self.assertNotIn('netprofit_yoy', result)

    def test_financials_do_not_mix_periods_and_fall_back_from_empty_latest(self):
        rows = [
            {'pubDate': '2026-10-29', 'statDate': '2026-09-30', 'roeAvg': ''},
            {'pubDate': '2026-08-29', 'statDate': '2026-06-30', 'roeAvg': '.08'},
            {'pubDate': '2026-04-29', 'statDate': '2026-03-31', 'YOYNI': '.2'},
        ]
        result = _financial(rows, '600000.SH', '2026-10-31T09:10:00+08:00')
        self.assertEqual(result['end_date'], '2026-06-30')
        self.assertEqual(result['roe'], 8)
        self.assertNotIn('netprofit_yoy', result)

    def test_quarters_start_with_latest_completed(self):
        self.assertEqual(_quarters(datetime(2026, 10, 31)), [(2026, 3), (2026, 2), (2026, 1), (2025, 4)])
        self.assertEqual(_quarters(datetime(2026, 1, 1))[0], (2025, 4))

    def test_cache_avoids_login_and_preserves_fetch_time(self):
        free._remember('industry:all', [{'code': 'sh.600000'}], 100, 'industry')
        original = free._cached('industry:all')['fetched_at']
        module = SimpleNamespace(query_stock_industry=lambda: self.fail('cache must avoid network'))
        adapter = BaoStockAdapter(module)
        self.assertEqual(adapter.stock_industry()[0]['code'], 'sh.600000')
        self.assertFalse(adapter._session_owned)
        self.assertEqual(free._cached('industry:all')['fetched_at'], original)
        self.assertEqual(free.capability_snapshot()['industry']['status'], 'available')
        self.assertNotIn('daily', free.capability_snapshot())

    def test_empty_financial_response_does_not_hide_other_valid_cache(self):
        free._remember('financial:valid', [{'roeAvg': '.1'}], 100, 'financial')
        free._remember('financial:empty', [], 100, 'financial')
        self.assertEqual(free.capability_snapshot()['financial']['status'], 'available')
        self.assertEqual(free.capability_snapshot()['financial']['count'], 1)

    def test_new_failed_probe_does_not_turn_old_cached_sample_into_current_success(self):
        free._remember('daily:sample', [{'close': 10}], 100, 'daily')
        old_time = free._cached('daily:sample')['fetched_at']
        free._capabilities['daily'] = {'status': 'timeout', 'checked_at': old_time,
            'count': 0, 'note': '本次接口超时'}
        current = free.capability_snapshot()['daily']
        self.assertEqual(current['status'], 'timeout')
        self.assertTrue(current['cache_available'])
        self.assertEqual(current['note'], '本次接口超时')

    def test_provider_error_is_not_an_empty_success(self):
        with self.assertRaises(RuntimeError):
            free._rows(SimpleNamespace(error_code='10001001'))

    def test_early_industry_failure_releases_adapter(self):
        adapter = FakeAdapter()
        adapter.stock_industry = lambda: (_ for _ in ()).throw(RuntimeError('failed'))
        result = gather_free_sector_company_evidence([], '2026-10-31T09:10:00+08:00', adapter)
        self.assertTrue(adapter.logged_out)
        self.assertFalse(result['sector_leaders'])
        self.assertEqual(result['status'], 'unavailable')

    def test_logout_is_idempotent(self):
        module = SimpleNamespace(login=lambda: SimpleNamespace(error_code='0'))
        adapter = BaoStockAdapter(module)
        with patch.object(adapter, '_abort_socket'):
            adapter.login()
            adapter.logout()
            adapter.logout()
        self.assertFalse(free._session_lock.locked())

    def test_timed_out_session_stops_subsequent_requests(self):
        release = threading.Event()
        adapter = BaoStockAdapter(SimpleNamespace())
        try:
            with patch.object(adapter, '_abort_socket'):
                with self.assertRaises(TimeoutError):
                    adapter._call(lambda: release.wait(1), timeout=.001)
                with self.assertRaises(TimeoutError):
                    adapter._call(lambda: self.fail('broken session must not query'))
        finally:
            release.set()
            adapter._running.join(1)

    def test_cached_samples_survive_failed_next_round_and_have_sources(self):
        first = gather_free_sector_company_evidence(
            [{'id': 'sector_banking'}], '2026-10-31T09:10:00+08:00', FakeAdapter())
        adapter = FakeAdapter()
        adapter.daily = lambda *args: (_ for _ in ()).throw(TimeoutError('timeout'))
        second = gather_free_sector_company_evidence(
            [{'id': 'sector_banking'}], '2026-10-31T10:10:00+08:00', adapter)
        self.assertEqual(second['sector_leaders'], first['sector_leaders'])
        self.assertTrue(set(second['sector_leaders']['sector_banking'][0]['source_ids']) <=
                        {r['id'] for r in second['sources']})

    def test_old_quote_is_labeled_stale(self):
        adapter = FakeAdapter()
        adapter.daily = lambda *args: [{'date': '2026-10-01', 'close': '10'}]
        result = gather_free_sector_company_evidence(
            [{'id': 'sector_banking'}], '2026-10-31T09:10:00+08:00', adapter)
        row = result['sector_leaders']['sector_banking'][0]
        self.assertTrue(row['quote']['stale'])
        self.assertEqual(next(r['status'] for r in result['sources'] if r['id'].startswith('baostock:daily')), 'stale')


if __name__ == '__main__':
    unittest.main()
