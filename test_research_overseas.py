import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import research_overseas as overseas

from research_overseas import (build_overseas_indicator,last_complete_session,
    match_akeso_publication,match_tencent_publication,parse_history,parse_sec_financials,recent_sessions,
    parse_hk_financials,parse_hk_financial_currency)


class OverseasCalendarTests(unittest.TestCase):
    def test_us_does_not_consume_unfinished_session(self):
        self.assertEqual(last_complete_session('US','2026-10-31T03:49:00+08:00'),'2026-10-29')
        self.assertEqual(last_complete_session('US','2026-10-31T04:15:00+08:00'),'2026-10-30')

    def test_local_holidays_differ_from_a_shares(self):
        self.assertEqual(last_complete_session('HK','2026-10-20T08:00:00+08:00'),'2026-10-16')
        self.assertEqual(last_complete_session('HK','2026-10-06T20:00:00+08:00'),'2026-10-06')
        self.assertEqual(last_complete_session('US','2026-07-04T12:00:00+08:00'),'2026-07-02')

    def test_unknown_calendar_year_is_not_assumed_open(self):
        self.assertIsNone(last_complete_session('US','2027-03-04T20:00:00+08:00'))

    def test_half_day_and_dst(self):
        self.assertEqual(last_complete_session('US','2026-11-28T02:20:00+08:00'),'2026-11-27')
        self.assertEqual(last_complete_session('HK','2026-02-16T12:20:00+08:00'),'2026-02-16')


class OverseasPriceTests(unittest.TestCase):
    def test_hk_raw_fallback_is_explicit(self):
        p={'data':{'hk09926':{'day':[['2026-10-29','10','11'],['2026-10-30','10','12']]}}}
        r=parse_history(p,'09926.HK','2026-10-31T03:49:00+08:00')
        self.assertEqual(r[-1]['adjustment'],'unadjusted')
        self.assertEqual(r[-1]['close'],12)

    def test_adjusted_hk_is_not_labelled_raw_close(self):
        p={'data':{'hk00700':{'qfqday':[['2026-10-30','10','12']]}}}
        r=parse_history(p,'00700.HK','2026-10-31T03:49:00+08:00')
        self.assertIsNone(r[-1]['unadjusted_close'])
        self.assertEqual(r[-1]['adjustment'],'forward_adjusted')

    def test_us_symbol_and_currency_are_validated(self):
        p={'chart':{'result':[{'meta':{'symbol':'MSFT','currency':'USD','exchangeTimezoneName':'America/New_York'}}]}}
        with self.assertRaises(ValueError):parse_history(p,'AAPL.US','2026-10-31T03:49:00+08:00')

    def test_unfinished_us_daily_point_is_discarded(self):
        p={'chart':{'result':[{'meta':{'symbol':'AAPL','currency':'USD','exchangeTimezoneName':'America/New_York'},
            'timestamp':[1793295000,1793381400],
            'indicators':{'adjclose':[{'adjclose':[10,12]}],'quote':[{'close':[10,12]}]}}]}}
        r=parse_history(p,'AAPL.US','2026-10-31T03:49:00+08:00')
        self.assertTrue(all(x['date']<='2026-10-29' for x in r))

    def samples(self,codes=('AAPL.US','MSFT.US','NVDA.US')):
        now='2026-10-31T03:49:00+08:00'
        days=recent_sessions('US',now)
        rows=[]
        for code in codes:
            rows.append({'ts_code':code,'name':code,'as_of':days[-1],'quote':{'market':'US',
                'trade_date':days[-1],'close':100,'pct_chg':1,'is_intraday':False},
                'membership_evidence':{'l1_name':'已核验','snapshot_date':'2026-10-31'},
                'source_ids':['official'],'selection_basis':'指定代表样本',
                'history':[{'date':d,'close':100+i}for i,d in enumerate(days)]})
        return now,rows

    def test_complete_basket_is_ready_and_input_is_not_mutated(self):
        now,rows=self.samples();original=copy.deepcopy(rows)
        b=build_overseas_indicator({'id':'overseas_us_equity','title':'美股'},rows,now)
        self.assertTrue(b['meta']['ready']);self.assertEqual(b['meta']['history_count'],61)
        self.assertEqual(b['meta']['as_of'],'2026-10-29');self.assertEqual(rows,original)

    def test_missing_recent_common_session_prevents_scoring(self):
        now,rows=self.samples();rows[0]['history'].pop(-3)
        b=build_overseas_indicator({'id':'overseas_us_equity','title':'美股'},rows,now)
        self.assertFalse(b['meta']['ready'])

    def test_mixed_market_sample_cannot_make_ready(self):
        now,rows=self.samples();rows[0]['quote']['market']='HK'
        b=build_overseas_indicator({'id':'overseas_us_equity','title':'美股'},rows,now)
        self.assertFalse(b['meta']['ready'])

    def test_missing_preset_sample_does_not_silently_reduce_basket(self):
        now,rows=self.samples()
        b=build_overseas_indicator({'id':'overseas_us_equity','title':'美股'},rows[:2],now)
        self.assertFalse(b['meta']['ready'])
        self.assertEqual(b['meta']['excluded'][0]['code'],'NVDA.US')

    def test_healthcare_uses_us_calendar_and_own_drug_company_samples(self):
        now,rows=self.samples(('ABBV.US','MRK.US'))
        b=build_overseas_indicator({'id':'overseas_healthcare','title':'海外医药'},rows,now)
        self.assertEqual(b['meta']['market'],'US')
        self.assertEqual(b['meta']['currency'],'USD')
        self.assertTrue(b['meta']['ready'])
        self.assertEqual(b['meta']['sample_count'],2)
        self.assertEqual(b['meta']['history_end'],'2026-10-29')
        self.assertIn('不代表官方指数',b['meta']['method'])

    def test_healthcare_does_not_reuse_general_us_tech_samples(self):
        now,rows=self.samples()
        self.assertIsNone(build_overseas_indicator({'id':'overseas_healthcare','title':'海外医药'},rows,now))


