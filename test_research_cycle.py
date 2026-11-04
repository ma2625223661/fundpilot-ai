"""Long-wave projection: subscription boundary, evidence dates and zero spend."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from research_accounts import AccountStore
from research_cycle import project_cycle, sector_evidence
from research_data import CHINA
import test_cloud_accounts as http_tests
from test_cloud_accounts import PASSWORD

NOW = datetime(2026, 11, 1, 12, tzinfo=CHINA)


def report(demand=49.4, funding=-7.2):
    url = 'https://www.stats.gov.cn/sj/zxfb/202610/t20261031_1965718.html'
    published = '2026-10-31T09:30:00+08:00'
    return {'as_of':'2026-11-01T11:00:00+08:00',
            'strategy':{'macro_evidence':{'status':'ok', 'published_at':published, 'url':url,
                'values':{'manufacturing':49.3, 'new_orders':demand, 'composite':49.7}}},
            'snapshot':{'sources':[{'id':'macro:nbs_pmi', 'status':'ok', 'as_of':published, 'url':url}]},
            'market_liquidity':{'status':'ok','annual_rate_pct':1.289,'rate_change_20d_bp':funding,
                'as_of':'2026-10-30','source_ids':['shibor']},
            'sector_analysis':[{'id':'sector_memory_chip','title':'存储芯片','status':'ok',
                'score_model':'company_research_v2','score_status':'provisional',
                'confirmed_score':60,'research_score':None,'research_tier':{'label':'待完成评估'},
                'quote':{'as_of':'2026-10-30T15:00:00+08:00'}, 'custom_index':{'ready':True},
                'score_breakdown':{'fundamentals':{'points':30},'trend':{'points':24},'catalysts':{'points':None}},
                'market_risk':{'score':56,'status':'complete'},
                'ai_research':{'private_paid_narrative':'must never appear'}}]}


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.now = NOW.timestamp()
        self.accounts = AccountStore(Path(self.tmp.name)/'accounts.db', clock=lambda:self.now)
        self.admin = self.accounts.create_user('owner',PASSWORD,admin=True)
        self.member = self.accounts.create_user('member',PASSWORD)

    def grant(self):
        self.accounts.subscriptions.manage(self.admin['id'],self.member['id'],'grant',
                                          'long-wave-test-grant',credits=10,days=30)

    def project(self, r=None, user=None):
        return project_cycle(self.accounts,(user or self.admin)['id'],report() if r is None else r)

    def test_subscription_enforced_in_projection(self):
        value=self.project(user=self.member)
        self.assertFalse(value['access']); self.assertNotIn('themes',value); self.assertNotIn('signals',value)
        self.grant();self.assertTrue(self.project(user=self.member)['access'])
        self.accounts.subscriptions.manage(self.admin['id'],self.member['id'],'pause','long-wave-test-pause')
        self.assertFalse(self.project(user=self.member)['access'])

    def test_exhausted_member_keeps_included_feature_until_expired(self):
        self.grant()
        with self.accounts.connection() as db: db.execute('UPDATE ai_subscriptions SET credits=0')
        self.assertTrue(self.project(user=self.member)['access'])
        self.now += 31*86400
        self.assertFalse(self.project(user=self.member)['access'])

    def test_no_spend_unlock_or_watchlist_mutation_and_no_narrative_leak(self):
        self.grant();self.accounts.watchlist(self.member['id'],'sector_memory_chip','add')
        before=self.accounts.subscriptions.ledger(self.member['id']);r=report();original=copy.deepcopy(r)
        for _ in range(3):v=self.project(r,self.member)
        self.assertEqual(v['credit_cost'],0);self.assertEqual(v['themes'][0]['watch_count'],1)
        self.assertEqual(self.accounts.subscriptions.summary(self.member['id'])['credits_remaining'],10)
        self.assertEqual(self.accounts.subscriptions.ledger(self.member['id']),before)
        self.assertEqual(self.accounts.subscriptions.summary(self.member['id'])['unlocked_count'],0)
        self.assertNotIn('must never appear',json.dumps(v));self.assertEqual(r,original)
        self.assertEqual(self.accounts.watchlist(self.member['id']),['sector_memory_chip'])
        self.assertEqual(self.project()['themes'][0]['watch_count'],0)

    def test_current_scenario_never_claims_long_wave_phase(self):
        v=self.project();self.assertEqual(v['current_scenario'],'transition')
        self.assertEqual(v['phase'],'unverified');self.assertEqual(v['coverage'],2)
        self.assertEqual(v['coverage_total'],5)
        self.assertTrue(all(s['value'] is None for s in v['signals'][2:]))
        self.assertFalse(any(k in v for k in ('phase_score','opportunity_probability','bottom_year')))

    def test_all_scenarios_thresholds_and_neutral_band(self):
        for pmi,bp,expected in [(50,-5,'repair'),(50,5,'friction'),(49.9,-5,'transition'),
                                (49.9,5,'pressure'),(50,4.99,'mixed'),(49,-4.99,'mixed'),(49,0,'mixed')]:
            v=self.project(report(pmi,bp));self.assertEqual(v['current_scenario'],expected)
            self.assertEqual(sum(s['active'] for s in v['scenarios']),0 if expected=='mixed' else 1)

    def test_pmi_invalid_future_missing_identity_or_out_of_range(self):
        for key,value in [('published_at','2026-11-02T09:30:00+08:00'),
                          ('published_at','2026-07-01T09:30:00+08:00'),
                          ('url','https://example.com/not-official'),('status','unavailable')]:
            r=report();r['strategy']['macro_evidence'][key]=value
            v=self.project(r);self.assertEqual(v['signals'][0]['status'],'missing')
            self.assertEqual(v['current_scenario'],'unverified')
        r=report();r['strategy']['macro_evidence']['values']['new_orders']=float('nan')
        self.assertEqual(self.project(r)['signals'][0]['status'],'missing')
        r=report();r['snapshot']['sources']=[]
        self.assertEqual(self.project(r)['signals'][0]['status'],'missing')

    def test_funding_stale_future_or_invalid_does_not_form_scenario(self):
        for key,value in [('as_of','2026-10-29'),('as_of','2026-11-02'),('status','error'),
                          ('rate_change_20d_bp',float('inf')),('source_ids',[])]:
            r=report();r['market_liquidity'][key]=value
            v=self.project(r);self.assertEqual(v['signals'][1]['status'],'missing')
            self.assertEqual(v['current_scenario'],'unverified')

    def test_invalid_report_removes_all_current_sector_scores(self):
        for as_of in ['2026-10-20T12:00:00+08:00','2026-11-02T12:00:00+08:00',None]:
            r=report();r['as_of']=as_of;v=self.project(r)
            self.assertEqual(v['status'],'awaiting_report');self.assertEqual(v['coverage'],0)
            self.assertEqual(sum(len(t['sectors']) for t in v['themes']),0)
        self.assertEqual(self.project({})['current_scenario'],'unverified')
        v=project_cycle(self.accounts,self.admin['id'],report(),report_stale=True)
        self.assertEqual(v['status'],'awaiting_report');self.assertEqual(v['coverage'],0)

    def test_partial_score_remains_partial_and_never_promoted(self):
        s=self.project()['themes'][0]['sectors'][0]
        self.assertIsNone(s['score']);self.assertEqual(s['known_score'],60)
        self.assertEqual(s['tier'],'待完成评估');self.assertIsNone(s['catalysts'])
        self.assertEqual([c['state'] for c in s['checks']],['met','met','unknown'])

    def test_stale_quote_wrong_score_model_and_incomplete_event(self):
        s=report()['sector_analysis'][0]
        for field,value in [('status','error'),('score_model','other_model')]:
            changed={**s,field:value};v=sector_evidence(changed,set(),NOW)
            self.assertIsNone(v['known_score']);self.assertIsNone(v['fundamentals'])
        s['quote']['as_of']='2026-10-29T15:00:00+08:00'
        self.assertEqual(sector_evidence(s,set(),NOW)['status'],'pending')
        s=report()['sector_analysis'][0];s.update(score_status='complete',research_score=80)
        self.assertIsNone(sector_evidence(s,set(),NOW)['score'])

    def test_unknown_trading_calendar_does_not_assume_freshness(self):
        self.now=datetime(2027,1,4,12,tzinfo=CHINA).timestamp()
        r=report();r['as_of']='2027-01-04T11:00:00+08:00';r['market_liquidity']['as_of']='2027-01-04'
        self.assertEqual(self.project(r)['signals'][1]['status'],'missing')


class CycleHTTPTests(unittest.TestCase):
    setUp=http_tests.CloudHTTPTests.setUp
    cleanup=http_tests.CloudHTTPTests.cleanup
    request=http_tests.CloudHTTPTests.request
    sign=http_tests.CloudHTTPTests.sign

    def test_http_auth_and_subscription_and_reads_only(self):
        path='/api/me/cycle'
        self.assertEqual(self.request(path)[0],401)
        status,value,_=self.request(path,cookie=self.member_cookie)
        self.assertEqual(status,200);self.assertFalse(value['access']);self.assertNotIn('themes',value)
        self.server.accounts.clock=lambda:NOW.timestamp()
        self.server.auto_engine.status.return_value={'report':report()}
        self.server.auto_engine.reset_mock()
        status,value,_=self.request(path,cookie=self.admin_cookie)
        self.assertEqual(status,200);self.assertTrue(value['access']);self.assertEqual(value['credit_cost'],0)
        self.assertEqual(value['current_scenario'],'transition')
        self.server.auto_engine.status.assert_called_once_with()
        self.server.auto_engine.request_scan.assert_not_called()
        for path in ['/research-cycle.js','/research-cycle.css']:
            self.assertEqual(self.request(path,cookie=self.admin_cookie)[0],200)
        html=self.request('/index.html',cookie=self.admin_cookie)[1].decode()
        self.assertIn('data-view="cycle"',html);self.assertIn('id="cycleBody"',html)


if __name__=='__main__':unittest.main()
