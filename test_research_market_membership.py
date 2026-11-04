"""Official membership identity, freshness and partial-evidence boundaries."""
import copy
import unittest
from unittest.mock import patch

import research_market_membership as membership

AS_OF = '2026-10-30'


def full_payload(key='hstech', codes=('700', '9988')):
    config = membership._config(key)
    return {'code': '0', 'data': {
        'numOfConsList': [{'indexCode': config['index_code'], 'indexName': config['index_name'], 'count': len(codes)}],
        'viewConsDetail': {config['index_code']: [
            {'indexCode': config['index_code'], 'indexName': config['index_name'], 'stockCode': code,
             'stockName': 'Official Security ' + code, 'exchangeListed': 'Hong Kong Stock Exchange',
             'stockType': 'HK', 'isDummy': 'N', 'dateTime': '2026-10-30 16:08:32'} for code in codes]}}}


def top_payload():
    return {'code': '0', 'data': [
        {'stockCode': str(100 + rank), 'stockName': 'Official Security ' + str(rank),
         'exchangeListed': 'Hong Kong Stock Exchange', 'weightOrder': rank,
         'tradeDate': '2026-10-29', 'indexPointContribution': '99.99'} for rank in range(1, 11)]}


def catalog_payload(key='hshdyi'):
    config = membership._config(key)
    return {'code': '0', 'data': [{'indexCode': config['index_code'], 'indexName': config['index_name'],
            'indexType': 'PI', 'indexSeriesCode': config['series_code'], 'regionName': 'Hong Kong-listed'}]}