class OverseasBusinessTests(unittest.TestCase):
    def cached(self,key,*_):
        if key.startswith('official:'):
            return json.dumps({'cik':'0001551152','tickers':['ABBV'],'exchanges':['NYSE']})
        if key.startswith('business:'):
            return '<p>AbbVie is a team creating medicines and solutions for patients.</p>'
        if key.startswith('finance:'):
            return json.dumps({'cik':1551152,'facts':{}})
        return '{}'

    def test_healthcare_requires_separate_issuer_business_evidence(self):
        spec=copy.deepcopy(overseas.SAMPLES['overseas_healthcare'][0])
        points=[{'date':'2026-10-28','close':100,'unadjusted_close':100,'adjustment':'adjusted'},
                {'date':'2026-10-29','close':101,'unadjusted_close':101,'adjustment':'adjusted'}]
        with patch.object(overseas,'_cached',side_effect=self.cached),patch.object(overseas,'parse_history',return_value=points):
            row,sources=overseas._collect(spec,'2026-10-31T03:49:00+08:00')
        self.assertIn('overseas:business:ABBV.US',row['source_ids'])
        self.assertEqual(row['business_evidence']['url'],spec['business_url'])
        self.assertIsNone(row['business_evidence']['published_at'])
        self.assertTrue(any(s['id']=='overseas:business:ABBV.US' for s in sources))

    def test_sec_listing_alone_and_script_text_cannot_prove_drug_business(self):
        spec=copy.deepcopy(overseas.SAMPLES['overseas_healthcare'][0])
        for body in ('<p>AbbVie investor portal.</p>',
                     '<script>AbbVie creating medicines and solutions</script><p>Investor portal</p>'):
            def cached(key,*args):
                return body if key.startswith('business:') else self.cached(key,*args)
            with self.subTest(body=body),patch.object(overseas,'_cached',side_effect=cached):
                with self.assertRaisesRegex(ValueError,'医药业务证据'):
                    overseas._collect(spec,'2026-10-31T03:49:00+08:00')


class OverseasFinancialTests(unittest.TestCase):
    def test_hk_quote_currency_never_becomes_financial_statement_currency(self):
        main={'result':{'data':[{'SECUCODE':'00700.HK','REPORT_DATE':'2026-06-30 00:00:00',
            'BASIC_EPS':12.639,'CURRENCY':'HKD'}]}}
        f=parse_hk_financials(main,'00700.HK','2026-10-31T03:49:00+08:00')
        self.assertEqual(f['eps'],12.639);self.assertIsNone(f['currency'])
        income={'result':{'data':[{'SECUCODE':'00700.HK','REPORT_DATE':'2026-06-30 00:00:00',
            'CURRENCY':'人民币','CURRENCY_CODE':'CNY'}]}}
        self.assertEqual(parse_hk_financial_currency(income,'00700.HK','2026-06-30'),'CNY')

    def test_hk_currency_missing_conflicting_or_other_period_stays_unknown(self):
        row={'SECUCODE':'00700.HK','REPORT_DATE':'2026-06-30 00:00:00','CURRENCY_CODE':'CNY'}
        wrong=dict(row,CURRENCY_CODE='HKD',REPORT_DATE='2026-03-31 00:00:00')
        self.assertEqual(parse_hk_financial_currency({'result':{'data':[row,wrong]}},'00700.HK','2026-06-30'),'CNY')
        self.assertIsNone(parse_hk_financial_currency({'result':{'data':[dict(row,CURRENCY='港元')]}},'00700.HK','2026-06-30'))
        self.assertIsNone(parse_hk_financial_currency({'result':{'data':[wrong]}},'00700.HK','2026-06-30'))

    def test_same_duration_comparison_and_no_future_filings(self):
        def r(start,end,value,filed):return {'start':start,'end':end,'val':value,'filed':filed}
        revenues=[r('2025-04-01','2025-06-30',100,'2025-08-01'),r('2025-01-01','2025-06-30',300,'2025-08-01'),
            r('2026-04-01','2026-06-30',120,'2026-08-01'),r('2026-07-01','2026-09-30',999,'2026-11-01')]
        x={'facts':{'us-gaap':{'Revenues':{'units':{'USD':revenues}},'NetIncomeLoss':{'units':{'USD':[
            r('2025-04-01','2025-06-30',-10,'2025-08-01'),r('2026-04-01','2026-06-30',5,'2026-08-01')]}}}}}
        f=parse_sec_financials(x,'2026-10-31T03:49:00+08:00')
        self.assertAlmostEqual(f['tr_yoy'],20);self.assertAlmostEqual(f['netprofit_yoy'],150)
        self.assertEqual(f['ann_date'],'2026-08-01')

    def test_akeso_publication_requires_period_and_real_announcement(self):
        payload={'News':[{'title':'INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED JUNE 30, 2026',
            'formatedDate':'27 August 2026','ID':8127054,'hasAttachments':True},
            {'title':'INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED JUNE 30, 2025',
            'formatedDate':'20 July 2026','ID':1,'hasAttachments':True}]}
        p=match_akeso_publication(payload,'2026-06-30','2026-10-31T03:49:00+08:00')
        self.assertEqual(p['ann_date'],'2026-08-27')
        self.assertIsNone(match_akeso_publication(payload,'2026-09-30','2026-10-31T03:49:00+08:00'))

    def test_tencent_uses_visible_matching_entry_not_modified_metadata(self):
        s='''<meta content="2026-08-20" name="dateModified"><article><p class='entry-meta'>August 12, 2026</p>
        <p class='entry-title'>Tencent Announces 2026 Second Quarter Results</p>
        <a href='https://www.tencent.com/wp-content/uploads/2026/08/Results.pdf'>Results</a></article>'''
        p=match_tencent_publication(s,'2026-06-30','2026-10-31T03:49:00+08:00')
        self.assertEqual(p['ann_date'],'2026-08-12')
        self.assertIsNone(match_tencent_publication(s,'2026-09-30','2026-10-31T03:49:00+08:00'))


