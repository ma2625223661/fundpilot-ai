"""Local-only review coverage across markets, assets, and frozen observations."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from research_accounts import AccountStore
from research_data import CHINA
from research_review import price_review
from research_review_evidence import session_days, local_history
from research_review_guidance import review_guidance
from test_research_review import sector, CONFIG
from test_cloud_accounts import PASSWORD


NOW = '2026-11-01T09:00:00+08:00'


def foreign(market='HK'):
    s = sector('overseas_test')
    days = session_days(market,'2026-10-30',30)
    history = [{'date':d,'value':100+i} for i,d in enumerate(days)]
    codes = ['09926.HK','06160.HK'] if market=='HK' else ['ABBV.US','MRK.US']
    s.update(group='overseas')
    s['custom_index'].update(market=market,currency='HKD' if market=='HK' else 'USD',history=history,
        constituents=[{'code':c,'name':c,'price_adjustment':'unadjusted'} for c in codes])
    s['leaders'] = [{'ts_code':c,'price_adjustment':'unadjusted',
                     'history':[{'date':r['date'],'close':r['value']} for r in history]} for c in codes]
    return s


def publisher(market='HK'):
    identity = 'overseas_hang_seng' if market=='HK' else 'overseas_sp500'
    key = 'reference:'+identity
    s = {'id':identity,'title':identity,'group':'overseas','status':'ok','score_scope':'reference_trend',
        'risk':'中风险','market_risk':{'score':50},
        'quote':{'code':'^HSI' if market=='HK' else '^GSPC','market':market,'as_of':'2026-10-30',
            'history_secid':key,'source_id':'source:'+identity,'asset_type':'equity_index','currency':'HKD' if market=='HK' else 'USD'}}
    rows = [{'date':d,'close':100} for d in session_days(market,'2026-10-30',30)]
    return s,key,rows


def market_report(market='HK'):
    s = foreign(market)
    ref,key,rows = publisher(market)
    return {'as_of':NOW,'sector_analysis':[s,ref,sector('index_csi300')],
            '_quote_histories':{key:{'rows':rows}},'snapshot':{'sources':[]}}


class MarketEvidenceTests(unittest.TestCase):
    def test_hk_and_us_use_native_reference_and_dates(self):
        for market,name in [('HK','恒生'),('US','标普500')]:
            r=market_report(market)
            r['snapshot']['sources']=[{'id':r['sector_analysis'][1]['quote']['source_id'],
                                      'name':'native reference','url':'https://example.test/index','status':'ok'}]
            v=price_review(r['sector_analysis'][0],None,'2026-10-30',report=r,as_of=NOW)
            self.assertEqual(v['status'],'completed')
            self.assertIn(name,v['reference_label'])
            self.assertEqual(v['sample_count'],2)
            self.assertEqual(v['trading_dates'],session_days(market,'2026-10-30',5))
            self.assertIn('未复权',v['adjustment_note'])
            self.assertEqual(len(v['series']),6)
            self.assertEqual(v['evidence']['reference_sources'][0]['name'],'native reference')

    def test_hk_calendar_differs_during_mainland_holiday(self):
        self.assertEqual(session_days('HK','2026-10-08',5),['2026-10-02','2026-10-05','2026-10-06','2026-10-07','2026-10-08'])
        self.assertEqual(session_days('HK','2026-10-20',2),['2026-10-16','2026-10-20'])
        self.assertEqual(session_days('HK','2027-01-04',26),[])

    def test_unfinished_foreign_close_is_not_consumed(self):
        r=market_report()
        v=price_review(r['sector_analysis'][0],None,'2026-10-30',report=r,as_of='2026-10-30T16:05:00+08:00')
        self.assertEqual(v['period_end'],'2026-10-29')

    def test_missing_native_benchmark_does_not_reuse_csi300(self):
        r=market_report();r['_quote_histories'].clear()
        v=price_review(r['sector_analysis'][0],sector('index_csi300'),'2026-10-30',report=r,as_of=NOW)
        self.assertEqual(v['status'],'partial')
        self.assertIsNone(v['score']);self.assertIsNone(v['excess_pct'])

    def test_mixed_foreign_constituents_are_rejected(self):
        s=foreign();s['custom_index']['constituents'][0]['code']='ABBV.US'
        self.assertEqual(price_review(s,None,'2026-10-30')['status'],'unsupported')

    def test_reference_has_distinct_fixed_model_not_missing_score_rescaling(self):
        r=market_report();s=r['sector_analysis'][1]
        v=price_review(s,None,'2026-10-30',report=r,as_of=NOW)
        self.assertEqual(v['status'],'completed');self.assertEqual(v['score'],67.5)
        self.assertEqual([c['maximum'] for c in v['components']],[40,35,25])
        self.assertIsNone(v['excess_pct'])
        g=review_guidance(v,s)
        self.assertEqual(g['status'],'ready');self.assertEqual(g['recommendation_index'],49)

    def test_exact_local_publisher_cache_only_and_no_network(self):
        s={'id':'bond','quote':{'code':'H11001','history_secid':'official:csindex:H11001','as_of':'2026-10-30','currency':'CNY'}}
        record={'quote':copy.deepcopy(s['quote']),'history':[{'date':'2026-10-30','close':100}]}
        with patch('research_evidence_cache.load_record',return_value=record),patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            self.assertEqual(len(local_history(s,{})),1)
            record['quote']['code']='other'
            self.assertEqual(local_history(s,{}),[])

    def test_rate_review_preserves_units_and_has_no_price_return(self):
        days=session_days('CN','2026-10-30',70)
        rows=[{'date':d,'annual_rate_pct':1.5-i*.001} for i,d in enumerate(days)]
        s={'id':'money','title':'货币','group':'defensive','quote':{'history_secid':'rate:ON','source_id':'rate',
            'asset_type':'money_rate','as_of':days[-1]}}
        r={'_quote_histories':{'rate:ON':{'rows':rows}}}
        v=price_review(s,None,days[-1],report=r,as_of=NOW)
        self.assertEqual(v['status'],'completed');self.assertNotIn('return_pct',v)
        self.assertAlmostEqual(v['rate_metrics']['rate_change_5d_bp'],-.5)
        g=review_guidance(v,s)
        self.assertEqual(g['name'],'流动性观察指数');self.assertNotIn('买入',g['headline'])


class ForeignObservationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.now=datetime.fromisoformat(NOW).timestamp()
        self.accounts=AccountStore(Path(tmp.name)/'accounts.db',clock=lambda:self.now)
        self.admin=self.accounts.create_user('owner',PASSWORD,admin=True)
        self.accounts.watchlist(self.admin['id'],'overseas_test','add')
        self.store=self.accounts.reviews

    def test_read_and_foreign_original_validation_are_local_and_frozen(self):
        r=market_report()
        self.now=datetime(2026,10,23,17,tzinfo=CHINA).timestamp()
        initial=copy.deepcopy(r);initial['as_of']='2026-10-23T17:00:00+08:00'
        for s in initial['sector_analysis']:
            if s.get('custom_index'):
                s['custom_index']['history']=[p for p in s['custom_index']['history'] if p['date']<='2026-10-23']
        self.store.capture(initial)
        self.now=datetime.fromisoformat(NOW).timestamp()
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            v=self.store.project(self.admin['id'],r,CONFIG)['items'][0]
        self.assertEqual(v['validation']['status'],'completed')
        self.assertEqual(v['validation']['expected_end'],'2026-10-30')
        self.assertEqual(v['guidance']['status'],'ready')
        r['sector_analysis'][0]['leaders'][0]['price_adjustment']='forward_adjusted'
        v=self.store.project(self.admin['id'],r,CONFIG)['items'][0]
        self.assertEqual(v['validation']['status'],'pending')

    def test_report_from_before_hk_close_does_not_authorize_current_guidance(self):
        r=market_report();r['as_of']='2026-10-30T15:30:00+08:00'
        v=self.store.project(self.admin['id'],r,CONFIG)['items'][0]
        self.assertEqual(v['status'],'completed')
        self.assertIsNone(v['guidance']['recommendation_index'])


class RateFeedbackTests(unittest.TestCase):
    def test_scheduled_wrapper_preserves_rate_units_without_price_return(self):
        from research_personal_ai import enrich_reviewed_report
        store=Mock()
        store.items.return_value=[{'id':'money','status':'completed','period_end':'2026-10-30',
            'review_kind':'rate','rate_metrics':{'annual_rate_pct':1.5,'rate_change_5d_bp':-.5},
            'score':53,'scope':'隔夜Shibor流动性观察','source_ids':['shibor']}]
        store.narrative.return_value=None
        subscriptions=Mock();subscriptions.accounts.reviews=store
        stats={'request_count':0,'requests_attempted':0,'requests_succeeded':0,'usage':{},
               'usage_complete':True,'errors':[],'terminal_error':False}
        captured=[]
        def enrich(report,*args):
            captured.append(copy.deepcopy(report['sector_analysis'][0]['review_feedback']))
            return {**report,'ai_research':copy.deepcopy(stats)}
        with patch('research_review.run_scheduled_reviews',return_value=stats), \
             patch('research_personal_ai.enrich_personal_report',side_effect=enrich), \
             patch('research_sector_ai.provider_json',side_effect=AssertionError('paid request')):
            out=enrich_reviewed_report({'sector_analysis':[{'id':'money'}]},subscriptions=subscriptions)
        self.assertIsNone(captured[0]['return_pct'])
        self.assertEqual(captured[0]['rate_metrics']['rate_change_5d_bp'],-.5)
        self.assertEqual(captured[0]['review_kind'],'rate')
        self.assertNotIn('review_feedback',out['sector_analysis'][0])
        self.assertEqual(out['automatic']['paid_api_call_count'],0)


class ClosedEvidenceRetentionTests(unittest.TestCase):
    def test_reference_failure_keeps_whole_current_pair_and_original_dates(self):
        from research_live_update import retain_reference_closes
        r=market_report();s=r['sector_analysis'][1]
        # The native market needs at least61 source observations for retention.
        key=s['quote']['history_secid']
        r['_quote_histories'][key]['rows']=[{'date':d,'close':100} for d in session_days('HK','2026-10-30',70)]
        s['quote'].update(score_scope='reference_trend',reference_session_completed=True,
            reference_timezone='Asia/Hong_Kong',reference_observed_at=NOW,
            reference_latest_completed_date='2026-10-30',reference_session_end='2026-10-30T16:10:00+08:00')
        matches={};histories={};sources=[]
        self.assertEqual(retain_reference_closes(matches,histories,sources,r,NOW),[s['id']])
        self.assertEqual(matches[s['id']]['as_of'],'2026-10-30')
        self.assertTrue(matches[s['id']]['cache_used'])
        self.assertEqual(len(histories[key]),70)
        self.assertEqual(retain_reference_closes({}, {}, [],r,'2026-11-02T17:00:00+08:00'),[])
        histories[key][0]['close']=999
        self.assertEqual(r['_quote_histories'][key]['rows'][0]['close'],100)

    def test_company_failure_never_retains_a_stale_or_intraday_tick(self):
        from research_live_update import retain_verified_closes
        row={'ts_code':'600000.SH','as_of':'2026-10-30T16:00:00+08:00',
             'quote':{'close':10,'pct_chg':1,'is_intraday':False},'source_ids':[]}
        prior={'sector_leaders':{'test':[row]}}
        def blank():return {'sector_leaders':{'test':[{'ts_code':'600000.SH','quote':{}}]},'sources':[]}
        current=retain_verified_closes(blank(),prior,NOW)
        self.assertTrue(current['sector_leaders']['test'][0]['quote']['retained_close'])
        self.assertEqual(current['sector_leaders']['test'][0]['as_of'],row['as_of'])
        self.assertEqual(retain_verified_closes(blank(),prior,'2026-11-02T17:00:00+08:00')['sector_leaders']['test'][0]['quote'],{})
        row['quote']['is_intraday']=True
        self.assertEqual(retain_verified_closes(blank(),prior,NOW)['sector_leaders']['test'][0]['quote'],{})


if __name__=='__main__':unittest.main()
