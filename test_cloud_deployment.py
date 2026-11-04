import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cloud_server import CloudAIConfigStore, create_cloud_server
from research_accounts import AccountError
from research_proxy import parse_trusted_proxies
import test_cloud_accounts as account_tests


def deployment_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / 'deploy/vps' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProxyRateHTTPTests(unittest.TestCase):
    setUp = account_tests.CloudHTTPTests.setUp
    cleanup = account_tests.CloudHTTPTests.cleanup
    request = account_tests.CloudHTTPTests.request
    sign = account_tests.CloudHTTPTests.sign

    def prime(self, bucket, count):
        with self.server.accounts.connection() as db:
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',
                       (bucket, self.server.accounts.clock(), count))

    def test_login_limit_isolated_by_ip_behind_trusted_caddy(self):
        self.server.trusted_proxies = parse_trusted_proxies('127.0.0.1')
        self.prime('auth-ip:198.51.100.8', 150)
        with patch.object(self.server.accounts, 'login', side_effect=AccountError('invalid', 401)):
            for forged in ('spoof1', 'spoof2'):
                self.assertEqual(self.request('/api/auth/login', {}, extra={
                    'X-Forwarded-For': forged + ', 198.51.100.8'})[0], 429)
            # A solved image challenge lets the request reach the (mocked) credential check.
            self.assertEqual(self.request('/api/auth/login', {'username': 'member'}, extra={
                'X-Forwarded-For': '198.51.100.9'})[0], 401)

    def test_direct_client_cannot_bypass_ip_limit_with_xff(self):
        self.prime('auth-ip:127.0.0.1', 150)
        self.assertEqual(self.request('/api/auth/login', {}, extra={'X-Forwarded-For': '198.51.100.7'})[0], 429)

    def test_registration_limits_both_individual_ip_and_botnet_total(self):
        self.server.trusted_proxies = parse_trusted_proxies('127.0.0.1')
        self.prime('registration-ip:198.51.100.8', 5)
        with patch.object(self.server.accounts, 'create_user', return_value={'id': 'member', 'role': 'member'}):
            self.assertEqual(self.request('/api/auth/register', {}, extra={
                'X-Forwarded-For': '198.51.100.8'})[0], 429)
            with patch.object(self.server.accounts, 'issue_session', return_value=('session', 'csrf')):
                self.assertEqual(self.request('/api/auth/register', {'username': 'proxyuser'}, extra={
                    'X-Forwarded-For': '198.51.100.9'})[0], 200)
            self.prime('registration-global', 200)
            self.assertEqual(self.request('/api/auth/register', {}, extra={
                'X-Forwarded-For': '198.51.100.10'})[0], 429)

    def test_cloud_http_endpoint_save_rejected_without_changes_or_paid_request(self):
        self.server.ai_config.environment_key = 'offline-test-key'
        before = self.server.ai_config.status()
        with patch.object(self.server.ai_config, 'verify') as verify:
            self.assertEqual(self.request('/api/ai/config', {'responses_base_url': 'http://provider.example/v1'},
                self.admin_cookie, self.admin_csrf)[0], 400)
        self.assertEqual(self.server.ai_config.status(), before)
        verify.assert_not_called()


