import copy
import json
import threading
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from research_sector_ai import enrich_sector_report
from research_service import ProviderError

CONFIG = {'key': 'private-test-key', 'model': 'deepseek-flash', 'enabled': True, 'revision': 7}


def evidence(count=2):
    rows = []
    sources = [{'id': 'sector_quotes', 'status': 'ok', 'name': '行业指数来源'},
               {'id': 'market', 'status': 'ok', 'name': '大盘来源'},
               {'id': 'news', 'status': 'ok', 'name': '公开新闻'}]
    for index in range(count):
        sector_id = 'sector_' + str(index)
        source_id = 'history:' + sector_id
        sources.append({'id': source_id, 'status': 'ok', 'name': '板块历史'})
        rows.append({'id': sector_id, 'title': '板块' + str(index), 'status': 'ok',
                     'score': 65 + index % 20, 'recommendation_index': 59,
                     'as_of': '2026-10-30T15:00:00+08:00', 'reasons': ['真实行情计算'],
                     'quote': {'source_id': 'sector_quotes', 'change_pct': 1.2, 'as_of': '2026-10-30T15:00:00+08:00'},
                     'metrics': {'return_20d': 3.4, 'sample_count': 80},
                     'sources': [source_id, {'id': 'sector_quotes', 'status': 'ok'}],
                     'news': [{'source_id': 'news', 'title': '公开政策信息'}]})
    return {'research_scope': 'sectors', 'sector_analysis': rows, 'model': '板块量化研究',
            'snapshot': {'as_of': '2026-10-30T15:01:00+08:00', 'sources': sources,
                         'market': [{'name': '市场指数', 'source_id': 'market', 'change_pct': -1}],
                         'news': [{'title': '公开新闻', 'source_id': 'news'}]},
            'strategy': {'regime': {'mode': 'defensive'}, 'panic': {'score': 70}}}


def response(ids, omit=(), invalid=None):
    rows = [{'id': sector_id, 'reason': '供给与趋势证据支持关注，市场压力构成反对证据。',
             'risks': ['有限历史无法覆盖所有风险。'], 'invalidation': '后续历史转弱时重新评估。',
             'evidence_ids': ['history:' + sector_id], 'score': 100, 'recommendation_index': 100}
            for sector_id in ids if sector_id not in omit]
    if invalid:
        invalid(rows)
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'sectors': rows}, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}}


