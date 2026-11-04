import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from research_ai_config import (AIConfigStore, DEFAULT_SCHEDULE, SCHEDULE_INTERVALS,
                                decrypt_key, encrypt_key, validate_schedule)
from research_service import MODELS, MODELS_URL, ProviderError, probe_deepseek_key, provider_json


KEY = 'sk-offline-test-credential-7f93'
OTHER_KEY = 'sk-offline-second-credential-8e64'


def encrypt(data):
    return bytes(value ^ 0xA5 for value in data)


def decrypt(data):
    return encrypt(data)


def valid_probe(key, model):
    return {'models': list(MODELS), 'model_available': model in MODELS}


class ManualConnectionTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.probe=Mock(return_value={'models':['gpt-6.1-sol']})
        self.store=AIConfigStore(Path(directory.name)/'manual.json',encrypt=encrypt,decrypt=decrypt,probe=self.probe)
        self.store.configure(key=KEY,model='gpt-6.1-sol',enabled=True,responses_base_url='https://fixture.example/v1')

    def test_concurrent_member_jobs_share_one_check_without_advancing_configuration(self):
        entered,release=threading.Event(),threading.Event()
        def probe(key,model):
            entered.set();release.wait(timeout=3)
            return {'models':[model]}
        self.probe.side_effect=probe
        revision=self.store.status()['revision']
        results=[]
        def check():results.append(self.store.connect_for_research(revision,lambda:True))
        first,second=threading.Thread(target=check),threading.Thread(target=check)
        first.start();self.assertTrue(entered.wait(2));second.start()
        release.set();first.join(3);second.join(3)
        self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
        self.assertEqual(self.probe.call_count,1)
        self.assertEqual(len(results),2)
        self.assertTrue(all(row['enabled'] and row['revision']==revision for row in results))
        self.assertTrue(self.store.status()['enabled'])

    def test_failed_check_cooldown_then_recovery_preserves_explicit_enable_preference(self):
        self.probe.side_effect=ProviderError('API Key 无效，请重新配置',401)
        revision=self.store.status()['revision']
        with patch('research_ai_config.time.monotonic',return_value=100):
            with self.assertRaises(RuntimeError):self.store.connect_for_research(revision)
            with self.assertRaises(RuntimeError):self.store.connect_for_research(revision)
        self.assertEqual(self.probe.call_count,1)
        self.assertEqual(self.store.status()['verification'],'failed')
        self.assertTrue(self.store.status()['enabled'])
        self.assertFalse(self.store.snapshot()['enabled'])
        self.probe.side_effect=None
        with patch('research_ai_config.time.monotonic',return_value=161):
            connected=self.store.connect_for_research(revision)
        self.assertTrue(connected['enabled'])
        self.assertEqual(connected['revision'],revision)
        self.assertEqual(self.probe.call_count,2)

    def test_permission_recheck_and_disabled_configuration_prevent_probe(self):
        revision=self.store.status()['revision']
        with self.assertRaises(RuntimeError):self.store.connect_for_research(revision,lambda:False)
        disabled=self.store.configure(enabled=False)
        with self.assertRaises(RuntimeError):self.store.connect_for_research(disabled['revision'])
        self.probe.assert_not_called()
        self.assertFalse(self.store.status()['enabled'])

    def test_disabled_during_probe_cannot_be_reenabled_by_delayed_result(self):
        entered,release=threading.Event(),threading.Event()
        def probe(key,model):
            entered.set();release.wait(timeout=3)
            return {'models':[model]}
        self.probe.side_effect=probe
        revision=self.store.status()['revision'];errors=[]
        def connect():
            try:self.store.connect_for_research(revision)
            except RuntimeError as error:errors.append(str(error))
        worker=threading.Thread(target=connect);worker.start()
        self.assertTrue(entered.wait(2))
        disabled=self.store.configure(enabled=False)
        release.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors),1)
        self.assertEqual(self.store.status(),disabled)


class AIConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'private' / 'ai-config.json'
        self.store = self.new_store()

    def tearDown(self):
        self.directory.cleanup()

    def new_store(self, **kwargs):
        return AIConfigStore(self.path, encrypt=kwargs.get('encrypt', encrypt),
                             decrypt=kwargs.get('decrypt', decrypt), probe=kwargs.get('probe', valid_probe))

    def configure(self):
        return self.store.configure(key=KEY, model=MODELS[0], enabled=True)

    def test_key_stays_encrypted_and_is_not_in_public_status(self):
        status = self.configure()
        self.assertTrue(status['configured'])
        self.assertTrue(status['enabled'])
        self.assertFalse(status['effective_enabled'])
        self.assertFalse(self.store.snapshot()['enabled'])
        self.assertEqual(status['verification'], 'unverified')
        self.assertEqual(status['key_hint'], '••••7f93')
        self.assertNotIn(KEY, json.dumps(status))
        self.assertNotIn(KEY.encode(), self.path.read_bytes())
        self.assertNotIn('key', json.loads(self.path.read_text(encoding='utf-8')))
        self.assertEqual(list(self.path.parent.glob('*.tmp-*')), [])

    def test_verified_credential_and_revision_restore_after_restart(self):
        configured = self.configure()
        verified = self.store.verify()
        self.assertEqual(verified['verification'], 'verified')
        self.assertNotEqual(verified['revision'], configured['revision'])
        self.assertTrue(verified['effective_enabled'])
        restored = self.new_store()
        self.assertEqual(restored.status(), verified)
        self.assertEqual(restored.snapshot()['key'], KEY)
        self.assertTrue(restored.snapshot()['enabled'])

    def test_snapshot_and_status_are_detached_copies(self):
        self.configure()
        self.store.verify()
        snapshot = self.store.snapshot()
        snapshot['key'] = OTHER_KEY
        snapshot['enabled'] = False
        self.store.status()['available_models'].clear()
        snapshot['schedule']['daily_time'] = '01:00'
        self.store.status()['schedule']['interval_minutes'] = 15
        self.assertEqual(self.store.snapshot()['key'], KEY)
        self.assertTrue(self.store.snapshot()['enabled'])
        self.assertEqual(self.store.status()['available_models'], list(MODELS))
        self.assertEqual(self.store.snapshot()['schedule'], DEFAULT_SCHEDULE)

    def test_schedule_can_be_saved_without_credentials_and_restored(self):
        schedule = {'mode': 'scheduled_interval', 'interval_minutes': 60,
                    'daily_time': '09:30', 'end_time': None, 'timezone': 'Asia/Shanghai'}
        previous = self.store.status()
        status = self.store.configure(schedule=schedule)
        self.assertFalse(status['configured'])
        self.assertFalse(status['enabled'])
        self.assertFalse(status['effective_enabled'])
        self.assertNotEqual(status['revision'], previous['revision'])
        self.assertEqual(status['schedule'], schedule)
        self.assertEqual(self.store.snapshot()['schedule'], schedule)
        self.assertEqual(self.new_store().status(), status)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['schedule'], schedule)
        schedule['daily_time'] = '00:00'
        self.assertEqual(self.store.status()['schedule']['daily_time'], '09:30')

    def test_all_supported_schedule_modes_and_intervals_preserve_verified_key(self):
        self.configure()
        verified = self.store.verify()
        self.store._probe = Mock(side_effect=AssertionError('schedule save must not probe'))
        for mode in ('interval', 'daily', 'scheduled_interval'):
            for interval in (1, 7, 15, 30, 45, 90, 1439, 1440):
                schedule = {'mode': mode, 'interval_minutes': interval,
                            'daily_time': '00:00' if interval == 15 else '23:59',
                            'end_time': None, 'timezone': 'Asia/Shanghai'}
                with self.subTest(mode=mode, interval=interval):
                    status = self.store.configure(schedule=schedule)
                    self.assertEqual(status['schedule'], schedule)
                    self.assertEqual(status['verification'], 'verified')
                    self.assertEqual(status['last_verified_at'], verified['last_verified_at'])
                    self.assertTrue(status['effective_enabled'])
                    self.assertEqual(self.store.snapshot()['key'], KEY)
                    self.assertEqual(self.new_store().status()['schedule'], schedule)
        self.store._probe.assert_not_called()

    def test_every_integer_minute_from_one_through_1440_is_accepted(self):
        for interval in SCHEDULE_INTERVALS:
            self.assertEqual(validate_schedule({'mode': 'interval', 'interval_minutes': interval})['interval_minutes'], interval)

    def test_invalid_schedules_cannot_change_state_or_persisted_file(self):
        self.configure()
        self.store.verify()
        previous, saved = self.store.status(), self.path.read_bytes()
        invalid = [None, [], 'daily', {}, {'mode': 'unknown'}, {'mode': True},
                   {'mode': 'interval', 'interval_minutes': 0}, {'mode': 'interval', 'interval_minutes': 1441},
                   {'mode': 'interval', 'interval_minutes': -1}, {'mode': 'interval', 'interval_minutes': True},
                   {'mode': 'interval', 'interval_minutes': '30'}, {'mode': 'interval', 'interval_minutes': 30.0},
                   {'mode': 'daily', 'daily_time': '9:30'}, {'mode': 'daily', 'daily_time': '24:00'},
                   {'mode': 'daily', 'daily_time': '23:60'}, {'mode': 'daily', 'daily_time': '15:30:00'},
                   {'mode': 'daily', 'daily_time': '１５:３０'}, {'mode': 'daily', 'daily_time': None},
                   {'mode': 'scheduled_interval', 'daily_time': ' 15:30'},
                   {'mode': 'daily', 'end_time': ''}, {'mode': 'daily', 'end_time': '9:30'},
                   {'mode': 'daily', 'end_time': '24:00'}, {'mode': 'daily', 'end_time': '15:30:00'},
                   {'mode': 'daily', 'end_time': False}, {'mode': 'daily', 'end_time': 930},
                   {'mode': 'daily', 'end_time': '１５:３０'},
                   {'mode': 'scheduled_interval', 'daily_time': '09:30', 'end_time': '09:30'},
                   {'mode': 'interval', 'timezone': 'UTC'}, {'mode': 'daily', 'timezone': None},
                   {'mode': 'daily', 'unexpected': True}]
        for schedule in invalid:
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                self.store.configure(schedule=schedule)
            self.assertEqual(self.store.status(), previous)
            self.assertEqual(self.path.read_bytes(), saved)

    def test_legacy_file_gets_default_schedule_and_bad_saved_schedule_fails_closed(self):
        self.configure()
        verified = self.store.verify()
        document = json.loads(self.path.read_text(encoding='utf-8'))
        document.pop('schedule')
        self.path.write_text(json.dumps(document), encoding='utf-8')
        restored = self.new_store()
        self.assertEqual(restored.status(), verified)
        self.assertEqual(restored.snapshot()['schedule'], DEFAULT_SCHEDULE)
        document['schedule'] = {**DEFAULT_SCHEDULE, 'mode': 'unknown'}
        self.path.write_text(json.dumps(document), encoding='utf-8')
        failed = self.new_store()
        self.assertFalse(failed.status()['configured'])
        self.assertFalse(failed.snapshot()['enabled'])
        self.assertEqual(failed.status()['schedule'], DEFAULT_SCHEDULE)

    def test_unchanged_schedule_keeps_revision_and_saving_time_never_enables_ai(self):
        first = self.store.configure(schedule={'mode': 'daily', 'daily_time': '09:00'})
        second = self.store.configure(schedule=first['schedule'])
        self.assertEqual(first, second)
        self.assertFalse(second['enabled'])
        self.assertFalse(second['configured'])
        with self.assertRaisesRegex(ValueError, '先配置'):
            self.store.configure(enabled=True, schedule={**DEFAULT_SCHEDULE, 'mode': 'scheduled_interval'})
        self.assertEqual(self.store.status(), first)

    def test_end_time_same_day_and_overnight_windows_roundtrip_without_probe(self):
        self.store._probe = Mock(side_effect=AssertionError('schedule save must not probe'))
        for mode in ('interval', 'daily', 'scheduled_interval'):
            for start, end in (('09:00', '15:00'), ('22:00', '06:00')):
                schedule = {**DEFAULT_SCHEDULE, 'mode': mode, 'daily_time': start,
                            'end_time': end, 'interval_minutes': 37}
                with self.subTest(mode=mode, start=start):
                    status = self.store.configure(schedule=schedule)
                    self.assertEqual(status['schedule'], schedule)
                    self.assertEqual(self.new_store().status()['schedule'], schedule)
                    self.assertFalse(status['effective_enabled'])
        self.store._probe.assert_not_called()

    def test_legacy_schedule_without_end_keeps_revision_and_adds_null_only_in_memory(self):
        self.configure()
        status = self.store.verify()
        document = json.loads(self.path.read_text(encoding='utf-8'))
        document['schedule'].pop('end_time')
        self.path.write_text(json.dumps(document), encoding='utf-8')
        original_bytes = self.path.read_bytes()
        restored = self.new_store()
        self.assertEqual(restored.status()['revision'], status['revision'])
        self.assertIsNone(restored.status()['schedule']['end_time'])
        self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_schedule_write_failure_preserves_prior_state_and_file(self):
        self.configure()
        self.store.verify()
        previous, saved = self.store.status(), self.path.read_bytes()
        with patch('research_ai_config.os.replace', side_effect=OSError('offline write failure')):
            with self.assertRaisesRegex(RuntimeError, '加密保存失败'):
                self.store.configure(schedule={'mode': 'scheduled_interval', 'daily_time': '08:00'})
        self.assertEqual(self.store.status(), previous)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_clear_deletes_encrypted_file_and_invalidates_revision(self):
        previous = self.configure()
        status = self.store.clear()
        self.assertFalse(status['configured'])
        self.assertFalse(status['enabled'])
        self.assertFalse(status['effective_enabled'])
        self.assertEqual(status['verification'], 'unconfigured')
        self.assertNotEqual(status['revision'], previous['revision'])
        self.assertEqual(self.store.snapshot()['key'], '')
        self.assertFalse(self.path.exists())

    def test_invalid_configuration_leaves_prior_state_and_file_intact(self):
        self.configure()
        self.store.verify()
        previous = self.store.status()
        saved = self.path.read_bytes()
        for invalid in ({'key': ''}, {'key': 'has space'}, {'key': 'sk-\ninside'},
                        {'key': '汉字'}, {'key': 123}, {'key': 'x' * 513},
                        {'model': 'arbitrary-model'}, {'model': []}, {'enabled': 1}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.store.configure(**invalid)
            self.assertEqual(self.store.status(), previous)
            self.assertEqual(self.path.read_bytes(), saved)

    def test_copy_whitespace_is_trimmed_and_legacy_model_alias_resolves(self):
        self.store.configure(key='  ' + KEY + '\r\n', model='deepseek-chat', enabled=True)
        self.assertEqual(self.store.snapshot()['key'], KEY)
        self.assertEqual(self.store.status()['model'], MODELS[0])

    def test_new_key_or_model_requires_reverification(self):
        self.configure()
        verified = self.store.verify()
        changed = self.store.configure(key=OTHER_KEY)
        self.assertNotEqual(changed['revision'], verified['revision'])
        self.assertEqual(changed['verification'], 'unverified')
        self.assertIsNone(changed['last_verified_at'])
        self.assertFalse(self.store.snapshot()['enabled'])
        self.store.verify()
        changed = self.store.configure(model=MODELS[1])
        self.assertEqual(changed['verification'], 'unverified')
        self.assertFalse(self.store.snapshot()['enabled'])

    def test_enabled_preference_can_pause_and_resume_verified_configuration(self):
        self.configure()
        verified = self.store.verify()
        paused = self.store.configure(enabled=False)
        self.assertNotEqual(paused['revision'], verified['revision'])
        self.assertEqual(paused['verification'], 'verified')
        self.assertFalse(paused['effective_enabled'])
        resumed = self.store.configure(enabled=True)
        self.assertTrue(resumed['effective_enabled'])
        self.assertEqual(self.store.snapshot()['key'], KEY)

    def test_auth_failure_preserves_saved_key_and_blocks_auto_calls(self):
        self.configure()
        self.store._probe = Mock(side_effect=ProviderError('API Key 无效，请重新配置', 401))
        failed = self.store.verify()
        self.assertTrue(failed['configured'])
        self.assertTrue(failed['enabled'])
        self.assertFalse(failed['effective_enabled'])
        self.assertEqual(failed['verification'], 'failed')
        self.assertEqual(failed['error'], 'API Key 无效，请重新配置')
        self.assertFalse(self.new_store().snapshot()['enabled'])

    def test_same_key_reverification_changes_revision_and_recovers_auto_eligibility(self):
        self.configure()
        original = self.store.verify()
        self.store._probe = Mock(side_effect=ProviderError('DeepSeek 余额不足', 402))
        failed = self.store.verify()
        self.assertNotEqual(failed['revision'], original['revision'])
        self.assertFalse(failed['effective_enabled'])
        self.store._probe = valid_probe
        recovered = self.store.verify()
        self.assertNotEqual(recovered['revision'], failed['revision'])
        self.assertTrue(recovered['effective_enabled'])
        checked_again = self.store.verify()
        self.assertNotEqual(checked_again['revision'], recovered['revision'])
        self.assertEqual(self.store.snapshot()['key'], KEY)

    def test_probe_errors_never_echo_upstream_or_key(self):
        self.configure()
        self.store._probe = Mock(side_effect=RuntimeError('Server echoed ' + KEY))
        status = self.store.verify()
        self.assertNotIn(KEY, json.dumps(status))
        self.assertNotIn(KEY.encode(), self.path.read_bytes())
        self.assertEqual(status['error'], 'DeepSeek 验证失败，请稍后重试')

    def test_unavailable_model_cannot_be_claimed_available_by_probe(self):
        self.configure()
        self.store._probe = lambda key, model: {'models': ['different-model'], 'model_available': True}
        status = self.store.verify()
        self.assertEqual(status['verification'], 'failed')
        self.assertIn('模型不可用', status['error'])
        self.assertFalse(status['effective_enabled'])

    def test_slow_old_probe_cannot_modify_new_configuration(self):
        self.configure()
        started = threading.Event()
        release = threading.Event()

        def delayed_probe(key, model):
            started.set()
            if not release.wait(3):
                raise RuntimeError('test timeout')
            return valid_probe(key, model)

        self.store._probe = delayed_probe
        worker = threading.Thread(target=self.store.verify)
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            changed = self.store.configure(key=OTHER_KEY)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.store.status(), changed)
        self.assertFalse(self.store.snapshot()['enabled'])

    def test_old_probe_cannot_override_a_new_accepted_verification(self):
        self.configure()
        started = threading.Event()
        release = threading.Event()

        def delayed_failure(key, model):
            started.set()
            if not release.wait(3):
                raise RuntimeError('test timeout')
            raise ProviderError('API Key 无效，请重新配置', 401)

        self.store._probe = delayed_failure
        worker = threading.Thread(target=self.store.verify)
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            self.store._probe = valid_probe
            latest = self.store.verify()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.store.status(), latest)
        self.assertTrue(self.store.snapshot()['enabled'])

    def test_encryption_failure_does_not_change_saved_or_active_configuration(self):
        self.configure()
        previous = self.store.status()
        saved = self.path.read_bytes()
        self.store._encrypt = Mock(side_effect=OSError('test crypto failure'))
        with self.assertRaisesRegex(RuntimeError, '加密保存失败'):
            self.store.configure(key=OTHER_KEY)
        self.assertEqual(self.store.status(), previous)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_atomic_replace_failure_keeps_old_file_and_cleans_temp(self):
        self.configure()
        previous = self.store.status()
        saved = self.path.read_bytes()
        with patch('research_ai_config.os.replace', side_effect=OSError('test permission failure')):
            with self.assertRaisesRegex(RuntimeError, '加密保存失败'):
                self.store.configure(key=OTHER_KEY)
        self.assertEqual(self.store.status(), previous)
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(list(self.path.parent.glob('*.tmp-*')), [])

    def test_corrupt_or_undecryptable_file_fails_closed(self):
        self.configure()
        saved = self.path.read_bytes()
        for contents in ('{invalid json', '{"version":1,"key":"plaintext"}'):
            self.path.write_text(contents, encoding='utf-8')
            failed = self.new_store()
            self.assertFalse(failed.status()['configured'])
            self.assertFalse(failed.snapshot()['enabled'])
            self.assertIn('无法读取', failed.status()['error'])
        self.path.write_bytes(saved)
        failed = self.new_store(decrypt=Mock(side_effect=RuntimeError('test decrypt failure')))
        self.assertFalse(failed.snapshot()['enabled'])

    def test_enabling_without_saved_key_is_rejected_without_writing(self):
        with self.assertRaisesRegex(ValueError, '先配置'):
            self.store.configure(enabled=True)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI integration')
    def test_windows_dpapi_round_trip_with_synthetic_offline_value(self):
        encrypted = encrypt_key(KEY.encode())
        self.assertNotEqual(encrypted, KEY.encode())
        self.assertEqual(decrypt_key(encrypted), KEY.encode())


