"""Offline synthetic announcements; never uses provider credentials or real calls."""
import copy
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_data import CHINA
from research_event_ai import enrich_event_report, refresh_event_indicators, SYSTEM
from research_news_verification import decode_verification, revalidate_verification, signature
from research_scarcity import profile_for, project_member_report, attention_for, summary_for
from research_balanced_score import catalyst_points
import test_research_cycle as cycle_tests
from test_research_cycle import NOW, report
import test_cloud_accounts as http_tests

SUMMARY = ('离线样本甲公告称高端芯片生产线的设备交付与客户认证需要二十四个月。'
           '本期仅两家厂商通过相关产品的客户认证，其他工艺仍在验证。'
           '公司提示市场需求与后续扩产存在不确定性，不能据此认定全行业短缺。')
QUOTE = '高端芯片生产线的设备交付与客户认证需要二十四个月'
OTHER = ('离线样本乙披露已完成新产线客户验收且具备批量交付条件。'
         '公司本期新增设备已经投入生产，后续需求和良率仍存在不确定性。'
         '以上披露只说明公司自身项目进度，不代表全部行业项目已经取得相同进展。')
OTHER_QUOTE = '已完成新产线客户验收且具备批量交付条件'
REASON = '原文披露该公司产线的交付和认证周期，支持局部扩产约束，不能推广到全部存储企业。'
CONFIG = {'enabled':True,'key':'synthetic-offline-key','model':'gpt-6.1-sol','revision':'test-scarcity'}


def verification(**changes):
    value={'verdict':'single_source','claim_type':'fact','claim_excerpt':QUOTE,'reason':REASON,
           'inference':'AI推断：本公司相关产线短期供给弹性有限，行业结论尚需核验。',
           'uncertainties':['仅有公司自身披露，缺少独立产业数据。'],'links':[]}
    value.update(changes)
    return value


def fixture(second=False):
    r=report();r['research_scope']='sectors'
    r['snapshot']['sources'].append({'id':'official_cninfo','status':'ok'})
    r['event_candidates']=[{'id':'synthetic-1','title':'离线样本甲产线公告','summary':SUMMARY,
        'published_at':'2026-10-30T18:00:00+08:00','evidence_complete':True,
        'url':'https://www.cninfo.com.cn/synthetic/1','source_id':'official_cninfo',
        'source_name':'离线公告夹具','event_type':'company_announcement','company_name':'离线样本甲',
        'stock_codes':['000001'],'sector_ids':['sector_memory_chip']}]
    if second:
        r['event_candidates'].append({**r['event_candidates'][0],'id':'synthetic-2','title':'离线样本乙新产线验收',
            'summary':OTHER,'company_name':'离线样本乙','stock_codes':['000002'],
            'url':'https://www.cninfo.com.cn/synthetic/2'})
    return r


def response(ver=None, dims=None, direction='tightening'):
    if dims is None:
        dims={'expansion':{'level':4,'reason':REASON,'fact_excerpt':QUOTE}}
    scarcity={'sector_id':'sector_memory_chip','category':'capacity','direction':direction,
        'scope':'离线样本甲的高端芯片产线','reason':REASON,'boundary':'单家公司披露不能代表全行业，更不能代表其他公司的产品。',
        'fact_excerpt':QUOTE,'dimensions':dims}
    value={'events':[{'id':'synthetic-1','verification':verification() if ver is None else ver,
        'assessments':[{'sector_id':'sector_memory_chip','direction':'positive','materiality':4,
            'breadth':3,'duration':4,'certainty':3,'reason':REASON,'fact_excerpt':QUOTE}],
        'scarcity_assessments':[scarcity]}]}
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}],
            'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}


def analyzed(r=None, **options):
    with patch('research_event_ai.now_iso',return_value=NOW.isoformat()), patch('research_event_ai.send_provider',side_effect=AssertionError('Paid call forbidden')):
        return enrich_event_report(fixture() if r is None else r,CONFIG,requester=lambda *_:response(**options))


