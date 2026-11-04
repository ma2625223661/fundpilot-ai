"""Offline event impact boundaries and request-accounting checks."""
import copy
import itertools
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from research_event_ai import (EVENT_CRITICAL_REASON, decode_events, enrich_event_report,
                               event_candidates, refresh_event_indicators)

CONFIG = {'key': 'offline-event-key-4a91', 'enabled': True,
          'revision': 'offline-event-revision', 'model': 'deepseek-flash'}
SUMMARY = ('公司披露本期已完成主要项目交付，并说明订单收入确认的时间与经营风险。'
           '公告同时提示原材料成本波动、项目验收延期和客户需求变动可能影响后续利润。'
           '以上信息仅涉及已披露公司业务，尚不能直接证明整个行业的需求同步改善。')
EXCERPT = '公司披露本期已完成主要项目交付'
REASON = '已披露项目交付可能改善该公司收入确认，但覆盖范围有限，仍需要核对后续验收与成本变化。'


def report(count=1):
    return {'research_scope': 'sectors', 'as_of': '2026-10-31T09:10:00+08:00',
            'sector_analysis': [{'id': 'sector_storage', 'title': '储能'},
                                {'id': 'sector_equipment', 'title': '设备'}],
            'snapshot': {'sources': [{'id': 'official_announcements', 'status': 'ok'}]},
            'event_candidates': [{'id': 'event-' + str(i), 'title': '项目交付与经营风险公告' + str(i),
                                  'summary': SUMMARY, 'evidence_complete': True,
                                  'published_at': '2026-10-30T18:00:00+08:00',
                                  'url': 'https://www.cninfo.com.cn/new/disclosure/' + str(i),
                                  'source_id': 'official_announcements', 'source_name': '公开披露'}
                                 for i in range(count)]}


def assessment(direction='positive', dims=(3, 3, 3, 3), board='sector_storage', **changes):
    result = {'sector_id': board, 'direction': direction,
              **dict(zip(('materiality', 'breadth', 'duration', 'certainty'), dims)),
              'reason': REASON, 'fact_excerpt': EXCERPT}
    result.update(changes)
    return result


def response(items=None, usage=None):
    if items is None:
        items = [{'id': 'event-0', 'assessments': [assessment()]}]
    # Valid source reasoning is part of the scheduled event response schema.
    items = [{**row, 'verification':row.get('verification', {
        'verdict':'single_source','claim_type':'fact','claim_excerpt':EXCERPT,'reason':REASON,
        'inference':'项目交付可能改善收入确认，尚需验收和成本证据。',
        'uncertainties':['只有公司披露，缺少独立交叉证据。'],'links':[]}),
        'scarcity_assessments':row.get('scarcity_assessments',[])} for row in items]
    return {'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'events': items}, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 101, 'completion_tokens': 49, 'total_tokens': 150}
                     if usage is None else usage}