class SectorAiTests(unittest.TestCase):
    def test_generated_reasoning_provenance_matches_wire_not_provider_text(self):
        from research_subscriptions import interpretation_price
        configurations=[({'model':'gpt-6.1-sol','reasoning_effort':'xhigh'},'xhigh',1.5),
                        ({'model':'gpt-6.1-sol','reasoning_effort':'medium'},'medium',1),
                        ({'model':'gpt-6.1-sol'},'medium',1),
                        ({'model':'deepseek-flash','reasoning_effort':'xhigh'},None,1)]
        for additions,effort,cost in configurations:
            with self.subTest(config=additions):
                def requester(_,ids,config):
                    return response(ids,invalid=lambda rows: rows[0].update(ai_reasoning_effort='xhigh'))
                result=enrich_sector_report(evidence(1),{**CONFIG,**additions},requester=requester)
                sector=result['sector_analysis'][0]
                self.assertEqual(result['ai_research']['reasoning_effort'],effort)
                self.assertEqual(sector['ai_reasoning_effort'],effort)
                self.assertEqual(interpretation_price(sector)['cost'],cost)

    def test_disabled_or_failed_report_does_not_retain_old_reasoning_provenance(self):
        value=evidence(1)
        value['sector_analysis'][0].update(ai_reasoning_effort='xhigh',ai_research_status='completed',ai_reason='old')
        provider=Mock()
        result=enrich_sector_report(value,{**CONFIG,'enabled':False},requester=provider)
        provider.assert_not_called()
        self.assertNotIn('ai_reasoning_effort',result['sector_analysis'][0])

    def test_advice_action_respects_score_gates_and_reference_scope(self):
        from research_sector_ai import _research_action
        company = {'status':'ok','score':65,'score_model':'company_research_v2','score_status':'complete',
                   'score_breakdown':{'fundamentals':{'points':28},'trend':{'points':18},'catalysts':{'points':0}}}
        self.assertEqual(_research_action(company),'track')
        for score,expected in [(64.99,'observe'),(50,'observe'),(49.99,'cautious'),(30,'cautious'),(29.99,'avoid')]:
            self.assertEqual(_research_action({**company,'score':score}),expected)
        self.assertEqual(_research_action({**company,'score_status':'provisional','score_maximum':70}),'wait')
        self.assertEqual(_research_action(company,True),'wait')
        self.assertEqual(_research_action({**company,'score':None}),'wait')
        self.assertEqual(_research_action({**company,'score_model':'reference_model'}),'reference')
        company['score_breakdown']['fundamentals']['points']=27.99
        self.assertEqual(_research_action(company),'observe')
        company['score_breakdown']['fundamentals']['points']=28
        company['score_breakdown']['trend']['points']=17.99
        self.assertEqual(_research_action(company),'observe')
        company['score_breakdown']['catalysts']['points']=0.01
        self.assertEqual(_research_action(company),'track')

    def test_advice_requires_same_action_and_verifiable_sector_sources(self):
        from research_sector_ai import _batch_evidence
        report=evidence(1)
        supplied,_=_batch_evidence(report,['sector_0'])
        self.assertEqual(supplied['sectors'][0]['research_action'],'reference')
        def requester(_,ids,config):
            return response(ids,invalid=lambda rows: rows[0].update(advice={
                'action':'reference','reason':'观察参考走势，核验公司证据。','watch_points':['核验下一期公司财务。']}))
        result=enrich_sector_report(report,CONFIG,requester=requester)
        self.assertEqual(result['sector_analysis'][0]['ai_advice']['action'],'reference')
        self.assertEqual(result['sector_analysis'][0]['recommendation_index'],59)
        for action,refs in [('track',['history:sector_0']),('reference',['invented'])]:
            result=enrich_sector_report(report,CONFIG,requester=lambda _,ids,config: response(ids,invalid=lambda rows: rows[0].update(
                advice={'action':action,'reason':'不匹配建议','watch_points':['复核财务']},evidence_ids=refs)))
            self.assertNotIn('ai_advice',result['sector_analysis'][0])

    def test_old_advice_is_removed_when_no_new_ai_research_runs(self):
        report=evidence(1)
        report['sector_analysis'][0].update(ai_reason='旧解读',ai_advice={'action':'track'},ai_research_status='completed')
        with patch('research_sector_ai.provider_json') as provider:
            result=enrich_sector_report(report,{**CONFIG,'enabled':False})
        provider.assert_not_called()
        self.assertNotIn('ai_advice',result['sector_analysis'][0])
        self.assertNotIn('ai_research_status',result['sector_analysis'][0])

    def test_legacy_media_news_cannot_enter_sector_ai_evidence(self):
        from research_sector_ai import _batch_evidence
        value = evidence(1)
        value['snapshot']['sources'].extend([
            {'id': 'news_sina', 'status': 'ok'}, {'id': 'policy_csrc', 'status': 'ok'}])
        value['snapshot']['news'] = [
            {'title': '普通媒体', 'source_id': 'news_sina'},
            {'title': '官方监管', 'source_id': 'policy_csrc'}]
        value['sector_analysis'][0]['news'] = copy.deepcopy(value['snapshot']['news'])
        supplied, _ = _batch_evidence(value, ['sector_0'])
        self.assertEqual([row['source_id'] for row in supplied['news']], ['policy_csrc'])
        self.assertEqual([row['source_id'] for row in supplied['sectors'][0]['news']], ['policy_csrc'])
        self.assertNotIn('news_sina', {row['id'] for row in supplied['sources']})

    def test_disabled_missing_key_wrong_scope_and_no_evidence_do_not_request(self):
        empty = evidence()
        for sector in empty['sector_analysis']:
            sector['status'] = 'missing'
        cases = [(evidence(), {**CONFIG, 'enabled': False}, 'disabled'),
                 (evidence(), {}, 'not_configured'),
                 ({**evidence(), 'research_scope': 'funds'}, CONFIG, 'no_evidence'),
                 (empty, CONFIG, 'no_evidence')]
        for report, config, status in cases:
            with self.subTest(status=status), patch('research_sector_ai.provider_json') as provider:
                result = enrich_sector_report(report, config)
                provider.assert_not_called()
                self.assertEqual(result['ai_research']['status'], status)
                self.assertEqual(result['ai_research']['request_count'], 0)

    def test_all_sectors_batched_actual_tokens_no_score_change_and_isolation(self):
        report = evidence(19)
        original = copy.deepcopy(report)
        called = []
        def requester(supplied, ids, config):
            called.append(tuple(ids))
            supplied['sector_analysis'][0]['score'] = 999
            return response(ids)
        result = enrich_sector_report(report, CONFIG, requester=requester)
        meta = result['ai_research']
        self.assertEqual(meta['analyzed_count'], 19)
        self.assertEqual(meta['request_count'], 3)
        self.assertEqual(meta['usage']['total_tokens'], 450)
        self.assertEqual(meta['status'], 'completed')
        self.assertEqual(meta['requested_count'], 19)
        self.assertTrue(result['automatic']['paid_api_calls'])
        self.assertEqual(report, original)
        for old, new in zip(original['sector_analysis'], result['sector_analysis']):
            self.assertEqual(new['score'], old['score'])
            self.assertEqual(new['recommendation_index'], 59)
            self.assertEqual(new['reasons'], old['reasons'])
            self.assertEqual(new['ai_research_status'], 'completed')
        self.assertNotIn('funds', result)

    def test_closed_or_failed_window_gate_never_calls_provider(self):
        def failed_gate():
            raise RuntimeError('sensitive details')
        for gate in (lambda: False, failed_gate):
            with self.subTest(gate=gate), patch('research_sector_ai.provider_json') as provider:
                result = enrich_sector_report(evidence(), CONFIG, can_start_request=gate)
                provider.assert_not_called()
                self.assertEqual(result['ai_research']['status'], 'window_closed')
                self.assertTrue(result['ai_research']['stopped_for_schedule'])
                self.assertEqual(result['ai_research']['usage']['total_tokens'], 0)
                self.assertNotIn('sensitive details', json.dumps(result))

    def test_final_gate_after_payload_preparation_prevents_paid_io(self):
        from research_sector_ai import _batch_evidence
        allowed = [True]
        def slow_evidence(*args):
            result = _batch_evidence(*args)
            allowed[0] = False
            return result
        with patch('research_sector_ai._batch_evidence', side_effect=slow_evidence), \
                patch('research_sector_ai.provider_json') as provider:
            result = enrich_sector_report(evidence(), CONFIG, can_start_request=lambda: allowed[0])
        provider.assert_not_called()
        self.assertEqual(result['ai_research']['request_count'], 0)
        self.assertEqual(result['ai_research']['status'], 'window_closed')

    def test_revision_change_preserves_usage_but_discards_narratives(self):
        current = [True]
        def requester(_, ids, config):
            current[0] = False
            return response(ids)
        result = enrich_sector_report(evidence(), CONFIG, is_current=lambda: current[0], requester=requester)
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'superseded')
        self.assertEqual(meta['analyzed_count'], 0)
        self.assertEqual(meta['analyzed_sector_ids'], [])
        self.assertEqual(meta['request_count'], 1)
        self.assertEqual(meta['usage']['total_tokens'], 150)
        self.assertTrue(all('ai_reason' not in row for row in result['sector_analysis']))

    def test_last_sent_batch_can_complete_after_window_ends(self):
        allowed = [True]
        def requester(_, ids, config):
            allowed[0] = False
            return response(ids)
        result = enrich_sector_report(evidence(), CONFIG, requester=requester, can_start_request=lambda: allowed[0])
        self.assertEqual(result['ai_research']['status'], 'completed')
        self.assertEqual(result['ai_research']['analyzed_count'], 2)

    def test_partial_response_unknown_source_and_duplicate_ids_do_not_claim_success(self):
        result = enrich_sector_report(evidence(), CONFIG,
                                      requester=lambda _, ids, config: response(ids, omit=('sector_1',)))
        self.assertEqual(result['ai_research']['status'], 'partial')
        self.assertEqual(result['ai_research']['analyzed_sector_ids'], ['sector_0'])
        invalids = [lambda rows: rows[0].update(evidence_ids=['invented-source']),
                    lambda rows: rows[0].update(evidence_ids=['history:sector_1']),
                    lambda rows: rows.append(copy.deepcopy(rows[0]))]
        for invalid in invalids:
            with self.subTest(invalid=invalid):
                result = enrich_sector_report(evidence(), CONFIG,
                                              requester=lambda _, ids, config: response(ids, invalid=invalid))
                self.assertNotIn('sector_0', result['ai_research']['analyzed_sector_ids'])

    def test_stale_and_failed_sector_sources_are_not_paid_targets(self):
        report = evidence(3)
        report['sector_analysis'][0]['status'] = 'stale'
        report['sector_analysis'][1]['status'] = 'missing'
        for source in report['snapshot']['sources']:
            if source['id'] in ('history:sector_2', 'sector_quotes'):
                source['status'] = 'error'
        with patch('research_sector_ai.provider_json') as provider:
            result = enrich_sector_report(report, CONFIG)
        provider.assert_not_called()
        self.assertEqual(result['ai_research']['status'], 'no_evidence')

    def test_auth_failure_halts_next_wave_and_redacts_arbitrary_error_details(self):
        def rejected(*args):
            raise ProviderError('secret provider body', 401)
        result = enrich_sector_report(evidence(40), CONFIG, requester=rejected)
        self.assertLessEqual(result['ai_research']['request_count'], 2)
        self.assertTrue(result['ai_research']['terminal_error'])
        self.assertFalse(result['ai_research']['usage_complete'])
        self.assertNotIn('secret provider body', json.dumps(result))
        self.assertNotIn(CONFIG['key'], json.dumps(result))

    def test_unknown_usage_is_not_reported_as_complete_and_payload_has_no_fund_work(self):
        report = evidence(1)
        raw = response(['sector_0'])
        raw.pop('usage')
        with patch('research_sector_ai.provider_json', return_value=raw) as provider:
            result = enrich_sector_report(report, CONFIG)
        payload = provider.call_args.args[2]
        data = json.loads(payload['messages'][1]['content'])
        self.assertEqual(data['requested_sector_ids'], ['sector_0'])
        self.assertEqual(data['research_scope'], 'sectors')
        self.assertNotIn('funds', data)
        self.assertNotIn('holdings', data)
        self.assertFalse(result['ai_research']['usage_complete'])
        self.assertEqual(result['ai_research']['usage']['total_tokens'], 0)
        self.assertEqual(result['ai_research']['status'], 'completed')


