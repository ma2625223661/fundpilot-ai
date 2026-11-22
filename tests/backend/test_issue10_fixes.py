"""Issue #10: productivity signal, ':retained' id growth, collection fallbacks
and retry order. Fixtures only; no network or real data directory."""
import copy
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import research_long_wave_data as lw
import research_overseas as overseas
import research_public_data as public
import research_sectors as sectors
from research_cycle import macro_signals, phase_for
from research_data import CHINA
from research_evidence_resilience import collapse_retained, retain_company_components, retained_base
from test_long_wave_evidence import AS_OF, ANNUAL, ANNUAL_URL, FAI, FAI_URL, INDUSTRY, INDUSTRY_URL
import test_research_evidence_resilience as resilience
from test_research_leader_index import BOARD

NOW = '2026-11-02T10:00:00+08:00'


class ProductivitySignalTests(unittest.TestCase):
    def report(self, kinds):
        parsed = {'fai': lw.parse_fai(FAI, FAI_URL, AS_OF), 'industry': lw.parse_industry(INDUSTRY, INDUSTRY_URL, AS_OF),
                  'annual': lw.parse_annual(ANNUAL, ANNUAL_URL, AS_OF)}
        evidence = {k: parsed[k] for k in kinds}
        sources = [{'id': lw.SOURCE_IDS[k], 'status': 'ok', 'as_of': v['published_at'], 'url': v['url']}
                   for k, v in evidence.items()]
        return {'strategy': {'long_wave_evidence': evidence}, 'snapshot': {'sources': sources}}

    def signal(self, kinds):
        now = datetime(2026, 11, 21, 10, tzinfo=CHINA)
        return next(s for s in macro_signals(self.report(kinds), now) if s['id'] == 'productivity')

    def test_monthly_and_annual_official_data_make_the_fifth_group(self):
        signal = self.signal(('fai', 'industry', 'annual'))
        self.assertEqual(signal['status'], 'ready')
        self.assertEqual(signal['value'], -8.1)
        self.assertIn('制造业投资累计同比 -2.9%', signal['detail'])
        self.assertIn('2025 年全员劳动生产率 184,413 元/人', signal['detail'])
        self.assertIn('每年约 2 月底更新一次', signal['detail'])
        self.assertEqual([r['url'] for r in signal['related']], [INDUSTRY_URL, ANNUAL_URL])
        self.assertIn('不是全要素生产率', signal['scope'])

    def test_annual_bulletin_is_optional_but_monthly_data_is_required(self):
        signal = self.signal(('fai', 'industry'))
        self.assertEqual(signal['status'], 'ready')
        self.assertIn('待统计公报核验', signal['detail'])
        missing = self.signal(('fai', 'annual'))
        self.assertEqual(missing['status'], 'missing')
        self.assertIn('规模以上工业增加值', missing['detail'])
        self.assertIsNone(missing['value'])

    def test_five_groups_give_the_dated_conditional_scenario(self):
        ready = [{'id': i, 'title': i, 'status': 'ready', 'as_of': '2026-11-16', 'period': '2026-10'}
                 for i in ('demand', 'funding', 'inflation', 'credit')] + [self.signal(('fai', 'industry', 'annual'))]
        phase = phase_for(ready)
        self.assertEqual(phase['phase_label'], '有条件的周期情景')
        self.assertEqual(phase['phase_basis'][-1]['period'], '2026-10')


class RetainedIdTests(unittest.TestCase):
    # Reuse the resilience fixtures without collecting that class's tests again.
    setUp = resilience.EvidenceResilienceTests.setUp
    previous = resilience.EvidenceResilienceTests.previous
    failed = resilience.EvidenceResilienceTests.failed

    def test_repeated_rounds_add_the_suffix_at_most_once_and_drop_old_failures(self):
        previous = self.previous()
        previous['sources'].append({'id': 'public:financial:old', 'status': 'error', 'error': '本轮采集预算用完，下轮继续'})
        for _ in range(5):
            current = self.failed()
            retain_company_components(current, previous, NOW, [BOARD])
            ids = [s['id'] for s in current['sources']]
            self.assertFalse([i for i in ids if i.count(':retained') > 1], ids)
            self.assertEqual(len(ids), len(set(ids)))
            for row in current['sector_leaders'][BOARD['id']]:
                self.assertFalse([i for i in row['source_ids'] if i.count(':retained') > 1])
            self.assertFalse(any(s.get('status') == 'error' and s.get('cache_used') for s in current['sources']))
            previous = current
        self.assertIn('public:members:' + BOARD['id'] + ':retained', ids)

    def test_existing_reports_are_collapsed_and_deduplicated(self):
        nested = 'public:members:x' + ':retained' * 124
        report = {'snapshot': {'sources': [{'id': nested, 'status': 'error'}, {'id': 'public:members:x:retained', 'status': 'ok'},
                                           {'id': 'public:members:x', 'status': 'error'}]},
                  'sector_analysis': [{'id': 's', 'source_ids': [nested, 'public:members:x:retained', 'other'],
                                       'sources': [{'id': nested}]}]}
        collapse_retained(report)
        self.assertEqual([s['id'] for s in report['snapshot']['sources']], ['public:members:x:retained', 'public:members:x'])
        self.assertEqual(report['snapshot']['sources'][0]['status'], 'ok')
        self.assertEqual(report['sector_analysis'][0]['source_ids'], ['public:members:x:retained', 'other'])
        self.assertEqual(report['sector_analysis'][0]['sources'][0]['id'], 'public:members:x:retained')
        self.assertEqual(retained_base(nested), 'public:members:x')


