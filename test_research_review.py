"""Isolated review evidence, access and cost controls; no real provider calls."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from research_accounts import AccountStore
from research_ai_cache import AIEvidenceCache
from research_ai_cost import AICostGuard
from research_data import CHINA
from research_review import price_review, sessions, run_scheduled_reviews
from research_review_guidance import review_action
from research_personal_ai import enrich_reviewed_report
import test_cloud_accounts as cloud_tests
from test_cloud_accounts import PASSWORD

CONFIG = {'model':'gpt-6.1-sol','responses_base_url':'https://provider.example/v1',
          'key':'isolated-test-key','enabled':True,'reasoning_effort':'medium',
          'cost_controls':{'daily_request_limit':10,'daily_token_limit':800000,'reuse_enabled':True}}


def sector(identity='sector_test', changes=None):
    days = sessions('2026-10-30', 30)
    changes = changes or [0]*29
    value = 100
    history = [{'date':days[0],'value':value}]
    for day, change in zip(days[1:],changes):
        value *= 1+change
        history.append({'date':day,'value':value})
    constituents = [{'code':'600000.SH','name':'A'},{'code':'000001.SZ','name':'B'}]
    return {'id':identity,'title':identity,'status':'ok','recommendation_index':65,'research_score':65,
            'confirmed_score':65,'score_status':'complete','score_model':'company_research_v2',
            'score_breakdown':{'fundamentals':{'points':30},'trend':{'points':20},'catalysts':{'points':15}},
            'research_tier':{'label':'乐观看待'},'risk':'中风险','market_risk':{'score':55},
            'custom_index':{'id':'leader:'+identity,'ready':True,'constituents':constituents,'history':history,
                            'is_intraday':False,'as_of':'2026-10-30T16:00:00+08:00'},
            'leaders':[{'ts_code':c['code'],'price_adjustment':'forward_adjusted',
                'history':[{'date':r['date'],'close':r['value']} for r in history]} for c in constituents]}


def report(changes=None):
    return {'as_of':'2026-11-01T09:00:00+08:00','research_scope':'sectors',
            'sector_analysis':[sector(changes=changes),sector('index_csi300')]}


def response(evidence,config):
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'reviews':[
        {'id':r['id'],'summary':'依照五日样本表现复核，观察后续证据。','lessons':['区分样本走势与完整研究判断。'],
         'next_checks':['核验下一期样本与风险变化。'],'evidence_ids':[r['source_ids'][0]],
         'action_plan':{'action':r['review_action'],'before_participation':'先观察样本与参考表现，再核验公司证据。',
                        'if_holding':'如已持有，核对原先持有逻辑和既定风控条件。',
                        'upgrade_signals':['五日相对表现改善。'],'risk_signals':['样本回撤继续扩大。']}}
        for r in evidence['reviews']]})}}],
        'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}


class ScoreTests(unittest.TestCase):
    def test_exact_five_intervals_and_flat_score(self):
        a,b=sector(),sector('index_csi300')
        v=price_review(a,b,'2026-10-30')
        self.assertEqual(v['trading_dates'],['2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30'])
        self.assertEqual(v['baseline_date'],'2026-10-23')
        self.assertEqual(len(v['series']),6)
        self.assertEqual(v['score'],62.5)
        self.assertEqual([c['points'] for c in v['components']],[12.5,12.5,25,12.5])

    def test_monotone_positive_and_negative_have_bounded_scores(self):
        a=price_review(sector(changes=[0]*24+[.01]*5),sector('index_csi300'),'2026-10-30')
        b=price_review(sector(changes=[0]*24+[-.01]*5),sector('index_csi300'),'2026-10-30')
        self.assertEqual(a['score'],100)
        self.assertEqual(b['score'],0)
        self.assertAlmostEqual(a['return_pct'],(1.01**5-1)*100,places=3)
        self.assertAlmostEqual(b['drawdown_pct'],(1-.99**5)*100,places=3)

    def test_formula_uses_only_pre_period_volatility(self):
        a=sector(changes=[.01,-.01]*12+[.02,-.01,.03,-.02,.01])
        v=price_review(a,sector('index_csi300'),'2026-10-30')
        import statistics,math
        values=[r['value'] for r in a['custom_index']['history']][-26:]
        sigma=statistics.pstdev([values[i]/values[i-1]-1 for i in range(1,21)])
        ret=values[-1]/values[-6]-1
        expected=25*max(0,min(1,.5+ret/(4*sigma*math.sqrt(5))))
        self.assertEqual(v['components'][0]['points'],round(expected,2))

    def test_missing_or_duplicate_closes_never_zero_fill(self):
        for mutate in ('missing','duplicate','nan','stale'):
            a=sector();h=a['custom_index']['history']
            if mutate=='missing':h.pop(-3)
            elif mutate=='duplicate':h.append(copy.deepcopy(h[-1]))
            elif mutate=='nan':h[-1]['value']=float('nan')
            else:h.pop()
            v=price_review(a,sector('index_csi300'),'2026-10-30')
            self.assertIsNone(v['score'],mutate)
            self.assertEqual(v['status'],'pending')

    def test_missing_reference_is_partial_and_never_rescaled(self):
        v=price_review(sector(),None,'2026-10-30')
        self.assertEqual(v['status'],'partial')
        self.assertIsNone(v['score']);self.assertIsNone(v['components'][1]['points'])

    def test_unknown_calendar_and_non_a_share_are_not_scored(self):
        self.assertEqual(sessions('2027-01-04',26),[])
        a=sector();a['custom_index']['constituents'][0]['code']='AAPL.US'
        self.assertEqual(price_review(a,sector('index_csi300'),'2026-10-30')['status'],'unsupported')
        self.assertIsNone(price_review(sector(),sector('index_csi300'),'2027-01-04')['score'])
        a=sector();a['group']='overseas'
        self.assertEqual(price_review(a,sector('index_csi300'),'2026-10-30')['status'],'unsupported')

    def test_holiday_and_intraday_endpoints(self):
        self.assertEqual(sessions('2026-10-08',2),['2026-09-30','2026-10-08'])
        a=sector();a['custom_index']['is_intraday']=True
        self.assertIsNone(price_review(a,sector('index_csi300'),'2026-10-30')['score'])
        v=price_review(sector(),a,'2026-10-30');self.assertEqual(v['status'],'partial')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=datetime(2026,11,1,9,tzinfo=CHINA).timestamp()
        self.accounts=AccountStore(Path(self.tmp.name)/'accounts.db',clock=lambda:self.now)
        self.admin=self.accounts.create_user('owner',PASSWORD,admin=True)
        self.user=self.accounts.create_user('member',PASSWORD)
        self.sub=self.accounts.subscriptions;self.store=self.accounts.reviews
        self.accounts.watchlist(self.user['id'],'sector_test','add')
        self.grant()
        self.config={**CONFIG,'_cost_guard':AICostGuard(Path(self.tmp.name)/'cost.db',clock=lambda:self.now),
                     '_evidence_cache':AIEvidenceCache(Path(self.tmp.name)/'cache.db',clock=lambda:self.now)}

    def grant(self,credits=10):
        self.sub.manage(self.admin['id'],self.user['id'],'grant','review-test-grant-123',credits=credits,days=30)

    def test_read_is_subscriber_scoped_and_free(self):
        a=self.store.project(self.user['id'],report(),CONFIG)
        self.assertEqual([x['id'] for x in a['items']],['sector_test'])
        self.assertTrue(a['access']);self.assertEqual(a['credit_cost'],0)
        self.assertEqual(self.store.project(self.admin['id'],report(),CONFIG)['status'],'empty')
        before=self.sub.ledger(self.user['id'])
        for _ in range(3):self.store.project(self.user['id'],report(),CONFIG)
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],10)
        self.assertEqual(self.sub.ledger(self.user['id']),before)
        self.sub.manage(self.admin['id'],self.user['id'],'pause','review-test-pause-123')
        locked=self.store.project(self.user['id'],report(),CONFIG)
        self.assertFalse(locked['access']);self.assertEqual(locked['items'],[])

    def test_exhausted_subscriber_keeps_included_review_until_expiry(self):
        with self.accounts.connection() as db:db.execute('UPDATE ai_subscriptions SET credits=0')
        self.assertEqual(self.sub.summary(self.user['id'])['status'],'exhausted')
        self.assertTrue(self.store.project(self.user['id'],report(),CONFIG)['access'])
        self.now+=31*86400
        self.assertFalse(self.store.project(self.user['id'],report(),CONFIG)['access'])

    def test_immutable_observation_and_no_historical_backfill(self):
        r=report();self.store.capture(r)
        r['sector_analysis'][0]['research_score']=99;self.store.capture(r)
        v=self.store.items(r,['sector_test'])[0]['validation']
        self.assertEqual(v['original']['score'],65)
        self.assertEqual(v['completed_sessions'],0)
        self.assertEqual(v['expected_end'],'2026-11-06')
        with self.accounts.connection() as db:count=db.execute('SELECT count(*) FROM review_journal').fetchone()[0]
        self.now+=86400*10;self.store.capture(r)
        with self.accounts.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM review_journal').fetchone()[0],count)

    def test_validation_waits_five_sessions_and_requires_entire_frozen_basket(self):
        self.now=datetime(2026,10,23,17,tzinfo=CHINA).timestamp()
        r=report();r['as_of']='2026-10-23T17:00:00+08:00';self.store.capture(r)
        self.now=datetime(2026,11,1,9,tzinfo=CHINA).timestamp()
        r=report();v=self.store.items(r,['sector_test'])[0]['validation']
        self.assertEqual(v['status'],'completed');self.assertEqual(v['return_pct'],0)
        r['sector_analysis'][0]['leaders'].pop()
        # The same code occurs in the reference fixture too; remove everywhere.
        for s in r['sector_analysis']:s['leaders']=[x for x in s['leaders'] if x['ts_code']!='000001.SZ']
        v=self.store.items(r,['sector_test'])[0]['validation']
        self.assertEqual(v['status'],'pending');self.assertEqual(v['missing_samples'],['000001.SZ'])

    def test_first_complete_decision_is_separate_from_initial_phase_record(self):
        r=report();r['sector_analysis'][0].update(score_status='provisional',research_score=None)
        self.store.capture(r)
        key=self.store.fingerprint(self.store.items(r,['sector_test'])[0],CONFIG)
        r=report();self.store.capture(r)
        v=self.store.items(r,['sector_test'])[0]
        self.assertEqual(v['validation']['original']['score'],65)
        self.assertEqual(key,self.store.fingerprint(v,CONFIG))
        with self.accounts.connection() as db:
            initial=json.loads(db.execute("SELECT payload FROM review_journal WHERE sector_id='sector_test'").fetchone()[0])
        self.assertIsNone(initial['score'])

    def test_mid_session_observation_never_uses_that_days_earlier_return(self):
        self.now=datetime(2026,10,26,14,50,tzinfo=CHINA).timestamp()
        r=report();r['as_of']='2026-10-26T14:50:00+08:00';self.store.capture(r)
        v=self.store.items(r,['sector_test'])[0]['validation']
        self.assertEqual(v['original']['baseline_date'],'2026-10-26')
        self.assertEqual(v['expected_end'],'2026-11-02');self.assertEqual(v['completed_sessions'],0)

    def run_ai(self,requester=None,allowed=None,config=None):
        return run_scheduled_reviews(self.store,report(),config or self.config,lambda:True,allowed or (lambda:True),requester or response)

    def test_no_call_without_schedule_or_guard_and_no_charge(self):
        request=Mock(side_effect=response)
        self.run_ai(request,lambda:False)
        self.run_ai(request,config=CONFIG)
        self.run_ai(request,config={**self.config,'enabled':False})
        request.assert_not_called();self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],10)

    def test_shared_durable_reuse_and_exact_usage(self):
        request=Mock(side_effect=response)
        a=self.run_ai(request);self.assertEqual(a['request_count'],1)
        self.assertEqual(a['usage']['total_tokens'],150);self.assertEqual(a['status'],'completed')
        b=self.run_ai(request);self.assertEqual(b['request_count'],0);self.assertEqual(request.call_count,1)
        v=self.store.project(self.user['id'],report(),CONFIG)['items'][0]
        self.assertEqual(v['ai']['status'],'completed');self.assertEqual(v['ai']['reasoning_effort'],'medium')
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],10)
        self.assertEqual(self.config['_cost_guard'].summary(CONFIG)['requests'],1)

    def test_effort_variants_are_not_repriced_same_text(self):
        request=Mock(side_effect=response);self.run_ai(request)
        self.sub.preference(self.user['id'],'xhigh')
        v=self.store.project(self.user['id'],report(),CONFIG)['items'][0]
        self.assertEqual(v['ai']['status'],'waiting')
        self.run_ai(request);self.assertEqual(request.call_count,2)
        self.assertEqual(request.call_args[0][1]['reasoning_effort'],'xhigh')

    def test_budget_blocks_upstream_without_raising_limits(self):
        request=Mock(side_effect=response)
        cfg={**self.config,'cost_controls':{**CONFIG['cost_controls'],'daily_request_limit':0}}
        stats=self.run_ai(request,config=cfg);request.assert_not_called()
        self.assertEqual(stats['status'],'budget_limited');self.assertEqual(stats['request_count'],0)

    def test_current_risk_caps_do_not_create_extra_paid_review_keys(self):
        request=Mock(side_effect=response)
        self.run_ai(request)
        original=report()
        changed=report()
        changed['sector_analysis'][0]['market_risk']['score']=90
        self.assertEqual(self.store.fingerprint(self.store.items(original,['sector_test'])[0],CONFIG),
                         self.store.fingerprint(self.store.items(changed,['sector_test'])[0],CONFIG))
        stats=run_scheduled_reviews(self.store,changed,self.config,lambda:True,lambda:True,request)
        self.assertEqual(stats['request_count'],0);self.assertEqual(request.call_count,1)
        item=self.store.project(self.user['id'],changed,CONFIG)['items'][0]
        self.assertEqual(item['guidance']['recommendation_index'],29)
        self.assertEqual(item['ai']['plan_status'],'limited')
        self.assertNotIn('action_plan',item['ai'])
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],10)

    def test_current_ai_action_plan_is_saved_and_stale_report_hides_it(self):
        self.run_ai()
        item=self.store.project(self.user['id'],report(),CONFIG)['items'][0]
        self.assertEqual(item['ai']['action_plan']['action'],'observe')
        self.assertEqual(item['ai']['plan_status'],'current')
        stale=self.store.project(self.user['id'],report(),CONFIG,report_stale=True)['items'][0]
        self.assertIsNone(stale['guidance']['recommendation_index'])
        self.assertEqual(stale['ai']['plan_status'],'limited')
        self.assertNotIn('action_plan',stale['ai'])

    def test_provider_cannot_upgrade_plan_or_assign_nested_index(self):
        for field in ('action','recommendation_index'):
            with self.subTest(field=field):
                self.sub.preference(self.user['id'],'medium' if field=='action' else 'xhigh')
                def invalid(evidence,config):
                    value=response(evidence,config)
                    content=json.loads(value['choices'][0]['message']['content'])
                    content['reviews'][0]['action_plan'][field]='track' if field=='action' else 100
                    value['choices'][0]['message']['content']=json.dumps(content)
                    return value
                stats=self.run_ai(invalid)
                self.assertEqual(stats['requests_succeeded'],0)
                self.assertEqual(self.store.project(self.user['id'],report(),CONFIG)['items'][0]['ai']['status'],'waiting')

    def test_invalid_source_or_provider_score_is_rejected_and_cooled_down(self):
        for bad in ('evidence_ids','score'):
            with self.subTest(bad=bad):
                with self.accounts.connection() as db:db.execute('DELETE FROM review_narratives')
                def invalid(evidence,config):
                    value=response(evidence,config);rows=json.loads(value['choices'][0]['message']['content'])
                    rows['reviews'][0][bad]=['invented'] if bad=='evidence_ids' else 99
                    value['choices'][0]['message']['content']=json.dumps(rows);return value
                # Different effort gives an independent attempt fingerprint.
                self.sub.preference(self.user['id'],'medium' if bad=='evidence_ids' else 'xhigh')
                request=Mock(side_effect=invalid);stats=self.run_ai(request)
                self.assertEqual(stats['usage']['total_tokens'],150)
                self.assertEqual(stats['requests_succeeded'],0)
                self.run_ai(request);self.assertEqual(request.call_count,1)

    def test_wrapper_preserves_review_usage_without_real_sector_calls(self):
        meta={'request_count':2,'requests_attempted':2,'requests_succeeded':2,
              'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30},'usage_complete':True,'errors':[]}
        with patch('research_personal_ai.enrich_personal_report',return_value={**report(),'ai_research':meta}):
            out=enrich_reviewed_report(report(),self.config,is_current=lambda:True,can_start_request=lambda:True,
                                        subscriptions=self.sub,review_requester=response)
        self.assertEqual(out['ai_research']['request_count'],3)
        self.assertEqual(out['ai_research']['usage']['total_tokens'],180)
        self.assertEqual(out['automatic']['paid_api_call_count'],3)
        self.assertEqual(out['ai_research']['five_day_review']['request_count'],1)

    def test_terminal_provider_error_stops_other_paid_research(self):
        from research_responses import ProviderError
        def fail(*args):raise ProviderError('invalid key',401)
        def main(report,config,*args):
            self.assertFalse(config['enabled'])
            return {**report,'ai_research':{'request_count':0,'requests_attempted':0,'requests_succeeded':0,
                    'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},'usage_complete':True,'errors':[]}}
        with patch('research_personal_ai.enrich_personal_report',side_effect=main):
            out=enrich_reviewed_report(report(),self.config,is_current=lambda:True,can_start_request=lambda:True,
                                        subscriptions=self.sub,review_requester=fail)
        self.assertTrue(out['ai_research']['terminal_error'])
        self.assertEqual(out['ai_research']['request_count'],1)
        self.assertTrue(out['ai_research']['configuration_enabled'])


class ReviewHTTPTests(unittest.TestCase):
    setUp = cloud_tests.CloudHTTPTests.setUp
    cleanup = cloud_tests.CloudHTTPTests.cleanup
    request = cloud_tests.CloudHTTPTests.request
    sign = cloud_tests.CloudHTTPTests.sign
    def test_review_endpoint_requires_account_and_subscription_without_triggering_ai(self):
        self.assertEqual(self.request('/api/me/reviews')[0],401)
        self.server.auto_engine.status.return_value={'report':report()}
        status,data,_=self.request('/api/me/reviews?user_id=forged',cookie=self.member_cookie)
        self.assertEqual(status,200);self.assertEqual(data['status'],'locked');self.assertEqual(data['items'],[])
        self.server.auto_engine.request_scan.assert_not_called()

    def test_native_reference_reads_internal_histories_without_publishing_them(self):
        from test_review_market_evidence import market_report
        r=market_report()
        user=self.server.accounts.login('owner',PASSWORD)
        self.server.accounts.watchlist(user['id'],'overseas_test','add')
        histories=r.pop('_quote_histories')
        self.server.auto_engine.status.return_value={'report':r}
        self.server.auto_engine.review_histories.return_value=histories
        status,data,_=self.request('/api/me/reviews',cookie=self.admin_cookie)
        self.assertEqual(status,200)
        self.assertEqual(data['items'][0]['status'],'completed')
        self.assertIn('恒生',data['items'][0]['reference_label'])
        self.assertNotIn('_quote_histories',data)
        self.server.auto_engine.request_scan.assert_not_called()


if __name__=='__main__':unittest.main()
