"""Startup regressions; local HTTP fixtures only, no data or model requests."""
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import launch


HEALTH = {'ok': True, 'provider': 'Responses', 'model': 'gpt-6.1-sol',
          'version': 6, 'research_scope': 'sectors',
          'automatic_research': True, 'login_required': True}


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.body = json.dumps(HEALTH).encode()
        self.redirect = False
        owner = self

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if owner.redirect and self.path == '/api/health':
                    self.send_response(302)
                    self.send_header('Location', '/other')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(owner.body)))
                self.end_headers()
                self.wfile.write(owner.body)

            def log_message(self, *args):
                pass

        self.service = ThreadingHTTPServer(('127.0.0.1', 0), HealthHandler)
        self.port = self.service.server_port
        self.thread = threading.Thread(target=self.service.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.service.shutdown()
        self.thread.join(2)
        self.service.server_close()

    def health(self, value):
        self.body = json.dumps(value).encode()

    def test_provider_and_model_do_not_define_site_identity(self):
        for provider in ('Responses', 'DeepSeek', 'another-provider', None):
            with self.subTest(provider=provider):
                self.health({**HEALTH, 'provider': provider, 'model': 'another-model'})
                self.assertTrue(launch.running_service(self.port))

    def test_unrelated_or_unprotected_services_are_rejected(self):
        for changes in ({'ok': False}, {'research_scope': 'funds'},
                        {'automatic_research': False}, {'login_required': False},
                        {'version': 5}, {'version': True}, {'version': '6'}):
            with self.subTest(changes=changes):
                self.health({**HEALTH, **changes})
                self.assertFalse(launch.running_service(self.port))
        self.health({})
        self.assertFalse(launch.running_service(self.port))

    def test_malformed_health_response_is_treated_as_another_service(self):
        for raw in (b'[]', b'null', b'1', b'"text"', b'<html>other app</html>',
                    b'\xff', json.dumps({**HEALTH, 'extra': 'x' * 65536}).encode()):
            with self.subTest(size=len(raw)):
                self.body = raw
                self.assertFalse(launch.running_service(self.port))

    def test_redirect_is_not_accepted_as_site_identity(self):
        self.redirect = True
        self.assertFalse(launch.running_service(self.port))

    def test_existing_backend_is_reused_without_loading_or_starting_another(self):
        create = Mock(side_effect=AssertionError('must not start a second backend'))
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}), \
                patch.object(launch.webbrowser, 'open') as browser, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(launch.main(['--port', str(self.port), '--no-browser']), 0)
            self.assertIn('已复用现有网站', output.getvalue())
        create.assert_not_called()
        browser.assert_not_called()

    def test_existing_backend_opens_site_once(self):
        with patch.object(launch.webbrowser, 'open', return_value=True) as browser, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(launch.main(['--port', str(self.port)]), 0)
        browser.assert_called_once_with(f'http://127.0.0.1:{self.port}/index.html')

    def test_browser_failure_does_not_turn_healthy_backend_into_start_failure(self):
        with patch.object(launch.webbrowser, 'open', side_effect=OSError('no browser')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(launch.main(['--port', str(self.port)]), 0)
            self.assertIn('手动访问', output.getvalue())

    def test_bind_race_rechecks_first_backend(self):
        create = Mock(side_effect=OSError(10048, 'address in use'))
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}), \
                patch.object(launch, 'running_service', side_effect=[False, True]) as probe, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(launch.main(['--port', str(self.port), '--no-browser']), 0)
        self.assertEqual(probe.call_count, 2)
        create.assert_called_once_with(self.port)

    def test_other_occupied_port_is_reported_and_left_running(self):
        self.health({'ok': True, 'service': 'unrelated'})
        create = Mock(side_effect=OSError(10048, 'address in use'))
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}), \
                patch.object(launch.time, 'sleep'), \
                patch.object(launch.webbrowser, 'open') as browser, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(launch.main(['--port', str(self.port), '--no-browser']), 1)
            self.assertIn('现有程序保持运行', output.getvalue())
            self.assertIn('--port 8876', output.getvalue())
        # The unrelated listener still owns its port after the failed launch.
        with socket.create_connection(('127.0.0.1', self.port), timeout=1):
            pass
        browser.assert_not_called()

    def test_cold_start_runs_only_one_engine_and_closes_cleanly(self):
        service = Mock()
        service.serve_forever.side_effect = KeyboardInterrupt
        create = Mock(return_value=service)
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}), \
                patch.object(launch, 'running_service', return_value=False), \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(launch.main(['--port', str(self.port), '--no-browser']), 0)
        create.assert_called_once_with(self.port)
        service.auto_engine.start.assert_called_once_with()
        service.auto_engine.close.assert_called_once_with()
        service.server_close.assert_called_once_with()

    def test_share_template_matches_current_launcher(self):
        template = launch.ROOT / 'work/share_templates/launch.py'
        if not template.is_file():
            self.skipTest('share template lives in the development workspace, not the release package')
        self.assertEqual(Path(launch.__file__).read_bytes(), template.read_bytes())

    def test_owner_extracted_launcher_recognizes_responses(self):
        path = Path(r'C:\Users\MYX\Desktop\基金研究所\FundPilot-AI-Windows-x64-20261031\launch.py')
        if not path.is_file():
            self.skipTest('owner local installation only')
        spec = importlib.util.spec_from_file_location('installed_launcher', path)
        installed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installed)
        self.assertTrue(installed.running_service(self.port))


if __name__ == '__main__':
    unittest.main()
