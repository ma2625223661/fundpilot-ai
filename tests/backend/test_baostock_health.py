import json
import subprocess
import time
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import research_baostock_health as health

NOW = '2026-10-31T09:00:00+08:00'


class BaoStockHealthTests(unittest.TestCase):
    def context(self):
        return {'as_of': NOW, 'end': '2026-10-30', 'start': '2026-10-20',
                'quarters': [(2026, 3), (2026, 2)]}

    def test_quarters_never_request_current_incomplete_quarter(self):
        self.assertEqual(health._quarters(date(2026, 10, 31)), [(2026, 3), (2026, 2)])
        self.assertEqual(health._quarters(date(2026, 1, 1)), [(2025, 4), (2025, 3)])

    def test_three_checks_run_independently_and_timeout_does_not_block_daily_or_finance(self):
        def check(cap, context, timeout):
            time.sleep(.03)
            return ({'status': 'timeout' if cap == 'industry' else 'available', 'count': 0 if cap == 'industry' else 1,
                     'checked_at': NOW, 'note': cap+' query timeout' if cap == 'industry' else ''}, [])
        with patch.object(health, '_check_one', side_effect=check) as called:
            result = health.probe_baostock_health(NOW)
        self.assertEqual(called.call_count, 3)
        self.assertEqual(result['verification'], 'partial')
        self.assertEqual(result['capabilities']['daily']['status'], 'available')
        self.assertIn('industry query timeout', result['error'])

    def test_valid_daily_sample_is_persistable_with_exact_cache_key(self):
        body = {'datasets': [{'query': 'daily query', 'cache_key': 'daily:sh.600519:2026-10-30',
            'error_code': '0', 'rows': [{'date': '2026-10-30', 'code': 'sh.600519', 'close': '1500'}]}]}
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(body))) as run:
            cap, cache = health._check_one('daily', self.context(), 23)
        self.assertEqual(run.call_args.kwargs['timeout'], 23)
        self.assertEqual(cap['status'], 'available')
        self.assertEqual(cap['data_date'], '2026-10-30')
        self.assertEqual(cache[0]['key'], 'daily:sh.600519:2026-10-30')
        self.assertTrue(cache[0]['sample_only'])

    def test_stale_daily_response_is_explained_instead_of_marked_available(self):
        body = {'datasets': [{'query': 'daily query', 'error_code': '0',
            'rows': [{'date': '2026-10-29', 'code': 'sh.600519', 'close': '1500'}]}]}
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(body))):
            cap, cache = health._check_one('daily', self.context(), 23)
        self.assertEqual(cap['status'], 'empty')
        self.assertIn('2026-10-29', cap['note'])
        self.assertIn('2026-10-30', cap['note'])
        self.assertEqual(cache, [])

    def test_successful_reconnection_is_explicit_in_capability_note(self):
        body = {'datasets': [{'query': 'industry query', 'error_code': '0', 'reconnected': True,
            'rows': [{'updateDate': '2026-10-26', 'code': 'sh.600519', 'industry': '饮料制造'}]}]}
        with patch.object(health.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(body))):
            cap, _ = health._check_one('industry', self.context(), 23)
        self.assertEqual(cap['status'], 'available')
        self.assertIn('重新连接后复查成功', cap['note'])

    def test_financial_disclosure_identity_and_numeric_values_are_checked(self):
        now, cutoff = health._date_context(NOW)
        valid = {'code': 'sh.600519', 'pubDate': '2026-10-30', 'statDate': '2026-09-30', 'roeAvg': '12'}
        self.assertEqual(health._valid_rows('financial', [valid], now, cutoff), [valid])
        for changes in ({'code': 'sz.000001'}, {'pubDate': '2026-10-31'}, {'statDate': '2026-12-31'}, {'roeAvg': 'nan'}):
            self.assertEqual(health._valid_rows('financial', [{**valid, **changes}], now, cutoff), [])

    def test_timeout_reports_the_exact_last_interface_phase(self):
        def run(*args, **kwargs):
            request = json.loads(kwargs['input'])
            health.Path(request['phase_path']).write_text(json.dumps({'query': 'query_stock_industry(code=sh.600519,date=2026-10-30)'}), encoding='utf-8')
            raise subprocess.TimeoutExpired('worker', 23)
        with patch.object(health.subprocess, 'run', side_effect=run):
            cap, cache = health._check_one('industry', self.context(), 23)
        self.assertEqual(cap['status'], 'timeout')
        self.assertIn('query_stock_industry', cap['note'])
        self.assertIn('2026-10-30', cap['note'])
        self.assertEqual(cache, [])

    def test_missing_calendar_remains_unverified_without_subprocess(self):
        with patch.object(health, 'is_trading_day', return_value=None), patch.object(health.subprocess, 'run') as run:
            result = health.probe_baostock_health(NOW)
        self.assertEqual(result['verification'], 'unverified')
        self.assertTrue(all(v['status'] == 'unverified' for v in result['capabilities'].values()))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