class EvidenceReasoningTests(unittest.TestCase):
    def test_single_source_never_becomes_independently_confirmed_by_tone(self):
        r=fixture();source=r['event_candidates'][0]
        v=decode_verification(verification(verdict='cross_checked'),source,r['event_candidates'])
        self.assertEqual(v['status'],'single_source');self.assertTrue(v['uncertainties'])

    def test_fabricated_quotes_missing_limits_and_external_links_are_rejected(self):
        source=fixture()['event_candidates'][0]
        for changes in ({'claim_excerpt':'这是一段输入中从未出现的消息内容'}, {'uncertainties':[]}, {'claim_type':'certain'}):
            self.assertEqual(decode_verification(verification(**changes),source,[source])['status'],'insufficient')
        v=decode_verification(verification(verdict='cross_checked',links=[{'event_id':'invented','relation':'supports','fact_excerpt':QUOTE,'reason':REASON}]),source,[source])
        self.assertEqual(v['status'],'single_source');self.assertEqual(v['links'],[])

    def test_independence_uses_issuer_and_duplicates_do_not_count(self):
        r=fixture(True);a,b=r['event_candidates']
        link={'event_id':b['id'],'relation':'supports','fact_excerpt':OTHER_QUOTE,'reason':REASON}
        self.assertEqual(decode_verification(verification(verdict='cross_checked',links=[link]),a,[a,b])['status'],'cross_checked')
        same={**b,'stock_codes':a['stock_codes']}
        self.assertEqual(decode_verification(verification(verdict='cross_checked',links=[link]),a,[a,same])['status'],'single_source')
        overlap={**b,'stock_codes':['000001','000002']}
        self.assertEqual(decode_verification(verification(verdict='cross_checked',links=[link]),a,[a,overlap])['status'],'single_source')
        reprint={**b,'summary':a['summary']};link['fact_excerpt']=QUOTE
        self.assertEqual(decode_verification(verification(verdict='cross_checked',links=[link]),a,[a,reprint])['status'],'single_source')

    def test_contradictions_override_supported_claim_and_are_preserved(self):
        r=fixture(True);a,b=r['event_candidates']
        ver=verification(verdict='cross_checked',links=[{'event_id':b['id'],'relation':'contradicts','fact_excerpt':OTHER_QUOTE,'reason':REASON}])
        v=decode_verification(ver,a,[a,b]);self.assertEqual(v['status'],'disputed');self.assertEqual(v['links'][0]['relation'],'contradicts')
        output=analyzed(r,ver=ver);p=profile_for('sector_memory_chip',NOW,output)
        self.assertEqual(p['status'],'needs_review');self.assertIsNone(p['strength']['confirmed_score'])
        self.assertFalse(output['event_analysis']['events'][0]['evidence_usable'])
        self.assertIsNone(catalyst_points(output['event_analysis'],'sector_memory_chip',NOW.isoformat())['points'])

    def test_changed_cross_reference_cannot_keep_cross_checked_status(self):
        r=fixture(True);a,b=r['event_candidates']
        v=decode_verification(verification(verdict='cross_checked',links=[{'event_id':b['id'],'relation':'supports','fact_excerpt':OTHER_QUOTE,'reason':REASON}]),a,[a,b])
        changed={**b,'summary':OTHER+'原文发生更正。'}
        self.assertEqual(revalidate_verification(v,a,[a,changed])['status'],'single_source')


