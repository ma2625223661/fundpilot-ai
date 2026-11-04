import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_auto import AutoResearchEngine, enforce_strategy
from research_data import CHINA
import research_auto_ai as automatic_ai
from research_auto_ai import enrich_auto_report
from research_data import now_iso
from test_research_auto import sample_report


CONFIG = {'key': 'sk-test-private-credential', 'model': 'deepseek-flash', 'enabled': True, 'revision': 'revision-1'}


def evidence_report(count=1):
    report = sample_report()
    template_fund = report['snapshot']['funds'][0]
    template_quant = report['quant'][0]
    template_analysis = report['analysis']['funds'][0]
    codes = [f'{index + 1:06d}' for index in range(count)]
    report['snapshot']['funds'] = [{**template_fund, 'code': code, 'name': f'独立策略{index}A',
                                    'history': [{'date': now_iso()[:10], 'nav': 1.2}]}
                                   for index, code in enumerate(codes)]
    report['snapshot'].update(sources=[], market=[], news=[])
    report['quant'] = [{**copy.deepcopy(template_quant), 'code': code, 'score': 80 + index % 10}
                       for index, code in enumerate(codes)]
    report['analysis']['funds'] = [{**copy.deepcopy(template_analysis), 'code': code,
                                   'score': report['quant'][index]['score'], 'invalidation': '原量化失效条件'}
                                  for index, code in enumerate(codes)]
    report['strategy']['candidates'] = [{'code': code, 'reason': '研究持有至少7天'} for code in codes]
    report['analysis'] = enforce_strategy(report['analysis'], report['strategy'])
    report.update(model='自动量化研究', engine='automatic', automatic={'paid_api_calls': False})
    return report


def response_for(codes, action='分批配置候选', omit=()):
    body = {'summary': '市场证据有限，按风险边界观察。',
            'market_view': '输入行情的压力代理尚低，基金公告覆盖仍有缺口。',
            'risks': ['新闻标题不能证明资金流向。'], 'funds': [
                {'code': code, 'score': 100, 'action': action,
                 'reason': f'支持：{code}的净值趋势；反对：公告资料覆盖有限。',
                 'invalidation': '若净值趋势破坏或公告风险出现则重新评估。',
                 'evidence_ids': [f'nav:{code}', 'fabricated-source'],
                 'operation_plan': {'entry_conditions': ['自动复核趋势及最新证据。'],
                                    'exit_conditions': ['趋势失效后撤出研究候选。'],
                                    'steps': ['立刻全仓买入'], 'position_limit': '100%'}}
                for code in codes if code not in omit]}
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(body, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}}