class CandidateTests(unittest.TestCase):
    def test_evidence_must_be_complete_and_long_enough(self):
        for change in ({'evidence_complete': False}, {'evidence_complete': None},
                       {'summary': '仅有标题，证据不足'}):
            with self.subTest(change=change):
                value = report()
                value['event_candidates'][0].update(change)
                self.assertEqual(event_candidates(value), [])
        value = report()
        del value['event_candidates'][0]['evidence_complete']
        self.assertEqual(event_candidates(value), [])

    def test_future_old_missing_time_source_and_nonhttps_are_excluded(self):
        for change in ({'published_at': '2026-10-31T09:11:00+08:00'},
                       {'published_at': '2026-10-23T09:10:00+08:00'},
                       {'published_at': None}, {'source_id': 'fabricated-source'},
                       {'url': 'javascript:alert(1)'}):
            with self.subTest(change=change):
                value = report()
                value['event_candidates'][0].update(change)
                self.assertEqual(event_candidates(value), [])
        value = report()
        value['snapshot']['sources'][0]['status'] = 'error'
        self.assertEqual(event_candidates(value), [])

    def test_seven_day_boundary_and_duplicate_candidates(self):
        value = report()
        value['event_candidates'][0]['published_at'] = '2026-10-24T09:10:00+08:00'
        value['event_candidates'].append(copy.deepcopy(value['event_candidates'][0]))
        self.assertEqual(len(event_candidates(value)), 1)

    def test_general_media_is_never_event_evidence(self):
        value = report()
        value['snapshot']['sources'] = [{'id': 'news_sina', 'status': 'ok'}]
        value['event_candidates'][0]['source_id'] = 'news_sina'
        self.assertEqual(event_candidates(value), [])

    def test_real_cninfo_collector_source_is_accepted(self):
        value = report()
        value['snapshot']['sources'] = [{'id': 'official_cninfo', 'status': 'ok'}]
        value['event_candidates'][0]['source_id'] = 'official_cninfo'
        self.assertEqual(len(event_candidates(value)), 1)

    def test_latest_selection_compares_real_instants_across_timezones(self):
        value=report(2)
        value['event_candidates'][0]['published_at']='2026-10-30T23:00:00+08:00'
        value['event_candidates'][1]['published_at']='2026-10-30T16:00:00+00:00'
        self.assertEqual([row['id'] for row in event_candidates(value)],['event-1','event-0'])


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.value = report()
        self.candidates = event_candidates(self.value)
        self.catalog = self.value['sector_analysis']

    def decode(self, assessments):
        return decode_events(response([{'id': 'event-0', 'assessments': assessments}]), self.candidates, self.catalog)

    def test_positive_and_negative_signs_and_absolute_impact_order(self):
        events, weak, count = self.decode([assessment('positive'),
                                         assessment('negative', (5, 5, 5, 5), 'sector_equipment')])
        self.assertEqual([e['impact_score'] for e in events], [-100, 60])
        self.assertEqual([e['direction'] for e in events], ['negative', 'positive'])
        self.assertEqual((weak, count), (0, 1))
        self.assertTrue(all(e['source_ids'] == ['official_announcements'] for e in events))

    def test_weak_hidden_40_is_medium_and_70_is_high(self):
        events, weak, count = self.decode([assessment(dims=(1, 1, 1, 1))])
        self.assertEqual(events, [])
        self.assertEqual((weak, count), (1, 1))
        events, _, _ = self.decode([assessment(dims=(2, 2, 2, 2))])
        self.assertEqual(events[0]['impact_score'], 40)
        self.assertEqual(events[0]['impact_level'], 'medium')
        dims70 = next(d for d in itertools.product(range(6), repeat=4)
                      if sum(x * w for x, w in zip(d, (40, 25, 20, 15))) == 350)
        events, _, _ = self.decode([assessment(dims=dims70)])
        self.assertEqual(events[0]['impact_score'], 70)
        self.assertEqual(events[0]['impact_level'], 'high')

    def test_critical_event_requires_severe_negative_and_clear_evidence(self):
        events, _, _ = self.decode([assessment('negative', (5, 5, 5, 5))])
        self.assertEqual(events[0]['severity'], 'critical')
        for direction, dims in [('positive', (5, 5, 5, 5)), ('negative', (4, 4, 4, 4)), ('negative', (5, 5, 5, 3))]:
            events, _, _ = self.decode([assessment(direction, dims)])
            self.assertEqual(events[0]['severity'], 'normal')

    def test_positive_event_alone_cannot_claim_excellent_market_trend(self):
        events, _, _ = self.decode([assessment('positive', (5, 5, 5, 5))])
        self.assertEqual(events[0]['signal'], 'neutral')
        self.catalog[0]['signal'] = 'trend_excellent'
        events, _, _ = self.decode([assessment('positive', (5, 5, 5, 5))])
        self.assertEqual(events[0]['signal'], 'trend_excellent')

    def test_nonexistent_event_and_sector_cannot_count_as_assessed(self):
        events, _, count = decode_events(response([{'id': 'invented', 'assessments': [assessment()]}]),
                                        self.candidates, self.catalog)
        self.assertEqual((events, count), ([], 0))
        events, _, count = self.decode([assessment(board='unknown_sector')])
        self.assertEqual((events, count), ([], 0))

    def test_fabricated_excerpt_and_invalid_dimensions_cannot_count_as_assessed(self):
        for item in (assessment(fact_excerpt='公司披露利润大增百分之五百并承诺下一年度翻倍'),
                     assessment(materiality=True), assessment(materiality=3.5),
                     assessment(materiality=6), assessment(reason='不错'),
                     assessment(direction='buy')):
            with self.subTest(item=item):
                events, _, count = self.decode([item])
                self.assertEqual((events, count), ([], 0))

    def test_explicit_no_relevance_is_assessed_but_malformed_assessments_are_not(self):
        self.assertEqual(self.decode([]), ([], 0, 1))
        for value in (None, 'strong', {}):
            events, _, count = decode_events(response([{'id': 'event-0', 'assessments': value}]),
                                            self.candidates, self.catalog)
            self.assertEqual((events, count), ([], 0))

    def test_duplicates_are_rejected_or_deduplicated_and_mixed_stays_explicit(self):
        with self.assertRaises(ValueError):
            decode_events(response([{'id': 'event-0', 'assessments': [assessment()]},
                                    {'id': 'event-0', 'assessments': [assessment()]}]),
                          self.candidates, self.catalog)
        events, _, count = self.decode([assessment('mixed'), assessment('mixed')])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['direction'], 'mixed')
        self.assertEqual(count, 1)


