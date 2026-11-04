import concurrent.futures
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_cloud_accounts as accounts_tests
from research_accounts import AccountError, AccountStore
from research_subscriptions import SubscriptionStore, content_identity


def report():
    return {'research_scope':'sectors', 'as_of':'2026-11-01T09:25:00+08:00',
        'summary':'公开研究摘要', 'ai_research':{'status':'completed'},
        'sector_analysis':[{'id':'semiconductor','title':'半导体','score':66,'status':'ok',
            'ai_reason':'PRIVATE_AI_REASON', 'ai_analysis':'PRIVATE_LEGACY_REASON',
            'ai_advice':{'reason':'PRIVATE_ADVICE'}, 'ai_risks':['PRIVATE_RISK'],
            'ai_invalidation':'PRIVATE_CONDITION', 'ai_research_status':'completed',
            'ai_generated_at':'2026-11-01T09:25:00+08:00', 'evidence_ids':['source-1']},
            {'id':'no-ai','title':'待分析','status':'ok','ai_research_status':'error'}]}


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1793500000
        self.store=AccountStore(Path(self.tmp.name)/'accounts.sqlite3', clock=lambda:self.now)
        self.admin=self.store.create_user('owner',accounts_tests.PASSWORD,admin=True)
        self.member=self.store.create_user('member',accounts_tests.PASSWORD)
        self.sub=self.store.subscriptions;self.seq=0

    def manage(self,action='grant',credits=3,days=30,**kwargs):
        self.seq+=1
        return self.sub.manage(self.admin['id'],self.member['id'],action,
            'test-operation-'+str(self.seq).zfill(8),credits=credits,days=days,**kwargs)

    def unlock(self,r=None):
        r=r or report()
        return self.sub.unlock(self.member['id'],r,'semiconductor',content_identity(r['sector_analysis'][0]))

    def test_default_no_subscription_and_admin_not_metered(self):
        self.assertEqual(self.sub.summary(self.member['id'])['status'],'unsubscribed')
        self.assertTrue(self.sub.summary(self.admin['id'])['can_unlock'])
        with self.assertRaises(AccountError):self.unlock()
        self.assertEqual(self.sub.ledger(self.member['id']),[])

    def test_summary_publishes_one_consistent_credit_unit(self):
        for user in (self.member,self.admin):
            summary=self.sub.summary(user['id'])
            self.assertEqual(summary['credit_unit'],'点')
            self.assertEqual(summary['credit_costs'],{'medium':1,'xhigh':1.5})

    @staticmethod
    def priced_report(effort='xhigh', version='morning'):
        value=report()
        value['sector_analysis'][0]['ai_reasoning_effort']=effort
        value['sector_analysis'][0]['ai_generated_at']=version
        return value

    def test_xhigh_uses_precise_half_points_and_repeated_reads_are_free(self):
        self.manage(credits=4)
        value=self.priced_report()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.unlock(value),range(8)))
        self.assertEqual(sum(r['charged_cost'] for r in results),1.5)
        self.assertEqual(sum(r['charged'] for r in results),1)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],2.5)
        charged=[r for r in self.sub.ledger(self.member['id']) if r['kind']=='unlock']
        self.assertEqual([(r['delta'],r['balance']) for r in charged],[(-1.5,2.5)])
        with self.store.connection() as db:
            raw=db.execute('SELECT credits,typeof(credits) FROM ai_subscriptions').fetchone()
            self.assertEqual(tuple(raw),(5,'integer'))
        self.assertFalse(self.unlock(value)['charged'])
        self.assertEqual(self.unlock(value)['charged_cost'],0)

    def test_one_point_cannot_unlock_xhigh_and_no_write_occurs(self):
        self.manage(credits=1)
        value=self.priced_report()
        projected=self.sub.project_report(value,self.member['id'])
        access=projected['sector_analysis'][0]['ai_access']
        self.assertEqual(access['cost'],1.5)
        self.assertEqual(access['reasoning_effort'],'xhigh')
        self.assertFalse(access['pricing_legacy'])
        self.assertFalse(access['can_unlock'])
        self.assertNotIn('PRIVATE_',json.dumps(projected))
        with self.assertRaisesRegex(AccountError,'本份解读需 1.5 点'):
            self.unlock(value)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],1)
        self.assertEqual(len(self.sub.ledger(self.member['id'])),1)
        medium=self.priced_report('medium')
        self.assertTrue(self.sub.project_report(medium,self.member['id'])['sector_analysis'][0]['ai_access']['can_unlock'])
        self.assertEqual(self.unlock(medium)['charged_cost'],1)

    def test_half_point_remainder_is_preserved_and_can_be_topped_up(self):
        self.manage(credits=2)
        self.unlock(self.priced_report())
        summary=self.sub.summary(self.member['id'])
        self.assertEqual(summary['credits_remaining'],0.5)
        self.assertEqual(summary['status'],'exhausted')
        self.assertFalse(summary['can_unlock'])
        self.assertFalse(self.unlock(self.priced_report())['charged'])
        self.assertFalse(self.sub.project_report(report(),self.member['id'])['sector_analysis'][0]['ai_access']['can_unlock'])
        self.manage(credits=0.5,days=0)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],1)
        self.assertEqual(self.unlock(report())['charged_cost'],1)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],0)

    def test_concurrent_distinct_xhigh_reports_cannot_overspend(self):
        self.manage(credits=2.5)
        values=[self.priced_report(version=str(i)) for i in range(8)]
        def unlock(value):
            try:return self.unlock(value)['charged_cost']
            except AccountError:return 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(unlock,values)),1.5)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],1)
        self.assertEqual(self.sub.summary(self.member['id'])['unlocked_count'],1)

    def test_legacy_pricing_identity_and_existing_unlock_are_preserved(self):
        self.manage(credits=3)
        value=report();identity=content_identity(value['sector_analysis'][0])
        old_access=self.sub.project_report(value,self.member['id'])['sector_analysis'][0]['ai_access']
        self.assertEqual(old_access['cost'],1)
        self.assertTrue(old_access['pricing_legacy'])
        self.assertIsNone(old_access['reasoning_effort'])
        self.assertEqual(self.unlock(value)['charged_cost'],1)
        value['sector_analysis'][0]['ai_reasoning_effort']='xhigh'
        self.assertEqual(content_identity(value['sector_analysis'][0]),identity)
        self.assertFalse(self.unlock(value)['charged'])
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],2)
        self.now+=31*86400
        self.assertEqual(self.unlock(value)['charged_cost'],0)
        self.assertIn('PRIVATE_',json.dumps(self.sub.project_report(value,self.member['id'])))
        self.manage('pause',credits=0,days=0)
        with self.assertRaises(AccountError):self.unlock(value)

    def test_unknown_or_malformed_provenance_uses_legacy_price(self):
        self.manage(credits=5)
        for effort in ('high',None,{},True):
            value=self.priced_report(effort,version=str(effort))
            access=self.sub.project_report(value,self.member['id'])['sector_analysis'][0]['ai_access']
            self.assertEqual(access['cost'],1)
            self.assertTrue(access['pricing_legacy'])
            self.assertIsNone(access['reasoning_effort'])

    def legacy_database(self):
        """Build an isolated old-schema state, never touch the service DB."""
        self.manage(credits=400);self.unlock()
        with self.store.connection() as db:
            db.execute('UPDATE ai_subscriptions SET credits=credits/2')
            db.execute('UPDATE ai_subscription_ledger SET delta=delta/2,balance=balance/2')
            db.execute("DELETE FROM ai_subscription_schema WHERE component='credits'")

    def test_v1_migration_preserves_human_balance_history_unlocks_and_restarts(self):
        self.legacy_database()
        for _ in range(3):
            restored=AccountStore(self.store.path,clock=lambda:self.now).subscriptions
            self.assertEqual(restored.summary(self.member['id'])['credits_remaining'],399)
            self.assertEqual([(r['delta'],r['balance']) for r in restored.ledger(self.member['id'])],[(-1,399),(400,400)])
            value=report();value['sector_analysis'][0]['ai_reasoning_effort']='xhigh'
            self.assertFalse(restored.unlock(self.member['id'],value,'semiconductor',content_identity(value['sector_analysis'][0]))['charged'])
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT credits FROM ai_subscriptions').fetchone()[0],798)
                self.assertEqual(db.execute("SELECT version FROM ai_subscription_schema WHERE component='credits'").fetchone()[0],2)

    def test_v1_migration_rolls_back_all_monetary_fields_when_interrupted(self):
        self.legacy_database()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_migration BEFORE UPDATE ON ai_subscription_ledger BEGIN SELECT RAISE(ABORT,'isolated migration interruption'); END")
        with self.assertRaises(sqlite3.IntegrityError):SubscriptionStore(self.store)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT credits FROM ai_subscriptions').fetchone()[0],399)
            self.assertEqual(db.execute("SELECT count(*) FROM ai_subscription_schema WHERE component='credits'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT delta FROM ai_subscription_ledger WHERE kind='unlock'").fetchone()[0],-1)
            db.execute('DROP TRIGGER fail_migration')
        restored=SubscriptionStore(self.store)
        self.assertEqual(restored.summary(self.member['id'])['credits_remaining'],399)

    def test_grant_renew_and_idempotent_retry(self):
        first=self.sub.manage(self.admin['id'],self.member['id'],'grant','same-operation-0001',credits=3,days=30)
        again=self.sub.manage(self.admin['id'],self.member['id'],'grant','same-operation-0001',credits=3,days=30)
        self.assertEqual(first,again);self.assertEqual(len(self.sub.ledger(self.member['id'])),1)
        renewed=self.manage(credits=2,days=10)
        self.assertEqual(renewed['credits_remaining'],5)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT expires FROM ai_subscriptions').fetchone()[0],self.now+40*86400)

    def test_atomic_same_report_unlock_and_cross_device_retries(self):
        self.manage()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.unlock(),range(8)))
        self.assertEqual(sum(r['charged'] for r in results),1)
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],2)
        self.assertEqual(self.sub.summary(self.member['id'])['unlocked_count'],1)
        self.assertEqual(sum(r['kind']=='unlock' for r in self.sub.ledger(self.member['id'])),1)

    def test_last_credit_cannot_be_overspent(self):
        self.manage(credits=1)
        second=report();second['sector_analysis'][0]['ai_generated_at']='2026-11-01T14:50:00+08:00'
        def unlock(r):
            try:return self.unlock(r)['charged']
            except AccountError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(unlock,[report(),second])),1)
        self.assertEqual(self.sub.summary(self.member['id'])['status'],'exhausted')
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],0)

    def test_shared_report_is_redacted_without_mutating_original(self):
        original=report();snapshot=copy.deepcopy(original)
        locked=self.sub.project_report(original,self.member['id'])
        self.assertNotIn('PRIVATE_',json.dumps(locked))
        self.assertEqual(locked['sector_analysis'][0]['score'],66)
        self.assertEqual(locked['sector_analysis'][0]['ai_access']['status'],'locked')
        self.assertEqual(locked['sector_analysis'][1]['ai_access']['status'],'not_ready')
        self.assertEqual(original,snapshot)
        self.assertIs(self.sub.project_report(original,self.admin['id']),original)

    def test_unlock_expiry_reuse_and_pause(self):
        self.manage(credits=1,days=1);self.unlock()
        self.assertIn('PRIVATE_',json.dumps(self.sub.project_report(report(),self.member['id'])))
        self.now+=86401
        self.assertEqual(self.sub.summary(self.member['id'])['status'],'expired')
        self.assertFalse(self.unlock()['charged'])
        self.manage('pause',credits=0,days=0)
        self.assertNotIn('PRIVATE_',json.dumps(self.sub.project_report(report(),self.member['id'])))
        with self.assertRaises(AccountError):self.unlock()
        self.manage('resume',credits=0,days=0)
        self.assertFalse(self.unlock()['charged'])

    def test_failed_or_changed_report_does_not_debit(self):
        self.manage()
        with self.assertRaises(AccountError):self.sub.unlock(self.member['id'],report(),'no-ai','madeup')
        with self.assertRaises(AccountError):self.sub.unlock(self.member['id'],report(),'semiconductor','old-version')
        self.assertEqual(self.sub.summary(self.member['id'])['credits_remaining'],3)
        self.assertEqual(len(self.sub.ledger(self.member['id'])),1)

    def test_member_cannot_grant_and_other_member_cannot_read_unlock(self):
        with self.assertRaises(AccountError) as error:
            self.sub.manage(self.member['id'],self.member['id'],'grant','forged-operation1',credits=100,days=30)
        self.assertEqual(error.exception.status,403)
        self.manage();self.unlock()
        other=self.store.create_user('other',accounts_tests.PASSWORD)
        self.assertNotIn('PRIVATE_',json.dumps(self.sub.project_report(report(),other['id'])))

    def test_subscription_and_usage_survive_restart(self):
        self.manage();self.unlock()
        restored=AccountStore(self.store.path,clock=lambda:self.now)
        self.assertEqual(restored.subscriptions.summary(self.member['id'])['credits_remaining'],2)
        self.assertFalse(restored.subscriptions.unlock(self.member['id'],report(),'semiconductor',content_identity(report()['sector_analysis'][0]))['charged'])

    def test_invalid_grants_fail_without_write(self):
        for credits,days in [(True,30),(-1,30),(100001,30),(1,-1),(1,4000),(0,0),(1,0),
                             (1.25,30),(float('nan'),30),(float('inf'),30),('1.5',30),(None,30)]:
            with self.assertRaises(AccountError):self.manage(credits=credits,days=days)
        self.assertEqual(self.sub.ledger(self.member['id']),[])


