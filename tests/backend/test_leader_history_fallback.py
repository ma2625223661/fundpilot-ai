import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import research_leader_history_fallback as fallback

NOW = '2026-10-31T09:00:00+08:00'


class LeaderHistoryFallbackTests(unittest.TestCase):
    def test_parser_requires_identity_finite_positive_completed_trading_date(self):
        rows = [
            {'date': '2026-10-30', 'code': 'sh.600031', 'close': '17.76'},
            {'date': '2026-10-29', 'code': 'sh.600048', 'close': '99'},
            {'date': '2026-10-31', 'code': 'sh.600031', 'close': '99'},
            {'date': '2026-10-28', 'code': 'sh.600031', 'close': 'nan'},
            {'date': '2026-10-27', 'code': 'sh.600031', 'close': '0'},
            {'date': '2025-10-30', 'code': 'sh.600031', 'close': '99'},
        ]
        self.assertEqual(fallback.parse_a_share_history(rows, '600031.SH', NOW),
                         [{'date': '2026-10-30', 'close': 17.76}])
        # Friday's intraday study cannot use Friday's unfinished daily close.
        self.assertEqual(fallback.parse_a_share_history(rows, '600031.SH', '2026-10-30T14:30:00+08:00'), [])

    def test_batch_is_one_bounded_child_process_and_keeps_source_and_adjustment(self):
        body = {'600031.SH': {'rows': [{'date': '2026-10-30', 'code': 'sh.600031', 'close': '17.76'}]},
                '600048.SH': {'rows': [], 'error': '无行情'}}
        with patch.object(fallback.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(body))) as run:
            result = fallback.fetch_a_share_histories(['600031.SH', '600048.SH', '600031.SH'], NOW, 99)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs['timeout'], 35)
        request = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(request['codes'], ['600031.SH', '600048.SH'])
        self.assertEqual(request['end'], '2026-10-30')
        self.assertEqual(result['600031.SH']['rows'][0]['close'], 17.76)
        self.assertEqual(result['600031.SH']['adjustment'], 'forward_adjusted')
        self.assertEqual(result['600031.SH']['url'], fallback.SOURCE_URL)
        self.assertEqual(result['600048.SH']['error'], '无行情')

    def test_timeout_does_not_treat_partial_process_output_as_valid_history(self):
        with patch.object(fallback.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 35, output='partial')):
            result = fallback.fetch_a_share_history('600031.SH', NOW)
        self.assertEqual(result['rows'], [])
        self.assertIn('超时', result['error'])

    def test_invalid_codes_and_oversized_batch_never_start_worker(self):
        with patch.object(fallback.subprocess, 'run') as run:
            for codes in (['00700.HK'], ['600031.SH;whoami'], [str(i).zfill(6)+'.SH' for i in range(61)]):
                with self.assertRaises(ValueError):
                    fallback.fetch_a_share_histories(codes, NOW)
            self.assertEqual(fallback.fetch_a_share_histories([], NOW), {})
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