class AutomaticAIResearchTests(unittest.TestCase):
    def test_disabled_missing_key_and_missing_evidence_make_no_paid_requests(self):
        report = evidence_report()
        for config, expected in [({}, 'not_configured'), ({**CONFIG, 'enabled': False}, 'disabled')]:
            with self.subTest(expected=expected), patch('research_auto_ai.provider_json') as paid:
                result = enrich_auto_report(report, config=config)
                paid.assert_not_called()
                self.assertEqual(result['ai_research']['status'], expected)
                self.assertFalse(result['automatic']['paid_api_calls'])
        report['snapshot']['funds'][0]['history'] = []
        with patch('research_auto_ai.provider_json') as paid:
            result = enrich_auto_report(report, config=CONFIG)
        paid.assert_not_called()
        self.assertEqual(result['ai_research']['status'], 'no_evidence')

    def test_all_96_funds_are_batched_and_usage_measures_actual_narratives(self):
        report = evidence_report(96)
        lock, batches, active, peak = threading.Lock(), [], 0, 0
        def requester(_, codes, config):
            nonlocal active, peak
            with lock:
                batches.append(codes)
                active += 1
                peak = max(peak, active)
            result = response_for(codes)
            with lock:
                active -= 1
            return result
        result = enrich_auto_report(report, config=CONFIG, requester=requester)
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'completed')
        self.assertEqual(meta['target_count'], 96)
        self.assertEqual(meta['analyzed_count'], 96)
        self.assertEqual(meta['request_count'], 12)
        self.assertEqual(meta['requests_succeeded'], 12)
        self.assertEqual(meta['usage']['total_tokens'], 1800)
        self.assertTrue(all(len(batch) <= 8 for batch in batches))
        self.assertLessEqual(peak, 2)
        self.assertEqual(result['engine'], 'automatic')
        self.assertTrue(result['automatic']['paid_api_calls'])
        self.assertEqual(report['analysis']['funds'][0].get('ai_reason'), None)
        self.assertNotIn(CONFIG['key'], json.dumps(result, ensure_ascii=False))

    def test_closed_window_never_calls_provider_and_keeps_quantitative_results(self):
        report = evidence_report(24)
        before = copy.deepcopy(report)
        with patch('research_auto_ai.provider_json') as paid:
            result = enrich_auto_report(report, CONFIG, can_start_request=lambda: False)
        paid.assert_not_called()
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'window_closed')
        self.assertTrue(meta['stopped_for_schedule'])
        self.assertIn('下个时段重新采集证据', meta['stopped_reason'])
        self.assertEqual(meta['target_count'], 24)
        self.assertEqual(meta['requested_count'], 0)
        self.assertEqual(meta['requested_codes'], [])
        self.assertEqual(meta['analyzed_count'], 0)
        self.assertEqual(meta['request_count'], 0)
        self.assertEqual(meta['requests_attempted'], 0)
        self.assertEqual(meta['requests_succeeded'], 0)
        self.assertEqual(meta['usage']['total_tokens'], 0)
        self.assertTrue(meta['usage_complete'])
        self.assertFalse(meta['terminal_error'])
        self.assertEqual(meta['error'], '')
        self.assertEqual(meta['errors'], [])
        self.assertFalse(result['automatic']['paid_api_calls'])
        self.assertEqual(result['analysis'], before['analysis'])
        self.assertEqual(report, before)

    def test_final_gate_after_payload_preparation_blocks_request_at_stop_time(self):
        now = [datetime.fromisoformat('2026-10-30T14:59:59+08:00')]
        stop = datetime.fromisoformat('2026-10-30T15:00:00+08:00')
        evidence = automatic_ai._batch_evidence
        def payload_crosses_stop(*args):
            result = evidence(*args)
            now[0] = stop
            return result
        with patch('research_auto_ai._batch_evidence', side_effect=payload_crosses_stop), \
             patch('research_auto_ai.provider_json') as paid:
            result = enrich_auto_report(evidence_report(8), CONFIG,
                                        can_start_request=lambda: now[0] < stop)
        paid.assert_not_called()
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'window_closed')
        self.assertEqual(meta['request_count'], 0)
        self.assertEqual(meta['requested_count'], 0)
        self.assertFalse(result['automatic']['paid_api_calls'])

    def test_two_inflight_requests_finish_but_no_later_wave_starts_after_stop(self):
        now = [datetime.fromisoformat('2026-10-30T14:59:59+08:00')]
        stop = now[0] + timedelta(seconds=1)
        lock, both_started, release = threading.Lock(), threading.Event(), threading.Event()
        calls, outputs, failures = [], [], []
        def requester(_, codes, config):
            with lock:
                calls.append(tuple(codes))
                if len(calls) == 2:
                    both_started.set()
            if not release.wait(3):
                raise RuntimeError('offline test timed out')
            return response_for(codes)
        def run():
            try:
                outputs.append(enrich_auto_report(evidence_report(40), CONFIG, requester=requester,
                                                   can_start_request=lambda: now[0] < stop))
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(both_started.wait(2))
            now[0] = stop
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(calls), 2)
        result, = outputs
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'window_closed')
        self.assertTrue(meta['stopped_for_schedule'])
        self.assertFalse(meta['terminal_error'])
        self.assertEqual(meta['target_count'], 40)
        self.assertEqual(meta['request_count'], 2)
        self.assertEqual(meta['requests_attempted'], 2)
        self.assertEqual(meta['requests_succeeded'], 2)
        self.assertEqual(meta['requested_count'], 16)
        self.assertEqual(meta['requested_codes'], [f'{index:06d}' for index in range(1, 17)])
        self.assertEqual(meta['analyzed_count'], 16)
        self.assertEqual(meta['usage'], {'prompt_tokens': 200, 'completion_tokens': 100, 'total_tokens': 300})
        self.assertTrue(meta['usage_complete'])
        self.assertEqual(result['automatic']['paid_api_call_count'], 2)
        self.assertTrue(all(row.get('ai_reason') for row in result['analysis']['funds'][:16]))
        self.assertTrue(all('ai_reason' not in row for row in result['analysis']['funds'][16:]))

    def test_already_sent_last_wave_can_finish_as_completed_after_stop(self):
        allowed = [True]
        calls, lock, both_started = [], threading.Lock(), threading.Event()
        def requester(_, codes, config):
            with lock:
                calls.append(tuple(codes))
                if len(calls) == 2:
                    allowed[0] = False
                    both_started.set()
            if not both_started.wait(2):
                raise RuntimeError('offline test timed out')
            return response_for(codes)
        result = enrich_auto_report(evidence_report(16), CONFIG, requester=requester,
                                    can_start_request=lambda: allowed[0])
        meta = result['ai_research']
        self.assertEqual(len(calls), 2)
        self.assertEqual(meta['status'], 'completed')
        self.assertFalse(meta['stopped_for_schedule'])
        self.assertEqual(meta['analyzed_count'], 16)
        self.assertEqual(meta['requested_count'], 16)
        self.assertEqual(meta['usage']['total_tokens'], 300)

    def test_config_superseded_takes_precedence_over_closed_window(self):
        current, window = [True], [True]
        calls = []
        def requester(_, codes, config):
            calls.append(tuple(codes))
            current[0] = window[0] = False
            return response_for(codes)
        result = enrich_auto_report(evidence_report(40), CONFIG, requester=requester,
                                    is_current=lambda: current[0], can_start_request=lambda: window[0])
        meta = result['ai_research']
        self.assertEqual(meta['status'], 'superseded')
        self.assertFalse(meta['stopped_for_schedule'])
        self.assertFalse(meta['terminal_error'])
        self.assertEqual(meta['analyzed_count'], 0)
        self.assertEqual(meta['request_count'], len(calls))
        self.assertEqual(meta['requested_count'], sum(len(batch) for batch in calls))
        self.assertEqual(meta['usage']['total_tokens'], 150 * len(calls))
        self.assertTrue(all('ai_reason' not in row for row in result['analysis']['funds']))

    def test_window_gate_failure_is_closed_and_does_not_echo_callback_error(self):
        def failed_gate():
            raise RuntimeError('must not echo ' + CONFIG['key'])
        with patch('research_auto_ai.provider_json') as paid:
            result = enrich_auto_report(evidence_report(), CONFIG, can_start_request=failed_gate)
        paid.assert_not_called()
        self.assertEqual(result['ai_research']['status'], 'window_closed')
        self.assertEqual(result['ai_research']['request_count'], 0)
        self.assertNotIn(CONFIG['key'], json.dumps(result, ensure_ascii=False))

    def test_model_cannot_raise_scores_promote_blocked_funds_or_replace_execution_plan(self):
        report = evidence_report(2)
        report['analysis']['funds'][1]['action'] = '暂缓新增'
        original_plan = copy.deepcopy(report['analysis']['funds'][0]['operation_plan'])
        result = enrich_auto_report(report, CONFIG, requester=lambda _, codes, config: response_for(codes))
        first, second = result['analysis']['funds']
        self.assertEqual(first['score'], 80)
        self.assertEqual(first['action'], '7 天以上研究候选')
        self.assertEqual(second['action'], '暂缓新增')
        self.assertFalse(first['execution_eligible'])
        self.assertEqual(first['operation_plan']['steps'], original_plan['steps'])
        self.assertEqual(first['operation_plan'].get('position_limit'), original_plan.get('position_limit'))
        self.assertNotIn('fabricated-source', first['evidence_ids'])
        self.assertIn('支持', first['ai_reason'])

    def test_ai_may_conservatively_downgrade_research_candidate(self):
        result = enrich_auto_report(evidence_report(), CONFIG,
                                    requester=lambda _, codes, config: response_for(codes, action='暂缓新增'))
        self.assertEqual(result['analysis']['funds'][0]['action'], '暂缓新增')
        self.assertIn('不安排', result['analysis']['funds'][0]['operation_plan']['steps'][0])
        self.assertEqual(result['strategy']['candidates'], [])
        self.assertEqual(result['strategy']['ai_downgraded_codes'], ['000001'])
        self.assertIn('没有保留', result['analysis']['summary'])

    def test_partial_and_invalid_narratives_do_not_claim_full_success(self):
        result = enrich_auto_report(evidence_report(2), CONFIG,
                                    requester=lambda _, codes, config: response_for(codes, omit=('000002',)))
        self.assertEqual(result['ai_research']['status'], 'partial')
        self.assertEqual(result['ai_research']['analyzed_count'], 1)
        self.assertNotIn('ai_reason', result['analysis']['funds'][1])
        invalid = response_for(['000001'])
        content = json.loads(invalid['choices'][0]['message']['content'])
        content['funds'][0]['evidence_ids'] = ['fabricated-source']
        invalid['choices'][0]['message']['content'] = json.dumps(content)
        result = enrich_auto_report(evidence_report(), CONFIG, requester=lambda *args: invalid)
        self.assertEqual(result['ai_research']['status'], 'error')
        self.assertEqual(result['ai_research']['analyzed_count'], 0)
        self.assertNotIn('ai_reason', result['analysis']['funds'][0])

    def test_authentication_error_stops_after_current_wave_and_never_leaks_error_body(self):
        calls = []
        def reject(_, codes, config):
            calls.append(codes)
            error = RuntimeError('API Key 无效 ' + CONFIG['key'])
            error.status_code = 401
            raise error
        result = enrich_auto_report(evidence_report(40), CONFIG, requester=reject)
        self.assertLessEqual(len(calls), 2)
        self.assertEqual(result['ai_research']['status'], 'error')
        self.assertTrue(result['ai_research']['terminal_error'])
        self.assertTrue(result['automatic']['paid_api_calls'])
        self.assertFalse(result['ai_research']['usage_complete'])
        self.assertNotIn(CONFIG['key'], json.dumps(result, ensure_ascii=False))

    def test_known_but_unprovided_or_unrelated_sources_do_not_count_as_fund_research(self):
        report = evidence_report(10)
        report['snapshot']['news'] = [{'title': '市场新闻', 'category': '财经新闻', 'source_id': 'market-news'}]
        def requester(_, codes, config):
            response = response_for(codes)
            content = json.loads(response['choices'][0]['message']['content'])
            for fund in content['funds']:
                if fund['code'] == '000009':
                    fund['evidence_ids'] = ['nav:000001']
                if fund['code'] == '000010':
                    fund['evidence_ids'] = ['market-news']
            response['choices'][0]['message']['content'] = json.dumps(content)
            return response
        result = enrich_auto_report(report, CONFIG, requester=requester)
        self.assertEqual(result['ai_research']['status'], 'partial')
        self.assertEqual(result['ai_research']['analyzed_count'], 8)
        self.assertNotIn('ai_reason', result['analysis']['funds'][8])
        self.assertNotIn('ai_reason', result['analysis']['funds'][9])

    def test_revision_change_discards_inflight_narrative_and_stops_new_batches(self):
        current = [True]
        calls = []
        def requester(_, codes, config):
            calls.append(codes)
            current[0] = False
            return response_for(codes)
        result = enrich_auto_report(evidence_report(40), CONFIG, is_current=lambda: current[0], requester=requester)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['ai_research']['status'], 'superseded')
        self.assertEqual(result['ai_research']['analyzed_count'], 0)
        self.assertTrue(result['automatic']['paid_api_calls'])
        self.assertNotIn('ai_reason', result['analysis']['funds'][0])

    def test_provider_payload_uses_existing_public_news_and_fund_notice_evidence(self):
        report = evidence_report()
        report['snapshot']['news'] = [
            {'title': '000001基金公告', 'category': '基金公告', 'source_id': 'notice:000001', 'url': 'https://example.test/notice'},
            {'title': '市场公开新闻', 'category': '财经新闻', 'source_id': 'news:1', 'url': 'https://example.test/news'}]
        with patch('research_auto_ai.provider_json', return_value=response_for(['000001'])) as paid:
            enrich_auto_report(report, CONFIG)
        payload = paid.call_args.args[2]
        evidence = json.loads(payload['messages'][1]['content'])
        self.assertEqual(len(evidence['automatic_evidence']['news']), 2)
        self.assertNotIn('history', evidence['automatic_evidence']['funds'][0])
        self.assertNotIn(CONFIG['key'], payload['messages'][1]['content'])

    def test_payload_distinguishes_historical_score_and_effective_index_with_holdings_proof(self):
        report = evidence_report()
        report['quant'][0]['score'] = 93
        report['analysis']['funds'][0].update(score=93, recommendation_index=71, board_match={
            'status': 'matched', 'board_id': 'sector_semiconductor',
            'matched_weight_pct': 30, 'disclosed_weight_pct': 50, 'coverage_pct': 60,
            'report_date': '2026-09-30', 'source_id': 'holdings:000001',
            'source_url': 'https://example.test/holdings/000001',
            'limitations': '前十大股票持仓不代表实时或完整仓位。'})
        report['snapshot']['funds'][0]['holdings'] = {
            'status': 'ok', 'report_date': '2026-09-30', 'source_id': 'holdings:000001',
            'source_url': 'https://example.test/holdings/000001',
            'rows': [{'code': '688001', 'name': '披露测试股票', 'weight_pct': 30, 'tags': ['半导体']}],
            'disclosed_weight_pct': 50, 'scope': '前十大股票，非完整或实时仓位'}
        report['snapshot']['sources'] = [
            {'id': 'holdings:000001', 'status': 'ok', 'as_of': '2026-09-30',
             'url': 'https://example.test/holdings/000001'},
            {'id': 'holdings:999999', 'status': 'ok', 'url': 'https://example.test/unrelated'}]
        with patch('research_auto_ai.provider_json', return_value=response_for(['000001'])) as paid:
            result = enrich_auto_report(report, CONFIG)
        self.assertEqual(paid.call_count, 1)
        payload = paid.call_args.args[2]
        evidence = json.loads(payload['messages'][1]['content'])
        context = evidence['fund_decision_context'][0]
        self.assertEqual((context['score'], context['recommendation_index']), (93, 71))
        self.assertEqual(context['board']['label'], '半导体')
        self.assertEqual(context['board_match']['report_date'], '2026-09-30')
        self.assertEqual(context['board_match']['matched_weight_pct'], 30)
        self.assertEqual({row['id'] for row in evidence['automatic_evidence']['sources']}, {'holdings:000001'})
        self.assertEqual(evidence['automatic_evidence']['funds'][0]['holdings']['rows'][0]['weight_pct'], 30)
        self.assertNotIn('history', evidence['automatic_evidence']['funds'][0])
        self.assertIn('历史研究分', evidence['score_definitions']['score'])
        self.assertIn('null', evidence['score_definitions']['recommendation_index'])
        self.assertIn('必须写“本批”', payload['messages'][0]['content'])
        self.assertNotIn(CONFIG['key'], payload['messages'][1]['content'])
        self.assertEqual((result['analysis']['funds'][0]['score'],
                          result['analysis']['funds'][0]['recommendation_index']), (93, 71))

    def test_own_holdings_citation_counts_but_another_funds_holdings_do_not(self):
        report = evidence_report(10)
        for fund in report['snapshot']['funds']:
            fund['holdings'] = {'status': 'ok', 'source_id': 'holdings:' + fund['code'],
                                'report_date': '2026-09-30',
                                'rows': [{'code': '688001', 'name': '测试股票', 'weight_pct': 10}]}
            report['snapshot']['sources'].append({'id': 'holdings:' + fund['code'], 'status': 'ok'})
        def requester(_, codes, config):
            response = response_for(codes)
            content = json.loads(response['choices'][0]['message']['content'])
            for fund in content['funds']:
                fund['evidence_ids'] = ['holdings:' + fund['code']]
                if fund['code'] == '000010':
                    fund['evidence_ids'] = ['holdings:000009']
            response['choices'][0]['message']['content'] = json.dumps(content)
            return response
        result = enrich_auto_report(report, CONFIG, requester=requester)
        self.assertEqual(result['ai_research']['status'], 'partial')
        self.assertEqual(result['ai_research']['request_count'], 2)
        self.assertEqual(result['ai_research']['analyzed_count'], 9)
        self.assertIn('holdings:000009', result['analysis']['funds'][8]['evidence_ids'])
        self.assertNotIn('ai_reason', result['analysis']['funds'][9])

    def test_failed_holdings_source_cannot_support_fund_research(self):
        report = evidence_report()
        report['snapshot']['funds'][0]['holdings'] = {
            'status': 'error', 'source_id': 'holdings:000001', 'rows': []}
        report['snapshot']['sources'] = [{'id': 'holdings:000001', 'status': 'error'}]
        response = response_for(['000001'])
        content = json.loads(response['choices'][0]['message']['content'])
        content['funds'][0]['evidence_ids'] = ['holdings:000001']
        response['choices'][0]['message']['content'] = json.dumps(content)
        result = enrich_auto_report(report, CONFIG, requester=lambda *args: response)
        self.assertEqual(result['ai_research']['status'], 'error')
        self.assertNotIn('ai_reason', result['analysis']['funds'][0])

    def test_each_of_eight_funds_receives_latest_notice_excerpt_before_extra_titles(self):
        report = evidence_report(8)
        report['snapshot']['warnings'] = ['公告正文仅为节选，未读取全文，不能视为全面尽调。']
        for fund in report['snapshot']['funds']:
            code = fund['code']
            # Grouped source order previously allowed the first four funds'
            # history to consume all24 notice slots.
            for day in range(1, 7):
                report['snapshot']['news'].append({
                    'title': code + f' 第{day}号公告', 'fund_code': code,
                    'category': '基金公告', 'source_id': 'announcements_' + code,
                    'published_at': f'2026-10-{day:02d}',
                    'summary': '公告分类：定期报告。',
                    'content': (code + '最新公告正文：' + '风' * 3000) if day == 6 else '',
                    'content_scope': '公告正文节选，非完整报告' if day == 6 else '标题与发布日期，正文未读取'})
        with patch('research_auto_ai.provider_json', return_value=response_for([fund['code'] for fund in report['snapshot']['funds']])) as paid:
            enrich_auto_report(report, CONFIG)
        payload = paid.call_args.args[2]
        evidence = json.loads(payload['messages'][1]['content'])['automatic_evidence']
        self.assertEqual(len(evidence['news']), 24)
        self.assertEqual({row['fund_code'] for row in evidence['news'][:8]},
                         {fund['code'] for fund in report['snapshot']['funds']})
        self.assertTrue(all(row['published_at'] == '2026-10-06' for row in evidence['news'][:8]))
        self.assertTrue(all(len(row['content']) == 2400 for row in evidence['news'][:8]))
        self.assertTrue(all('非完整报告' in row['content_scope'] for row in evidence['news'][:8]))
        self.assertTrue(all(row['latest_has_excerpt'] and row['supplied_notice_count'] == 3
                            for row in evidence['notice_coverage']))
        self.assertIn('未读取全文', evidence['warnings'][0])

    def test_missing_notice_excerpt_is_explicit_in_batch_evidence(self):
        report = evidence_report(2)
        report['snapshot']['news'] = [{'title': '000001公告', 'fund_code': '000001',
                                      'category': '基金公告', 'source_id': 'announcements_000001',
                                      'summary': '公告分类：定期报告。',
                                      'content_scope': '标题与发布日期，正文未读取'}]
        with patch('research_auto_ai.provider_json', return_value=response_for(['000001', '000002'])) as paid:
            enrich_auto_report(report, CONFIG)
        evidence = json.loads(paid.call_args.args[2]['messages'][1]['content'])['automatic_evidence']
        self.assertFalse(evidence['notice_coverage'][0]['latest_has_excerpt'])
        self.assertEqual(evidence['notice_coverage'][1]['supplied_notice_count'], 0)
        self.assertTrue(any('未取得正文节选' in message for message in evidence['warnings']))
        self.assertTrue(any('本批未取得基金公告' in message for message in evidence['warnings']))


