import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import research_public_data as data
from research_public_config import PublicDataConfigStore
from research_bond_model import score_bond
from research_sectors import analyze_sector, sector_catalog, match_sector_quotes

NOW = '2026-10-31T03:00:00+08:00'


def financial(**changes):
    return {'SECUCODE': '600000.SH', 'NOTICE_DATE': '2026-10-30 00:00:00',
            'REPORTDATE': '2026-09-30 00:00:00', 'BASIC_EPS': 1.17,
            'WEIGHTAVG_ROE': 5.2, 'YSTZ': 4.42, 'SJLTZ': 4.52, 'XSMLL': None, **changes}


def payload(*rows):
    return {'success': True, 'result': {'data': list(rows)}}


def quote_text(stamp='20261030161441', **changes):
    fields = [''] * 49
    values = {1: '浦发银行', 2: '600000', 3: '10.02', 30: stamp,
              32: '.30', 37: '64774', 38: '.19', 39: '6.45', 45: '3337.24', 46: '.44'}
    values.update({int(k): v for k, v in changes.items()})
    for k, v in values.items():
        fields[k] = v
    return 'v_sh600000="' + '~'.join(fields) + '";'


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        from test_helpers.isolated_public_cache import isolate_public_cache
        isolate_public_cache(self)

    def test_financial_uses_prior_day_disclosure_and_preserves_percent_units(self):
        value = data.parse_financial(payload(financial(), financial(NOTICE_DATE='2026-10-31', BASIC_EPS=9)), '600000.SH', NOW)
        self.assertEqual(value['eps'], 1.17)
        self.assertEqual(value['roe'], 5.2)
        self.assertIsNone(value['grossprofit_margin'])
        self.assertEqual(value['ann_date'], '2026-10-30')

    def test_future_wrong_company_empty_and_bad_payload_are_not_financial_evidence(self):
        for row in (financial(NOTICE_DATE='2026-11-01'), financial(SECUCODE='000001.SZ'),
                    financial(REPORTDATE='2026-12-31'), financial(NOTICE_DATE='invalid')):
            self.assertIsNone(data.parse_financial(payload(row), '600000.SH', NOW))
        self.assertIsNone(data.parse_financial(payload(), '600000.SH', NOW))
        with self.assertRaises(ValueError):
            data.parse_financial({'success': False}, '600000.SH', NOW)

    def test_quote_units_datetime_and_identity_are_verified(self):
        q = data.parse_quotes(quote_text(), {'600000.SH'}, NOW)['600000.SH']
        self.assertEqual(q['amount'], 647740000)
        self.assertAlmostEqual(q['total_mv'], 33372400)
        self.assertFalse(q['is_intraday'])
        self.assertEqual(data.parse_quotes(quote_text(), {'000001.SZ'}, NOW), {})
        self.assertEqual(data.parse_quotes(quote_text('20261102150000'), {'600000.SH'}, NOW), {})
        self.assertEqual(data.parse_quotes(quote_text(**{'3': '0'}), {'600000.SH'}, NOW), {})

    def test_current_intraday_is_not_mislabelled_as_close_and_stale_quotes_rejected(self):
        q = data.parse_quotes(quote_text('20261030142950'), {'600000.SH'}, '2026-10-30T14:30:00+08:00')
        self.assertTrue(q['600000.SH']['is_intraday'])
        self.assertEqual(data.parse_quotes(quote_text('20261030100000'), {'600000.SH'}, '2026-10-30T14:30:00+08:00'), {})
        self.assertEqual(data.parse_quotes(quote_text(), {'600000.SH'}, '2026-11-02T16:00:00+08:00'), {})

    def test_last_close_is_valid_across_verified_holiday_and_unknown_year_stays_unknown(self):
        text = quote_text('20260930150000')
        rows = data.parse_quotes(text, {'600000.SH'}, '2026-10-08T09:10:00+08:00')
        self.assertEqual(rows['600000.SH']['trade_date'], '2026-09-30')
        self.assertFalse(rows['600000.SH']['is_intraday'])
        self.assertEqual(data.parse_quotes(text, {'600000.SH'}, '2026-10-08T14:30:00+08:00'), {})
        self.assertEqual(data.parse_quotes(text, {'600000.SH'}, '2027-01-04T09:10:00+08:00'), {})

    def test_official_membership_checks_scope_date_exchange_and_code(self):
        sheet = MagicMock(ncols=9, nrows=2)
        sheet.cell_value.return_value = '成份券代码Constituent Code'
        base = ['20261030', '930851', '云计算', '', '000066', '中国长城', '', '深圳证券交易所', '']
        sheet.row_values.return_value = base
        workbook = MagicMock()
        workbook.sheet_by_index.return_value = sheet
        ref = {'code': '930851', 'aliases': ['云计算']}
        with patch('xlrd.open_workbook', return_value=workbook):
            value = data.parse_members(b'xls', ref, NOW)
            self.assertEqual(value[0]['ts_code'], '000066.SZ')
            for position, invalid in ((0, '20261102'), (0, '20260101'), (1, '000300'), (2, '人工智能'), (7, '未知交易所')):
                changed = list(base)
                changed[position] = invalid
                sheet.row_values.return_value = changed
                with self.assertRaises(ValueError):
                    data.parse_members(b'xls', ref, NOW)

    def test_references_do_not_use_consumer_for_food_or_financial_real_estate_for_finance(self):
        refs = data.reference_memberships(sector_catalog())
        self.assertEqual(refs['sector_food_beverage']['code'], '000815')
        self.assertEqual(refs['sector_consumer']['code'], '000932')
        self.assertEqual(refs['sector_financial_real_estate']['code'], '000934')
        self.assertEqual(refs['sector_finance']['code'], '932075')
        self.assertNotEqual(refs['sector_finance']['code'], refs['sector_financial_real_estate']['code'])
        self.assertNotIn('index_chinext', refs)

    def test_all_network_failures_remain_visible_without_invented_company_samples(self):
        with patch.object(data, 'fetch_members', side_effect=OSError('offline')), \
             patch.object(data, '_fixed_samples', {}), patch.object(data, '_save'):
            result = data.gather_public_company_evidence([{'id': 'sector_cloud_computing'}], NOW)
        self.assertEqual(result['sector_leaders'], {})
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['sources'][0]['status'], 'error')

    def test_public_data_is_used_and_total_failure_falls_back_to_existing_connection(self):
        import research_sectors as sectors
        snapshot = {'market': [], 'news': [], 'sources': [], 'warnings': []}
        failed_source = {'id': 'public:members:sector_cloud_computing', 'status': 'error'}
        public = {'sources': [failed_source], 'warnings': ['公开连接失败'], 'sector_leaders': {}}
        fallback = {'sources': [{'id': 'baostock:stock_industry', 'status': 'error'}],
                    'warnings': [], 'sector_leaders': {}}
        with patch.object(sectors, 'collect_sector_market', return_value=copy.deepcopy(snapshot)), \
             patch.object(sectors, 'collect_sector_quotes', return_value=([], [])), \
             patch.object(sectors, 'collect_verified_references', return_value=([], [], {})), \
             patch.object(sectors, 'collect_macro_risk', return_value=({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'})), \
             patch.object(sectors, 'fetch_text', return_value=''), \
             patch.object(sectors, 'collect_sector_histories', return_value=({}, [])), \
             patch('research_overseas.collect_overseas_references', return_value=([], [], {})), \
             patch('research_reference_fallbacks.collect_money_reference', return_value=([], [], {})), \
             patch('research_public_data.gather_public_company_evidence', return_value=public) as extra, \
             patch('research_free_data.gather_free_sector_company_evidence', return_value=fallback) as old:
            r = sectors.run_sector_research(data_config={'provider':'baostock','secondary_provider':'public_multisource'})
        extra.assert_called_once()
        old.assert_called_once()
        self.assertIn(failed_source, r['company_evidence']['sources'])
        self.assertEqual(r['coverage']['fully_ready_sector_count'], 0)
        self.assertTrue(all(row['recommendation_index'] is None for row in r['sector_analysis']))

    def test_probe_is_async_and_partial_does_not_become_verified(self):
        release = threading.Event()
        called = []
        def probe():
            called.append(1)
            release.wait(2)
            return {'verification': 'partial', 'capabilities': {'industry': {'status': 'available', 'count': 50}}}
        with patch('research_public_config.capability_snapshot', return_value={}):
            store = PublicDataConfigStore(probe=probe)
            start = time.monotonic()
            self.assertEqual(store.verify()['verification'], 'checking')
            self.assertLess(time.monotonic() - start, .2)
            store.verify()
            release.set()
            store._worker.join(1)
            self.assertEqual(len(called), 1)
            self.assertEqual(store.status()['verification'], 'partial')


class DurableMembershipCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'csi-last-good.json'
        self.ref = {'code': '930851', 'title': '中证云计算与大数据主题指数', 'aliases': ['云计算']}
        self.rows = [{'ts_code': '000066.SZ', 'name': '中国长城', 'member_date': '2026-10-30',
                      'index_code': '930851', 'index_name': '云计算'},
                     {'ts_code': '600570.SH', 'name': '恒生电子', 'member_date': '2026-10-30',
                      'index_code': '930851', 'index_name': '云计算'}]
        for target, value in (('_cache', {}), ('_member_last_good', {}), ('_member_fetch_status', {}),
                              ('_fixed_samples', {}), ('MEMBER_CACHE_PATH', self.path),
                              ('FIXED_SAMPLE_PATH', Path(self.directory.name) / 'fixed.json')):
            patcher = patch.object(data, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(data, 'now_iso', return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def persist(self, fetched_at='2026-10-30T17:00:00+08:00'):
        with patch.object(data, 'parse_members', return_value=copy.deepcopy(self.rows)):
            return data.import_member_workbook(b'complete-official-workbook', self.ref, NOW, fetched_at)

    def test_valid_full_workbook_is_persisted_separately_with_original_provenance(self):
        self.persist()
        document = json.loads(self.path.read_text(encoding='utf-8'))
        snapshot = document['snapshots']['930851']
        self.assertTrue(snapshot['parsed_complete'])
        self.assertEqual(snapshot['parsed_count'], 2)
        self.assertEqual(snapshot['fetched_at'], '2026-10-30T17:00:00+08:00')
        self.assertEqual(snapshot['source_url'], data.MEMBER_BASE + '930851cons.xls')
        self.assertTrue(data._valid_member_snapshot(snapshot, self.ref, NOW))

    def test_network_failure_uses_full_last_good_and_preserves_failed_attempt(self):
        self.persist()
        data._cache.clear()
        before = self.path.read_text(encoding='utf-8')
        with patch.object(data, 'fetch_bytes', side_effect=OSError('HTTP 403')):
            result = data.fetch_members(self.ref, NOW)
        self.assertEqual(result, self.rows)
        result.pop()
        self.assertEqual(len(data._member_last_good['930851']['rows']), 2)
        status = data.member_fetch_status('930851')
        self.assertEqual(status['cache_status'], 'last_good_after_failure')
        self.assertEqual(status['fetched_at'], '2026-10-30T17:00:00+08:00')
        self.assertEqual(status['last_attempt_at'], NOW)
        self.assertIn('403', status['last_attempt_error'])
        self.assertEqual(self.path.read_text(encoding='utf-8'), before)

    def test_recent_durable_cache_survives_empty_shared_cache_without_new_fetch(self):
        self.persist('2026-10-31T02:30:00+08:00')
        data._cache.clear()
        # Simulate a process restart loading the independent file.
        document = json.loads(self.path.read_text(encoding='utf-8'))
        data._member_last_good.clear()
        data._member_last_good.update(document['snapshots'])
        with patch.object(data, 'fetch_bytes', side_effect=AssertionError('unexpected fetch')):
            self.assertEqual(data.fetch_members(self.ref, NOW), self.rows)
        self.assertEqual(data.member_fetch_status('930851')['cache_status'], 'persistent_cache')

    def test_stale_future_wrong_identity_and_partial_snapshots_never_fall_back(self):
        self.persist()
        original = copy.deepcopy(data._member_last_good['930851'])
        for change in ({'parsed_complete': False}, {'parsed_count': 1}, {'code': '000300'},
                       {'source_url': 'https://example.com/fake.xls'}, {'rows': 123},
                       {'rows': [{**row, 'member_date': '2026-11-02'} for row in self.rows]},
                       {'rows': [{**row, 'member_date': '2026-08-01'} for row in self.rows]},
                       {'rows': [{**row, 'index_name': '人工智能'} for row in self.rows]}):
            with self.subTest(change=change):
                data._cache.clear()
                data._member_last_good['930851'] = {**original, **change}
                with patch.object(data, 'fetch_bytes', side_effect=OSError('offline')):
                    with self.assertRaises(OSError):
                        data.fetch_members(self.ref, NOW)

    def test_bad_new_workbook_does_not_overwrite_valid_snapshot(self):
        self.persist()
        data._cache.clear()
        original = self.path.read_text(encoding='utf-8')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'not an xls workbook'
        with patch.object(data, 'fetch_bytes', return_value=b'not an xls workbook'), \
             patch.object(data, 'parse_members', side_effect=ValueError('invalid header')):
            self.assertEqual(data.fetch_members(self.ref, NOW), self.rows)
        self.assertEqual(self.path.read_text(encoding='utf-8'), original)
        self.assertIn('invalid header', data.member_fetch_status('930851')['last_attempt_error'])

    def test_collector_marks_fallback_partial_and_keeps_original_dates(self):
        self.persist()
        data._cache.clear()
        with patch.object(data, 'reference_memberships', return_value={'board': self.ref}), \
             patch.object(data, 'fetch_bytes', side_effect=OSError('HTTP 403')), \
             patch('research_theme_memberships.fetch_theme_memberships', return_value={'memberships': {}, 'references': {}, 'sources': []}), \
             patch.object(data, 'fetch_quotes', return_value={}), patch.object(data, '_save'):
            result = data.gather_public_company_evidence([{'id': 'board'}], NOW)
        source = result['sources'][0]
        self.assertEqual(source['status'], 'partial')
        self.assertEqual(source['as_of'], '2026-10-30')
        self.assertEqual(source['fetched_at'], '2026-10-30T17:00:00+08:00')
        self.assertTrue(source['cache_used'])
        self.assertIn('本轮官方成分采集失败', source['error'])

    def test_readable_cache_budget_does_not_erase_previous_file(self):
        cache_path = Path(self.directory.name) / 'shared-cache.json'
        cache_path.write_text('{"datasets":{}}', encoding='utf-8')
        data._cache['large'] = {'expires': time.time()+100, 'fetched_at': NOW, 'data': 'x'*400}
        with patch.object(data, 'CACHE_PATH', cache_path), patch.object(data, 'MAX_CACHE_BYTES', 100):
            data._save()
        self.assertEqual(cache_path.read_text(encoding='utf-8'), '{"datasets":{}}')

    def original_selected_document(self):
        return {'sources': [{'id': 'public:members:board', 'status': 'ok', 'count': 50,
            'url': data.MEMBER_BASE + '930851cons.xls', 'as_of': '2026-10-30',
            'fetched_at': '2026-10-30T17:00:00+08:00'}],
            'sector_leaders': {'board': [{'ts_code': row['ts_code'], 'name': row['name'],
                'membership_evidence': {'l1_name': '云计算（官方指数成分）',
                    'snapshot_date': '2026-10-30', 'evidence_type': 'official_index'},
                'source_ids': ['public:members:board']} for row in self.rows]}}

    def test_fixed_selected_pool_is_independent_and_does_not_become_full_membership(self):
        content = json.dumps(self.original_selected_document(), ensure_ascii=False).encode('utf-8')
        recovered = data.import_fixed_samples_snapshot(content, {'board': self.ref}, NOW)
        self.assertEqual(len(recovered['board']['rows']), 2)
        self.assertEqual(recovered['board']['original_full_member_count'], 50)
        self.assertFalse(recovered['board']['complete_membership'])
        self.assertEqual(data._member_last_good, {})
        self.assertEqual(data._cache, {})
        rows, metadata = data.fixed_sample_members('board', self.ref, NOW)
        self.assertEqual(rows[0]['evidence_type'], 'official_fixed_sample')
        self.assertIn('不代表本轮完整成分池市值排名', rows[0]['selection_basis'])
        self.assertEqual(metadata['fetched_at'], '2026-10-30T17:00:00+08:00')

    def test_fixed_pool_rejects_future_stale_wrong_reference_and_missing_successful_citation(self):
        original = self.original_selected_document()
        for mode in ('failed', 'wrong_url', 'missing_source', 'wrong_name', 'future'):
            document = copy.deepcopy(original)
            if mode == 'failed':
                document['sources'][0]['status'] = 'error'
            elif mode == 'wrong_url':
                document['sources'][0]['url'] = data.MEMBER_BASE + '000300cons.xls'
            elif mode == 'missing_source':
                document['sector_leaders']['board'][0]['source_ids'] = []
            elif mode == 'wrong_name':
                document['sector_leaders']['board'][0]['membership_evidence']['l1_name'] = '其他（官方指数成分）'
            else:
                document['sources'][0]['fetched_at'] = '2026-11-01T01:00:00+08:00'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                data.import_fixed_samples_snapshot(json.dumps(document).encode(), {'board': self.ref}, NOW)
        data.import_fixed_samples_snapshot(json.dumps(original).encode(), {'board': self.ref}, NOW)
        self.assertEqual(data.fixed_sample_members('board', self.ref, '2026-12-16T10:00:00+08:00'), ([], {}))
        self.assertEqual(data.fixed_sample_members('board', {**self.ref, 'code': '000300'}, NOW), ([], {}))

    def test_fixed_fallback_source_is_partial_with_actual_failed_attempt_and_original_count(self):
        document = self.original_selected_document()
        data.import_fixed_samples_snapshot(json.dumps(document).encode(), {'board': self.ref}, NOW)
        with patch.object(data, 'reference_memberships', return_value={'board': self.ref}), \
             patch.object(data, 'fetch_bytes', side_effect=OSError('HTTP 403')), \
             patch('research_theme_memberships.fetch_theme_memberships', return_value={'memberships': {}, 'references': {}, 'sources': []}), \
             patch.object(data, 'fetch_quotes', return_value={}), patch.object(data, '_save'):
            result = data.gather_public_company_evidence([{'id': 'board'}], NOW)
        source = result['sources'][0]
        self.assertEqual(source['status'], 'partial')
        self.assertEqual(source['count'], 2)
        self.assertEqual(source['original_full_member_count'], 50)
        self.assertFalse(source['complete_membership'])
        self.assertEqual(source['fetched_at'], '2026-10-30T17:00:00+08:00')
        self.assertIn('HTTP 403', source['error'])
        self.assertIn('非完整名单', source['error'])

    def test_saved_full_workbook_keeps_unknown_http_time_separate_from_file_save_and_reverification(self):
        with patch.object(data, 'parse_members', return_value=copy.deepcopy(self.rows)):
            data.import_member_workbook(b'saved-workbook', self.ref, NOW, None,
                                       filesystem_saved_at='2026-10-31T01:00:00+08:00')
        data._cache.clear()
        self.assertTrue(data._valid_member_snapshot(data._member_last_good['930851'], self.ref, NOW))
        with patch.object(data, 'fetch_bytes', side_effect=AssertionError('unnecessary')):
            self.assertEqual(data.fetch_members(self.ref, NOW), self.rows)
        status = data.member_fetch_status('930851')
        self.assertIsNone(status['fetched_at'])
        self.assertEqual(status['fetched_at_precision'], 'unknown')
        self.assertEqual(status['filesystem_saved_at'], '2026-10-31T01:00:00+08:00')
        self.assertEqual(status['verified_at'], NOW)

    def visible_history_document(self):
        url = data.MEMBER_BASE + '930851cons.xls'
        return {'report_as_of': NOW, 'method': '从网站历史详情可见DOM恢复固定样本',
            'sources': [{'name': '中证官方成分 · 中证云计算与大数据主题指数', 'url': url, 'status': '可用',
                'text': '中证官方成分 · 云计算数据时间：2026-10-30本次获取：2026/10/30 17:00:00可用'}],
            'sectors': [{'id': 'board', 'samples': [{'code': row['ts_code'], 'name': row['name'],
                'membership_date': row['member_date']} for row in self.rows],
                'company_evidence': [{'identity': row['name'] + row['ts_code'] + ' · 行业代表样本',
                    'links': [{'name': '中证官方成分 · 云计算', 'url': url}],
                    'membership': '归属依据：云计算（官方指数成分） → 成分名单日期 2026-10-30'} for row in self.rows]}]}

    def test_visible_history_requires_crosschecked_sample_source_dates_and_keeps_unknown_full_count(self):
        document = self.visible_history_document()
        recovered = data.import_visible_fixed_samples(json.dumps(document, ensure_ascii=False).encode(), {'board': self.ref}, NOW)
        self.assertIsNone(recovered['board']['original_full_member_count'])
        rows, metadata = data.fixed_sample_members('board', self.ref, NOW)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(metadata['original_full_member_count'])
        self.assertEqual(metadata['fetched_at'], '2026-10-30T17:00:00+08:00')
        self.assertEqual(metadata['original_report_as_of'], NOW)
        self.assertIn('DOM', metadata['recovery_method'])

    def test_visible_history_wrong_company_source_alias_or_date_never_imported(self):
        for mode in ('identity', 'link', 'alias', 'date', 'source_state'):
            document = self.visible_history_document()
            evidence = document['sectors'][0]['company_evidence'][0]
            if mode == 'identity':
                evidence['identity'] = '其他600000.SH · 行业代表样本'
            elif mode == 'link':
                evidence['links'] = []
            elif mode == 'alias':
                evidence['membership'] = evidence['membership'].replace('云计算', '其他方向')
            elif mode == 'date':
                document['sectors'][0]['samples'][0]['membership_date'] = '2026-10-29'
            else:
                document['sources'][0]['status'] = '错误'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                data.import_visible_fixed_samples(json.dumps(document).encode(), {'board': self.ref}, NOW)


class BondModelTests(unittest.TestCase):
    def metrics(self, **changes):
        return dict(sample_count=121, return_5d=.1, return_20d=.4, return_60d=1.2,
                    ma20_gap=.2, annual_volatility=2, max_drawdown=-.5, **changes)

    def test_bond_formula_is_reproducible_and_missing_data_does_not_score(self):
        m = self.metrics()
        self.assertEqual(score_bond(m)['score'], 60)
        for key, value in (('sample_count', 60), ('annual_volatility', None), ('max_drawdown', float('nan'))):
            bad = {**m, key: value}
            self.assertIsNone(score_bond(bad))
        self.assertLess(score_bond({**m, 'max_drawdown': -5, 'annual_volatility': 8})['score'], 60)

    def test_defensive_stock_regime_does_not_cap_bond_model(self):
        from test_research_sectors import history
        quote = {'asset_type': 'bond', 'return_type': 'full_price_with_coupon', 'change_pct': .2,
                 'name': '中证全债', 'as_of': '2026-10-30', 'data_frequency': 'daily', 'as_of_precision': 'date'}
        results = [analyze_sector({'id': 'bond', 'title': '债券市场'}, quote, history(), [], [], NOW,
                                  {'mode': mode}) for mode in ('defensive', 'offensive')]
        self.assertEqual(results[0]['recommendation_index'], results[1]['recommendation_index'])
        self.assertGreater(results[0]['recommendation_index'], 39)
        self.assertEqual(results[0]['score_model'], 'bond_trend_v1')
