import copy
import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import research_public_data as public
import research_theme_memberships as theme
from research_evidence_resilience import (complete_history, retain_company_components,
    retain_closed_baskets, remember_company_evidence)
from research_leader_index import build_indicator, collect_leader_histories
from test_research_leader_index import member, BOARD
from test_research_public_data import quote_text

NOW = '2026-11-02T10:00:00+08:00'


class EvidenceResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in [('_cache', {}), ('CACHE_PATH', Path(self.temp.name) / 'cache.json')]:
            mocked = patch.object(public, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def previous(self):
        rows = [member(), member('000001.SZ')]
        sources = []
        for row in rows:
            code = row['ts_code']
            row['source_ids'] = ['public:members:' + BOARD['id'], 'public:financial:' + code, 'leader_history:' + code]
            row['price_adjustment'] = 'forward_adjusted'
            for identity in row['source_ids']:
                sources.append({'id': identity, 'url': 'https://example.org/' + code,
                                'status': 'ok', 'as_of': '2026-10-30', 'fetched_at': '2026-10-31T04:00:00+08:00'})
        return {'sector_leaders': {BOARD['id']: rows}, 'sources': sources}

    def failed(self):
        return {'sector_leaders': {}, 'sources': [{'id': 'public:members:' + BOARD['id'],
                'status': 'error', 'error': '本轮采集预算用完，下轮继续'}]}

    def test_repeated_failed_full_updates_recover_native_dates_and_recompute(self):
        previous = self.previous()
        for _ in range(3):
            current = self.failed()
            retain_company_components(current, previous, NOW, [BOARD])
            retain_closed_baskets(current, NOW)
            rows = current['sector_leaders'][BOARD['id']]
            self.assertTrue(build_indicator(BOARD, rows, NOW)['meta']['ready'])
            self.assertEqual(rows[0]['membership_evidence']['snapshot_date'], '2026-10-30')
            self.assertEqual(rows[0]['as_of'], '2026-10-30T15:00:00+08:00')
            self.assertNotIn('recommendation_index', current)
            previous = current

    def test_persistent_last_good_survives_incomplete_report_and_process_reload(self):
        remember_company_evidence(self.previous(), NOW)
        public._cache = json.loads(public.CACHE_PATH.read_text(encoding='utf-8'))['datasets']
        current = self.failed()
        retain_company_components(current, {}, NOW, [BOARD])
        self.assertEqual(len(current['sector_leaders'][BOARD['id']]), 2)
        self.assertEqual(current['sector_leaders'][BOARD['id']][0]['financials']['ann_date'], '2026-10-30')

    def test_successful_membership_change_never_resurrects_removed_company(self):
        current = {'sector_leaders': {BOARD['id']: [member()]},
                   'sources': [{'id': 'public:members:' + BOARD['id'], 'status': 'ok'}]}
        retain_company_components(current, self.previous(), NOW)
        self.assertEqual(len(current['sector_leaders'][BOARD['id']]), 1)
        remember_company_evidence(self.previous(), NOW)
        current['sources'][0]['count'] = 1
        current['selection_universes'] = {BOARD['id']: {'verified_member_codes': ['600000.SH']}}
        retain_company_components(current, self.previous(), NOW)
        failed = self.failed()
        retain_company_components(failed, {}, NOW, [BOARD])
        self.assertEqual([r['ts_code'] for r in failed['sector_leaders'][BOARD['id']]], ['600000.SH'])

    def test_future_expired_and_wrong_security_financials_are_rejected(self):
        for change in ('expired', 'future', 'wrong_security'):
            prior = self.previous()
            row = prior['sector_leaders'][BOARD['id']][0]
            if change == 'expired': row['membership_evidence']['snapshot_date'] = '2026-08-01'
            if change == 'future': row['membership_evidence']['snapshot_date'] = '2026-11-03'
            if change == 'wrong_security': row['financials']['ts_code'] = '601999.SH'
            current = self.failed() if change != 'wrong_security' else copy.deepcopy(prior)
            if change == 'wrong_security': current['sector_leaders'][BOARD['id']][0]['financials'] = None
            retain_company_components(current, prior, NOW)
            rows = current['sector_leaders'][BOARD['id']]
            if change == 'wrong_security': self.assertIsNone(rows[0]['financials'])
            else: self.assertNotIn('600000.SH', [r['ts_code'] for r in rows])

    def test_partial_intraday_basket_falls_back_as_a_whole_with_exact_close_date(self):
        current = self.previous()
        rows = current['sector_leaders'][BOARD['id']]
        rows[0].update(as_of='2026-11-02T09:59:00+08:00', quote={'close': 12, 'pct_chg': 20, 'is_intraday': True})
        rows[1].update(quote={}, as_of=None)
        retain_closed_baskets(current, NOW)
        self.assertTrue(all(r['quote']['retained_close'] and not r['quote']['is_intraday'] for r in rows))
        self.assertEqual({r['as_of'] for r in rows}, {'2026-10-30T15:00:00+08:00'})
        self.assertTrue(build_indicator(BOARD, rows, NOW)['meta']['ready'])
        stale = self.previous()
        stale['sector_leaders'][BOARD['id']][1].update(quote={}, as_of=None)
        retain_closed_baskets(stale, '2026-11-02T16:00:00+08:00')
        self.assertEqual(stale['sector_leaders'][BOARD['id']][1]['quote'], {})

    def test_complete_history_is_reused_without_network_and_original_source_date(self):
        current = self.previous()
        with patch('research_leader_index.fetch_text') as fetch, patch('research_leader_history_fallback.fetch_a_share_histories') as backup:
            collect_leader_histories(current, NOW)
        fetch.assert_not_called()
        backup.assert_not_called()
        self.assertTrue(complete_history(current['sector_leaders'][BOARD['id']][0]['history'], NOW))
        source = [s for s in current['sources'] if s['id'] == 'leader_history:600000.SH'][-1]
        self.assertEqual(source['fetched_at'], '2026-10-31T04:00:00+08:00')

    def test_business_timeout_reuses_original_verified_date_without_extending_validity(self):
        spec = theme.BUSINESS_EVIDENCE['sector_insurance'][0]
        ref = theme.BUSINESS_REFERENCES['sector_insurance']
        old = '2026-10-30T12:00:00+08:00'
        key = 'business_evidence:' + spec['ts_code'] + ':' + ref['code'] + ':last_good'
        public._remember(key, {'content': ' '.join(spec['required']), 'observed_at': old}, 45*86400)
        with patch.object(theme, '_download', side_effect=TimeoutError()):
            row = theme.fetch_business_member(spec, ref, NOW)
        self.assertTrue(row['cache_used'])
        self.assertEqual(row['observed_at'], old)
        self.assertIsNone(theme.retained_business_member(spec, ref, '2026-12-20T10:00:00+08:00'))

    def test_business_changed_facts_do_not_fall_back_to_old_page(self):
        spec = theme.BUSINESS_EVIDENCE['sector_insurance'][0]
        ref = theme.BUSINESS_REFERENCES['sector_insurance']
        public._remember('business_evidence:' + spec['ts_code'] + ':' + ref['code'] + ':last_good',
                         {'content': ' '.join(spec['required']), 'observed_at': '2026-10-30T12:00:00+08:00'}, 45*86400)
        with patch.object(theme, '_download', return_value=b'changed product page'), self.assertRaises(ValueError):
            theme.fetch_business_member(spec, ref, NOW)

    def test_empty_financial_response_is_not_cached_for_a_day(self):
        with patch.object(public, 'fetch_text', return_value='{"success": true, "result": {"data": []}}'):
            self.assertIsNone(public.fetch_financial('600000.SH', NOW))
        self.assertIsNone(public._get('financial:600000.SH'))

    def test_morning_quote_remains_valid_through_lunch_without_wall_clock_expiry(self):
        text = quote_text('20261102113000')
        for clock in ('12:00:00', '12:59:59'):
            rows = public.parse_quotes(text, {'600000.SH'}, '2026-11-02T' + clock + '+08:00')
            self.assertEqual(rows['600000.SH']['as_of'], '2026-11-02T11:30:00+08:00')
        self.assertEqual(public.parse_quotes(quote_text('20261102100000'), {'600000.SH'}, '2026-11-02T12:00:00+08:00'), {})

    def test_tick_received_during_collection_is_not_mistaken_for_future(self):
        rows = public.parse_quotes(quote_text('20261102100100'), {'600000.SH'}, NOW,
                                   received_at='2026-11-02T10:01:02+08:00')
        self.assertIn('600000.SH', rows)
        self.assertEqual(public.parse_quotes(quote_text('20261102100200'), {'600000.SH'}, NOW,
                                            received_at='2026-11-02T10:01:02+08:00'), {})

    def test_cni_timeout_preserves_complete_snapshot_but_not_expired_or_changed_identity(self):
        ref = theme.CNI_REFERENCES['sector_memory_chip']
        rows = [{'ts_code': '603986.SH', 'name': '兆易创新', 'member_date': '2026-10-30',
                 'index_code': ref['code'], 'index_name': ref['title']}]
        public._remember('cni_members:' + ref['code'] + ':last_good', rows, 45*86400)
        with patch.object(theme, '_download', side_effect=TimeoutError()):
            cached = theme.fetch_cni_members(ref, NOW)
            self.assertEqual(cached[0]['member_date'], '2026-10-30')
            self.assertTrue(cached[0]['cache_used'])
            with self.assertRaises(TimeoutError):
                theme.fetch_cni_members(ref, '2026-12-20T10:00:00+08:00')

    def test_real_pipeline_survives_full_scan_failures_then_quote_tick_and_restart(self):
        import research_sectors as sectors
        previous = {'as_of': NOW, 'company_evidence': self.previous()}
        failed = {**self.failed(), 'warnings': [], 'provider': 'public_multisource'}
        mocks = {'now_iso': NOW, 'sector_catalog': [BOARD],
                 'collect_sector_market': {'market': [], 'news': [], 'sources': [], 'warnings': []},
                 'collect_sector_quotes': ([], []), 'collect_verified_references': ([], [], {}),
                 'collect_macro_risk': ({'status': 'unavailable'}, {'id': 'macro', 'status': 'error'}),
                 'fetch_text': '', 'collect_sector_histories': ({}, [])}
        with ExitStack() as stack:
            for name, value in mocks.items():
                stack.enter_context(patch.object(sectors, name, return_value=copy.deepcopy(value)))
            stack.enter_context(patch.object(public, 'gather_public_company_evidence', side_effect=lambda *_: copy.deepcopy(failed)))
            stack.enter_context(patch('research_free_data.gather_free_sector_company_evidence', side_effect=lambda *_: copy.deepcopy(failed)))
            stack.enter_context(patch.object(public, 'fetch_quotes', return_value={}))
            for mode in ('full', 'full', 'tick', 'restart'):
                report = sectors.run_sector_research(previous={'_public_report': {} if mode == 'restart' else previous,
                    '_public_only': mode == 'tick'}, data_config={'provider': 'baostock', 'secondary_provider': 'public_multisource'})
                result = report['sector_analysis'][0]
                self.assertIsNotNone(result['recommendation_index'], mode)
                self.assertNotEqual(result['score_status'], 'complete')
                self.assertTrue(result['custom_index']['ready'])
                self.assertEqual(result['as_of'], '2026-10-30T15:00:00+08:00')
                self.assertEqual(len(report['company_evidence']['sector_leaders'][BOARD['id']]), 2)
                self.assertEqual(report['automatic']['paid_api_calls'], False)
                previous = report

    def test_overseas_financial_failure_uses_same_security_report_and_market_calendar(self):
        from research_overseas import recent_sessions
        rows = []
        for code in ('09926.HK', '06160.HK'):
            row = member(code)
            days = recent_sessions('HK', NOW)
            row.update(as_of=days[-1], history=[{'date': d, 'close': 100+i} for i, d in enumerate(days)])
            row['quote'].update(market='HK', trade_date=days[-1])
            row['source_ids'] = ['overseas:finance:' + code]
            rows.append(row)
        identity = 'overseas_hk_innovative_drug'
        prior = {'sector_leaders': {identity: rows}, 'sources': []}
        remember_company_evidence(prior, NOW)
        current = copy.deepcopy(prior)
        current['sector_leaders'][identity][1]['financials'] = {}
        retain_company_components(current, prior, NOW)
        self.assertEqual(current['sector_leaders'][identity][1]['financials'], rows[1]['financials'])
        failed = {'sector_leaders': {}, 'sources': [{'id': 'overseas:sample:' + code, 'status': 'error', 'error': 'URLError'} for code in ('09926.HK', '06160.HK')]}
        retain_company_components(failed, {}, NOW, [{'id': identity}])
        self.assertEqual(len(failed['sector_leaders'][identity]), 2)
        expired = {'sector_leaders': {}, 'sources': failed['sources']}
        retain_company_components(expired, {}, '2026-11-02T17:00:00+08:00', [{'id': identity}])
        self.assertFalse(any(r.get('quote') for r in expired['sector_leaders'][identity]))


if __name__ == '__main__':
    unittest.main()