class RequestTests(unittest.TestCase):
    def test_retained_events_expire_by_publication_and_recheck_current_trend(self):
        value = report()
        value['sector_analysis'][0].update(status='ok', signal='trend_excellent')
        output = enrich_event_report(value, CONFIG, requester=lambda *_: response([
            {'id': 'event-0', 'assessments': [assessment('positive', (5, 5, 5, 5))]}]))
        self.assertEqual(output['event_analysis']['events'][0]['signal'], 'trend_excellent')
        output['sector_analysis'][0]['signal'] = 'neutral'
        refresh_event_indicators(output)
        self.assertEqual(output['event_analysis']['events'][0]['signal'], 'neutral')
        output['as_of'] = '2026-11-07T09:10:00+08:00'
        refresh_event_indicators(output)
        self.assertEqual(output['event_analysis']['events'], [])

    def test_failed_policy_collection_is_unavailable_not_no_events(self):
        value = report(0)
        value['snapshot']['sources'] = [{'id': 'policy_ndrc_notice', 'status': 'error'}]
        output = enrich_event_report(value, CONFIG, requester=Mock())
        self.assertEqual(output['event_analysis']['status'], 'data_unavailable')

    def test_critical_official_event_overrides_positive_sector_signal(self):
        value = report()
        value['sector_analysis'][0]['signal'] = 'trend_excellent'
        output = enrich_event_report(value, CONFIG, requester=lambda *_: response([
            {'id': 'event-0', 'assessments': [assessment('negative', (5, 5, 5, 5))]}]))
        self.assertEqual(output['sector_analysis'][0]['severity'], 'critical')
        self.assertEqual(output['sector_analysis'][0]['signal'], 'neutral')

    def critical_report(self, **baseline):
        value=report()
        value['sector_analysis'][0].update(status='ok', severity='normal', signal='trend_excellent',
                                          indicator_reason='原有趋势依据', **baseline)
        return enrich_event_report(value, CONFIG, requester=lambda *_: response([
            {'id':'event-0','assessments':[assessment('negative',(5,5,5,5))]}]))

    def test_event_critical_overlay_is_removed_when_event_disappears(self):
        output=self.critical_report()
        sector=output['sector_analysis'][0]
        self.assertEqual(sector['event_severity'],'critical')
        self.assertEqual(sector['indicator_reason'],EVENT_CRITICAL_REASON)
        output['event_analysis']['events']=[]
        refresh_event_indicators(output)
        self.assertEqual((sector['severity'],sector['signal'],sector['indicator_reason']),
                         ('normal','trend_excellent','原有趋势依据'))
        self.assertEqual(sector['event_severity'],'normal')
        self.assertNotIn('event_indicator_baseline',sector)

    def test_expired_event_critical_clears_on_same_retained_sector(self):
        output=self.critical_report()
        sector=output['sector_analysis'][0]
        output['as_of']='2026-11-07T09:10:00+08:00'
        refresh_event_indicators(output)
        self.assertEqual(output['event_analysis']['events'],[])
        self.assertEqual(sector['severity'],'normal')
        self.assertEqual(sector['signal'],'trend_excellent')

    def test_repeated_event_refresh_preserves_independent_quantitative_risk(self):
        value=report()
        value['sector_analysis'][0].update(status='ok', severity='critical', signal='neutral',
                                          indicator_reason='独立行情回撤触发的量化特大风险')
        output=enrich_event_report(value,CONFIG,requester=lambda *_:response([
            {'id':'event-0','assessments':[assessment('negative',(5,5,5,5))]}]))
        for _ in range(3):
            refresh_event_indicators(output)
        sector=output['sector_analysis'][0]
        self.assertEqual(sector['event_indicator_baseline']['indicator_reason'],
                         '独立行情回撤触发的量化特大风险')
        output['event_analysis']['events']=[]
        refresh_event_indicators(output)
        self.assertEqual(sector['severity'],'critical')
        self.assertEqual(sector['indicator_reason'],'独立行情回撤触发的量化特大风险')

    def test_legacy_event_reason_clears_without_erasing_unrelated_risk(self):
        value=report()
        value['sector_analysis'][0].update(severity='critical',signal='neutral',indicator_reason=EVENT_CRITICAL_REASON)
        value['sector_analysis'][1].update(severity='critical',signal='neutral',indicator_reason='独立风险')
        value['event_analysis']={'events':[],'eligible_count':None,'candidate_count':'invalid'}
        refresh_event_indicators(value)
        self.assertEqual(value['sector_analysis'][0]['severity'],'normal')
        self.assertEqual(value['sector_analysis'][1]['severity'],'critical')
        self.assertEqual(value['sector_analysis'][1]['indicator_reason'],'独立风险')
        self.assertEqual(value['event_analysis']['coverage']['eligible_count'],0)

    def test_disabled_reanalysis_removes_old_overlay_without_a_request(self):
        prior=self.critical_report()
        requester=Mock()
        output=enrich_event_report(prior,{**CONFIG,'enabled':False},requester=requester)
        requester.assert_not_called()
        self.assertEqual(output['sector_analysis'][0]['severity'],'normal')
        self.assertEqual(output['sector_analysis'][0]['signal'],'trend_excellent')

    def test_latest_twelve_budget_discloses_omitted_candidates(self):
        provider=Mock(side_effect=lambda payload,config: response([
            {'id':row['id'],'assessments':[assessment()]} for row in payload['events']]))
        value=report(13)
        for i,row in enumerate(value['event_candidates']):
            row['published_at']='2026-10-30T18:'+str(i).zfill(2)+':00+08:00'
        output=enrich_event_report(value,CONFIG,requester=provider)
        meta=output['event_analysis']
        provider.assert_called_once()
        sent=provider.call_args.args[0]['events']
        self.assertEqual(sent[0]['id'],'event-12')
        self.assertNotIn('event-0',{row['id'] for row in sent})
        self.assertEqual((meta['eligible_count'],meta['selected_count'],meta['assessed_count'],
                          meta['truncated_count'],meta['unassessed_count']),(13,12,12,1,1))
        self.assertEqual(meta['status'],'partial')
        self.assertEqual(meta['request_count'],1)
        self.assertIn('1 条合规候选未送评',meta['summary'])
        self.assertIn('不代表已检查全网或全部重要事件',meta['summary'])

    def test_disabled_request_coverage_does_not_claim_evaluation(self):
        requester=Mock()
        output=enrich_event_report(report(13),{**CONFIG,'enabled':False},requester=requester)
        requester.assert_not_called()
        coverage=output['event_analysis']['coverage']
        self.assertEqual((coverage['selected_count'],coverage['assessed_count'],
                          coverage['truncated_count'],coverage['unassessed_count']),(12,0,1,13))

    def test_missing_key_disabled_and_incomplete_evidence_do_not_request(self):
        for config in ({}, {**CONFIG, 'key': ''}, {**CONFIG, 'enabled': False}):
            with self.subTest(config=config), patch('research_event_ai.provider_json') as provider:
                output = enrich_event_report(report(), config)
                provider.assert_not_called()
                self.assertEqual(output['event_analysis']['request_count'], 0)
        value = report()
        value['event_candidates'][0]['evidence_complete'] = False
        provider = Mock()
        output = enrich_event_report(value, CONFIG, requester=provider)
        provider.assert_not_called()
        self.assertEqual(output['event_analysis']['eligible_count'], 0)

    def test_window_and_revision_gates_prevent_request_even_after_payload_build(self):
        for options in ({'can_start_request': lambda: False}, {'is_current': lambda: False}):
            provider = Mock()
            output = enrich_event_report(report(), CONFIG, requester=provider, **options)
            provider.assert_not_called()
            self.assertEqual(output['event_analysis']['request_count'], 0)
        allowed = [True]
        def progress(*_):
            allowed[0] = False
        provider = Mock()
        output = enrich_event_report(report(), CONFIG, requester=provider, progress=progress,
                                     can_start_request=lambda: allowed[0])
        provider.assert_not_called()
        self.assertEqual(output['event_analysis']['request_count'], 0)

    def test_revision_change_discards_events_and_keeps_actual_usage(self):
        current = [True]
        def requester(*_):
            current[0] = False
            return response()
        output = enrich_event_report(report(), CONFIG, requester=requester, is_current=lambda: current[0])
        meta = output['event_analysis']
        self.assertEqual(meta['status'], 'superseded')
        self.assertEqual(meta['events'], [])
        self.assertEqual(meta['request_count'], 1)
        self.assertEqual(meta['usage']['total_tokens'], 150)

    def test_actual_usage_not_estimated_and_input_report_unchanged(self):
        value = report()
        old = copy.deepcopy(value)
        output = enrich_event_report(value, CONFIG, requester=lambda *_: response())
        meta = output['event_analysis']
        self.assertEqual(meta['status'], 'completed')
        self.assertEqual(meta['usage'], {'prompt_tokens': 101, 'completion_tokens': 49, 'total_tokens': 150})
        self.assertEqual(meta['request_count'], 1)
        self.assertTrue(meta['usage_complete'])
        self.assertEqual(value, old)
        output = enrich_event_report(value, CONFIG, requester=lambda *_: response(usage={}))
        self.assertFalse(output['event_analysis']['usage_complete'])
        self.assertEqual(output['event_analysis']['usage']['total_tokens'], 0)

    def test_invalid_model_output_is_partial_not_completed_and_provider_errors_are_safe(self):
        output = enrich_event_report(report(), CONFIG, requester=lambda *_: response([
            {'id': 'event-0', 'assessments': [assessment(fact_excerpt='编造的事实内容足够长但从未出现在原文里面')]}]))
        self.assertNotEqual(output['event_analysis']['status'], 'completed')
        self.assertEqual(output['event_analysis']['assessed_count'], 0)
        self.assertEqual(output['event_analysis']['usage']['total_tokens'], 150)
        def fail(*_):
            raise RuntimeError(CONFIG['key'])
        output = enrich_event_report(report(), CONFIG, requester=fail)
        self.assertEqual(output['event_analysis']['request_count'], 1)
        self.assertEqual(output['event_analysis']['usage']['total_tokens'], 0)
        self.assertFalse(output['event_analysis']['usage_complete'])
        self.assertNotIn(CONFIG['key'], json.dumps(output))


