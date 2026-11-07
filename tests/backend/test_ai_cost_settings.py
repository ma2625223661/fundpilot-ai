import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from research_ai_config import AIConfigStore, DEFAULT_COST_CONTROLS, validate_cost_controls
from cloud_server import CloudAIConfigStore, CloudHandler
from research_local_auth import LocalAccountHandler


class CostSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'config.json'
        self.probe = Mock(return_value={'models':['deepseek-flash']})

    def store(self):
        return AIConfigStore(self.path, encrypt=lambda x:b'encrypted-'+x[::-1],
            decrypt=lambda x:x[10:][::-1], probe=self.probe)

    def test_cost_only_change_preserves_verified_revision_and_closed_switch(self):
        store = self.store()
        store.configure(key='offline-config-key-123456789', enabled=False)
        verified = store.verify()
        self.probe.reset_mock()
        limits = {'reuse_enabled':False,'daily_request_limit':14,'daily_token_limit':2000000}
        changed = store.configure(cost_controls=limits)
        self.assertEqual(changed['revision'], verified['revision'])
        self.assertEqual(changed['verification'], 'verified')
        self.assertFalse(changed['enabled'])
        self.probe.assert_not_called()
        self.assertEqual(self.store().status(), changed)
        limits['daily_request_limit'] = 500
        public = store.status();public['cost_controls']['daily_request_limit'] = 900
        snapshot = store.snapshot();snapshot['cost_controls']['daily_request_limit'] = 800
        self.assertEqual(store.status()['cost_controls']['daily_request_limit'],14)

    def test_legacy_document_receives_defaults_without_changing_other_settings(self):
        store = self.store();store.configure(key='offline-config-key-123456789', enabled=False)
        expected = store.verify()
        document = json.loads(self.path.read_text(encoding='utf-8'));document.pop('cost_controls')
        self.path.write_text(json.dumps(document),encoding='utf-8')
        self.assertEqual(self.store().status(),expected)
        self.assertEqual(self.store().status()['cost_controls'],DEFAULT_COST_CONTROLS)

    def test_invalid_limits_are_rejected_atomically(self):
        store=self.store();store.configure(cost_controls={'daily_request_limit':14})
        previous=store.status();saved=self.path.read_bytes()
        for value in (None,[],{'unexpected':1},{'reuse_enabled':1},{'daily_request_limit':True},
                {'daily_request_limit':0},{'daily_request_limit':10001},{'daily_token_limit':999},
                {'daily_token_limit':1000000001},{'daily_token_limit':1.5}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                store.configure(cost_controls=value)
            self.assertEqual(store.status(),previous);self.assertEqual(self.path.read_bytes(),saved)
        self.assertEqual(validate_cost_controls({}),DEFAULT_COST_CONTROLS)

    def test_cloud_budget_settings_persist_without_secret_and_legacy_default(self):
        environment={'DEEPSEEK_API_KEY':'offline-service-key-123456789'}
        store=CloudAIConfigStore(self.path,environment,probe=self.probe)
        before=store.status();store.configure(cost_controls={'daily_request_limit':15})
        self.assertEqual(store.status()['revision'],before['revision'])
        self.assertFalse(store.status()['enabled']);self.probe.assert_not_called()
        self.assertNotIn(environment['DEEPSEEK_API_KEY'],self.path.read_text(encoding='utf-8'))
        self.assertEqual(CloudAIConfigStore(self.path,environment).status()['cost_controls']['daily_request_limit'],15)
        document=json.loads(self.path.read_text(encoding='utf-8'));document.pop('cost_controls')
        self.path.write_text(json.dumps(document),encoding='utf-8')
        self.assertEqual(CloudAIConfigStore(self.path,environment).status()['cost_controls'],DEFAULT_COST_CONTROLS)

    def test_local_and_cloud_handler_budget_save_never_probes_or_immediately_runs(self):
        for kind in (LocalAccountHandler,CloudHandler):
            with self.subTest(kind=kind.__name__):
                path=Path(self.folder.name)/(kind.__name__+'.json')
                store=CloudAIConfigStore(path,{},probe=self.probe) if kind is CloudHandler else AIConfigStore(path,
                    encrypt=lambda x:x,decrypt=lambda x:x,probe=self.probe)
                handler=kind.__new__(kind);engine=Mock();handler.server=SimpleNamespace(ai_config=store,auto_engine=engine)
                handler.reply=Mock(side_effect=lambda status,value:(status,value))
                status,value=handler.ai_action('/api/ai/config',{'cost_controls':{'daily_request_limit':12}})
                self.assertEqual(status,200);self.assertFalse(value['config']['enabled'])
                engine.config_changed.assert_called_once_with(schedule_only=True)
                self.probe.assert_not_called()


if __name__=='__main__':
    unittest.main()
