"""Personal choices and public-only schedules, with no live paid requests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_cloud_accounts as http_tests
from research_accounts import AccountStore, AccountError
from research_ai_cache import AIEvidenceCache
from research_ai_cost import AICostGuard
from research_personal_ai import enrich_personal_report
from research_subscriptions import content_identity, select_interpretation
from test_research_sector_ai import evidence, response


CONFIG = {'model':'gpt-6.1-sol', 'key':'isolated-test-key', 'enabled':True,
          'reasoning_effort':'xhigh', 'revision':1,
          'cost_controls':{'daily_request_limit':20, 'daily_token_limit':1000000, 'reuse_enabled':True}}


def variants():
    value = evidence(1)
    value['as_of'] = '2026-11-02T09:20:00+08:00'
    row = value['sector_analysis'][0]
    row.update(ai_reason='PRIVATE_XHIGH', ai_risks=['risk'], ai_invalidation='condition',
               ai_research_status='completed', ai_reasoning_effort='xhigh',
               ai_generated_at=value['as_of'], ai_variant_version=1, evidence_ids=['history:sector_0'])
    row['ai_variants'] = {'medium':{key:copy.deepcopy(val) for key,val in row.items()
                                   if key.startswith('ai_') or key=='evidence_ids'}}
    row['ai_variants']['medium'].update(ai_reason='PRIVATE_MEDIUM', ai_reasoning_effort='medium')
    return value


class PersonalChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AccountStore(Path(self.tmp.name)/'accounts.db')
        self.admin = self.store.create_user('owner',http_tests.PASSWORD,admin=True)
        self.user = self.store.create_user('member',http_tests.PASSWORD)
        self.sub = self.store.subscriptions
        self.sub.manage(self.admin['id'], self.user['id'], 'grant', 'personal-initial-grant', credits=4, days=30)

    def choose(self, effort):
        return self.sub.preference(self.user['id'],effort)

    def test_choice_persists_per_user_without_charge_or_global_change(self):
        before = self.sub.ledger(self.user['id'])
        self.assertIsNone(self.sub.summary(self.user['id'])['preferred_reasoning_effort'])
        for effort in ('medium','xhigh','medium'):
            self.assertEqual(self.choose(effort)['credits_remaining'],4)
        restored = AccountStore(self.store.path).subscriptions
        self.assertEqual(restored.summary(self.user['id'])['preferred_reasoning_effort'],'medium')
        self.assertIsNone(restored.summary(self.admin['id'])['preferred_reasoning_effort'])
        self.assertEqual(restored.ledger(self.user['id']),before)
        for invalid in (None,True,{},'high','ultra'):
            with self.assertRaises(AccountError):self.choose(invalid)

    def test_matching_variant_is_selected_and_others_never_leak(self):
        raw=variants(); saved=copy.deepcopy(raw)
        self.choose('medium')
        projected=self.sub.project_report(raw,self.user['id'])
        text=json.dumps(projected)
        self.assertNotIn('PRIVATE_',text); self.assertNotIn('ai_variants',text)
        access=projected['sector_analysis'][0]['ai_access']
        self.assertEqual((access['cost'],access['reasoning_effort']),(1,'medium'))
        result=self.sub.unlock(self.user['id'],raw,'sector_0',access['content_id'])
        self.assertEqual(result['charged_cost'],1)
        unlocked=self.sub.project_report(raw,self.user['id'])
        self.assertIn('PRIVATE_MEDIUM',json.dumps(unlocked));self.assertNotIn('PRIVATE_XHIGH',json.dumps(unlocked))
        self.assertFalse(self.sub.unlock(self.user['id'],raw,'sector_0',access['content_id'])['charged'])
        self.choose('xhigh')
        with self.assertRaises(AccountError):self.sub.unlock(self.user['id'],raw,'sector_0',access['content_id'])
        selected=self.sub.project_report(raw,self.user['id'])['sector_analysis'][0]
        self.assertEqual(selected['ai_access']['cost'],1.5)
        self.assertEqual(self.sub.unlock(self.user['id'],raw,'sector_0',selected['ai_access']['content_id'])['charged_cost'],1.5)
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],1.5)
        self.choose('medium')
        self.assertEqual(self.sub.project_report(raw,self.user['id'])['sector_analysis'][0]['ai_access']['status'],'unlocked')
        self.assertEqual(raw,saved)

    def test_missing_selected_variant_cannot_unlock_other_depth(self):
        raw=variants();raw['sector_analysis'][0].pop('ai_variants')
        self.choose('medium')
        own=self.sub.project_report(raw,self.user['id'])['sector_analysis'][0]
        self.assertEqual(own['ai_access']['status'],'not_ready')
        self.assertNotIn('PRIVATE_',json.dumps(own))
        with self.assertRaisesRegex(AccountError,'未扣减'):
            self.sub.unlock(self.user['id'],raw,'sector_0',content_identity(raw['sector_analysis'][0]))
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],4)

    def test_legacy_unlock_survives_new_preference_without_repricing(self):
        raw=variants(); row=raw['sector_analysis'][0]
        for key in ('ai_variants','ai_variant_version','ai_reasoning_effort'):row.pop(key)
        identity=content_identity(row)
        self.sub.unlock(self.user['id'],raw,'sector_0',identity)
        self.choose('xhigh')
        projected=self.sub.project_report(raw,self.user['id'])['sector_analysis'][0]
        self.assertEqual(projected['ai_access']['status'],'unlocked')
        self.assertTrue(projected['ai_access']['pricing_legacy'])
        self.assertTrue(projected['ai_access']['preference_pending'])
        self.assertFalse(self.sub.unlock(self.user['id'],raw,'sector_0',identity)['charged'])

    def test_distinct_efforts_keep_distinct_identities_even_if_wording_matches(self):
        raw=variants()['sector_analysis'][0]
        raw['ai_variants']['medium']['ai_reason']=raw['ai_reason']
        self.assertNotEqual(content_identity(select_interpretation(raw,'medium')),content_identity(raw))

    def test_demand_only_includes_enabled_funded_subscribers_and_their_watchlists(self):
        self.choose('medium')
        with self.store.connection() as db:
            db.execute('UPDATE users SET watchlist=? WHERE id=?',(json.dumps(['sector_0','sector_0']),self.user['id']))
        self.assertEqual(self.sub.research_demand(),{'medium':{'sector_0'},'xhigh':set()})
        self.sub.manage(self.admin['id'],self.user['id'],'pause','personal-pause-test')
        self.assertEqual(self.sub.research_demand(),{'medium':set(),'xhigh':set()})


class ScheduledVariantTests(unittest.TestCase):
    def config(self, folder):
        return {**CONFIG, '_evidence_cache':AIEvidenceCache(Path(folder)/'cache.db'),
                '_cost_guard':AICostGuard(Path(folder)/'cost.db'), '_cost_config_provider':lambda:dict(CONFIG)}

    def test_schedule_keeps_public_default_without_enqueuing_personal_variants(self):
        with tempfile.TemporaryDirectory() as folder:
            config=self.config(folder);sub=Mock();sub.research_demand.return_value={'medium':{'sector_1'},'xhigh':set()}
            calls=[]
            def send(report,ids,settings):
                calls.append((list(ids),settings['reasoning_effort']))
                return response(ids)
            with patch('research_sector_ai.provider_json') as real_provider:
                out=enrich_personal_report(evidence(3),config,subscriptions=sub,requester=send,can_start_request=lambda:True)
                second=enrich_personal_report(evidence(3),config,subscriptions=sub,requester=send,can_start_request=lambda:True)
            real_provider.assert_not_called();sub.research_demand.assert_not_called()
            self.assertEqual(calls,[(['sector_0','sector_1','sector_2'],'xhigh')])
            self.assertTrue(all('ai_variants' not in row for row in out['sector_analysis']))
            self.assertEqual(out['ai_research']['request_count'],1)
            self.assertEqual(out['automatic']['paid_api_call_count'],1)
            self.assertEqual(second['ai_research']['request_count'],0)
            self.assertEqual(config['_cost_guard'].summary(config)['request_units'],1.5)

    def test_no_demand_or_outside_schedule_does_not_start_extra_calls(self):
        sub=Mock();sub.research_demand.return_value={'medium':{'sector_0'},'xhigh':set()}
        with patch('research_sector_ai.provider_json') as provider:
            for config,can_start in [({**CONFIG,'enabled':False},True),(CONFIG,False)]:
                send=Mock()
                out=enrich_personal_report(evidence(1),config,subscriptions=sub,requester=send,can_start_request=lambda:can_start)
                send.assert_not_called();self.assertEqual(out['ai_research']['request_count'],0)
        provider.assert_not_called()

    def test_personal_watchlist_demand_is_not_queried_by_the_public_runner(self):
        sub=Mock();sub.research_demand.side_effect=AssertionError('personal work must be explicit')
        calls=[]
        def send(report,ids,config):
            calls.append(config['reasoning_effort'])
            return response(ids)
        out=enrich_personal_report(evidence(1),CONFIG,subscriptions=sub,requester=send,can_start_request=lambda:True)
        self.assertEqual(calls,['xhigh'])
        self.assertEqual(out['sector_analysis'][0]['ai_research_status'],'completed')
        self.assertEqual(out['ai_research']['personal_variants'],[])
        sub.research_demand.assert_not_called()


class PersonalChoiceHTTPTests(unittest.TestCase):
    setUp=http_tests.CloudHTTPTests.setUp
    cleanup=http_tests.CloudHTTPTests.cleanup
    request=http_tests.CloudHTTPTests.request
    sign=http_tests.CloudHTTPTests.sign

    def test_member_choice_is_authenticated_csrf_scoped_and_never_triggers_scan(self):
        endpoint='/api/me/ai-preference';body={'reasoning_effort':'medium'}
        self.assertEqual(self.request(endpoint,body)[0],401)
        self.assertEqual(self.request(endpoint,body,self.member_cookie)[0],403)
        result=self.request(endpoint,body,self.member_cookie,self.member_csrf)
        self.assertEqual(result[0],200)
        self.assertEqual(result[1]['subscription']['preferred_reasoning_effort'],'medium')
        self.assertIsNone(self.request('/api/me/ai-subscription',cookie=self.admin_cookie)[1]['subscription']['preferred_reasoning_effort'])
        self.assertEqual(self.request(endpoint,{**body,'user_id':'forged'},self.member_cookie,self.member_csrf)[0],400)
        self.assertEqual(self.request(endpoint,{'reasoning_effort':'high'},self.member_cookie,self.member_csrf)[0],400)
        self.server.auto_engine.request_scan.assert_not_called()

    def test_selection_refreshes_projection_version_and_prevents_wrong_depth_charge(self):
        raw=variants();self.server.auto_engine.status.return_value={'report':raw,'report_version':'v1'}
        req=lambda path,body=None:self.request(path,body,self.member_cookie,self.member_csrf)
        before=req('/api/auto/report')[1]
        req('/api/me/ai-preference',{'reasoning_effort':'medium'})
        after=req('/api/auto/report')[1]
        self.assertNotEqual(before['report_version'],after['report_version'])
        self.assertNotIn('PRIVATE_',json.dumps(after))
        self.assertEqual(after['report']['sector_analysis'][0]['ai_access']['reasoning_effort'],'medium')
        wrong={'report_id':raw['as_of'],'sector_id':'sector_0','content_id':content_identity(raw['sector_analysis'][0])}
        self.assertEqual(req('/api/me/ai-unlock',wrong)[0],409)
        self.server.auto_engine.request_scan.assert_not_called()


if __name__=='__main__':unittest.main()