class ScarcityTests(unittest.TestCase):
    def test_no_news_no_fixed_profiles_or_manually_filled_scores(self):
        self.assertIsNone(profile_for('sector_memory_chip',NOW,report()))
        self.assertIsNone(profile_for('sector_rare_earth_magnet',NOW,report()))
        self.assertEqual(summary_for(report(),NOW)['status'],'pending')

    def test_each_dimension_needs_its_own_exact_excerpt_and_missing_is_not_zero(self):
        r=analyzed(dims={'expansion':{'level':4,'reason':REASON,'fact_excerpt':QUOTE},
            'technology':{'level':5,'reason':REASON,'fact_excerpt':'输入中不存在的所谓垄断事实与行业判断'}})
        p=profile_for('sector_memory_chip',NOW,r)
        self.assertEqual(p['strength']['coverage'],1);self.assertEqual(p['strength']['confirmed_score'],20)
        self.assertEqual(p['strength']['possible_range'],[20,95]);self.assertIsNone(p['strength']['score'])
        self.assertEqual(p['scope_level'],'company');self.assertEqual(p['strength']['dimensions'][1]['fact_excerpt'],QUOTE)

    def test_forecasts_and_easing_do_not_form_an_active_scarcity_badge(self):
        p=profile_for('sector_memory_chip',NOW,analyzed(ver=verification(claim_type='forecast')))
        self.assertEqual(p['status'],'needs_review');self.assertIsNone(p['strength']['score'])
        p=profile_for('sector_memory_chip',NOW,analyzed(direction='easing'))
        self.assertEqual(p['status'],'easing')

    def test_missing_verification_cannot_trigger_confirmed_catalyst_or_scarcity(self):
        value=response();parsed=json.loads(value['choices'][0]['message']['content'])
        del parsed['events'][0]['verification'];value['choices'][0]['message']['content']=json.dumps(parsed)
        with patch('research_event_ai.now_iso',return_value=NOW.isoformat()):
            output=enrich_event_report(fixture(),CONFIG,requester=lambda *_:value)
        self.assertFalse(output['event_analysis']['events'][0]['evidence_usable'])
        self.assertIsNone(profile_for('sector_memory_chip',NOW,output))
        self.assertIsNone(catalyst_points(output['event_analysis'],'sector_memory_chip',NOW.isoformat())['points'])

    def test_full_score_requires_four_supported_dimensions(self):
        dims={key:{'level':4,'reason':REASON,'fact_excerpt':QUOTE} for key in ['concentration','expansion','substitution','technology']}
        p=profile_for('sector_memory_chip',NOW,analyzed(dims=dims))
        self.assertEqual(p['strength']['score'],80);self.assertEqual(p['verification']['status'],'single_source')

    def test_changed_future_expired_failed_and_stale_sources_cannot_retain_numbers(self):
        r=analyzed()
        self.assertIsNone(profile_for('sector_memory_chip',NOW+timedelta(days=8),r))
        self.assertIsNone(profile_for('sector_memory_chip',datetime(2026,10,30,12,tzinfo=CHINA),r))
        for mutation in ['summary','source','stale']:
            changed=copy.deepcopy(r)
            if mutation=='summary':changed['event_candidates'][0]['summary']+='原文更正。'
            if mutation=='source':changed['snapshot']['sources'][-1]['status']='error'
            if mutation=='stale':changed['report_stale']=True
            self.assertIsNone(profile_for('sector_memory_chip',NOW,changed))
            if mutation=='summary':self.assertEqual(summary_for(changed,NOW)['assessed_count'],0)

    def test_company_mapping_cannot_be_invented(self):
        r=fixture();r['event_candidates'][0]['sector_ids']=[]
        self.assertIsNone(profile_for('sector_memory_chip',NOW,analyzed(r)))
        r['company_evidence']={'sector_leaders':{'sector_memory_chip':[{'ts_code':'000001.SZ','name':'离线样本甲'}]}}
        self.assertIsNotNone(profile_for('sector_memory_chip',NOW,analyzed(r)))

    def test_labels_never_change_original_scores_unlock_identity_or_balance(self):
        from research_subscriptions import content_identity
        r=analyzed();s=r['sector_analysis'][0];original=copy.deepcopy(r);identity=content_identity(s)
        with patch('research_responses.send_provider',side_effect=AssertionError('Paid call forbidden')):
            v=project_member_report(r,'active',NOW)
        self.assertEqual(r,original);self.assertEqual(content_identity(v['sector_analysis'][0]),identity)
        self.assertEqual(v['sector_analysis'][0]['scarcity']['credit_cost'],0)
        self.assertEqual({k:v for k,v in v['sector_analysis'][0].items() if k!='scarcity'},s)

    def test_attention_respects_original_gates_and_never_adds_scarcity_bonus(self):
        s={'id':'sector_memory_chip','status':'ok','score_model':'company_research_v2','score_status':'complete',
           'research_score':68,'confirmed_score':68,'score_breakdown':{
               'fundamentals':{'points':25},'trend':{'points':25},'catalysts':{'points':18}}}
        self.assertEqual(attention_for(s)['score'],68);self.assertEqual(attention_for(s)['label'],'中性')
        s['score_breakdown']['fundamentals']['points']=30
        self.assertEqual(attention_for(s)['label'],'乐观看待')
        s['score_status']='provisional';self.assertIsNone(attention_for(s)['score'])
        self.assertIsNone(attention_for(s,stale=True)['known_score'])

    def test_subscriber_boundary_includes_all_raw_model_fields_and_history(self):
        r=analyzed();original=copy.deepcopy(r)
        for status in ['unsubscribed','expired','paused']:
            v=project_member_report(r,status,NOW)
            for key in ['scarcity','scarcity_access','scarcity_summary']:
                self.assertNotIn(key,v);self.assertNotIn(key,v['sector_analysis'][0])
            self.assertNotIn('scarcity_analysis',v['event_analysis']);self.assertNotIn('source_verifications',v['event_analysis'])
            self.assertNotIn('verification',v['event_analysis']['events'][0])
        for status in ['admin','active','exhausted']:
            v=project_member_report(r,status,NOW)
            self.assertEqual(v['sector_analysis'][0]['scarcity']['sector_id'],'sector_memory_chip')
            self.assertNotIn('scarcity',project_member_report(r,status,NOW,historical=True)['sector_analysis'][0])
        self.assertEqual(r,original)

    def test_one_existing_request_is_used_with_bounded_selection(self):
        calls=[]
        with patch('research_event_ai.now_iso',return_value=NOW.isoformat()):
            r=enrich_event_report(fixture(),CONFIG,requester=lambda *args:(calls.append(args) or response()))
        self.assertEqual(len(calls),1);self.assertEqual(r['event_analysis']['request_count'],1)
        self.assertIn('不能保证内容真实',SYSTEM);self.assertIn('相反证据',SYSTEM)
        from research_live_update import retain_interpretations
        r['ai_research']={'revision':CONFIG['revision']}
        fresh=fixture();fresh['as_of']='2026-11-01T12:05:00+08:00'
        reused=retain_interpretations(fresh,r,CONFIG)
        self.assertIsNotNone(profile_for('sector_memory_chip',NOW+timedelta(minutes=5),reused))
        fresh=fixture();fresh['event_candidates'][0]['summary']+='文档已更正。';fresh['as_of']='2026-11-01T12:05:00+08:00'
        reused=retain_interpretations(fresh,r,CONFIG)
        self.assertIsNone(profile_for('sector_memory_chip',NOW+timedelta(minutes=5),reused))