class SubscriptionHTTPTests(unittest.TestCase):
    setUp=accounts_tests.CloudHTTPTests.setUp
    cleanup=accounts_tests.CloudHTTPTests.cleanup
    request=accounts_tests.CloudHTTPTests.request
    sign=accounts_tests.CloudHTTPTests.sign

    def test_http_reports_actual_price_and_accepts_fractional_topups(self):
        member=self.server.accounts.login('member',accounts_tests.PASSWORD)
        value=report();value['sector_analysis'][0]['ai_reasoning_effort']='xhigh'
        # Current/global model metadata cannot underprice this stored xhigh report.
        value['ai_research']['reasoning_effort']='medium'
        self.server.auto_engine.status.return_value={'report':value,'report_version':'v1'}
        grant={'user_id':member['id'],'action':'grant','request_id':'fraction-grant-0001','credits':1,'days':30}
        def request(path,body=None,admin=False):
            return self.request(path,body,self.admin_cookie if admin else self.member_cookie,
                self.admin_csrf if admin else self.member_csrf)
        self.assertEqual(request('/api/admin/ai-subscription',grant,True)[0],200)
        before=request('/api/auto/report')[1]['report']['sector_analysis'][0]['ai_access']
        self.assertEqual(before['cost'],1.5);self.assertFalse(before['can_unlock'])
        body={'sector_id':'semiconductor','content_id':before['content_id'],'report_id':value['as_of']}
        self.assertEqual(request('/api/me/ai-unlock',body)[0],403)
        grant.update(request_id='fraction-grant-0002',credits=0.5,days=0)
        self.assertEqual(request('/api/admin/ai-subscription',grant,True)[1]['subscription']['credits_remaining'],1.5)
        status,result,_=request('/api/me/ai-unlock',body)
        self.assertEqual(status,200);self.assertEqual(result['charged_cost'],1.5)
        self.assertEqual(result['subscription']['credits_remaining'],0)
        self.assertEqual(request('/api/me/ai-unlock',body)[1]['charged_cost'],0)
        items=request('/api/me/ai-subscription')[1]['items']
        self.assertEqual(items[0]['delta'],-1.5);self.assertEqual(items[0]['balance'],0)
        self.server.auto_engine.request_scan.assert_not_called()

    def test_subscription_admin_workflow_and_report_boundaries(self):
        member=self.server.accounts.login('member',accounts_tests.PASSWORD)
        original=report();self.server.auto_engine.status.return_value={'report':original,'report_version':'v1'}
        def request(path,body=None,admin=False):
            return self.request(path,body,self.admin_cookie if admin else self.member_cookie,
                self.admin_csrf if admin else self.member_csrf)
        self.assertEqual(request('/api/me/ai-subscription')[1]['subscription']['status'],'unsubscribed')
        grant={'user_id':member['id'],'action':'grant','request_id':'http-grant-0000001','credits':2,'days':30}
        self.assertEqual(request('/api/admin/ai-subscription',grant)[0],403)
        self.assertEqual(request('/api/admin/ai-subscription',grant,True)[0],200)
        for path in ['/api/auto/report','/api/auto/status']:
            status,value,_=request(path);self.assertEqual(status,200)
            self.assertNotIn('PRIVATE_',json.dumps(value))
        request('/api/me/history',{'report_ids':[original['as_of']]})
        from urllib.parse import quote
        history='/api/me/history/report?as_of='+quote(original['as_of'])
        self.assertNotIn('PRIVATE_',json.dumps(request(history)[1]))
        content=content_identity(original['sector_analysis'][0])
        body={'sector_id':'semiconductor','content_id':content,'report_id':original['as_of']}
        result=request('/api/me/ai-unlock',body)
        self.assertEqual(result[0],200);self.assertTrue(result[1]['charged'])
        self.assertIn('PRIVATE_',json.dumps(result[1]['sector']))
        self.assertFalse(request('/api/me/ai-unlock',body)[1]['charged'])
        self.assertIn('PRIVATE_',json.dumps(request(history)[1]))
        self.assertEqual(request('/api/me/ai-subscription')[1]['subscription']['credits_remaining'],1)
        self.assertEqual(original,report())
        self.server.auto_engine.request_scan.assert_not_called()

    def test_csrf_anonymous_and_forged_account(self):
        self.assertEqual(self.request('/api/me/ai-subscription')[0],401)
        self.assertEqual(self.request('/api/me/ai-unlock',{},self.member_cookie)[0],403)
        self.assertEqual(self.request('/api/admin/ai-subscription',{},self.admin_cookie)[0],403)
        body={'user_id':'forged','sector_id':'x','content_id':'x','report_id':'x'}
        self.assertEqual(self.request('/api/me/ai-unlock',body,self.member_cookie,self.member_csrf)[0],400)


if __name__=='__main__':unittest.main()
