"""Detailed research contracts use local fixtures, never live model requests."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from research_accounts import AccountStore
from research_ai_cache import AIEvidenceCache
from research_sector_ai import SYSTEM, _batch_evidence, enrich_sector_report, has_detailed_advice
from research_subscriptions import content_identity
from test_research_sector_ai import CONFIG, evidence, response


def detailed_advice(ref='history:sector_0', action='reference', scope='reference'):
    return {'schema_version':2, 'scope':scope, 'action':action,
        'reason':'PRIVATE_CONCLUSION：先观察样本走势，再核验公司证据。',
        'watch_points':['下一交易日核对近20日走势是否继续改善。'],
        'evidence_chain':[{'fact':'输入近20日收益为3.4%。',
            'interpretation':'PRIVATE_LOGIC：仅支持样本走势观察，不能替代公司研究。','evidence_ids':[ref]}],
        'action_plan':[{'trigger':'下一交易日行情更新后。',
            'step':'PRIVATE_STEP：对比近20日收益和回撤，检查样本覆盖是否改变。','evidence_ids':[ref]}],
        'scenarios':[{'condition':'后续可核验走势转弱。',
            'response':'PRIVATE_SCENARIO：降低关注优先级，核验变化是否持续。','evidence_ids':[ref]}],
        'review_conditions':['PRIVATE_REVIEW：行情来源失效或样本覆盖不足时暂停原结论。']}


class DetailedSectorAdviceTests(unittest.TestCase):
    def setUp(self):
        self.config={**CONFIG,'model':'gpt-6.1-sol','reasoning_effort':'medium',
                     '_require_detailed_advice':True}

    def run_report(self, report=None, advice=None, **config):
        value=report or evidence(1)
        def send(_,ids,settings):
            return response(ids,invalid=lambda rows:[row.update(advice=copy.deepcopy(
                detailed_advice() if advice is None else advice)) for row in rows])
        return enrich_sector_report(value,{**self.config,**config},requester=send)

    def test_detailed_output_keeps_rules_sources_and_research_scope(self):
        original=evidence(1)
        supplied,_=_batch_evidence(original,['sector_0'])
        self.assertEqual(supplied['sectors'][0]['advice_scope'],'reference')
        result=self.run_report(original)
        sector=result['sector_analysis'][0]
        self.assertTrue(has_detailed_advice(sector,result))
        self.assertEqual(sector['ai_advice'],detailed_advice())
        self.assertEqual(sector['score'],original['sector_analysis'][0]['score'])
        self.assertEqual(sector['recommendation_index'],59)
        self.assertIn('70分上限不能换算成100分',SYSTEM)
        self.assertIn('精确买卖价格',SYSTEM)

    def test_company_partial_score_keeps_wait_action_and_70_point_scope(self):
        value=evidence(1)
        value['sector_analysis'][0].update(score_model='company_research_v2',score_status='provisional',score_maximum=70)
        advice=detailed_advice(action='wait',scope='company')
        result=self.run_report(value,advice)
        sector=result['sector_analysis'][0]
        self.assertEqual(sector['score_maximum'],70)
        self.assertTrue(has_detailed_advice(sector,result))
        self.assertEqual(sector['ai_advice']['action'],'wait')
        self.assertEqual(sector['ai_advice']['scope'],'company')

    def test_required_details_reject_wrong_action_scope_missing_sections_or_unrelated_sources(self):
        value=evidence(2)
        variants=[]
        for name,bad in [('action','track'),('scope','company'),('schema_version',1),
                         ('scenarios',[]),('action_plan',[]),('review_conditions',[]),('evidence_chain',[])]:
            item=detailed_advice();item[name]=bad;variants.append(item)
        for source in ('invented','history:sector_1','market'):
            item=detailed_advice();item['evidence_chain'][0]['evidence_ids']=[source];variants.append(item)
        for item in variants:
            with self.subTest(advice=item):
                result=self.run_report(value,item)
                self.assertNotIn('ai_reason',result['sector_analysis'][0])
                self.assertEqual(result['ai_research']['analyzed_count'],0)
                self.assertIn('完整且可核验的详细建议',result['ai_research']['error'])

    def test_legacy_public_advice_is_readable_but_cannot_satisfy_new_detailed_generation(self):
        legacy={'action':'reference','reason':'只观察参考指标。','watch_points':['核验下个交易日行情。']}
        old=self.run_report(advice=legacy,_require_detailed_advice=False)
        sector=old['sector_analysis'][0]
        self.assertEqual(sector['ai_advice'],legacy)
        self.assertFalse(has_detailed_advice(sector,old))
        strict=self.run_report(advice=legacy)
        self.assertNotIn('ai_reason',strict['sector_analysis'][0])

    def test_all_allowed_source_ids_remain_valid_beyond_the_eighth(self):
        value=evidence(1);ids=['extra:'+str(i) for i in range(10)]
        value['snapshot']['sources'].extend({'id':ref,'status':'ok'} for ref in ids)
        value['sector_analysis'][0]['sources'].extend(ids)
        selected=ids[-1]
        def send(_,sectors,config):
            return response(sectors,invalid=lambda rows:rows[0].update(
                evidence_ids=['history:sector_0',*ids],advice=detailed_advice(selected)))
        result=enrich_sector_report(value,self.config,requester=send)
        self.assertTrue(has_detailed_advice(result['sector_analysis'][0],result))

    def test_detailed_cache_preserves_nested_advice_and_unlock_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=AIEvidenceCache(Path(folder)/'cache.db')
            with patch('research_sector_ai.now_iso',return_value='2026-11-02T09:20:00+08:00'):
                first=self.run_report(_evidence_cache=cache)
            provider=Mock()
            second=enrich_sector_report(evidence(1),{**self.config,'_evidence_cache':cache},requester=provider)
            provider.assert_not_called()
            a,b=first['sector_analysis'][0],second['sector_analysis'][0]
            self.assertTrue(has_detailed_advice(b,second))
            self.assertTrue(b['ai_reused'])
            self.assertEqual(content_identity(a),content_identity(b))
            changed=copy.deepcopy(b);changed['ai_advice']['action_plan'][0]['step']='新的核验步骤。'
            self.assertNotEqual(content_identity(changed),content_identity(b))

    def test_subscriber_filter_hides_every_detailed_section_until_atomic_unlock(self):
        with tempfile.TemporaryDirectory() as folder:
            accounts=AccountStore(Path(folder)/'accounts.db')
            password='Detailed-test-password-2026'
            admin=accounts.create_user('owner',password,admin=True)
            user=accounts.create_user('member',password)
            value=self.run_report();value['as_of']='2026-11-02T09:20:00+08:00'
            sub=accounts.subscriptions
            sub.manage(admin['id'],user['id'],'grant','detailed-advice-grant',credits=3,days=30)
            locked=sub.project_report(value,user['id'])['sector_analysis'][0]
            self.assertNotIn('ai_advice',locked)
            self.assertNotIn('ai_reason',locked)
            identity=content_identity(value['sector_analysis'][0])
            self.assertTrue(sub.unlock(user['id'],value,'sector_0',identity)['charged'])
            opened=sub.project_report(value,user['id'])['sector_analysis'][0]
            self.assertEqual(opened['ai_advice'],detailed_advice())
            self.assertFalse(sub.unlock(user['id'],value,'sector_0',identity)['charged'])


if __name__=='__main__':
    unittest.main()
