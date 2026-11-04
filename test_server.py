from test_holdings_fixtures import portfolio
import copy
import gzip
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock
from pathlib import Path

from server import Handler, ROOT
from research_service import DEFAULT_PREFS, ai_analysis, constrain_ai, parse_codes, run_research, validate_request
from research_ai_config import AIConfigStore

OPEN = urllib.request.urlopen
SNAPSHOT = {'as_of': '2026-10-29T17:00:00+08:00', 'funds': [], 'market': [], 'news': [], 'sources': [], 'warnings': []}


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'dist')))
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.server.allowed_hosts = {f'127.0.0.1:{cls.server.server_port}'}
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def send(self, payload=None, origin=None, path='/api/analyze'):
        data = {} if payload is None else payload
        request = urllib.request.Request(self.origin + path, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'Origin': origin or self.origin})
        try:
            response = OPEN(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read())

    def test_health_and_page(self):
        with OPEN(self.origin + '/api/health') as r:
            self.assertEqual(json.load(r)['version'], 5)
        with OPEN(self.origin + '/index.html') as r:
            self.assertIn('sector-research.js', r.read().decode())
            self.assertIn("connect-src 'self'", r.headers['Content-Security-Policy'])

    def test_auto_status_and_refresh_are_background_only_and_origin_guarded(self):
        engine = Mock()
        engine.status.return_value = {'status': 'running', 'stage': '扫描目录', 'report': None}
        self.server.auto_engine = engine
        with OPEN(self.origin + '/api/auto/status') as response:
            self.assertEqual(json.load(response)['status'], 'running')
        engine.start.assert_called_once()
        request = urllib.request.Request(self.origin + '/api/auto/refresh', data=b'{}',
                                         headers={'Content-Type': 'application/json', 'Origin': 'https://external.invalid'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            OPEN(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        engine.request_scan.assert_not_called()
        request.add_header('Origin', self.origin)
        with OPEN(request) as response:
            self.assertEqual(response.code, 202)
        engine.request_scan.assert_called_once_with(refresh=False)
        del self.server.auto_engine

    def test_summary_route_omits_report_and_report_route_negotiates_gzip(self):
        engine = Mock()
        engine.status.side_effect = lambda **options: (
            {'status': 'ready', 'report': None, 'has_report': True, 'report_version': 'v1'}
            if options.get('include_report') is False else
            {'status': 'ready', 'report': {'evidence': '持仓证据' * 5000}})
        self.server.auto_engine = engine
        self.addCleanup(lambda: delattr(self.server, 'auto_engine'))
        with OPEN(self.origin + '/api/auto/status?summary=1') as response:
            state = json.load(response)
            self.assertIsNone(state['report'])
            self.assertEqual(state['report_version'], 'v1')
        engine.status.assert_called_with(include_report=False)
        request = urllib.request.Request(self.origin + '/api/auto/report', headers={'Accept-Encoding': 'gzip'})
        with OPEN(request) as response:
            compressed = response.read()
            self.assertEqual(response.headers['Content-Encoding'], 'gzip')
            self.assertEqual(int(response.headers['Content-Length']), len(compressed))
            self.assertEqual(json.loads(gzip.decompress(compressed))['report']['evidence'], '持仓证据' * 5000)
            self.assertLess(len(compressed), 1500)
        for encoding in ('gzip;q=0', 'gzip;q=invalid'):
            request = urllib.request.Request(self.origin + '/api/auto/report', headers={'Accept-Encoding': encoding})
            with OPEN(request) as response:
                self.assertIsNone(response.headers.get('Content-Encoding'))
                self.assertIn('report', json.load(response))

    @patch('server.run_research')
    def test_origin_and_parameter_gate_precedes_research(self, research):
        self.assertEqual(self.send(origin='https://external.invalid')[0], 403)
        for payload in [{'codes': ['../../../']}, {'prefs': {'pos': -5}}, {'key': 'space key'}, {'prefs': {'min': True}}, {'prefs': {'min': 'nan'}}]:
            self.assertEqual(self.send(payload)[0], 400)
        research.assert_not_called()

    @patch('server.run_research')
    def test_no_manual_context_or_api_key_required(self, research):
        research.return_value = {'engine': 'quant', 'analysis': {'summary': '自动数据决策'}}
        code, body = self.send({'codes': ['110020'], 'prefs': DEFAULT_PREFS})
        self.assertEqual(code, 200)
        self.assertEqual(body['engine'], 'quant')
        self.assertEqual(research.call_args.kwargs['key'], '')
        self.assertEqual(research.call_args.kwargs['context'], '')

    @patch('server.run_research')
    def test_get_preview_applies_query_preferences_without_paid_key(self, research):
        research.return_value = {'ok': True}
        query = urllib.parse.urlencode({'codes': '110020', 'pos': 15, 'min': 80, 'risk': '均衡配置'})
        with OPEN(self.origin + '/api/research?' + query) as response:
            self.assertEqual(response.code, 200)
        self.assertEqual(research.call_args.args[1], {'risk': '均衡配置', 'pos': 15, 'min': 80})
        self.assertNotIn('key', research.call_args.kwargs)

    def attach_ai(self, probe=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        # Synthetic offline key and reversible test crypto; never touches production credentials.
        self.server.ai_config = AIConfigStore(Path(folder.name) / 'config.json',
            encrypt=lambda value: b'test:' + value[::-1], decrypt=lambda value: value[5:][::-1],
            probe=probe or Mock(return_value={'models': ['deepseek-flash', 'deepseek-v4-pro']}))
        self.server.auto_engine = Mock()
        self.server.auto_engine.status.return_value = {'status': 'idle', 'report': None}
        self.addCleanup(lambda: delattr(self.server, 'ai_config'))
        self.addCleanup(lambda: delattr(self.server, 'auto_engine'))
        return self.server.ai_config

    def test_saved_ai_config_retains_blank_key_and_returns_only_public_status(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        with OPEN(self.origin + '/api/ai/config') as response:
            self.assertFalse(json.load(response)['configured'])
        secret = 'sk-synthetic-offline-1234'
        code, body = self.send({'key': secret, 'model': 'deepseek-flash', 'enabled': True}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['effective_enabled'])
        self.assertTrue(body['connection']['ok'])
        self.assertNotIn(secret, json.dumps(body))
        self.assertNotIn('key', body['config'])
        probe.assert_called_once_with(secret, 'deepseek-flash')
        self.server.auto_engine.config_changed.assert_called_once()
        code, body = self.send({'key': '  ', 'enabled': True}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['effective_enabled'])
        self.assertEqual(store.snapshot()['key'], secret)
        restored = AIConfigStore(store.path, encrypt=store._encrypt, decrypt=store._decrypt, probe=probe)
        self.assertTrue(restored.status()['effective_enabled'])
        self.assertEqual(restored.snapshot()['key'], secret)

    def test_ai_failure_is_sanitized_and_blocks_automatic_calls(self):
        secret = 'sk-synthetic-only-5678'
        probe = Mock(side_effect=RuntimeError('upstream echoed ' + secret))
        store = self.attach_ai(probe)
        code, body = self.send({'key': secret, 'enabled': True}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['configured'])
        self.assertFalse(body['config']['effective_enabled'])
        self.assertFalse(body['connection']['ok'])
        self.assertNotIn(secret, json.dumps(body))
        self.assertFalse(store.snapshot()['enabled'])
        self.server.auto_engine.config_changed.assert_called_once()

    def test_schedule_only_save_without_key_is_persistent_and_never_probes(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        schedule = {'mode': 'scheduled_interval', 'interval_minutes': 60,
                    'daily_time': '09:30', 'end_time': None, 'timezone': 'Asia/Shanghai'}
        code, body = self.send({'schedule': schedule}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertEqual(body['config']['schedule'], schedule)
        self.assertFalse(body['config']['configured'])
        self.assertFalse(body['config']['enabled'])
        self.assertTrue(body['connection']['skipped'])
        with OPEN(self.origin + '/api/ai/config') as response:
            self.assertEqual(json.load(response)['schedule'], schedule)
        restored = AIConfigStore(store.path, encrypt=store._encrypt, decrypt=store._decrypt, probe=probe)
        self.assertEqual(restored.snapshot()['schedule'], schedule)
        self.server.auto_engine.config_changed.assert_called_once_with(schedule_only=True)
        probe.assert_not_called()

    def test_schedule_save_preserves_verified_key_and_enabled_without_probe(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        secret = 'sk-synthetic-schedule-1234'
        store.configure(key=secret, enabled=True)
        previous = store.verify()
        probe.reset_mock()
        schedule = {'mode': 'daily', 'interval_minutes': 120,
                    'daily_time': '15:30', 'end_time': None, 'timezone': 'Asia/Shanghai'}
        code, body = self.send({'key': '', 'model': 'deepseek-flash', 'enabled': True,
                               'schedule': schedule}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['effective_enabled'])
        self.assertEqual(body['config']['verification'], previous['verification'])
        self.assertEqual(body['config']['last_verified_at'], previous['last_verified_at'])
        self.assertEqual(store.snapshot()['key'], secret)
        self.assertNotIn(secret, json.dumps(body))
        self.assertEqual(body['config']['schedule'], schedule)
        self.assertTrue(body['connection']['skipped'])
        probe.assert_not_called()
        self.server.auto_engine.config_changed.assert_called_once_with(schedule_only=True)

    def test_schedule_validation_rejects_before_mutation_probe_or_engine_notice(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        previous = store.status()
        for schedule in (None, {}, {'mode': 'unsupported'}, {'mode': 'interval', 'interval_minutes': 0},
                         {'mode': 'interval', 'interval_minutes': 1441},
                         {'mode': 'interval', 'interval_minutes': True},
                         {'mode': 'interval', 'interval_minutes': 37.0},
                         {'mode': 'interval', 'interval_minutes': '37'},
                         {'mode': 'daily', 'daily_time': '24:00'}, {'mode': 'daily', 'daily_time': '9:00'},
                         {'mode': 'daily', 'end_time': '24:00'}, {'mode': 'daily', 'end_time': '9:00'},
                         {'mode': 'daily', 'end_time': ''}, {'mode': 'daily', 'end_time': '09:30:00'},
                         {'mode': 'daily', 'end_time': '０９:３０'}, {'mode': 'daily', 'end_time': 930},
                         {'mode': 'scheduled_interval', 'daily_time': '09:30', 'end_time': '09:30'},
                         {'mode': 'scheduled_interval', 'timezone': 'UTC'}, {'mode': 'daily', 'unknown': 1}):
            with self.subTest(schedule=schedule):
                code, body = self.send({'schedule': schedule}, path='/api/ai/config')
                self.assertEqual(code, 400)
                self.assertIn('运行时间', body['error'])
                self.assertEqual(store.status(), previous)
                self.assertFalse(store.path.exists())
        probe.assert_not_called()
        self.server.auto_engine.config_changed.assert_not_called()

    def test_enabling_with_schedule_still_requires_and_verifies_credentials(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        schedule = {'mode': 'scheduled_interval', 'interval_minutes': 30,
                    'daily_time': '09:30', 'end_time': None, 'timezone': 'Asia/Shanghai'}
        self.assertEqual(self.send({'enabled': True, 'schedule': schedule}, path='/api/ai/config')[0], 400)
        self.assertFalse(store.path.exists())
        code, body = self.send({'key': 'sk-synthetic-offline-time-9876', 'enabled': True,
                               'schedule': schedule}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['effective_enabled'])
        self.assertTrue(body['connection']['ok'])
        self.assertEqual(body['config']['schedule'], schedule)
        probe.assert_called_once()

    def test_arbitrary_integer_intervals_and_end_times_roundtrip_without_credentials_or_probe(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        for interval in (1, 37, 45, 1439, 1440):
            schedule = {'mode': 'scheduled_interval', 'interval_minutes': interval,
                        'daily_time': '22:00', 'end_time': '06:00', 'timezone': 'Asia/Shanghai'}
            with self.subTest(interval=interval):
                code, body = self.send({'schedule': schedule}, path='/api/ai/config')
                self.assertEqual(code, 200)
                self.assertEqual(body['config']['schedule'], schedule)
                self.assertFalse(body['config']['configured'])
                self.assertFalse(body['config']['effective_enabled'])
                self.assertTrue(body['connection']['skipped'])
                with OPEN(self.origin + '/api/ai/config') as response:
                    self.assertEqual(json.load(response)['schedule'], schedule)
                restored = AIConfigStore(store.path, encrypt=store._encrypt, decrypt=store._decrypt, probe=probe)
                self.assertEqual(restored.status()['schedule'], schedule)
        self.assertEqual(self.server.auto_engine.config_changed.call_count, 5)
        self.assertTrue(all(call.kwargs == {'schedule_only': True}
                            for call in self.server.auto_engine.config_changed.call_args_list))
        probe.assert_not_called()

    def test_legacy_missing_end_normalizes_to_null_and_invalid_window_does_not_replace_file(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        legacy = {'mode': 'daily', 'interval_minutes': 45,
                  'daily_time': '09:30', 'timezone': 'Asia/Shanghai'}
        code, body = self.send({'schedule': legacy}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertEqual(body['config']['schedule'], {**legacy, 'end_time': None})
        previous, saved = store.status(), store.path.read_bytes()
        self.server.auto_engine.config_changed.reset_mock()
        for end in ('09:30', '24:01', '6:00', False, ['15:00']):
            with self.subTest(end=end):
                code, body = self.send({'schedule': {**legacy, 'end_time': end}}, path='/api/ai/config')
                self.assertEqual(code, 400)
                self.assertIn('运行时间', body['error'])
                self.assertEqual(store.status(), previous)
                self.assertEqual(store.path.read_bytes(), saved)
        probe.assert_not_called()
        self.server.auto_engine.config_changed.assert_not_called()

    def test_ai_disable_test_and_clear_never_echo_key(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        secret = 'sk-synthetic-offline-7890'
        code, body = self.send({'key': secret, 'enabled': False}, path='/api/ai/config')
        self.assertEqual(code, 200)
        self.assertTrue(body['config']['configured'])
        self.assertFalse(body['config']['effective_enabled'])
        probe.assert_not_called()
        code, body = self.send(path='/api/ai/test')
        self.assertEqual(code, 200)
        self.assertTrue(body['connection']['ok'])
        self.assertFalse(body['config']['effective_enabled'])
        code, body = self.send(path='/api/ai/clear')
        self.assertEqual(code, 200)
        self.assertFalse(body['config']['configured'])
        self.assertFalse(store.path.exists())
        self.assertEqual(store.snapshot()['key'], '')
        self.assertEqual(self.server.auto_engine.config_changed.call_count, 3)

    def test_ai_config_origin_loopback_and_parameter_guards(self):
        probe = Mock(return_value={'models': ['deepseek-flash']})
        store = self.attach_ai(probe)
        self.assertEqual(self.send({'key': 'test'}, origin='https://external.invalid', path='/api/ai/config')[0], 403)
        with patch.object(Handler, 'local_client', return_value=False):
            for path in ('/api/ai/config', '/api/ai/test', '/api/ai/clear'):
                self.assertEqual(self.send({'key': 'test'}, path=path)[0], 403)
        for payload in ([], {'key': 'bad key'}, {'key': 3}, {'enabled': True}, {'model': []}, {'enabled': 'true'}):
            self.assertEqual(self.send(payload, path='/api/ai/config')[0], 400)
        self.assertFalse(store.status()['configured'])
        probe.assert_not_called()
        self.server.auto_engine.config_changed.assert_not_called()

    @patch('server.run_research', return_value={'engine': 'ai'})
    def test_manual_uses_verified_saved_key_and_free_preview_does_not(self, research):
        store = self.attach_ai()
        secret = 'sk-synthetic-offline-abcd'
        store.configure(key=secret, model='deepseek-v4-pro', enabled=True)
        store.verify()
        code, body = self.send({'codes': ['110020'], 'use_saved_key': True})
        self.assertEqual(code, 200)
        self.assertEqual(research.call_args.kwargs['key'], secret)
        self.assertEqual(research.call_args.kwargs['model'], 'deepseek-v4-pro')
        self.assertNotIn(secret, json.dumps(body))
        self.send({'codes': ['110020'], 'use_saved_key': False})
        self.assertEqual(research.call_args.kwargs['key'], '')
        with OPEN(self.origin + '/api/research?codes=110020') as response:
            self.assertEqual(response.code, 200)
        self.assertNotIn('key', research.call_args.kwargs)


class ResearchServiceTests(unittest.TestCase):
    def test_ai_payload_preserves_separate_scores_and_disclosed_holdings_source(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['funds'] = [{'code': '110020', 'history': [{'nav': 1.2}],
                              'holdings': {'status': 'ok', 'report_date': '2026-09-30',
                                           'source_id': 'holdings:110020',
                                           'rows': [{'code': '688001', 'weight_pct': 20}]}}]
        snapshot['sources'] = [{'id': 'holdings:110020', 'status': 'ok'}]
        baseline = {'summary': 'baseline', 'market_view': '', 'risks': [], 'next_steps': [], 'funds': [
            {'code': '110020', 'score': 93, 'recommendation_index': 71, 'action': '继续观察',
             'reason': 'trend', 'invalidation': 'risk', 'evidence_ids': [],
             'operation_plan': {'steps': ['观察']}}]}
        proposed = {'summary': 'AI解释', 'market_view': '市场', 'funds': [
            {'code': '110020', 'score': 100, 'recommendation_index': 100,
             'evidence_ids': ['holdings:110020']}]}
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(proposed)}}]}
        with patch('research_service.provider_json', return_value=response) as paid:
            result = ai_analysis(snapshot, [{'code': '110020', 'score': 93}], baseline,
                                 DEFAULT_PREFS, 'test-private-key', 'deepseek-flash', '')
        evidence = json.loads(paid.call_args.args[2]['messages'][1]['content'])
        self.assertIn('历史研究分', evidence['score_definitions']['score'])
        self.assertEqual(evidence['baseline_decisions_and_operations']['funds'][0]['recommendation_index'], 71)
        self.assertNotIn('history', evidence['automatic_evidence']['funds'][0])
        self.assertEqual(evidence['automatic_evidence']['funds'][0]['holdings']['report_date'], '2026-09-30')
        self.assertEqual((result['funds'][0]['score'], result['funds'][0]['recommendation_index']), (93, 71))
        self.assertIn('holdings:110020', result['funds'][0]['evidence_ids'])
        self.assertNotIn('test-private-key', paid.call_args.args[2]['messages'][1]['content'])

    def test_codes_and_models(self):
        self.assertEqual(parse_codes('110020，110020 000216'), ['110020', '000216'])
        self.assertEqual(validate_request({'model': 'deepseek-chat'})[3], 'deepseek-flash')
        with self.assertRaises(ValueError):
            parse_codes(['110020'] * 9)

    @patch('research_service.collect_research')
    @patch('research_service.provider_json')
    def test_free_research_never_calls_paid_api(self, paid, collect):
        collect.return_value = copy.deepcopy(SNAPSHOT)
        result = run_research(['110020'], DEFAULT_PREFS)
        self.assertEqual(result['engine'], 'quant')
        self.assertIn('数据', result['analysis']['summary'])
        paid.assert_not_called()

    @patch('research_service.collect_research')
    @patch('research_service.search_news')
    @patch('research_service.ai_analysis')
    def test_ai_failure_keeps_quant_plan(self, ai, search, collect):
        collect.return_value = copy.deepcopy(SNAPSHOT)
        search.return_value = ([], [], ['联网检索不可用'])
        ai.side_effect = RuntimeError('API Key 无效')
        result = run_research(['110020'], DEFAULT_PREFS, key='test-placeholder')
        self.assertEqual(result['engine'], 'quant')
        self.assertEqual(result['ai_error'], 'API Key 无效')
        self.assertIn('联网检索不可用', result['snapshot']['warnings'])

    def test_ai_cannot_invent_fund_score_or_remove_execution_limits(self):
        baseline = {'summary': 'baseline', 'market_view': '', 'risks': ['missing data'], 'next_steps': ['wait'], 'funds': [
            {'code': '110020', 'name': '真实基金', 'score': None, 'action': '数据不足', 'reason': '资料不足', 'invalidation': '等数据', 'evidence_ids': ['nav:110020'],
             'operation_plan': {'new_position': '等待', 'steps': ['等待数据'], 'position_limit': '不超过25%'}}]}
        proposed = {'summary': 'AI解释', 'market_view': '市场', 'funds': [
            {'code': '110020', 'score': 100, 'name': '虚构名称', 'action': '立即满仓', 'reason': '补充', 'evidence_ids': ['fake'], 'operation_plan': {'steps': ['立即满仓'], 'position_limit': '100%'}},
            {'code': '999999', 'score': 99}]}
        result = constrain_ai(proposed, baseline, SNAPSHOT)
        self.assertEqual(len(result['funds']), 1)
        fund = result['funds'][0]
        self.assertIsNone(fund['score'])
        self.assertEqual(fund['name'], '真实基金')
        self.assertEqual(fund['action'], '数据不足')
        self.assertEqual(fund['operation_plan']['steps'], ['等待数据'])
        self.assertNotIn('fake', fund['evidence_ids'])

    def test_ai_can_pause_candidate_and_remove_buy_steps(self):
        baseline = {'summary': 'baseline', 'market_view': '', 'risks': [], 'next_steps': [], 'funds': [
            {'code': '110020', 'name': '真实基金', 'score': 80, 'action': '分批配置候选', 'reason': 'trend', 'invalidation': 'risk', 'evidence_ids': [],
             'operation_plan': {'new_position': '分批', 'steps': ['第一批'], 'existing_position': '未达到计划时评估分批新增', 'entry_conditions': ['通过原条件即可新增']}}]}
        proposed = {'summary': '公告风险', 'market_view': '', 'funds': [{'code': '110020', 'action': '暂缓新增'}]}
        result = constrain_ai(proposed, baseline, SNAPSHOT)
        self.assertEqual(result['funds'][0]['action'], '暂缓新增')
        self.assertIn('暂不执行', result['funds'][0]['operation_plan']['steps'][0])
        self.assertNotIn('分批新增', result['funds'][0]['operation_plan']['existing_position'])
        self.assertNotIn('通过原条件即可新增', result['funds'][0]['operation_plan']['entry_conditions'])

    @patch('research_service.collect_research')
    @patch('research_service.search_news', return_value=([], [], []))
    def test_research_sections_use_final_ai_decision_and_keep_all_funds(self, search, collect):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['funds'] = [{'code': '110020', 'name': '研究测试A', 'fund_type': '股票型', 'nav_date': '2026-10-29', 'holdings': portfolio(['软件开发'])}]
        collect.return_value = snapshot
        baseline = {'summary': '量化', 'market_view': '', 'risks': [], 'next_steps': [], 'funds': [
            {'code': '110020', 'name': '研究测试A', 'score': 80, 'action': '分批配置候选', 'reason': '完整证据',
             'invalidation': '风险变化', 'operation_plan': {'new_position': '分批', 'steps': ['第一批']}}]}
        revised = copy.deepcopy(baseline)
        revised['funds'][0]['action'] = '暂缓新增'
        quant = [{'code': '110020', 'quality': 'ok', 'nav_date': '2026-10-29', 'score': 80, 'action': '分批配置候选',
                  'metrics': {'volatility_annual': 10, 'max_drawdown': -3},
                  'thresholds': {'annual_volatility_limit': 15, 'drawdown_limit': 8}}]
        with patch('research_service.build_quant', return_value=quant), \
                patch('research_service.build_analysis', return_value=baseline), \
                patch('research_service.ai_analysis', return_value=revised):
            result = run_research(['110020'], DEFAULT_PREFS, key='test-placeholder')
        self.assertEqual(result['analysis']['funds'][0]['reason'], '完整证据')
        self.assertEqual(len(result['quant']), 1)
        card = result['sections'][0]['funds'][0]
        self.assertEqual(card['action'], '暂缓新增')
        self.assertEqual(card['role'], 'observation')
        self.assertNotIn('第一批', card['operation_plan']['steps'])


if __name__ == '__main__':
    unittest.main()
