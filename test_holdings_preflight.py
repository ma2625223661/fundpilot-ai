"""Missing portfolios receive a discovery budget independent of known boards."""
import copy
import unittest

from research_universe import pick_holdings_preflight_codes
from test_holdings_fixtures import portfolio

STAMP = '2026-10-30T17:00:00+08:00'


def candidate(code, **extra):
    return {'code': code, 'name': '独立样本' + code, 'fund_type': '股票型',
            'eligible': True, 'universe_bucket': 'medium_high', 'screen_group': '股票', **extra}


class PreflightTests(unittest.TestCase):
    def test_unseen_portfolios_cannot_be_starved_by_many_proven_boards(self):
        known = [candidate(f'{i:06d}', holdings=portfolio(['银行']), holdings_checked_at=STAMP) for i in range(1, 120)]
        unknown = [candidate(f'{i:06d}') for i in range(120, 220)]
        universe = {'as_of': STAMP, 'funds': known + unknown}
        before = copy.deepcopy(universe)
        chosen = pick_holdings_preflight_codes(universe)
        self.assertEqual(len(chosen), 96)
        self.assertTrue(set(chosen).issubset({fund['code'] for fund in unknown}))
        self.assertEqual(universe, before)

    def test_persisted_check_times_rotate_past_success_and_failure(self):
        funds = [candidate(f'{i:06d}') for i in range(1, 10)]
        universe = {'as_of': STAMP, 'funds': funds}
        first = pick_holdings_preflight_codes(universe, 3)
        for fund in funds:
            if fund['code'] in first:
                fund.update(holdings_checked_at=STAMP, holdings={'status': 'error'})
        second = pick_holdings_preflight_codes(universe, 3)
        self.assertFalse(set(first) & set(second))

    def test_discovery_preference_does_not_bypass_recent_checks_or_source_eligibility(self):
        funds = [candidate('000001'), candidate('000002'),
                 candidate('000003', holdings_checked_at=STAMP, holdings={'status': 'error'}),
                 candidate('000004', eligible=False)]
        selected = pick_holdings_preflight_codes({'as_of': STAMP, 'funds': funds}, 3,
                                                preferred_codes=['000003', '000004', '000002'])
        self.assertEqual(selected, ['000002', '000001'])

    def test_due_stale_and_partial_data_can_retry_but_recent_cache_is_not_replayed(self):
        old = '2026-10-29T17:00:00+08:00'
        funds = [candidate('000001', holdings_checked_at=old, holdings={'status': 'error'}),
                 candidate('000002', holdings_checked_at=old, holdings=portfolio(['银行'], report_date='2025-01-01')),
                 candidate('000003', holdings_checked_at=STAMP, holdings=portfolio(['银行']))]
        selected = pick_holdings_preflight_codes({'as_of': STAMP, 'funds': funds}, 96)
        self.assertEqual(set(selected), {'000001', '000002'})

    def test_undated_partial_legacy_portfolios_are_rechecked(self):
        unknown = portfolio(['银行'])
        unknown['rows'][0].update(tag_status='unknown', tags=[])
        funds = [candidate('000001', holdings=unknown), candidate('000002', holdings=portfolio(['银行']))]
        self.assertEqual(pick_holdings_preflight_codes({'as_of': STAMP, 'funds': funds}), ['000001'])

    def test_names_do_not_determine_the_preflight_directions_or_order(self):
        funds = [candidate(f'{i:06d}') for i in range(1, 10)]
        universe = {'as_of': STAMP, 'funds': funds}
        first = pick_holdings_preflight_codes(universe, 5)
        for fund in funds:
            fund['name'] = '任意展示' + fund['code']
        self.assertEqual(pick_holdings_preflight_codes(universe, 5), first)

    def test_known_nonstock_source_types_and_oversized_limits_remain_bounded(self):
        funds = [candidate(f'{i:06d}') for i in range(1, 120)]
        funds += [candidate('900001', fund_type='货币型'), candidate('900002', fund_type='债券型-短债')]
        selected = pick_holdings_preflight_codes({'as_of': STAMP, 'funds': funds}, 5000)
        self.assertEqual(len(selected), 96)
        self.assertNotIn('900001', selected)
        self.assertNotIn('900002', selected)
        self.assertFalse(pick_holdings_preflight_codes({'as_of': STAMP, 'funds': funds}, 0))


if __name__ == '__main__':
    unittest.main()