class AutomaticAIEngineTests(unittest.TestCase):
    def test_schedule_only_change_waits_for_next_slot_before_ai(self):
        config = dict(CONFIG)
        config['schedule'] = {'mode': 'interval', 'interval_minutes': 60,
                              'daily_time': '15:30', 'timezone': 'Asia/Shanghai'}
        engine = AutoResearchEngine(config_provider=lambda: dict(config))
        try:
            # Do not start the real scheduler in this unit test.
            engine.start = lambda: None
            engine.config_changed(schedule_only=True)
            due = engine._ai_due(dict(config))
            self.assertIsNotNone(due)
            self.assertGreater((due - datetime.now(CHINA)).total_seconds(), 50 * 60)
        finally:
            engine.close()

    def test_config_save_during_scan_schedules_immediate_followup_and_discards_old_revision(self):
        config = dict(CONFIG)
        first_entered, release_first, second_completed = threading.Event(), threading.Event(), threading.Event()
        calls, ai_revisions = [], []
        def runner(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                first_entered.set()
                release_first.wait(3)
            return evidence_report()
        def ai_runner(report, config, progress, is_current, can_start_request=None):
            ai_revisions.append((config['revision'], is_current()))
            result = enrich_auto_report(report, config, is_current=is_current,
                                         requester=lambda _, codes, cfg: response_for(codes),
                                         can_start_request=can_start_request)
            if len(ai_revisions) == 2:
                second_completed.set()
            return result
        engine = AutoResearchEngine(interval=3600, runner=runner, config_provider=lambda: dict(config), ai_runner=ai_runner)
        try:
            engine.start()
            self.assertTrue(first_entered.wait(1))
            config['revision'] = 'revision-2'
            engine.config_changed()
            release_first.set()
            self.assertTrue(second_completed.wait(3))
            engine._worker.join(2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(ai_revisions, [('revision-1', False), ('revision-2', True)])
            self.assertEqual(engine.status()['report']['ai_research']['revision'], 'revision-2')
        finally:
            release_first.set()
            engine.close()

    def test_status_and_restore_never_call_provider_or_claim_old_ai_is_fresh(self):
        config = dict(CONFIG)
        report = enrich_auto_report(evidence_report(), config, requester=lambda _, codes, cfg: response_for(codes))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = AutoResearchEngine(path, config_provider=lambda: dict(config))
            engine._persist(report, now_iso())
            restored = AutoResearchEngine(path, config_provider=lambda: dict(config))
            with patch('research_auto_ai.provider_json') as paid:
                self.assertEqual(restored.status()['report']['ai_research']['status'], 'stale')
                paid.assert_not_called()
            engine._state.update(status='ready', report=report, completed_at=now_iso())
            config['revision'] = 'replacement'
            with patch('research_auto_ai.provider_json') as paid:
                state = engine.status()
                paid.assert_not_called()
            self.assertEqual(state['report']['ai_research']['status'], 'stale')
            self.assertNotIn('ai_reason', state['report']['analysis']['funds'][0])
            self.assertNotIn(CONFIG['key'], path.read_text(encoding='utf-8'))
            engine.close()
            restored.close()

    def test_auth_failure_is_not_retried_on_later_scans_until_revision_changes(self):
        config = dict(CONFIG)
        engine = AutoResearchEngine(runner=lambda **kwargs: evidence_report(), config_provider=lambda: dict(config))
        with patch('research_auto_ai.provider_json', side_effect=RuntimeError('API Key 无效')) as paid:
            engine.request_scan()
            engine._worker.join(2)
            self.assertEqual(paid.call_count, 1)
            engine.request_scan()
            engine._worker.join(2)
            self.assertEqual(paid.call_count, 1)
            self.assertTrue(engine.status()['report']['ai_research']['blocked_until_config_change'])
            config['revision'] = 'fixed-key'
            engine.request_scan()
            engine._worker.join(2)
            self.assertEqual(paid.call_count, 2)
        engine.close()


if __name__ == '__main__':
    unittest.main()