class CollectionFallbackTests(unittest.TestCase):
    def test_ranking_uses_the_mirror_and_tells_connection_from_format(self):
        payload = json.dumps({'data': {'total': 1, 'diff': [{'f12': 'BK0001', 'f14': '测试', 'f2': 1, 'f3': 1}]}})
        calls = []

        def fetch(url, *args):
            calls.append(url)
            if url.startswith('https://push2.'):
                raise OSError('refused')
            return payload
        with patch.object(sectors, 'fetch_text', side_effect=fetch):
            rows, sources = sectors.collect_sector_quotes()
        self.assertTrue(rows)
        self.assertTrue(any('82.push2.eastmoney.com' in url for url in calls))
        self.assertTrue(all(s['status'] == 'ok' for s in sources))
        with patch.object(sectors, 'fetch_text', side_effect=OSError('down')):
            _, sources = sectors.collect_sector_quotes()
        self.assertIn('主地址与备用地址均未响应', sources[0]['error'])
        with patch.object(sectors, 'fetch_text', return_value='{"data": {"diff": "x"}}'):
            _, sources = sectors.collect_sector_quotes()
        self.assertIn('响应格式发生变化', sources[0]['error'])

    def test_yahoo_refusal_is_retried_on_the_second_host(self):
        calls = []

        def once(url):
            calls.append(url)
            if 'query1' in url:
                raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)
            return '{}'
        with patch.object(overseas, '_fetch_once', side_effect=once):
            self.assertEqual(overseas._fetch('https://query1.finance.yahoo.com/v8/finance/chart/MRK?x=1'), '{}')
        self.assertEqual(calls[-1], 'https://query2.finance.yahoo.com/v8/finance/chart/MRK?x=1')
        with patch.object(overseas, '_fetch_once', side_effect=OSError('down')), self.assertRaises(OSError):
            overseas._fetch('https://example.org/x')


class MemberRetryTests(unittest.TestCase):
    def test_csi_refusal_is_retried_once_then_reported(self):
        reference = {'code': '930914', 'aliases': ['港股通高股息']}
        refused = urllib.error.HTTPError('u', 403, 'Forbidden', {}, None)
        with patch.object(public, '_get', return_value=None), patch.object(public, '_member_last_good', {}), \
                patch.object(public, 'time') as clock, patch.object(public, '_set_member_fetch_status'), \
                patch.object(public, 'import_member_workbook', return_value=['row']) as imported, \
                patch.object(public, 'fetch_bytes', side_effect=[refused, b'xls']) as fetch:
            self.assertEqual(public.fetch_members(reference, NOW), ['row'])
        self.assertEqual(fetch.call_count, 2)
        clock.sleep.assert_called_once_with(public.MEMBER_RETRY_SECONDS)
        self.assertEqual(imported.call_args.args[0], b'xls')
        with patch.object(public, '_get', return_value=None), patch.object(public, '_member_last_good', {}), \
                patch.object(public, 'time'), patch.object(public, '_set_member_fetch_status'), \
                patch.object(public, 'fetch_bytes', side_effect=urllib.error.HTTPError('u', 404, 'Missing', {}, None)) as fetch, \
                self.assertRaises(urllib.error.HTTPError):
            public.fetch_members(reference, NOW)
        self.assertEqual(fetch.call_count, 1)


class RetryOrderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for name, value in [('_cache', {}), ('CACHE_PATH', Path(temp.name) / 'cache.json')]:
            mocked = patch.object(public, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_items_that_ran_out_of_time_go_first_next_round(self):
        def work(item):
            if item == 'c':
                raise OSError('no')
            return item
        first = public._parallel(['a', 'b', 'c'], work, 5, retry_key='work')
        self.assertEqual(first['c'][0], None)
        self.assertEqual(public.retry_first('work', ['a', 'b', 'c']), ['c', 'a', 'b'])
        # Without a key nothing is remembered (callers pass lambdas with no stable name).
        public._parallel(['x'], lambda item: 1 / 0, 5)
        self.assertNotIn('retry_first:<lambda>', public._cache)
        public.remember_failures('leader_history', ['600000.SH'])
        self.assertEqual(public.retry_first('leader_history', ['000001.SZ', '600000.SH']), ['600000.SH', '000001.SZ'])


if __name__ == '__main__':
    unittest.main()