class DeepSeekProbeTests(unittest.TestCase):
    @patch('research_service.fetch_bytes')
    def test_probe_uses_official_get_models_without_generation(self, opened):
        opened.return_value = json.dumps({'data': [{'id': model} for model in MODELS]}).encode()
        result = probe_deepseek_key(KEY, MODELS[0])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, MODELS_URL)
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
        self.assertEqual(opened.call_args.kwargs['timeout'], 15)
        self.assertEqual(result, {'models': list(MODELS), 'model_available': True})

    @patch('research_service.fetch_bytes')
    def test_invalid_or_oversized_model_responses_are_rejected(self, opened):
        for payload in ({'data': 'wrong'}, {'data': [{'id': KEY}]}, {'data': [{'id': 'bad model'}]}, [], None):
            with self.subTest(payload=payload):
                opened.return_value = json.dumps(payload).encode()
                with self.assertRaisesRegex(ProviderError, '数据格式无效'):
                    probe_deepseek_key(KEY)
        opened.return_value = b'x' * 200_001
        with self.assertRaisesRegex(ProviderError, '数据格式无效'):
            probe_deepseek_key(KEY)

    @patch('research_service.fetch_bytes')
    def test_http_and_network_errors_are_safe_and_machine_readable(self, opened):
        for code in (401, 402, 429, 503):
            opened.side_effect = urllib.error.HTTPError(MODELS_URL, code, KEY, {}, io.BytesIO(KEY.encode()))
            with self.assertRaises(ProviderError) as caught:
                probe_deepseek_key(KEY)
            self.assertNotIn(KEY, str(caught.exception))
            self.assertEqual(caught.exception.status_code, code)
            self.assertEqual(caught.exception.code, code)
        opened.side_effect = urllib.error.URLError(KEY)
        with self.assertRaisesRegex(ProviderError, '连接失败或超时'):
            probe_deepseek_key(KEY)

    @patch('research_service.fetch_bytes')
    def test_existing_generation_provider_preserves_signature_and_safe_errors(self, opened):
        opened.side_effect = urllib.error.HTTPError(MODELS_URL, 401, KEY, {}, io.BytesIO(KEY.encode()))
        with self.assertRaises(ProviderError) as caught:
            provider_json('https://api.deepseek.com/chat/completions', KEY, {'model': MODELS[0]}, 90)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertIsInstance(caught.exception, RuntimeError)
        self.assertNotIn(KEY, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