class HTTPSConfigTests(unittest.TestCase):
    def test_production_factory_uses_explicit_loopback_proxy_and_bind_address(self):
        with tempfile.TemporaryDirectory() as folder:
            service = create_cloud_server(0, folder, 'https://research.example.com', environ={
                'FUNDPILOT_SETUP_TOKEN': 's' * 32, 'FUNDPILOT_TRUSTED_PROXIES': '127.0.0.1/32',
                'FUNDPILOT_BIND_HOST': '127.0.0.1'})
            try:
                self.assertEqual(service.server_address[0], '127.0.0.1')
                self.assertEqual(service.trusted_proxies, parse_trusted_proxies('127.0.0.1/32'))
                self.assertFalse(service.ai_config.snapshot()['enabled'])
            finally:
                service.auto_engine.close()
                service.server_close()

    def test_plaintext_environment_is_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'HTTPS'):
                CloudAIConfigStore(Path(folder) / 'settings.json', {'FUNDPILOT_AI_BASE_URL': 'http://provider.example/v1'})

    def test_saved_plaintext_endpoint_disables_ai(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            store = CloudAIConfigStore(path, {'FUNDPILOT_AI_BASE_URL': 'https://provider.example/v1'})
            store.configure(reasoning_effort='medium')
            value = json.loads(path.read_text())
            value.update(responses_base_url='http://provider.example/v1', enabled=True)
            path.write_text(json.dumps(value))
            restored = CloudAIConfigStore(path, {'FUNDPILOT_AI_BASE_URL': 'https://provider.example/v1'})
            self.assertFalse(restored.snapshot()['enabled'])
            self.assertTrue(restored.snapshot()['responses_base_url'].startswith('https://'))
            self.assertTrue(restored.status()['error'])


class DeploymentAssetsTests(unittest.TestCase):
    def test_environment_has_unique_secret_and_existing_file_is_preserved(self):
        prepare = deployment_module('prepare_env').prepare
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'a'
            path = prepare('research.example.com', first)
            original = path.read_bytes()
            values = dict(line.split('=', 1) for line in path.read_text().splitlines())
            self.assertEqual(len(values['FUNDPILOT_SETUP_TOKEN']), 32)
            self.assertEqual(values['FUNDPILOT_TRUSTED_PROXIES'], '127.0.0.1/32')
            self.assertEqual(values['FUNDPILOT_AI_ENABLED'], '0')
            self.assertNotIn('{$FUNDPILOT_DOMAIN}', (first / 'Caddyfile.generated').read_text())
            second = prepare('research.example.com', Path(folder) / 'b').read_text()
            self.assertNotEqual(second, original.decode())
            with self.assertRaises(FileExistsError):
                prepare('other.example.com', first)
            self.assertEqual(path.read_bytes(), original)
            config = first / 'Caddyfile.generated'
            original_config = config.read_bytes()
            self.assertEqual(prepare('research.example.com', first, reuse_existing=True), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(config.read_bytes(), original_config)
            with self.assertRaisesRegex(ValueError, '域名'):
                prepare('other.example.com', first, reuse_existing=True)
            self.assertEqual(path.read_bytes(), original)
            config.unlink()
            prepare('research.example.com', first, reuse_existing=True)
            self.assertEqual(config.read_bytes(), original_config)
            for domain in ('http://example.com', 'example.com/path', 'example.com\nmalicious', '127.0.0.1', '*.example.com'):
                with self.subTest(domain=domain), self.assertRaises(ValueError):
                    prepare(domain, Path(folder) / 'invalid')

    def test_online_backup_includes_wal_and_preserves_foreign_files(self):
        backup = deployment_module('backup_accounts').backup_accounts
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'accounts.sqlite3'
            snapshots = Path(folder) / 'backups'
            snapshots.mkdir()
            unrelated = snapshots / 'notes.txt'
            unrelated.write_text('keep')
            expired = snapshots / 'accounts-20000101T000000000000Z.sqlite3'
            expired.write_text('expired snapshot')
            connection = sqlite3.connect(database)
            try:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA wal_autocheckpoint=0')
                connection.execute('CREATE TABLE users (name TEXT)')
                connection.execute('INSERT INTO users VALUES (?)', ('kept-user',))
                connection.commit()
                self.assertTrue(Path(str(database) + '-wal').exists())
                snapshot = backup(database, snapshots)
                restored = sqlite3.connect(snapshot)
                try:
                    self.assertEqual(restored.execute('SELECT name FROM users').fetchall(), [('kept-user',)])
                    self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                finally:
                    restored.close()
                connection.execute('INSERT INTO users VALUES (?)', ('still-writable',))
                connection.commit()
            finally:
                connection.close()
            self.assertTrue(unrelated.exists())
            self.assertFalse(expired.exists())
            with self.assertRaises(FileNotFoundError):
                backup(Path(folder) / 'missing.sqlite3', snapshots)
            self.assertTrue(snapshot.exists())


if __name__ == '__main__':
    unittest.main()
