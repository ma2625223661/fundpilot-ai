import copy
import unittest

from research_overview import build_market_overview


AS_OF = '2026-10-30T15:30:00+08:00'


def fund(code='000001', day='2026-10-30', value=1, **extra):
    return {'code': code, 'nav_date': day, 'return_1d': value, **extra}


def overview(rows=None, snapshot=None, complete=True):
    return build_market_overview({'as_of': AS_OF, 'funds': rows or [], 'coverage': {'complete': complete}},
                                 {'as_of': AS_OF, **(snapshot or {})})


class MarketOverviewTests(unittest.TestCase):
    def assert_totals(self, breadth):
        self.assertEqual(breadth['up'] + breadth['down'] + breadth['flat'], breadth['covered_count'])
        self.assertEqual(sum(item['count'] for item in breadth['buckets']), breadth['covered_count'])
        self.assertEqual(breadth['covered_count'] + breadth['excluded_count'], breadth['scope_count'])
        self.assertEqual(breadth['total'], breadth['covered_count'])

    def test_all_nine_buckets_and_exact_boundaries(self):
        values = [-6, -5, -4, -3, -2, -1, -.1, 0, .1, .99, 1, 2.99, 3, 4.99, 5, 7]
        result = overview([fund(f'{i:06d}', value=value) for i, value in enumerate(values)])['breadth']
        self.assertEqual([item['count'] for item in result['buckets']], [2, 2, 2, 1, 1, 2, 2, 2, 2])
        self.assertEqual((result['up'], result['down'], result['flat']), (8, 7, 1))
        self.assertEqual(result['status'], 'ok')
        self.assert_totals(result)

    def test_most_common_nav_date_wins_without_mixing_dates(self):
        rows = [fund('000001', '2026-10-29', 2), fund('000002', '2026-10-29', -2),
                fund('000003', '2026-10-30', 5)]
        result = overview(rows)['breadth']
        self.assertEqual(result['nav_date'], '2026-10-29')
        self.assertEqual((result['up'], result['down']), (1, 1))
        self.assertEqual(result['excluded_reasons'], {'other_nav_date': 1})
        self.assertEqual(result['date_range'], {'min': '2026-10-29', 'max': '2026-10-30'})
        self.assertEqual(result['status'], 'partial')
        self.assert_totals(result)

    def test_date_ties_take_latest_and_share_classes_are_separate(self):
        rows = [fund('000001', '2026-10-29'), fund('000002', '2026-10-30'), fund('000003', '2026-10-30'),
                fund('000004', '2026-10-29')]
        result = overview(rows)['breadth']
        self.assertEqual(result['nav_date'], '2026-10-30')
        self.assertEqual(result['covered_count'], 2)
        self.assertIn('A/C', result['scope'])
        self.assert_totals(result)

    def test_seven_calendar_days_and_missing_future_dates_are_excluded(self):
        rows = [fund('000001', '2026-10-24'), fund('000002', '2026-10-23'),
                fund('000003', '2026-10-31'), fund('000004', '2026-02-30'), fund('000005', None)]
        result = overview(rows)['breadth']
        self.assertEqual(result['nav_date'], '2026-10-24')
        self.assertEqual(result['covered_count'], 1)
        self.assertEqual(result['excluded_reasons'], {'stale_nav_date': 1, 'future_nav_date': 1, 'missing_nav_date': 2})
        self.assert_totals(result)

    def test_only_daily_returns_are_used_and_nonfinite_values_rejected(self):
        values = [None, True, float('nan'), float('inf'), -100, -101, 101, '--']
        rows = [fund(f'{i:06d}', value=value, return_1w=7, return_1m=30, nav=1.3) for i, value in enumerate(values)]
        result = overview(rows)['breadth']
        self.assertEqual(result['status'], 'insufficient')
        self.assertEqual(result['covered_count'], 0)
        self.assertEqual(result['excluded_count'], len(values))
        self.assertEqual(result['excluded_reasons'], {'missing_daily_return': len(values)})
        self.assert_totals(result)

    def test_index_gains_cannot_become_fund_breadth(self):
        result = overview(snapshot={'market': [{'code': 'sh000001', 'last': 4000, 'change_pct': 2, 'as_of': AS_OF}]})
        self.assertEqual(result['indices'][0]['status'], 'ok')
        self.assertEqual(result['breadth']['status'], 'insufficient')
        self.assertEqual(result['breadth']['up'], 0)

    def test_public_daily_ranking_has_priority_over_deep_sample(self):
        snapshot = {'funds': [{'code': '000002', 'nav_date': '2026-10-30',
                              'history': [{'date': '2026-10-30', 'return_pct': -5}]}]}
        result = overview([fund()], snapshot)['breadth']
        self.assertEqual(result['source_id'], 'universe:ranking')
        self.assertEqual((result['up'], result['down']), (1, 0))
        self.assertNotIn('有限', result['scope'])

    def test_old_report_falls_back_to_disclosed_latest_history_return(self):
        snapshot = {'funds': [{'code': '000002', 'nav_date': '2026-10-30',
                              'history': [{'date': '2026-10-29', 'nav': 1.1, 'return_pct': 4},
                                          {'date': '2026-10-30', 'nav': 1.0, 'return_pct': -1.2}]}]}
        result = overview(snapshot=snapshot)['breadth']
        self.assertEqual(result['source_id'], 'fund:nav_sample')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['nav_date'], '2026-10-30')
        self.assertEqual((result['up'], result['down']), (0, 1))
        self.assertIn('有限', result['scope'])
        self.assert_totals(result)

    def test_history_does_not_backfill_latest_missing_return_or_calculate_nav_delta(self):
        snapshot = {'funds': [{'code': '000002', 'nav_date': '2026-10-30',
                              'history': [{'date': '2026-10-29', 'nav': 1, 'return_pct': 4},
                                          {'date': '2026-10-30', 'nav': 1.5, 'return_pct': None}]}]}
        result = overview(snapshot=snapshot)['breadth']
        self.assertEqual(result['covered_count'], 0)
        self.assertEqual(result['excluded_count'], 1)
        self.assertEqual(result['status'], 'insufficient')

    def test_history_head_conflict_and_future_history_are_not_backfilled(self):
        snapshot = {'funds': [
            {'code': '000001', 'nav_date': '2026-10-30', 'history': [{'date': '2026-10-29', 'return_pct': 1}]},
            {'code': '000002', 'nav_date': '2026-10-31', 'history': [
                {'date': '2026-10-30', 'return_pct': 1}, {'date': '2026-10-31', 'return_pct': 2}]}]}
        result = overview(snapshot=snapshot)['breadth']
        self.assertEqual(result['covered_count'], 0)
        self.assertEqual(result['excluded_count'], 2)
        self.assert_totals(result)

    def test_duplicate_codes_do_not_inflate_counts_and_latest_cannot_be_backfilled(self):
        rows = [fund(), fund(), fund('000002', '2026-10-29', 1), fund('000002', '2026-10-30', None),
                fund('000003', value=1), fund('000003', value=-1), fund('bad'), fund(1)]
        result = overview(rows)['breadth']
        self.assertEqual(result['scope_count'], 3)
        self.assertEqual(result['covered_count'], 1)
        self.assertEqual(result['excluded_count'], 2)
        self.assert_totals(result)

    def test_no_snapshot_date_uses_universe_date_without_using_wall_clock(self):
        result = build_market_overview({'as_of': AS_OF, 'funds': [fund()]}, {})
        self.assertEqual(result['as_of'], AS_OF)
        self.assertEqual(result['breadth']['covered_count'], 1)
        result = build_market_overview({'funds': [fund()]}, {})
        self.assertIsNone(result['as_of'])
        self.assertEqual(result['breadth']['status'], 'insufficient')
        self.assertEqual(result['breadth']['excluded_reasons'], {'missing_reference_date': 1})

    def test_reference_timestamp_is_converted_to_china_date(self):
        result = overview([fund()], {'as_of': '2026-10-29T18:00:00+00:00'})
        self.assertEqual(result['breadth']['covered_count'], 1)
        self.assertEqual(result['as_of'], '2026-10-30T02:00:00+08:00')

    def test_index_mapping_order_freshness_and_numeric_validation(self):
        market = [
            {'code': 'sz399006', 'name': '创业板指', 'last': 2800, 'change_pct': -.5, 'as_of': AS_OF},
            {'code': 'sh000300', 'last': 4100, 'change_pct': 1, 'as_of': '2026-10-27T15:00:00+08:00'},
            {'code': 'sz399001', 'last': 12000, 'change_pct': 2, 'as_of': '2026-10-26T15:00:00+08:00'},
            {'code': 'sh000001', 'name': '上证指数', 'last': 3900, 'change_pct': 1.2, 'as_of': AS_OF,
             'source_id': 'test', 'source_url': 'https://example.test/quote'},
            {'code': 'other', 'last': 1, 'change_pct': 1, 'as_of': AS_OF}]
        result = overview(snapshot={'market': market})['indices']
        self.assertEqual([row['code'] for row in result], ['sh000001', 'sz399001', 'sh000300', 'sz399006'])
        self.assertEqual([row['status'] for row in result], ['ok', 'stale', 'ok', 'ok'])
        self.assertEqual(result[0]['value'], 3900)
        self.assertEqual(result[0]['change_pct'], 1.2)
        self.assertEqual(result[0]['source_id'], 'test')
        self.assertEqual(result[0]['source_url'], 'https://example.test/quote')

    def test_missing_future_and_invalid_index_fields_stay_unknown(self):
        for extra in ({'as_of': None}, {'as_of': '2026-10-30T16:00:00+08:00'},
                      {'last': True}, {'last': -1}, {'last': float('inf')}, {'change_pct': float('nan')}):
            with self.subTest(extra=extra):
                quote = {'code': 'sh000001', 'last': 4000, 'change_pct': 1, 'as_of': AS_OF, **extra}
                result = overview(snapshot={'market': [quote]})['indices'][0]
                self.assertEqual(result['status'], 'unknown')

    def test_indices_are_deduplicated_by_latest_source_time(self):
        quotes = [{'code': 'sh000001', 'last': 3999, 'change_pct': 1, 'as_of': '2026-10-30T15:00:00+08:00'},
                  {'code': 'sh000001', 'last': 4000, 'change_pct': 2, 'as_of': AS_OF}]
        result = overview(snapshot={'market': quotes})['indices']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['value'], 4000)

    def test_input_is_unchanged_and_result_is_reproducible(self):
        universe = {'as_of': AS_OF, 'funds': [fund()], 'coverage': {'complete': True}}
        snapshot = {'as_of': AS_OF, 'market': [{'code': 'sh000001', 'last': 4000, 'change_pct': 1, 'as_of': AS_OF}]}
        before = copy.deepcopy((universe, snapshot))
        first = build_market_overview(universe, snapshot)
        self.assertEqual((universe, snapshot), before)
        self.assertEqual(first, build_market_overview(universe, snapshot))

    def test_malformed_containers_are_safe_and_empty(self):
        for universe, snapshot in ((None, None), ({'funds': 'bad'}, {'market': None, 'funds': {}})):
            result = build_market_overview(universe, snapshot)
            self.assertEqual(result['indices'], [])
            self.assertEqual(result['breadth']['status'], 'insufficient')
            self.assert_totals(result['breadth'])


if __name__ == '__main__':
    unittest.main()