class EventCostIntegrationTests(unittest.TestCase):
    def setUp(self):
        from research_ai_cache import AIEvidenceCache
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [datetime(2026, 10, 31, 10, tzinfo=timezone(timedelta(hours=8))).timestamp()]
        self.cache = AIEvidenceCache(Path(self.temp.name) / 'cache.sqlite3', clock=lambda: self.clock[0])
        self.config = {**CONFIG, '_evidence_cache':self.cache}

    def test_same_event_evidence_reuses_without_usage_and_original_publication_is_preserved(self):
        generated = datetime.fromtimestamp(self.clock[0], timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        with patch('research_event_ai.now_iso', return_value=generated):
            first = enrich_event_report(report(), self.config, requester=lambda *_:response())
        self.clock[0] += 300
        value = report(); value['as_of'] = '2026-10-31T09:15:00+08:00'
        provider = Mock()
        second = enrich_event_report(value, self.config, requester=provider)
        provider.assert_not_called()
        meta = second['event_analysis']
        self.assertEqual(meta['status'], 'completed')
        self.assertEqual(meta['reused_count'], 1)
        self.assertEqual(meta['request_count'], 0)
        self.assertEqual(meta['usage']['total_tokens'], 0)
        self.assertEqual(meta['generated_at'], generated)
        self.assertEqual(first['event_analysis']['generated_at'], generated)
        self.assertEqual(meta['events'][0]['published_at'], '2026-10-30T18:00:00+08:00')

    def test_weak_and_explicit_unrelated_results_are_cached_without_claiming_display_events(self):
        for assessments, weak in [([assessment(dims=(1, 1, 1, 1))], 1), ([], 0)]:
            value = report(); value['event_candidates'][0]['title'] += str(weak)
            enrich_event_report(value, self.config, requester=lambda *_:response([
                {'id':'event-0', 'assessments':assessments}]))
            provider = Mock()
            output = enrich_event_report(value, self.config, requester=provider)
            provider.assert_not_called()
            meta = output['event_analysis']
            self.assertEqual((meta['assessed_count'], meta['hidden_weak_count'], meta['events']), (1, weak, []))
            self.assertEqual(meta['coverage']['unassessed_count'], 0)
            self.assertEqual(meta['reused_count'], 1)

    def test_failed_event_is_not_recharged_within_thirty_minutes_and_changed_event_can_run(self):
        provider = Mock(side_effect=TimeoutError())
        first = enrich_event_report(report(), self.config, requester=provider)
        self.assertEqual(first['event_analysis']['request_count'], 1)
        blocked = Mock()
        second = enrich_event_report(report(), self.config, requester=blocked)
        blocked.assert_not_called()
        self.assertEqual(second['event_analysis']['status'], 'retry_deferred')
        changed = report(); changed['event_candidates'][0]['summary'] += '后续新增项目验收事实。'
        fresh = Mock(return_value=response())
        enrich_event_report(changed, self.config, requester=fresh)
        fresh.assert_called_once()
        self.clock[0] += 1800
        retry = Mock(return_value=response())
        enrich_event_report(report(), self.config, requester=retry)
        retry.assert_called_once()

    def test_invalid_response_is_not_cached_and_retry_is_deferred(self):
        invalid = response([{'id':'event-0','assessments':[assessment(materiality=6)]}])
        first = enrich_event_report(report(), self.config, requester=lambda *_:invalid)
        self.assertEqual(first['event_analysis']['assessed_count'], 0)
        provider = Mock()
        second = enrich_event_report(report(), self.config, requester=provider)
        provider.assert_not_called()
        self.assertEqual(second['event_analysis']['status'], 'retry_deferred')
        self.assertEqual(second['event_analysis']['reused_count'], 0)

    def test_cached_events_expire_from_publication_and_do_not_charge_again(self):
        enrich_event_report(report(), self.config, requester=lambda *_:response())
        value = report(); value['as_of'] = '2026-11-07T09:10:00+08:00'
        provider = Mock()
        output = enrich_event_report(value, self.config, requester=provider)
        provider.assert_not_called()
        self.assertEqual(output['event_analysis']['eligible_count'], 0)
        self.assertEqual(output['event_analysis']['events'], [])

    def test_reprocessing_prior_critical_overlay_reuses_independent_baseline(self):
        value = report()
        value['sector_analysis'][0].update(status='ok',signal='trend_excellent',severity='normal')
        first = enrich_event_report(value, self.config, requester=lambda *_:response([
            {'id':'event-0','assessments':[assessment('negative',(5,5,5,5))]}]))
        self.assertEqual(first['sector_analysis'][0]['signal'], 'neutral')
        provider = Mock()
        output = enrich_event_report(first, self.config, requester=provider)
        provider.assert_not_called()
        self.assertEqual(output['event_analysis']['reused_count'], 1)
        self.assertEqual(output['sector_analysis'][0]['severity'], 'critical')

    def test_source_business_model_and_prompt_changes_do_not_reuse_old_event_assessments(self):
        value = report()
        value['company_evidence'] = {'sector_leaders':{'sector_storage':[{
            'ts_code':'600000.SH', 'name':'测试企业', 'business_evidence':'原业务',
            'membership_evidence':{'l2_name':'储能','snapshot_date':'2026-10-30'}}]}}
        enrich_event_report(value, self.config, requester=lambda *_:response())
        variants = []
        changed = copy.deepcopy(value)
        changed['snapshot']['sources'][0]['id'] = 'official_cninfo'
        changed['event_candidates'][0]['source_id'] = 'official_cninfo'
        variants.append((changed, {}))
        changed = copy.deepcopy(value)
        changed['company_evidence']['sector_leaders']['sector_storage'][0]['business_evidence'] = '新业务'
        variants.append((changed, {}))
        variants.append((value, {'model':'deepseek-v4-pro'}))
        for changed, additions in variants:
            with self.subTest(additions=additions):
                provider = Mock(return_value=response())
                output = enrich_event_report(changed, {**self.config, **additions}, requester=provider)
                provider.assert_called_once()
                self.assertEqual(output['event_analysis']['reused_count'], 0)
        provider = Mock(return_value=response())
        with patch('research_event_ai.SYSTEM', 'changed event prompt'):
            enrich_event_report(value, self.config, requester=provider)
        provider.assert_called_once()

    def test_historical_wrong_scope_and_disabled_reports_never_send_even_with_cached_evidence(self):
        enrich_event_report(report(), self.config, requester=lambda *_:response())
        for value, config in [({**report(), 'report_stale':True}, self.config),
                ({**report(), 'research_scope':'funds'}, self.config),
                (report(), {**self.config,'enabled':False})]:
            provider = Mock()
            result = enrich_event_report(value, config, requester=provider)
            provider.assert_not_called()
            self.assertEqual(result['event_analysis']['request_count'], 0)
            self.assertEqual(result['event_analysis']['reused_count'], 0)

    def test_revision_changed_during_cache_read_discards_cached_assessment(self):
        enrich_event_report(report(), self.config, requester=lambda *_:response())
        current = [True]
        original = self.cache.get
        def cache_read(*args):
            value = original(*args); current[0] = False
            return value
        provider = Mock()
        with patch.object(self.cache, 'get', side_effect=cache_read):
            result = enrich_event_report(report(), self.config, requester=provider,
                is_current=lambda:current[0])
        provider.assert_not_called()
        self.assertEqual(result['event_analysis']['status'], 'superseded')
        self.assertEqual(result['event_analysis']['events'], [])
        self.assertEqual(result['event_analysis']['assessed_count'], 0)

    def test_oversize_event_is_guarded_before_provider_io(self):
        from research_ai_cost import AICostGuard
        value = report(); value['event_candidates'][0]['summary'] += '额' * 110000
        config = {**self.config, '_cost_guard':AICostGuard(Path(self.temp.name) / 'cost.sqlite3')}
        provider = Mock()
        output = enrich_event_report(value, config, requester=provider)
        provider.assert_not_called()
        self.assertEqual(output['event_analysis']['status'], 'input_too_large')
        self.assertEqual(output['event_analysis']['request_count'], 0)


if __name__ == '__main__':
    unittest.main()
