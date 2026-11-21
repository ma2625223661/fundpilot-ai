"""Manual research integration; every model response is a local fixture."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

import test_cloud_accounts as http_tests
from research_accounts import AccountError, AccountStore
from research_ai_cache import AIEvidenceCache
from research_ai_cost import AICostGuard
from research_ai_config import AIConfigStore
from research_manual_ai import ManualSectorResearch
from research_subscriptions import content_identity
from test_personal_ai_choice import CONFIG, variants
from test_research_sector_ai import evidence, response


def detailed_advice(sector_id):
    refs=['history:'+sector_id]
    return {'schema_version':2,'scope':'reference','action':'reference',
            'reason':'仅观察参考走势，并核验公司证据。','watch_points':['观察后续走势。'],
            'evidence_chain':[{'fact':'近期走势记录已提供。','interpretation':'证据仅支持参考观察。','evidence_ids':refs}],
            'action_plan':[{'trigger':'下一次行情更新。','step':'重新核验走势与风险。','evidence_ids':refs}],
            'scenarios':[{'condition':'后续走势转弱。','response':'降低参考优先级并重新核验。','evidence_ids':refs}],
            'review_conditions':['后续走势或数据来源发生变化时复核。']}


def detailed_response(report,ids,config):
    def details(rows):
        for row in rows:
            row.update(reason='manual '+config['reasoning_effort'],advice=detailed_advice(row['id']))
    return response(ids,invalid=details)


class ManualResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.accounts = AccountStore(Path(self.tmp.name)/'accounts.db')
        self.admin = self.accounts.create_user('owner',http_tests.PASSWORD,admin=True)
        self.user = self.accounts.create_user('member',http_tests.PASSWORD)
        self.other = self.accounts.create_user('another',http_tests.PASSWORD)
        self.sub = self.accounts.subscriptions
        self.sub.manage(self.admin['id'],self.user['id'],'grant','manual-initial-grant',credits=5,days=30)
        self.sub.manage(self.admin['id'],self.user['id'],'limits','manual-initial-grant-calls',daily_limit=100,monthly_limit=1000)
        self.config = copy.deepcopy(CONFIG)
        self.report = evidence(2); self.report['as_of'] = '2026-11-02T19:55:00+08:00'
        self.report_stale = False
        self.engine = Mock(); self.engine._lock = threading.RLock()
        self.engine.status.side_effect = lambda **kwargs:{'report':copy.deepcopy(self.report),'report_stale':self.report_stale}
        self.engine._ai_cost_guard = AICostGuard(Path(self.tmp.name)/'cost.db')
        self.engine._ai_evidence_cache = AIEvidenceCache(Path(self.tmp.name)/'cache.db')
        self.calls = []
        def send(report, ids, config):
            self.calls.append((list(ids),config['reasoning_effort']))
            return detailed_response(report,ids,config)
        self.send = send
        self.jobs = ManualSectorResearch(self.accounts,lambda:self.engine,lambda:self.config,requester=send)
        self.addCleanup(self.finish)

    def finish(self):
        for worker in list(self.jobs._workers):
            worker.join(timeout=5)

    def run_job(self, effort='medium', sector_id='sector_0'):
        with patch('research_sector_ai.provider_json') as provider:
            started=self.jobs.start(self.user['id'],sector_id,self.report['as_of'],effort)
            self.finish()
            result=self.jobs.status(self.user['id'],started['job_id'])
        provider.assert_not_called()
        return result

    def connection_store(self, probe):
        store=AIConfigStore(Path(self.tmp.name)/'manual-connect.json',encrypt=lambda data:data,decrypt=lambda data:data,probe=probe)
        store.configure(key='isolated-test-key',model='gpt-6.1-sol',enabled=True,
                        responses_base_url='https://fixture.example/v1')
        self.jobs.config_provider=store.snapshot
        self.jobs.connection_checker=store.connect_for_research
        self.jobs.configuration_lock=store._lock
        return store

    def test_explicit_depth_charges_once_and_persists_refresh_and_restart(self):
        original=copy.deepcopy(self.report)
        result=self.run_job()
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual((result['charged'],result['charged_cost']),(True,1))
        self.assertEqual(result['sector']['ai_reasoning_effort'],'medium')
        self.assertEqual(result['sector']['ai_access']['status'],'unlocked')
        self.assertEqual(result['subscription']['credits_remaining'],4)
        self.assertEqual(result['subscription']['credits_reserved'],0)
        projected=self.sub.project_report(self.jobs.overlay(self.report),self.user['id'])
        self.assertEqual(projected['sector_analysis'][0]['ai_reason'],'manual medium')
        self.jobs=ManualSectorResearch(self.accounts,lambda:self.engine,lambda:self.config,requester=self.send)
        again=self.run_job()
        self.assertFalse(again['charged']);self.assertEqual(again['charged_cost'],0)
        self.assertEqual(self.calls,[(['sector_0'],'medium')])
        deep=self.run_job('xhigh')
        self.assertEqual(deep['charged_cost'],1.5)
        self.assertEqual(deep['subscription']['credits_remaining'],2.5)
        self.assertEqual(deep['sector']['ai_reasoning_effort'],'xhigh')
        self.assertEqual(self.report,original)
        usage=self.engine._ai_cost_guard.summary(self.config)
        self.assertEqual((usage['requests'],usage['request_units']),(2,2.5))

    def test_completed_research_is_in_personal_history_with_timestamp_after_restart_and_report_change(self):
        result=self.run_job('xhigh')
        self.assertTrue(result['saved'])
        report_id=self.report['as_of']
        generated_at=result['sector']['ai_generated_at']
        self.assertTrue(generated_at)
        self.assertEqual([row['as_of'] for row in self.accounts.history(self.user['id'])],[report_id])
        self.assertEqual(self.accounts.history(self.other['id']),[])
        with self.assertRaises(AccountError):self.accounts.historical_report(self.other['id'],report_id)
        self.report['as_of']='2026-11-02T20:00:00+08:00'
        self.config['revision']+=1
        reopened=AccountStore(self.accounts.path)
        jobs=ManualSectorResearch(reopened,lambda:self.engine,lambda:self.config,requester=Mock())
        archived=reopened.historical_report(self.user['id'],report_id)
        historical=reopened.subscriptions.project_report(jobs.overlay(archived,historical=True),self.user['id'])
        sector=historical['sector_analysis'][0]
        self.assertEqual(sector['ai_generated_at'],generated_at)
        self.assertEqual(sector['ai_reason'],'manual xhigh')
        self.assertEqual(sector['ai_advice']['schema_version'],2)
        self.assertEqual(sector['ai_access']['status'],'unlocked')
        jobs.requester.assert_not_called()

    def test_personal_saved_history_survives_other_users_new_configuration_and_same_id_evidence(self):
        first=self.run_job()
        original_id=self.report['as_of']
        original_score=self.report['sector_analysis'][0]['score']
        original_content=content_identity(first['sector'])
        self.sub.manage(self.admin['id'],self.other['id'],'grant','history-other-grant',credits=5,days=30)
        self.sub.manage(self.admin['id'],self.other['id'],'limits','history-other-grant-calls',daily_limit=100,monthly_limit=1000)
        self.config['revision']+=1
        self.config['responses_base_url']='https://different-fixture.example/v1'
        self.report['sector_analysis'][0]['score']=0
        def changed_response(report,ids,config):
            value=detailed_response(report,ids,config)
            parsed=json.loads(value['choices'][0]['message']['content'])
            for row in parsed['sectors']:row['reason']='new separate medium'
            value['choices'][0]['message']['content']=json.dumps(parsed)
            return value
        self.jobs.requester=changed_response
        started=self.jobs.start(self.other['id'],'sector_0',original_id,'medium')
        self.finish();second=self.jobs.status(self.other['id'],started['job_id'])
        self.assertEqual(second['status'],'completed',second)
        self.assertNotEqual(content_identity(second['sector']),original_content)
        for user,expected_score,expected_reason in ((self.user,original_score,'manual medium'),
                                                   (self.other,0,'new separate medium')):
            # Browser history synchronizations retain the personal snapshot.
            self.accounts.history(user['id'],[original_id])
            archived=self.accounts.historical_report(user['id'],original_id)
            projected=self.sub.project_report(self.jobs.overlay(archived,historical=True,user_id=user['id']),user['id'])
            sector=projected['sector_analysis'][0]
            self.assertEqual(sector['score'],expected_score)
            self.assertEqual(sector['ai_reason'],expected_reason)
            self.assertEqual(sector['ai_access']['status'],'unlocked')
            self.assertEqual(self.sub.summary(user['id'])['credits_remaining'],4)
        self.accounts.history(self.user['id'],[])
        with self.assertRaises(AccountError):self.accounts.historical_report(self.user['id'],original_id)
        with self.accounts.connection() as db:
            self.assertFalse(db.execute('SELECT 1 FROM records WHERE user_id=?',(self.user['id'],)).fetchone())

    def test_historical_overlay_without_personal_snapshot_prefers_the_users_owned_configuration(self):
        first=self.run_job()
        original_report=copy.deepcopy(self.report)
        self.sub.manage(self.admin['id'],self.other['id'],'grant','legacy-history-other',credits=5,days=30)
        self.sub.manage(self.admin['id'],self.other['id'],'limits','legacy-history-other-calls',daily_limit=100,monthly_limit=1000)
        self.config['revision']+=1
        self.config['responses_base_url']='https://separate-fixture.example/v1'
        def changed_response(report,ids,config):
            value=detailed_response(report,ids,config)
            value['choices'][0]['message']['content']=value['choices'][0]['message']['content'].replace('manual medium','new separate medium')
            return value
        self.jobs.requester=changed_response
        started=self.jobs.start(self.other['id'],'sector_0',self.report['as_of'],'medium')
        self.finish()
        self.assertEqual(self.jobs.status(self.other['id'],started['job_id'])['status'],'completed')
        # Legacy records use the shared evidence archive without a personal payload.
        first_projection=self.sub.project_report(self.jobs.overlay(original_report,historical=True,user_id=self.user['id']),self.user['id'])
        self.assertEqual(first_projection['sector_analysis'][0]['ai_reason'],'manual medium')
        self.assertEqual(first_projection['sector_analysis'][0]['ai_access']['status'],'unlocked')
        self.assertEqual(first_projection['sector_analysis'][0]['ai_access']['content_id'],content_identity(first['sector']))
        admin_projection=self.jobs.overlay(original_report,historical=True,user_id=self.admin['id'])
        self.assertEqual(self.sub.project_report(admin_projection,self.admin['id'],reasoning_effort='medium')['sector_analysis'][0]['ai_reason'],'new separate medium')

    def test_admin_personal_snapshot_freezes_original_text_and_generation_time(self):
        started=self.jobs.start(self.admin['id'],'sector_0',self.report['as_of'],'medium')
        self.finish();first=self.jobs.status(self.admin['id'],started['job_id'])
        self.assertEqual(first['status'],'completed',first)
        original_time=first['sector']['ai_generated_at']
        self.sub.manage(self.admin['id'],self.other['id'],'grant','admin-history-other',credits=5,days=30)
        self.sub.manage(self.admin['id'],self.other['id'],'limits','admin-history-other-calls',daily_limit=100,monthly_limit=1000)
        self.config['revision']+=1
        self.config['responses_base_url']='https://admin-history-fixture.example/v1'
        def different(report,ids,config):
            value=detailed_response(report,ids,config)
            value['choices'][0]['message']['content']=value['choices'][0]['message']['content'].replace('manual medium','other later text')
            return value
        self.jobs.requester=different
        started=self.jobs.start(self.other['id'],'sector_0',self.report['as_of'],'medium')
        self.finish();self.assertEqual(self.jobs.status(self.other['id'],started['job_id'])['status'],'completed')
        archived=self.accounts.historical_report(self.admin['id'],self.report['as_of'])
        replay=self.jobs.overlay(archived,historical=True,user_id=self.admin['id'])
        self.assertNotIn('_personal_record_snapshot',replay)
        sector=self.sub.project_report(replay,self.admin['id'])['sector_analysis'][0]
        self.assertEqual(sector['ai_reason'],'manual medium')
        self.assertEqual(sector['ai_generated_at'],original_time)

    def test_history_save_failure_rolls_back_points_unlock_and_narrative(self):
        with patch.object(self.accounts,'_remember_report',side_effect=AccountError('fixture archive failure',503)):
            result=self.run_job()
        self.assertEqual(result['status'],'failed',result)
        self.assertFalse(result['charged'])
        self.assertEqual(result['subscription']['credits_remaining'],5)
        self.assertEqual(result['subscription']['credits_reserved'],0)
        self.assertEqual(self.accounts.history(self.user['id']),[])
        with self.accounts.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ai_manual_narratives').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM ai_unlocks').fetchone()[0],0)

    def test_archived_narrative_survives_short_job_retention_and_same_id_evidence_revision(self):
        first=self.run_job()
        original_report_id=self.report['as_of']
        # Existing current report archives may have been made before the result.
        self.report['sector_analysis'][0]['score']=0
        revised=self.run_job()
        self.assertEqual(revised['status'],'completed',revised)
        archived=self.accounts.historical_report(self.user['id'],original_report_id)
        self.assertEqual(archived['sector_analysis'][0]['score'],0)
        replay=self.sub.project_report(self.jobs.overlay(archived,historical=True),self.user['id'])
        self.assertEqual(replay['sector_analysis'][0]['ai_advice']['schema_version'],2)
        now=self.accounts.clock()
        self.accounts.clock=lambda:now+8*86400
        self.report['as_of']='2026-11-02T20:00:00+08:00'
        later=self.run_job()
        self.assertEqual(later['status'],'completed',later)
        with self.accounts.connection() as db:
            self.assertFalse(db.execute('SELECT 1 FROM ai_manual_jobs WHERE id=?',(first['job_id'],)).fetchone())
            self.assertTrue(db.execute('SELECT 1 FROM ai_manual_narratives WHERE report_id=?',(original_report_id,)).fetchone())
        archived=self.accounts.historical_report(self.user['id'],original_report_id)
        replay=self.sub.project_report(self.jobs.overlay(archived,historical=True),self.user['id'])
        self.assertEqual(replay['sector_analysis'][0]['ai_access']['status'],'unlocked')

    def test_get_and_report_projection_never_request_ai(self):
        for _ in range(3):
            self.jobs.pending(self.user['id']); self.jobs.overlay(self.report)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.jobs.pending(self.user['id']),{'jobs':[]})

    def test_public_completed_same_depth_is_reused_with_no_provider_request(self):
        self.report=variants(); self.report['ai_research']={'revision':CONFIG['revision']}
        self.report['sector_analysis'][0]['ai_advice']=detailed_advice('sector_0')
        self.report['sector_analysis'][0]['ai_variants']['medium']['ai_advice']=detailed_advice('sector_0')
        result=self.run_job('xhigh')
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['reused']);self.assertEqual(result['charged_cost'],1.5)
        self.assertEqual(self.calls,[])
        self.assertFalse(self.run_job('xhigh')['charged'])

    def test_eligibility_authentication_budget_and_invalid_parameters_block_calls(self):
        for effort in ('high',None,{},True):
            with self.assertRaises(AccountError):
                self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],effort)
        with self.assertRaises(AccountError):
            self.jobs.start(self.other['id'],'sector_0',self.report['as_of'],'medium')
        with self.assertRaises(AccountError):
            self.jobs.start(self.user['id'],'sector_0','old-report','medium')
        self.report['sector_analysis'][0].update(status='missing',leaders=[],quote={},metrics={})
        with self.assertRaises(AccountError):
            self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertEqual(self.calls,[])
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],5)

    def test_failure_releases_reservation_and_never_debits(self):
        self.jobs.requester=Mock(side_effect=TimeoutError('fixture-only'))
        result=self.run_job('xhigh')
        self.assertEqual(result['status'],'failed',result)
        self.assertEqual((result['charged'],result['charged_cost']),(False,0))
        self.assertEqual(result['subscription']['credits_remaining'],5)
        self.assertEqual(result['subscription']['credits_reserved'],0)
        self.assertNotIn('ai_variants',self.jobs.overlay(self.report)['sector_analysis'][0])
        self.assertEqual(len([row for row in self.sub.ledger(self.user['id']) if row['kind']=='unlock']),0)

    def test_duplicate_clicks_use_one_job_and_reserve_balance_against_other_unlocks(self):
        self.sub.manage(self.admin['id'],self.user['id'],'grant','manual-extra-grant',credits=0,days=1)
        self.sub.manage(self.admin['id'],self.user['id'],'limits','manual-extra-grant-calls',daily_limit=100,monthly_limit=1000)
        with self.accounts.connection() as db:
            db.execute('UPDATE ai_subscriptions SET credits=3 WHERE user_id=?',(self.user['id'],))
        entered,release=threading.Event(),threading.Event()
        def send(report,ids,config):
            entered.set();release.wait(timeout=5)
            return self.send(report,ids,config)
        self.jobs.requester=send
        started=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'xhigh')
        self.assertTrue(entered.wait(timeout=2))
        try:
            duplicate=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'xhigh')
            self.assertEqual(duplicate['job_id'],started['job_id'])
            self.assertEqual(self.jobs.pending(self.user['id'])['jobs'][0]['job_id'],started['job_id'])
            self.assertEqual(self.sub.summary(self.user['id'])['credits_reserved'],1.5)
            raw=variants();self.sub.preference(self.user['id'],'xhigh')
            with self.assertRaises(AccountError):
                self.sub.unlock(self.user['id'],raw,'sector_0',content_identity(raw['sector_analysis'][0]))
            with self.assertRaises(AccountError):
                self.jobs.start(self.user['id'],'sector_1',self.report['as_of'],'medium')
            with self.assertRaises(AccountError):
                self.jobs.status(self.other['id'],started['job_id'])
        finally:
            release.set();self.finish()
        final=self.jobs.status(self.user['id'],started['job_id'])
        self.assertEqual(final['status'],'completed',final)
        self.assertEqual(final['subscription']['credits_remaining'],0)
        self.assertEqual(self.calls,[(['sector_0'],'xhigh')])

    def test_model_change_or_subscription_pause_during_generation_does_not_debit(self):
        entered,release=threading.Event(),threading.Event()
        def send(report,ids,config):
            entered.set();release.wait(timeout=5)
            return response(ids)
        self.jobs.requester=send
        started=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertTrue(entered.wait(timeout=2))
        self.sub.manage(self.admin['id'],self.user['id'],'pause','manual-pause-during')
        release.set();self.finish()
        result=self.jobs.status(self.user['id'],started['job_id'])
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['charged'])
        self.assertEqual(result['subscription']['credits_remaining'],5)

    def test_global_provider_budget_blocks_manual_calls_without_spending_member_points(self):
        self.config['cost_controls']['daily_request_limit']=0
        result=self.run_job('medium')
        self.assertEqual(result['status'],'failed',result)
        self.assertEqual(self.calls,[])
        self.assertFalse(result['charged'])
        self.assertEqual(result['subscription']['credits_reserved'],0)
        self.assertEqual(result['subscription']['credits_remaining'],5)

    def test_configuration_change_discards_inflight_result_and_hidden_variant(self):
        entered,release=threading.Event(),threading.Event()
        def send(report,ids,config):
            entered.set();release.wait(timeout=5)
            return response(ids)
        self.jobs.requester=send
        started=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertTrue(entered.wait(timeout=2))
        self.config['revision']+=1
        release.set();self.finish()
        result=self.jobs.status(self.user['id'],started['job_id'])
        self.assertEqual(result['status'],'failed',result)
        self.assertFalse(result['charged'])
        self.assertEqual(result['subscription']['credits_reserved'],0)
        self.assertEqual(result['subscription']['credits_remaining'],5)
        self.assertNotIn('ai_variants',self.jobs.overlay(self.report)['sector_analysis'][0])

    def test_top_level_stale_report_blocks_start_even_when_inner_report_claims_fresh(self):
        self.report_stale = True
        self.report['report_stale'] = False
        with self.assertRaises(AccountError) as caught:
            self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.jobs.pending(self.user['id']),{'jobs':[]})
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],5)

    def test_unverified_real_configuration_snapshot_returns_503_without_model_call(self):
        store = AIConfigStore(Path(self.tmp.name)/'unverified.json',encrypt=lambda data:data,decrypt=lambda data:data)
        store.configure(key='isolated-test-key',model='gpt-6.1-sol',enabled=True,
                        responses_base_url='https://fixture.example/v1')
        self.assertEqual(store.status()['verification'],'unverified')
        self.assertTrue(store.status()['enabled'])
        self.assertFalse(store.snapshot()['enabled'])
        self.jobs.config_provider = store.snapshot
        with self.assertRaises(AccountError) as caught:
            self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'],5)

    def test_authorized_click_connects_then_generates_without_changing_admin_preference(self):
        probe=Mock(return_value={'models':['gpt-6.1-sol']})
        store=self.connection_store(probe)
        revision=store.status()['revision']
        result=self.run_job('xhigh')
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['charged_cost'],1.5)
        self.assertEqual(probe.call_count,1)
        self.assertEqual(store.status()['revision'],revision)
        self.assertTrue(store.status()['enabled'])
        self.assertTrue(store.snapshot()['enabled'])
        self.assertEqual(result['sector']['ai_advice']['schema_version'],2)

    def test_connection_failure_has_no_generation_no_debit_and_polling_never_rechecks(self):
        probe=Mock(side_effect=RuntimeError('isolated fixture failure'))
        store=self.connection_store(probe)
        original=store.status()['revision']
        failed=self.run_job()
        self.assertEqual(failed['status'],'failed',failed)
        for _ in range(3):self.jobs.status(self.user['id'],failed['job_id'])
        self.assertEqual(probe.call_count,1)
        self.assertEqual(self.calls,[])
        self.assertEqual(failed['subscription']['credits_remaining'],5)
        self.assertEqual(failed['subscription']['credits_reserved'],0)
        self.assertTrue(store.status()['enabled'])
        self.assertEqual(store.status()['revision'],original)
        retry=self.run_job()
        self.assertEqual(retry['status'],'failed',retry)
        self.assertEqual(probe.call_count,1)

    def test_membership_and_admin_disable_are_checked_before_connection_network(self):
        probe=Mock(return_value={'models':['gpt-6.1-sol']})
        store=self.connection_store(probe)
        for user_id in (self.other['id'],):
            with self.assertRaises(AccountError):
                self.jobs.start(user_id,'sector_0',self.report['as_of'],'medium')
        self.sub.manage(self.admin['id'],self.user['id'],'pause','connection-pause')
        with self.assertRaises(AccountError):
            self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.sub.manage(self.admin['id'],self.user['id'],'resume','connection-resume')
        with self.accounts.connection() as db:
            db.execute('UPDATE ai_subscriptions SET credits=1 WHERE user_id=?',(self.user['id'],))
        with self.assertRaises(AccountError):
            self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        store.configure(enabled=False)
        with self.assertRaises(AccountError):
            self.jobs.start(self.admin['id'],'sector_0',self.report['as_of'],'medium')
        probe.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_new_manual_request_does_not_charge_for_or_reuse_incomplete_legacy_advice(self):
        self.report=variants();self.report['ai_research']={'revision':CONFIG['revision']}
        result=self.run_job('xhigh')
        self.assertEqual(result['status'],'completed',result)
        self.assertFalse(result['reused'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(result['sector']['ai_advice']['schema_version'],2)
        self.report['sector_analysis'][0]['score']=0
        self.jobs.requester=lambda report,ids,config:response(ids)
        failed=self.run_job('medium')
        self.assertEqual(failed['status'],'failed',failed)
        self.assertFalse(failed['charged'])
        self.assertEqual(failed['subscription']['credits_remaining'],3.5)

    def test_configuration_disable_cannot_land_between_final_validation_and_commit(self):
        store=self.connection_store(Mock(return_value={'models':['gpt-6.1-sol']}))
        store.verify()
        validation,release_validation,configuration_finished=(threading.Event() for _ in range(3))
        original=self.jobs._evidence_current
        def held_validation(*args,**kwargs):
            if threading.current_thread().name=='manual-sector-ai':
                with self.accounts.connection() as db:
                    reserved=db.execute("SELECT COUNT(*) FROM ai_manual_jobs WHERE status='running'").fetchone()[0]
                # The settlement call holds both guards and a write transaction.
                if reserved and self.jobs.configuration_lock._is_owned():
                    validation.set();release_validation.wait(timeout=3)
            return original(*args,**kwargs)
        self.jobs._evidence_current=held_validation
        started=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertTrue(validation.wait(2))
        def disable():
            store.configure(enabled=False);configuration_finished.set()
        changer=threading.Thread(target=disable);changer.start()
        try:
            self.assertFalse(configuration_finished.wait(.1))
        finally:
            release_validation.set();self.finish();changer.join(timeout=3)
        self.assertTrue(configuration_finished.is_set())
        result=self.jobs.status(self.user['id'],started['job_id'])
        # This change necessarily linearizes after the completed transaction;
        # therefore its old result is historical, with truthful payment facts.
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['charged'])
        self.assertTrue(result['stale'])
        self.assertEqual(result['subscription']['credits_remaining'],4)

    def test_configuration_disabled_before_final_guard_discards_without_debit(self):
        store=self.connection_store(Mock(return_value={'models':['gpt-6.1-sol']}))
        store.verify()
        entered,release=threading.Event(),threading.Event()
        def send(report,ids,config):
            entered.set();release.wait(timeout=3)
            return detailed_response(report,ids,config)
        self.jobs.requester=send
        started=self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
        self.assertTrue(entered.wait(2))
        store.configure(enabled=False)
        release.set();self.finish()
        result=self.jobs.status(self.user['id'],started['job_id'])
        self.assertEqual(result['status'],'failed',result)
        self.assertFalse(result['charged'])
        self.assertEqual(result['subscription']['credits_remaining'],5)
        self.assertEqual(result['subscription']['credits_reserved'],0)

    def test_report_replacement_changed_evidence_and_expiry_discard_inflight_results(self):
        baseline = copy.deepcopy(self.report)
        changes = ('report_id','evidence','expiry','source')
        for change in changes:
            with self.subTest(change=change):
                self.report = copy.deepcopy(baseline)
                self.report_stale = False
                # Each fresh fixture gets an independent evidence-cache key;
                # the earlier provider attempt must not mask this admission.
                self.report['sector_analysis'][0]['score'] = 50+changes.index(change)
                entered,release = threading.Event(),threading.Event()
                def send(report,ids,config):
                    entered.set();release.wait(timeout=5)
                    return response(ids)
                self.jobs.requester = send
                started = self.jobs.start(self.user['id'],'sector_0',self.report['as_of'],'medium')
                self.assertTrue(entered.wait(timeout=2))
                try:
                    if change=='report_id':self.report['as_of']='2026-11-02T20:00:00+08:00'
                    elif change=='evidence':self.report['sector_analysis'][0]['score']=0
                    elif change=='expiry':self.report_stale=True
                    else:self.report['snapshot']['sources']=[]
                finally:
                    release.set();self.finish()
                result = self.jobs.status(self.user['id'],started['job_id'])
                self.assertEqual(result['status'],'failed',result)
                self.assertFalse(result['charged'])
                self.assertEqual(result['subscription']['credits_remaining'],5)
                self.assertEqual(result['subscription']['credits_reserved'],0)
                self.assertNotIn('ai_variants',self.jobs.overlay(self.report)['sector_analysis'][0])

    def test_same_report_id_changed_evidence_hides_old_overlay_and_generates_new_result(self):
        first = self.run_job()
        old_identity = content_identity(first['sector'])
        self.report['sector_analysis'][0]['score']=0
        hidden = self.jobs.overlay(self.report)['sector_analysis'][0]
        self.assertNotIn('ai_reason',hidden)
        self.assertNotIn('ai_variants',hidden)
        result = self.run_job()
        self.assertEqual(result['status'],'completed',result)
        self.assertFalse(result['reused'])
        self.assertEqual(len(self.calls),2)
        # Fixed timestamps and identical fixture text may preserve content ID;
        # a fresh request is still required for the changed evidence.
        self.assertIsNotNone(old_identity)

    def test_completed_job_expiry_preserves_payment_facts_but_cannot_reapply_old_result(self):
        completed = self.run_job()
        self.assertTrue(completed['applicable'])
        self.assertFalse(completed['stale'])
        baseline_report,baseline_config = copy.deepcopy(self.report),copy.deepcopy(self.config)
        for change in ('configuration','report_id','evidence','expiry'):
            with self.subTest(change=change):
                self.report,self.config = copy.deepcopy(baseline_report),copy.deepcopy(baseline_config)
                self.report_stale=False
                if change=='configuration':self.config['revision']+=1
                elif change=='report_id':self.report['as_of']='2026-11-02T20:00:00+08:00'
                elif change=='evidence':self.report['sector_analysis'][0]['score']=0
                else:self.report_stale=True
                result = self.jobs.status(self.user['id'],completed['job_id'])
                self.assertEqual(result['status'],'completed',result)
                self.assertTrue(result['charged'])
                self.assertEqual(result['charged_cost'],1)
                self.assertTrue(result['stale'])
                self.assertFalse(result['applicable'])
                self.assertNotIn('sector',result)
                self.assertNotIn('_configuration',result)
                self.assertNotIn('_evidence_key',result)
                self.assertEqual(result['subscription']['credits_remaining'],4)


class ManualResearchHTTPTests(unittest.TestCase):
    setUp=http_tests.CloudHTTPTests.setUp
    cleanup=http_tests.CloudHTTPTests.cleanup
    request=http_tests.CloudHTTPTests.request
    sign=http_tests.CloudHTTPTests.sign

    def prepare_live_jobs(self,probe,requester):
        store=AIConfigStore(Path(self.tmp.name)/'fixture-config.json',encrypt=lambda data:data,decrypt=lambda data:data,probe=probe)
        store.configure(key='isolated-test-key',model='gpt-6.1-sol',enabled=True,
                        responses_base_url='https://fixture.example/v1')
        self.server.ai_config=store
        report=evidence(1);report['as_of']='2026-11-02T20:00:00+08:00'
        self.server.auto_engine.status.return_value={'report':report,'report_stale':False}
        self.server.auto_engine._lock=threading.RLock()
        self.server.auto_engine._ai_cost_guard=None
        self.server.auto_engine._ai_evidence_cache=None
        # Exercise the actual cloud/local-shared factory, without a provider.
        from cloud_server import CloudHandler
        handler=CloudHandler.__new__(CloudHandler);handler.server=self.server
        jobs=handler.manual_research();jobs.requester=requester
        self.addCleanup(lambda:[worker.join(timeout=3) for worker in list(jobs._workers)])
        admin=self.request('/api/auth/me',cookie=self.admin_cookie)[1]
        member=self.request('/api/auth/me',cookie=self.member_cookie)[1]
        body={'sector_id':'sector_0','report_id':report['as_of'],'reasoning_effort':'xhigh'}
        return jobs,store,admin,member,body

    def test_member_http_click_connects_researches_and_settles_selected_points(self):
        connecting,release_connect,researching,release_research=(threading.Event() for _ in range(4))
        def probe(key,model):
            connecting.set();release_connect.wait(timeout=3)
            return {'models':[model]}
        def requester(report,ids,config):
            researching.set();release_research.wait(timeout=3)
            return detailed_response(report,ids,config)
        checker=Mock(side_effect=probe)
        jobs,store,admin,member,body=self.prepare_live_jobs(checker,requester)
        self.server.accounts.subscriptions.manage(admin['id'],member['id'],'grant','http-connect-grant',credits=3,days=30)
        self.server.accounts.subscriptions.manage(admin['id'],member['id'],'limits','http-connect-grant-calls',daily_limit=100,monthly_limit=1000)
        code,started,_=self.request('/api/me/ai-research',body,self.member_cookie,self.member_csrf)
        self.assertEqual(code,202)
        self.assertTrue(connecting.wait(2))
        poll='/api/me/ai-research?job_id='+started['job_id']
        try:
            self.assertEqual(self.request(poll,cookie=self.member_cookie)[1]['phase'],'connecting')
            self.assertEqual(checker.call_count,1)
            release_connect.set();self.assertTrue(researching.wait(2))
            self.assertEqual(self.request(poll,cookie=self.member_cookie)[1]['phase'],'researching')
        finally:
            release_connect.set();release_research.set()
            for worker in list(jobs._workers):worker.join(timeout=3)
        code,result,_=self.request(poll,cookie=self.member_cookie)
        self.assertEqual(code,200)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['charged_cost'],1.5)
        self.assertEqual(result['subscription']['credits_remaining'],1.5)
        self.assertEqual(result['sector']['ai_advice']['schema_version'],2)
        self.assertTrue(result['saved'])
        history=self.request('/api/me/history',cookie=self.member_cookie)[1]['items']
        self.assertEqual(history[0]['as_of'],body['report_id'])
        store.configure(reasoning_effort='medium')
        replay=self.request('/api/me/history/report?as_of='+quote(body['report_id'],safe=''),cookie=self.member_cookie)[1]['report']
        self.assertEqual(replay['sector_analysis'][0]['ai_generated_at'],result['sector']['ai_generated_at'])
        self.assertEqual(replay['sector_analysis'][0]['ai_advice']['schema_version'],2)
        self.assertEqual(checker.call_count,1)
        self.server.auto_engine.request_scan.assert_not_called()

    def test_http_restrictions_reject_before_connection_and_failure_polling_is_read_only(self):
        checker=Mock(side_effect=RuntimeError('isolated fixture failure'))
        requester=Mock(side_effect=AssertionError('must not generate'))
        jobs,store,admin,member,body=self.prepare_live_jobs(checker,requester)
        endpoint='/api/me/ai-research'
        def click():return self.request(endpoint,body,self.member_cookie,self.member_csrf)
        self.assertEqual(click()[0],403)
        sub=self.server.accounts.subscriptions
        sub.manage(admin['id'],member['id'],'grant','http-failure-grant',credits=3,days=30)
        sub.manage(admin['id'],member['id'],'limits','http-failure-grant-calls',daily_limit=100,monthly_limit=1000)
        sub.manage(admin['id'],member['id'],'pause','http-failure-pause')
        self.assertEqual(click()[0],403)
        sub.manage(admin['id'],member['id'],'resume','http-failure-resume')
        with self.server.accounts.connection() as db:db.execute('UPDATE ai_subscriptions SET credits=1 WHERE user_id=?',(member['id'],))
        self.assertEqual(click()[0],403)
        with self.server.accounts.connection() as db:db.execute('UPDATE ai_subscriptions SET credits=6 WHERE user_id=?',(member['id'],))
        store.configure(enabled=False)
        self.assertEqual(click()[0],503)
        checker.assert_not_called()
        store.configure(enabled=True)
        code,started,_=click()
        self.assertIn(code,(200,202))
        for worker in list(jobs._workers):worker.join(timeout=3)
        poll=endpoint+'?job_id='+started['job_id']
        for _ in range(3):
            result=self.request(poll,cookie=self.member_cookie)[1]
            self.assertEqual(result['status'],'failed',result)
            self.assertFalse(result['charged'])
            self.assertEqual(result['subscription']['credits_remaining'],3)
            self.assertEqual(result['subscription']['credits_reserved'],0)
        self.assertEqual(checker.call_count,1)
        requester.assert_not_called()

    def test_http_history_and_historical_unlock_keep_each_users_paid_configuration(self):
        counter=[0]
        def requester(report,ids,config):
            counter[0]+=1
            value=detailed_response(report,ids,config)
            value['choices'][0]['message']['content']=value['choices'][0]['message']['content'].replace(
                'manual medium','historical result '+str(counter[0]))
            return value
        jobs,store,admin,member,body=self.prepare_live_jobs(Mock(return_value={'models':['gpt-6.1-sol']}),requester)
        body['reasoning_effort']='medium'
        other_cookie,other_csrf=self.sign('/api/auth/register','another')
        other=self.request('/api/auth/me',cookie=other_cookie)[1]
        for user in (member,other):
            self.server.accounts.subscriptions.manage(admin['id'],user['id'],'grant','history-http-'+user['id'],credits=3,days=30)
            self.server.accounts.subscriptions.manage(admin['id'],user['id'],'limits','history-http-calls-'+user['id'],daily_limit=100,monthly_limit=1000)
        results=[]
        for index,(cookie,csrf) in enumerate(((self.member_cookie,self.member_csrf),(other_cookie,other_csrf))):
            if index:store.configure(responses_base_url='https://different-fixture.example/v1')
            _,started,_=self.request('/api/me/ai-research',body,cookie,csrf)
            for worker in list(jobs._workers):worker.join(timeout=3)
            results.append(self.request('/api/me/ai-research?job_id='+started['job_id'],cookie=cookie)[1])
        self.assertTrue(all(row['status']=='completed' for row in results),results)
        self.server.auto_engine.status.return_value['report']['as_of']='2026-11-02T20:05:00+08:00'
        historical_url='/api/me/history/report?as_of='+quote(body['report_id'],safe='')
        for index,cookie in enumerate((self.member_cookie,other_cookie)):
            replay=self.request(historical_url,cookie=cookie)[1]['report']['sector_analysis'][0]
            self.assertEqual(replay['ai_reason'],'historical result '+str(index+1))
            self.assertEqual(replay['ai_access']['status'],'unlocked')
        unlock={'sector_id':'sector_0','report_id':body['report_id'],
                'content_id':results[0]['sector']['ai_access']['content_id']}
        code,reopened,_=self.request('/api/me/ai-unlock',unlock,self.member_cookie,self.member_csrf)
        self.assertEqual(code,200,reopened)
        self.assertFalse(reopened['charged'])
        self.assertEqual(reopened['sector']['ai_reason'],'historical result 1')
        self.assertEqual(reopened['subscription']['credits_remaining'],2)
        self.assertEqual(counter[0],2)

    def test_post_is_account_scoped_and_csrf_protected_get_only_reads_jobs(self):
        endpoint='/api/me/ai-research';body={'sector_id':'sector_0','report_id':'current','reasoning_effort':'medium'}
        self.assertEqual(self.request(endpoint,body)[0],401)
        self.assertEqual(self.request(endpoint,body,self.member_cookie)[0],403)
        self.assertEqual(self.request(endpoint)[0],401)
        jobs=Mock();self.server.manual_ai=jobs
        jobs.start.return_value={**body,'status':'running','job_id':'a'*32}
        result=self.request(endpoint,body,self.member_cookie,self.member_csrf)
        self.assertEqual(result[0],202)
        member=self.request('/api/auth/me',cookie=self.member_cookie)[1]
        jobs.start.assert_called_once_with(member['id'],'sector_0','current','medium')
        self.assertEqual(self.request(endpoint,{**body,'user_id':'forged'},self.member_cookie,self.member_csrf)[0],400)
        jobs.pending.return_value={'jobs':[]}
        self.assertEqual(self.request(endpoint,cookie=self.member_cookie)[1],{'jobs':[]})
        jobs.pending.assert_called_once_with(member['id'])
        jobs.status.return_value={'status':'completed','job_id':'a'*32}
        self.assertEqual(self.request(endpoint+'?job_id='+'a'*32,cookie=self.member_cookie)[0],200)
        jobs.status.assert_called_once_with(member['id'],'a'*32)
        self.server.auto_engine.request_scan.assert_not_called()


if __name__=='__main__':
    unittest.main()