class FullMembershipTests(unittest.TestCase):
    def test_full_membership_and_source_scope(self):
        snapshot = membership.parse_hsi_membership(full_payload(), 'hstech', AS_OF)
        self.assertTrue(snapshot['complete'])
        self.assertEqual(set(snapshot['members']), {'00700', '09988'})
        self.assertEqual(snapshot['source_date'], AS_OF)
        self.assertIn('不代表披露报告日', snapshot['mapping_scope'])

    def test_missing_full_list_never_becomes_empty_membership(self):
        payload = full_payload()
        payload['data']['viewConsDetail'] = None
        with self.assertRaisesRegex(ValueError, '未提供完整成分'):
            membership.parse_hsi_membership(payload, 'hstech', AS_OF)

    def test_mismatched_count_or_index_is_rejected(self):
        for mutation in ('count', 'indexCode', 'indexName'):
            payload = full_payload()
            declaration = payload['data']['numOfConsList'][0]
            declaration[mutation] = 30 if mutation == 'count' else 'wrong identity'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                membership.parse_hsi_membership(payload, 'hstech', AS_OF)

    def test_duplicate_dummy_or_other_exchange_is_rejected(self):
        for field, value in [('stockCode', '700'), ('isDummy', 'Y'), ('stockType', 'CN'),
                             ('exchangeListed', 'Shanghai Stock Exchange'), ('indexCode', '00001.00')]:
            payload = full_payload()
            rows = payload['data']['viewConsDetail']['02083.00']
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                membership.parse_hsi_membership(payload, 'hstech', AS_OF)

    def test_six_digit_official_code_is_not_silently_converted(self):
        with self.assertRaises(ValueError):
            membership.parse_hsi_membership(full_payload(codes=('000700',)), 'hstech', AS_OF)

    def test_future_stale_invalid_or_incoherent_dates_are_rejected(self):
        for value in ('2026-10-31 16:00:00', '2026-10-01 16:00:00',
                      '2026-10-30 99:00:00', None, '2026-10-29 16:00:00'):
            payload = full_payload()
            payload['data']['viewConsDetail']['02083.00'][1]['dateTime'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                membership.parse_hsi_membership(payload, 'hstech', AS_OF)


class PartialMembershipTests(unittest.TestCase):
    def test_top_ten_is_partial_and_rank_is_not_a_portfolio_weight(self):
        snapshot = membership.parse_hsi_top10(top_payload(), 'hshdyi', AS_OF, catalog_payload())
        self.assertFalse(snapshot['complete'])
        self.assertEqual(snapshot['source_date'], '2026-10-29')
        self.assertEqual(snapshot['members']['00101'], {'name': 'Official Security 1', 'source_date': '2026-10-29'})
        self.assertNotIn('weight', str(snapshot['members']))

    def test_official_catalog_identity_is_required(self):
        for field in ('indexCode', 'indexName', 'indexSeriesCode', 'regionName', 'indexType'):
            catalog = catalog_payload()
            catalog['data'][0][field] = 'incorrect'
            with self.subTest(field=field), self.assertRaises(ValueError):
                membership.parse_hsi_top10(top_payload(), 'hshdyi', AS_OF, catalog)
        with self.assertRaises(ValueError):
            membership.parse_hsi_top10(top_payload(), 'hshdyi', AS_OF)

    def test_top_ten_duplicates_ranks_missing_rows_dates_and_market_are_rejected(self):
        invalid = []
        payload = top_payload(); payload['data'].pop(); invalid.append(payload)
        payload = top_payload(); payload['data'][1]['stockCode'] = '101'; invalid.append(payload)
        payload = top_payload(); payload['data'][1]['weightOrder'] = 1; invalid.append(payload)
        payload = top_payload(); payload['data'][1]['tradeDate'] = '2026-10-30'; invalid.append(payload)
        payload = top_payload(); payload['data'][1]['exchangeListed'] = 'Shanghai'; invalid.append(payload)
        for number, payload in enumerate(invalid):
            with self.subTest(number=number), self.assertRaises(ValueError):
                membership.parse_hsi_top10(payload, 'hshdyi', AS_OF, catalog_payload())

    def test_tri_state_membership_and_mainland_identity_boundary(self):
        full = membership.parse_hsi_membership(full_payload(), 'hstech', AS_OF)
        partial = membership.parse_hsi_top10(top_payload(), 'hshdyi', AS_OF, catalog_payload())
        context = {'indices': {'hstech': full, 'hshdyi': partial}}
        evidence = membership.membership_for_security('00700', context)
        self.assertTrue(evidence['memberships']['overseas_hang_seng_technology']['matched'])
        self.assertIsNone(evidence['memberships']['overseas_hk_dividend']['matched'])
        self.assertEqual(evidence['region'], 'hk')
        self.assertFalse(membership.membership_for_security('00101', context)['memberships']['overseas_hang_seng_technology']['matched'])
        self.assertTrue(membership.membership_for_security('00101', context)['memberships']['overseas_hk_dividend']['matched'])
        for code in ('000700', '700', '600519', 'AAPL', ''):
            with self.subTest(code=code):
                result = membership.membership_for_security(code, context)
                self.assertTrue(all(item['matched'] is None for item in result['memberships'].values()))

    def test_explicit_hong_kong_identifiers_are_supported(self):
        snapshot = membership.parse_hsi_membership(full_payload(), 'hstech', AS_OF)
        for code in ('HK00700', '00700.HK'):
            evidence = membership.membership_for_security(code, {'indices': {'hstech': snapshot}})
            self.assertTrue(evidence['memberships']['overseas_hang_seng_technology']['matched'])

    def test_absence_or_failure_does_not_create_negative_evidence(self):
        for context in ({}, None, {'indices': {}, 'errors': {'hstech': 'network failure'}}):
            result = membership.membership_for_security('00700', context)
            self.assertTrue(all(item['matched'] is None for item in result['memberships'].values()))


class ContextCollectionTests(unittest.TestCase):
    def setUp(self):
        membership._cache.clear()

    def tearDown(self):
        membership._cache.clear()

    def test_context_limits_network_to_requested_boards_and_reuses_cache(self):
        with patch.object(membership, '_fetch_json', return_value=full_payload()) as fetch:
            first = membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng_technology'])
            second = membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng_technology'])
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(first['indices']['hstech']['fetched_at'], second['indices']['hstech']['fetched_at'])
            self.assertEqual(set(first['indices']), {'hstech'})
            membership.fetch_membership_context(AS_OF, refresh=True, board_ids=['overseas_hang_seng_technology'])
            self.assertEqual(fetch.call_count, 2)

    def test_cache_is_copied_and_historical_as_of_is_revalidated(self):
        with patch.object(membership, '_fetch_json', return_value=full_payload()) as fetch:
            first = membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng_technology'])
            first['indices']['hstech']['members'].clear()
            second = membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng_technology'])
            self.assertEqual(len(second['indices']['hstech']['members']), 2)
            historical = membership.fetch_membership_context('2026-10-29', board_ids=['overseas_hang_seng_technology'])
            self.assertEqual(historical['status'], 'unavailable')
            self.assertIn('hstech', historical['errors'])
            self.assertEqual(fetch.call_count, 1)

    def test_network_failure_is_isolated_from_other_indices(self):
        def fetch(url):
            if 'seriesCode=hstech' in url:
                return full_payload()
            raise OSError('source unavailable')
        with patch.object(membership, '_fetch_json', side_effect=fetch):
            context = membership.fetch_membership_context(AS_OF,
                board_ids=['overseas_hang_seng', 'overseas_hang_seng_technology'])
        self.assertEqual(context['status'], 'partial')
        self.assertIn('hstech', context['indices'])
        self.assertIn('hsi', context['errors'])

    def test_partial_context_needs_catalog_and_preserves_unknowns(self):
        def fetch(url):
            return catalog_payload() if url == membership.CATALOG_URL else top_payload()
        with patch.object(membership, '_fetch_json', side_effect=fetch):
            context = membership.fetch_membership_context(AS_OF, board_ids=['overseas_hk_dividend'])
        # hshylv is intentionally absent from this mocked catalog and must fail.
        self.assertEqual(set(context['indices']), {'hshdyi'})
        self.assertIn('hshylv', context['errors'])
        self.assertIsNone(membership.membership_for_security('00700', context)['memberships']['overseas_hk_dividend']['matched'])

    def test_no_network_for_unconfigured_board(self):
        with patch.object(membership, '_fetch_json') as fetch:
            context = membership.fetch_membership_context(AS_OF, board_ids=['sector_brain_computer'])
        fetch.assert_not_called()
        self.assertEqual(context['indices'], {})

    def test_negative_cache_bounds_repeated_failed_requests(self):
        with patch.object(membership, '_fetch_json', side_effect=OSError('unavailable')) as fetch:
            membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng'])
            membership.fetch_membership_context(AS_OF, board_ids=['overseas_hang_seng'])
            self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