class ScarcityCycleTests(unittest.TestCase):
    setUp=cycle_tests.CycleTests.setUp
    grant=cycle_tests.CycleTests.grant
    project=cycle_tests.CycleTests.project

    def test_member_projection_is_read_only_pending_honest_and_stale_hidden(self):
        self.grant();before=self.accounts.subscriptions.summary(self.member['id'])
        r=analyzed();original=copy.deepcopy(r);v=self.project(r,self.member)
        self.assertEqual(v['scarcity_sectors'][0]['scarcity']['status'],'reviewed')
        self.assertIsNone(v['themes'][0]['sectors'][0]['score'])
        self.assertEqual(self.accounts.subscriptions.summary(self.member['id']),before);self.assertEqual(r,original)
        self.assertEqual(self.project(report(),self.member)['scarcity_summary']['status'],'pending')
        r['as_of']='2026-10-20T12:00:00+08:00';self.assertEqual(self.project(r)['scarcity_sectors'],[])


class ScarcityHTTPTests(unittest.TestCase):
    setUp=http_tests.CloudHTTPTests.setUp
    cleanup=http_tests.CloudHTTPTests.cleanup
    request=http_tests.CloudHTTPTests.request
    sign=http_tests.CloudHTTPTests.sign

    def test_http_subscription_boundary_and_refresh_never_starts_scan(self):
        self.server.accounts.clock=lambda:NOW.timestamp()
        self.server.auto_engine.status.return_value={'report':analyzed(),'report_version':'scarcity-test'}
        self.assertEqual(self.request('/api/auto/report')[0],401)
        _,v,_=self.request('/api/auto/report',cookie=self.member_cookie)
        self.assertNotIn('scarcity',v['report']['sector_analysis'][0])
        admin=self.server.accounts.login('owner',http_tests.PASSWORD);member=self.server.accounts.login('member',http_tests.PASSWORD)
        self.server.accounts.subscriptions.manage(admin['id'],member['id'],'grant','news-scarcity-grant',credits=0,days=30)
        for cookie in [self.member_cookie,self.admin_cookie]:
            _,v,_=self.request('/api/auto/report',cookie=cookie)
            self.assertEqual(v['report']['sector_analysis'][0]['scarcity']['strength']['confirmed_score'],20)
        self.server.accounts.subscriptions.manage(admin['id'],member['id'],'pause','news-scarcity-pause')
        _,v,_=self.request('/api/auto/report',cookie=self.member_cookie)
        self.assertNotIn('scarcity',v['report']['sector_analysis'][0]);self.assertFalse(self.request('/api/me/cycle',cookie=self.member_cookie)[1]['access'])
        self.server.auto_engine.request_scan.assert_not_called()


if __name__=='__main__':unittest.main()
