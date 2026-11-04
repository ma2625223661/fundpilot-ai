"""Exercise the actual local factory with password protection enabled by default."""
import shutil
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import server
from research_ai_config import AIConfigStore
import test_cloud_accounts as cloud_tests
PASSWORD=cloud_tests.PASSWORD


class LocalHTTPTests(cloud_tests.CloudHTTPTests):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shutil.copytree(server.ROOT / 'dist', root / 'dist')
        with patch('server.ROOT', root):
            self.server = server.create_server(0)
        self.server.auto_engine.close()
        self.server.auto_engine = Mock()
        self.server.auto_engine.status.return_value = {'status':'idle','has_report':False}
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)
        self.origin = self.server.public_url
        self.admin_cookie,self.admin_csrf = self.sign('/api/auth/setup','owner')
        self.member_cookie,self.member_csrf = self.sign('/api/auth/register','member')

    def test_local_factory_keeps_research_and_advertises_password_gate(self):
        health = self.request('/api/health')[1]
        self.assertTrue(health['login_required'])
        access = self.request('/api/access',cookie=self.admin_cookie)[1]
        self.assertEqual(access['scope'],'account_local')
        self.assertTrue(access['can_manage_settings'])
        context = self.request('/session-context.js',cookie=self.member_cookie)[1]
        self.assertIn(b'"mode": "local"',context)
        self.assertFalse(self.request('/api/access',cookie=self.member_cookie)[1]['can_manage_settings'])

    def test_first_admin_must_be_created_on_server_computer(self):
        from research_local_auth import LocalAccountHandler
        with patch.object(LocalAccountHandler,'local_client',return_value=False):
            value=self.request('/api/auth/status')[1]
            self.assertFalse(value['setup_available'])
            self.assertEqual(self.request('/api/auth/setup',{'username':'outsider','password':PASSWORD})[0],403)

    def test_lan_uses_validated_origin_and_keeps_admin_settings_local(self):
        from research_local_auth import LocalAccountHandler
        with patch.object(LocalAccountHandler,'local_client',return_value=False):
            self.assertFalse(self.request('/api/access',cookie=self.admin_cookie)[1]['can_manage_settings'])
            for route in ['/api/ai/config','/api/ai/test','/api/data/test','/api/data/public/test']:
                self.assertEqual(self.request(route,{},self.admin_cookie,self.admin_csrf)[0],403,route)
        alias=f'localhost:{self.server.server_port}'
        self.assertEqual(self.request('/api/auth/me',cookie=self.admin_cookie,extra={'Host':alias})[0],200)
        self.assertEqual(self.request('/api/auth/logout',{},self.member_cookie,self.member_csrf,
            {'Host':alias,'Origin':'http://'+alias})[0],200)

    def test_local_admin_key_remains_encrypted_and_no_paid_call_for_disabled_save(self):
        store=AIConfigStore(Path(self.tmp.name)/'test-model.json',
            encrypt=lambda value:b'encrypted:'+value[::-1], decrypt=lambda value:value[10:][::-1],
            probe=Mock(side_effect=AssertionError('no model request')))
        self.server.ai_config=store
        secret='sk-local-account-unit-test-1234567890'
        status,value,_=self.request('/api/ai/config',{'key':secret,'model':'deepseek-flash','enabled':False},self.admin_cookie,self.admin_csrf)
        self.assertEqual(status,200,value)
        self.assertTrue(value['config']['configured'])
        self.assertNotIn(secret,str(value))
        self.assertNotIn(secret,store.path.read_text())
        self.assertEqual(store.snapshot()['key'],secret)
        store._probe.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
