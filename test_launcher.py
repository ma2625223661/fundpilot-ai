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



class FakeChild:
    def __init__(self, port):
        self.port, self.returncode = port, None

    def poll(self):
        return self.returncode


class HotReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'dist').mkdir()
        for name in ('server.py', 'research_x.py', 'test_server.py', 'notes.md', 'dist/index.html'):
            (self.root / name).write_text('x', encoding='utf-8')

    def test_watch_list_covers_backend_code_and_page_names_but_not_tests(self):
        files = launch.watched_files(self.root)
        self.assertEqual(set(files), {'server.py', 'research_x.py', 'dist/index.html'})
        before = dict(files)
        (self.root / 'dist' / 'index.html').write_text('edited page', encoding='utf-8')
        self.assertEqual(launch.changed_files(before, launch.watched_files(self.root)), [])
        (self.root / 'dist' / 'new.js').write_text('x', encoding='utf-8')
        (self.root / 'test_server.py').write_text('edited test', encoding='utf-8')
        __import__('os').utime(self.root / 'server.py', ns=(1, 1))
        self.assertEqual(launch.changed_files(before, launch.watched_files(self.root)), ['dist/new.js', 'server.py'])

    def run_supervisor(self, snapshots, *, crash_at=None, interrupt=False):
        spawned, stopped, opened = [], [], []
        def spawn(port):
            spawned.append(FakeChild(port))
            return spawned[-1]
        def snapshot():
            value = snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]
            return dict(value)
        cycle = {'n': 0}
        def sleep(_):
            if _ == launch.WATCH_INTERVAL:
                cycle['n'] += 1
                if crash_at == cycle['n']:
                    spawned[-1].returncode = 1
                if interrupt and cycle['n'] == 3:
                    raise KeyboardInterrupt
        args = SimpleNamespace(port=8765, no_browser=False)
        with patch.object(launch, 'reuse_service', return_value=False), \
                patch.object(launch, 'open_site', side_effect=lambda url, nb: opened.append(url)), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            code = launch.supervise(args, sleep=sleep, spawn=spawn, stop=stopped.append, snapshot=snapshot,
                                    healthy=lambda port: True, stalled=lambda child: False, max_cycles=6)
        return code, spawned, stopped, opened, output.getvalue()

    def test_code_change_restarts_the_backend_once_and_opens_the_browser_once(self):
        a, b = {'server.py': 1}, {'server.py': 2}
        # initial, cycle1, cycle2(changed), debounce check, then stable.
        code, spawned, stopped, opened, output = self.run_supervisor([a, a, b, b, b])
        self.assertEqual(code, 0)
        self.assertEqual(len(spawned), 2)
        self.assertEqual(stopped[:1], [spawned[0]])
        self.assertEqual(stopped[-1], spawned[1])
        self.assertEqual(opened, ['http://127.0.0.1:8765/index.html'])
        self.assertIn('检测到修改：server.py', output)

    def test_crashed_backend_waits_for_a_fix_instead_of_looping(self):
        a, b = {'server.py': 1}, {'server.py': 2}
        code, spawned, stopped, opened, output = self.run_supervisor([a, a, a, a, b, b], crash_at=2)
        self.assertIn('网站后台已退出（代码 1）', output)
        self.assertEqual(len(spawned), 2)  # only the fix triggers a new start

    def test_ctrl_c_stops_the_backend(self):
        a = {'server.py': 1}
        code, spawned, stopped, opened, output = self.run_supervisor([a], interrupt=True)
        self.assertEqual(code, 0)
        self.assertEqual(stopped, [spawned[0]])
        self.assertIn('正在停止网站后台', output)

    def test_existing_site_is_reused_instead_of_supervising(self):
        with patch.object(launch, 'reuse_service', return_value=True), \
                patch.object(launch, 'spawn_backend') as spawn:
            self.assertEqual(launch.main(['--reload', '--no-browser']), 0)
        spawn.assert_not_called()

    def test_child_waits_for_previous_backend_to_release_port(self):
        busy = OSError(98, 'Address in use')
        create = Mock(side_effect=[busy, busy, 'server'])
        sleeps = []
        self.assertEqual(launch.create_child_server(create, 8765, sleep=sleeps.append, clock=lambda: 0), 'server')
        self.assertEqual(len(sleeps), 2)
        with self.assertRaises(OSError):
            launch.create_child_server(Mock(side_effect=OSError(13, 'denied')), 8765,
                                       sleep=sleeps.append, clock=iter([0, 99]).__next__)

    def test_child_stops_on_stop_file_or_when_the_supervisor_is_gone(self):
        control = self.root / 'control'
        control.mkdir()
        server = Mock()
        thread = launch.watch_supervisor(server, control, 1, interval=.01, alive=lambda pid: True)
        server.shutdown.assert_not_called()
        (control / 'stop').write_text('stop', encoding='utf-8')
        thread.join(2)
        server.shutdown.assert_called_once_with()
        orphan = Mock()
        launch.watch_supervisor(orphan, self.root / 'other', 1, interval=.01, alive=lambda pid: False).join(2)
        orphan.shutdown.assert_called_once_with()

    def test_parent_liveness_never_signals_the_process(self):
        self.assertTrue(launch.parent_alive(__import__('os').getppid()))
        self.assertFalse(launch.parent_alive(2 ** 22 + 12345))

    def test_serve_loop_heartbeat_and_stall_detection(self):
        control = self.root / 'control'
        control.mkdir()
        server = SimpleNamespace(service_actions=Mock())
        now = [100.0]
        actions = launch.install_stall_diagnostics(server, control, clock=lambda: now[0])
        with patch('faulthandler.dump_traceback_later') as arm:
            actions(); actions()
        self.assertEqual(arm.call_count, 2)
        self.assertEqual(server.service_actions, actions)
        heartbeat = control / 'heartbeat'
        self.assertTrue(heartbeat.exists())
        process = Mock(); process.poll.return_value = None
        child = launch.Backend(process, control)
        self.assertFalse(launch.backend_stalled(child))
        old = __import__('time').time() - launch.STALL_RESTART_SECONDS - 5
        __import__('os').utime(heartbeat, (old, old))
        self.assertTrue(launch.backend_stalled(child))
        heartbeat.unlink()
        self.assertFalse(launch.backend_stalled(child, now=child.started + 1))
        self.assertTrue(launch.backend_stalled(child, now=child.started + launch.STARTUP_GRACE_SECONDS + 1))
        process.poll.return_value = 1
        self.assertFalse(launch.backend_stalled(child, now=child.started + 999))

    def test_stale_control_folders_from_killed_supervisors_are_removed(self):
        base = self.root / 'data' / '.reload'
        stale, live = base / '1-1', base / '2-2'
        for folder in (stale, live):
            folder.mkdir(parents=True)
            (folder / 'heartbeat').write_text('x', encoding='utf-8')
        old = __import__('time').time() - 3600
        for path in (stale, stale / 'heartbeat'):
            __import__('os').utime(path, (old, old))
        launch.clean_stale_controls(self.root)
        self.assertFalse(stale.exists())
        self.assertTrue(live.exists())

    def test_stalled_backend_is_restarted(self):
        a = {'server.py': 1}
        spawned, stopped = [], []
        def spawn(port):
            spawned.append(FakeChild(port)); return spawned[-1]
        with patch.object(launch, 'reuse_service', return_value=False), \
                patch.object(launch, 'open_site'), patch('sys.stdout', new_callable=io.StringIO) as output:
            launch.supervise(SimpleNamespace(port=8765, no_browser=True), sleep=lambda _: None, spawn=spawn,
                             stop=stopped.append, snapshot=lambda: dict(a), healthy=lambda port: True,
                             stalled=lambda child: child is spawned[0], max_cycles=3)
        self.assertEqual(len(spawned), 2)
        self.assertEqual(stopped[0], spawned[0])
        self.assertIn('没有响应，正在自动重启', output.getvalue())

    def test_start_cmd_enables_hot_reload(self):
        self.assertIn('launch.py" --reload %*', (launch.ROOT / 'start.cmd').read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