class OverseasCacheTests(unittest.TestCase):
    def facts(self):
        def r(start,end,value,filed):return {'start':start,'end':end,'val':value,'filed':filed,'accn':'audit-id'}
        return {'cik':320193,'entityName':'Apple Inc.','facts':{'us-gaap':{
            'Revenues':{'label':'unused','units':{'USD':[r('2025-04-01','2025-06-30',100,'2025-08-01'),
                r('2026-04-01','2026-06-30',120,'2026-08-01')]}},
            'NetIncomeLoss':{'units':{'USD':[r('2025-04-01','2025-06-30',10,'2025-08-01'),
                r('2026-04-01','2026-06-30',12,'2026-08-01')]}},
            'UnusedBalanceSheetFact':{'unused':'x'*1_000_000}}}}

    def test_slim_sec_payload_preserves_values_dates_and_audit_fields(self):
        full=self.facts();small=overseas.compact_sec_facts(full)
        self.assertEqual(parse_sec_financials(full,'2026-10-31T03:49:00+08:00'),
            parse_sec_financials(small,'2026-10-31T03:49:00+08:00'))
        self.assertNotIn('UnusedBalanceSheetFact',small['facts']['us-gaap'])
        self.assertEqual(small['facts']['us-gaap']['Revenues']['units']['USD'][0]['accn'],'audit-id')
        self.assertLess(len(json.dumps(small)),2000)

    def test_cache_is_independent_bounded_and_rejects_large_single_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'overseas.json'
            with patch.object(overseas,'CACHE_PATH',path),patch.object(overseas,'_cache',{}):
                for i in range(9):overseas._cache_put('test:'+str(i),'x'*590_000,60)
                overseas._save_cache()
                self.assertLessEqual(path.stat().st_size,overseas.CACHE_LIMIT)
                self.assertLess(len(overseas._cache),9)
                with self.assertRaises(ValueError):
                    overseas._cache_put('oversized','x'*600_001,60)

    def test_explicit_legacy_migration_preserves_domestic_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'public.json';dest=Path(directory)/'overseas.json'
            expiry=overseas.clock_time.time()+100
            domestic={'data':[{'code':'931743'}],'expires':expiry,'fetched_at':'2026-10-31T03:00:00+08:00'}
            path.write_text(json.dumps({'datasets':{'members:931743':domestic,'overseas:finance:AAPL.US':{
                'data':json.dumps(self.facts()),'expires':expiry,'fetched_at':'2026-10-31T03:00:00+08:00'}}}),encoding='utf-8')
            with patch.object(overseas,'CACHE_PATH',dest),patch.object(overseas,'_cache',{}):
                result=overseas.migrate_legacy_cache(path)
                self.assertEqual(result['migrated'],1)
                self.assertEqual(json.loads(path.read_text())['datasets'],{'members:931743':domestic})
                moved=json.loads(overseas._cache_get('finance:AAPL.US'))
                self.assertEqual(parse_sec_financials(moved,'2026-10-31T03:49:00+08:00')['ann_date'],'2026-08-01')
                self.assertLess(dest.stat().st_size,3000)


if __name__=='__main__':unittest.main()