class SectorCostIntegrationTests(unittest.TestCase):
    def setUp(self):
        from research_ai_cache import AIEvidenceCache
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [datetime(2026, 10, 31, 10, tzinfo=timezone(timedelta(hours=8))).timestamp()]
        self.cache = AIEvidenceCache(Path(self.temp.name) / 'cache.sqlite3', clock=lambda: self.clock[0])
        self.config = {**CONFIG, '_evidence_cache': self.cache}

    def run_report(self, value=None, requester=None, **options):
        return enrich_sector_report(value or evidence(), self.config,
            requester=requester or (lambda _, ids, config: response(ids)), **options)

    def test_same_evidence_reuses_without_calls_or_old_usage_and_keeps_generation_time(self):
        generated = datetime.fromtimestamp(self.clock[0], timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        with patch('research_sector_ai.now_iso', return_value=generated):
            first = self.run_report()
        self.clock[0] += 300
        value = evidence()
        value['snapshot']['sources'][0]['fetched_at'] = '2026-10-31T10:05:00+08:00'
        provider = Mock()
        second = self.run_report(value, provider)
        provider.assert_not_called()
        self.assertEqual(second['ai_research']['status'], 'completed')
        self.assertEqual(second['ai_research']['reused_count'], 2)
        self.assertEqual(second['ai_research']['request_count'], 0)
        self.assertEqual(second['ai_research']['usage']['total_tokens'], 0)
        self.assertFalse(second['automatic']['paid_api_calls'])
        self.assertEqual([s['ai_generated_at'] for s in second['sector_analysis']], [generated] * 2)
        self.assertEqual(first['ai_research']['usage']['total_tokens'], 150)

    def test_cache_persists_generation_reasoning_for_reused_reports(self):
        self.config.update(model='gpt-6.1-sol',reasoning_effort='xhigh')
        generated=datetime.fromtimestamp(self.clock[0],timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        with patch('research_sector_ai.now_iso',return_value=generated):
            first=self.run_report(evidence(1))
        self.assertEqual(first['sector_analysis'][0]['ai_reasoning_effort'],'xhigh')
        provider=Mock()
        second=self.run_report(evidence(1),provider)
        provider.assert_not_called()
        self.assertTrue(second['sector_analysis'][0]['ai_reused'])
        self.assertEqual(second['sector_analysis'][0]['ai_reasoning_effort'],'xhigh')
        self.assertEqual(second['sector_analysis'][0]['ai_generated_at'],first['sector_analysis'][0]['ai_generated_at'])

    def test_cache_write_crossing_a_second_keeps_the_same_unlock_identity(self):
        from research_subscriptions import content_identity
        self.config.update(model='gpt-6.1-sol',reasoning_effort='medium')
        generated=datetime.fromtimestamp(self.clock[0]-1,timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        first_value={**evidence(1),'as_of':'2026-10-31T10:00:00+08:00'}
        with patch('research_sector_ai.now_iso',return_value=generated):
            first=self.run_report(first_value)
        self.clock[0]+=300
        provider=Mock()
        second=self.run_report({**first_value,'as_of':'2026-10-31T10:05:00+08:00'},provider)
        provider.assert_not_called()
        original,reused=first['sector_analysis'][0],second['sector_analysis'][0]
        self.assertTrue(reused['ai_reused'])
        self.assertEqual(reused['ai_generated_at'],generated)
        self.assertEqual(content_identity(original),content_identity(reused))

    def test_reused_provenance_is_original_and_legacy_cache_is_not_repriced(self):
        from research_subscriptions import interpretation_price
        self.config.update(model='gpt-6.1-sol',reasoning_effort='xhigh')
        raw=json.loads(response(['sector_0'])['choices'][0]['message']['content'])['sectors'][0]
        for provenance,cost,legacy in [('medium',1,False),('xhigh',1.5,False),(None,1,True)]:
            with self.subTest(original=provenance):
                cached=dict(raw)
                if provenance is not None:cached['ai_reasoning_effort']=provenance
                item={'value':cached,'created_at':'2026-10-31T09:20:00+08:00'}
                provider=Mock()
                with patch.object(self.cache,'get',return_value=item):
                    result=self.run_report(evidence(1),provider)
                provider.assert_not_called()
                sector=result['sector_analysis'][0]
                self.assertEqual(sector['ai_reasoning_effort'],provenance)
                self.assertEqual(sector['ai_generated_at'],item['created_at'])
                self.assertEqual(interpretation_price(sector)['cost'],cost)
                self.assertEqual(interpretation_price(sector)['pricing_legacy'],legacy)
                self.assertEqual(result['ai_research']['reasoning_effort'],'xhigh')

    def test_changing_reasoning_strength_requests_new_actual_generation(self):
        self.config.update(model='gpt-6.1-sol',reasoning_effort='medium')
        first=self.run_report(evidence(1))
        self.config['reasoning_effort']='xhigh'
        provider=Mock(side_effect=lambda _,ids,config:response(ids))
        second=self.run_report(evidence(1),provider)
        provider.assert_called_once()
        self.assertEqual(first['sector_analysis'][0]['ai_reasoning_effort'],'medium')
        self.assertEqual(second['sector_analysis'][0]['ai_reasoning_effort'],'xhigh')

    def test_changed_local_evidence_only_sends_changed_sector(self):
        self.run_report()
        value = evidence()
        value['sector_analysis'][1]['quote']['change_pct'] = -2
        provider = Mock(side_effect=lambda _, ids, config: response(ids))
        output = self.run_report(value, provider)
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[1], ['sector_1'])
        self.assertEqual(output['ai_research']['reused_sector_ids'], ['sector_0'])
        self.assertEqual(output['ai_research']['request_count'], 1)

    def test_source_model_prompt_financial_and_business_changes_invalidate_reuse(self):
        value = evidence(1)
        value['sector_analysis'][0]['leaders'] = [{'ts_code':'600000.SH', 'as_of':'2026-10-30',
            'source_ids':['sector_quotes'], 'financials':{'roe':10,'ann_date':'2026-10-20'},
            'business_evidence':{'summary':'原有业务'}}]
        self.run_report(value)
        variants = []
        for field, new in [('financials', {'roe':11,'ann_date':'2026-10-20'}),
                           ('business_evidence', {'summary':'新披露业务'})]:
            changed = copy.deepcopy(value)
            changed['sector_analysis'][0]['leaders'][0][field] = new
            variants.append((changed, {}))
        changed = copy.deepcopy(value); changed['snapshot']['sources'][0]['url'] = 'https://example.com/new'
        variants.append((changed, {}))
        variants.append((value, {'model':'deepseek-v4-pro'}))
        for changed, additions in variants:
            with self.subTest(additions=additions, evidence=changed):
                provider = Mock(side_effect=lambda _, ids, config: response(ids))
                result = enrich_sector_report(changed, {**self.config, **additions}, requester=provider)
                provider.assert_called_once()
                self.assertEqual(result['ai_research']['reused_count'], 0)
        with patch('research_sector_ai.SYSTEM', 'changed prompt'):
            provider = Mock(side_effect=lambda _, ids, config: response(ids))
            enrich_sector_report(value, self.config, requester=provider)
            provider.assert_called_once()

    def test_unknown_or_invalid_request_is_not_immediately_recharged(self):
        for kind in ('timeout', 'invalid'):
            with self.subTest(kind=kind):
                value = evidence(1); value['sector_analysis'][0]['summary'] = kind
                provider = Mock(side_effect=TimeoutError() if kind == 'timeout' else lambda _, ids, config: response(ids, omit=ids))
                first = self.run_report(value, provider)
                self.assertEqual(first['ai_research']['request_count'], 1)
                blocked = Mock()
                second = self.run_report(value, blocked)
                blocked.assert_not_called()
                self.assertEqual(second['ai_research']['status'], 'retry_deferred')
                self.assertEqual(second['ai_research']['request_count'], 0)
                self.clock[0] += 1800
                retry = Mock(side_effect=lambda _, ids, config: response(ids))
                self.run_report(value, retry)
                retry.assert_called_once()

    def test_changed_evidence_can_retry_without_waiting_for_failed_old_evidence(self):
        self.run_report(evidence(1), Mock(side_effect=TimeoutError()))
        changed = evidence(1); changed['sector_analysis'][0]['metrics']['return_20d'] = 4
        provider = Mock(side_effect=lambda _, ids, config: response(ids))
        self.run_report(changed, provider)
        provider.assert_called_once()

    def test_stale_leader_report_historical_disabled_and_revision_never_send(self):
        stale = evidence(1)
        stale['sector_analysis'][0].update(status='stale', leaders=[{
            'as_of':'2026-10-30', 'source_ids':['sector_quotes']}])
        for value, config, options in [(stale, self.config, {}),
                ({**evidence(), 'report_stale':True}, self.config, {}),
                (evidence(), {**self.config,'enabled':False}, {}),
                (evidence(), self.config, {'is_current':lambda:False})]:
            with self.subTest(options=options):
                provider = Mock()
                result = enrich_sector_report(value, config, requester=provider, **options)
                provider.assert_not_called()
                self.assertEqual(result['ai_research']['request_count'], 0)

    def test_cached_result_is_discarded_if_revision_changes_during_cache_read(self):
        self.run_report(evidence(1))
        current = [True]
        original = self.cache.get
        def cache_read(*args):
            value = original(*args); current[0] = False
            return value
        with patch.object(self.cache, 'get', side_effect=cache_read):
            provider = Mock()
            result = self.run_report(evidence(1), provider, is_current=lambda: current[0])
        provider.assert_not_called()
        self.assertEqual(result['ai_research']['status'], 'superseded')
        self.assertNotIn('ai_reason', result['sector_analysis'][0])

    def test_large_sector_evidence_is_split_before_guard_and_single_oversize_is_blocked(self):
        from research_ai_cost import AICostGuard
        config = {**self.config, '_cost_guard':AICostGuard(Path(self.temp.name) / 'cost.sqlite3')}
        value = evidence(3)
        for sector in value['sector_analysis']:
            sector['summary'] = '证' * 40000
        provider = Mock(side_effect=lambda _, ids, cfg: response(ids))
        result = enrich_sector_report(value, config, requester=provider)
        self.assertEqual(result['ai_research']['status'], 'completed')
        self.assertEqual(result['ai_research']['request_count'], 2)
        self.assertTrue(all(len(call.args[1]) <= 2 for call in provider.call_args_list))
        value = evidence(1); value['sector_analysis'][0]['summary'] = '证' * 110000
        provider = Mock()
        result = enrich_sector_report(value, config, requester=provider)
        provider.assert_not_called()
        self.assertEqual(result['ai_research']['status'], 'input_too_large')
        self.assertEqual(result['ai_research']['request_count'], 0)

    def test_wrapper_exposes_zero_call_event_refusal_without_disabling_sector(self):
        for status in ('budget_limited', 'input_too_large', 'retry_deferred'):
            event = {'status':status, 'error':'费用保护已暂缓事件分析', 'request_count':0,
                     'assessed_count':0, 'reused_count':0, 'events':[]}
            value = evidence(1); value['event_analysis'] = event
            provider = Mock(side_effect=lambda _, ids, cfg: response(ids))
            with patch('research_event_ai.enrich_event_report', return_value=value):
                result = enrich_sector_report(value, CONFIG, requester=provider)
            provider.assert_called_once()
            meta = result['ai_research']
            self.assertEqual(meta['event_status'], status)
            self.assertEqual(meta['event_error'], event['error'])
            self.assertEqual(meta['status'], 'partial')
            self.assertEqual(meta['request_count'], 1)
            self.assertEqual(meta['usage']['total_tokens'], 150)

    def test_wrapper_exposes_cached_event_count_without_inheriting_usage(self):
        value = evidence(1)
        value['event_analysis'] = {'status':'completed', 'request_count':0, 'assessed_count':2,
            'reused_count':2, 'events':[], 'usage':{'prompt_tokens':999,'completion_tokens':999,'total_tokens':1998}}
        with patch('research_event_ai.enrich_event_report', return_value=value):
            result = enrich_sector_report(value, CONFIG, requester=lambda _, ids, cfg: response(ids))
        meta = result['ai_research']
        self.assertEqual(meta['event_reused_count'], 2)
        self.assertEqual(meta['event_status'], 'completed')
        self.assertEqual(meta['usage']['total_tokens'], 150)

    def joint_evidence(self):
        from test_research_event_ai import report as event_report
        value=evidence(1);event_value=event_report()
        value.update(as_of=event_value['as_of'],event_candidates=event_value['event_candidates'])
        value['snapshot']['sources'] += event_value['snapshot']['sources']
        return value

    def test_full_pipeline_reprocessing_has_zero_event_and_sector_calls(self):
        from test_research_event_ai import response as event_response, assessment
        first=enrich_sector_report(self.joint_evidence(), self.config,
            requester=lambda _,ids,cfg:response(ids),
            event_requester=lambda *_:event_response([{'id':'event-0','assessments':[assessment(board='sector_0')]}]))
        self.assertEqual(first['ai_research']['request_count'],2)
        sector_provider,event_provider=Mock(),Mock()
        second=enrich_sector_report(first,self.config,requester=sector_provider,event_requester=event_provider)
        sector_provider.assert_not_called();event_provider.assert_not_called()
        self.assertEqual(second['ai_research']['status'],'completed')
        self.assertEqual(second['ai_research']['request_count'],0)
        self.assertEqual(second['ai_research']['usage']['total_tokens'],0)
        self.assertEqual(second['ai_research']['reused_count'],1)
        self.assertEqual(second['ai_research']['event_reused_count'],1)

    def test_real_shared_guard_blocks_all_calls_at_zero_budget(self):
        from research_ai_cost import AICostGuard
        config={**self.config,'_cost_guard':AICostGuard(Path(self.temp.name)/'zero.sqlite3'),
                'cost_controls':{'daily_request_limit':0}}
        sector_provider,event_provider=Mock(),Mock()
        result=enrich_sector_report(self.joint_evidence(),config,
            requester=sector_provider,event_requester=event_provider)
        sector_provider.assert_not_called();event_provider.assert_not_called()
        self.assertEqual(result['ai_research']['status'],'budget_limited')
        self.assertEqual(result['ai_research']['event_status'],'budget_limited')
        self.assertEqual(result['ai_research']['request_count'],0)

    def test_oversize_event_real_guard_still_admits_small_sector_request(self):
        from research_ai_cost import AICostGuard
        value=self.joint_evidence();value['event_candidates'][0]['summary'] += '额'*110000
        config={**self.config,'_cost_guard':AICostGuard(Path(self.temp.name)/'oversize.sqlite3')}
        sector_provider=Mock(side_effect=lambda _,ids,cfg:response(ids));event_provider=Mock()
        result=enrich_sector_report(value,config,requester=sector_provider,event_requester=event_provider)
        sector_provider.assert_called_once();event_provider.assert_not_called()
        self.assertEqual(result['ai_research']['status'],'partial')
        self.assertEqual(result['ai_research']['event_status'],'input_too_large')
        self.assertEqual(result['ai_research']['request_count'],1)


if __name__ == '__main__':
    unittest.main()
