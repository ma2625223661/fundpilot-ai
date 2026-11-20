"""Startup regressions; local HTTP fixtures only, no data or model requests."""
import importlib.util
import io
import os
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
            self.assertIn('已复用正在运行的网站', output.getvalue())
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
        # Local-only is the default since issue #5.
        create.assert_called_once_with(self.port, local_only=True)

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
        # Local-only is the default since issue #5.
        create.assert_called_once_with(self.port, local_only=True)
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
        (self.root / 'backend').mkdir()
        # Backend code lives in backend/; a stray test or a .py at the top level is not watched.
        for name in ('backend/server.py', 'backend/research_x.py', 'backend/test_server.py', 'backend/notes.md',
                     'top_level.py', 'dist/index.html'):
            (self.root / name).write_text('x', encoding='utf-8')

    def test_watch_list_covers_backend_code_and_page_names_but_not_tests(self):
        files = launch.watched_files(self.root)
        self.assertEqual(set(files), {'server.py', 'research_x.py', 'dist/index.html'})
        before = dict(files)
        (self.root / 'dist' / 'index.html').write_text('edited page', encoding='utf-8')
        self.assertEqual(launch.changed_files(before, launch.watched_files(self.root)), [])
        (self.root / 'dist' / 'new.js').write_text('x', encoding='utf-8')
        (self.root / 'backend' / 'test_server.py').write_text('edited test', encoding='utf-8')
        __import__('os').utime(self.root / 'backend' / 'server.py', ns=(1, 1))
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
        self.assertIn('launch.py" --reload --background %*', (launch.ROOT / 'start.cmd').read_text(encoding='utf-8'))
        vbs = (launch.ROOT / '启动网站.vbs').read_bytes()
        self.assertTrue(vbs.isascii())  # VBScript reads ANSI/UTF-16: keep it encoding-proof
        self.assertIn(b'launch.py"" --reload --background", 0, False', vbs)  # window style 0 = hidden
        self.assertIn('--stop', (launch.ROOT / '停止网站.cmd').read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_daily_log_tees_console_output_and_keeps_two_weeks(self):
        from datetime import datetime, timedelta
        folder = self.root / 'logs'
        folder.mkdir()
        for days in range(20, 0, -1):
            (folder / f'fundpilot-{(datetime(2026, 11, 4) - timedelta(days=days)):%Y-%m-%d}.log').write_text('old')
        console = io.StringIO()
        log = launch.DailyLog(console, folder, clock=lambda: datetime(2026, 11, 4, 15, 30))
        log.write('FundPilot AI 已启动\n')
        self.assertEqual(console.getvalue(), 'FundPilot AI 已启动\n')
        self.assertEqual((folder / 'fundpilot-2026-11-04.log').read_text(encoding='utf-8'), 'FundPilot AI 已启动\n')
        self.assertEqual(len(list(folder.glob('fundpilot-*.log'))), launch.LOG_KEEP_DAYS)

    def test_account_backup_is_consistent_daily_and_pruned(self):
        import sqlite3
        from datetime import datetime
        from research_local_backup import backup_accounts
        (self.root / 'data').mkdir()
        db = sqlite3.connect(self.root / 'data' / 'accounts.sqlite3')
        db.execute('PRAGMA journal_mode=WAL')  # like the live account store
        db.execute('CREATE TABLE users(name TEXT)'); db.execute("INSERT INTO users VALUES ('owner')"); db.commit()
        self.addCleanup(db.close)  # the site keeps its connection open during backups
        made = backup_accounts(self.root, keep=3, now=datetime(2026, 11, 4))
        self.assertEqual(made.name, 'accounts-20261104.sqlite3')
        self.assertEqual(sorted(p.name for p in made.parent.iterdir()), ['accounts-20261104.sqlite3'])  # no -wal/-shm/partial
        copy = sqlite3.connect(made)
        self.assertEqual(copy.execute('SELECT name FROM users').fetchall(), [('owner',)])
        copy.close()
        self.assertIsNone(backup_accounts(self.root, keep=3, now=datetime(2026, 11, 4)))  # once per day
        for day in (5, 6, 7):
            backup_accounts(self.root, keep=3, now=datetime(2026, 11, day))
        names = sorted(p.name for p in (self.root / 'backups' / 'accounts').glob('*.sqlite3'))
        self.assertEqual(names, ['accounts-20261105.sqlite3', 'accounts-20261106.sqlite3', 'accounts-20261107.sqlite3'])
        self.assertIsNone(backup_accounts(self.root / 'missing'))

    def test_local_only_flag_reaches_the_server_and_the_child(self):
        service = Mock(); service.serve_forever.side_effect = KeyboardInterrupt
        create = Mock(return_value=service)
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}), \
                patch.object(launch, 'running_service', return_value=False), patch('sys.stdout', new_callable=io.StringIO) as out:
            launch.main(['--port', '8765', '--no-browser', '--local-only'])
        create.assert_called_once_with(8765, local_only=True)
        self.assertIn('仅本机访问', out.getvalue())
        with patch.object(launch.subprocess, 'Popen') as popen, patch.object(launch, 'ROOT', self.root):
            launch.spawn_backend(8765, local_only=True)
        self.assertIn('--local-only', popen.call_args.args[0])

    def test_lan_access_is_opt_in_and_warns_about_plain_http(self):
        for argv, env in ((['--allow-lan'], {}), ([], {'FUNDPILOT_ALLOW_LAN': '1'})):
            service = Mock(); service.serve_forever.side_effect = KeyboardInterrupt
            create = Mock(return_value=service)
            with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}),                     patch.dict(os.environ, env),                     patch.object(launch, 'running_service', return_value=False), patch('sys.stdout', new_callable=io.StringIO) as out:
                launch.main(['--port', '8765', '--no-browser', *argv])
            create.assert_called_once_with(8765)
            self.assertIn('未加密的 HTTP', out.getvalue())
        # Without the opt-in the site stays on this computer and says how to open it up.
        service = Mock(); service.serve_forever.side_effect = KeyboardInterrupt
        create = Mock(return_value=service)
        with patch.dict(sys.modules, {'server': SimpleNamespace(create_server=create)}),                 patch.object(launch, 'running_service', return_value=False), patch('sys.stdout', new_callable=io.StringIO) as out:
            launch.main(['--port', '8765', '--no-browser'])
        create.assert_called_once_with(8765, local_only=True)
        self.assertIn('--allow-lan', out.getvalue())

    def test_local_only_server_refuses_lan_hosts(self):
        import server
        handler = SimpleNamespace(headers=SimpleNamespace(get_all=lambda name, default=None: ['192.168.1.9:8765']),
                                  server=SimpleNamespace(allowed_hosts={'127.0.0.1:8765'}, server_port=8765, local_only=True))
        with patch.object(server, 'lan_addresses', return_value=['192.168.1.9']):
            self.assertFalse(server.Handler.valid_host(handler))
            handler.server.local_only = False
            self.assertTrue(server.Handler.valid_host(handler))



class BackgroundModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_background_start_relaunches_without_a_window_and_returns(self):
        with patch.object(launch, 'reuse_service', return_value=False), \
                patch.object(launch.subprocess, 'Popen') as popen, patch.dict(launch.os.environ, {}, clear=False):
            launch.os.environ.pop(launch.DETACHED_ENV, None)
            self.assertEqual(launch.main(['--reload', '--background', '--port', '8765']), 0)
        command, options = popen.call_args.args[0], popen.call_args.kwargs
        self.assertNotIn('--background', command)
        self.assertIn('--reload', command)
        self.assertEqual(options['env'][launch.DETACHED_ENV], '1')
        self.assertEqual(options['stdin'], launch.subprocess.DEVNULL)

    def test_background_start_reuses_a_running_site(self):
        with patch.object(launch, 'reuse_service', return_value=True), patch.object(launch.subprocess, 'Popen') as popen:
            launch.os.environ.pop(launch.DETACHED_ENV, None)
            self.assertEqual(launch.main(['--reload', '--background']), 0)
        popen.assert_not_called()

    def test_console_flag_keeps_the_visible_window_mode(self):
        with patch.object(launch, 'supervise', return_value=0) as supervise, patch.object(launch.subprocess, 'Popen') as popen:
            launch.os.environ.pop(launch.DETACHED_ENV, None)
            self.assertEqual(launch.main(['--reload', '--background', '--console']), 0)
        popen.assert_not_called()
        supervise.assert_called_once()

    def test_stop_writes_a_request_and_waits_for_the_site_to_go_down(self):
        states = iter([True, True, False])
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(launch.stop_site(8765, sleep=lambda _: None, healthy=lambda port: next(states), root=self.root), 0)
        self.assertTrue(launch.stop_request_file(self.root).exists())  # the supervisor consumes it
        self.assertIn('网站已停止', out.getvalue())
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(launch.stop_site(8765, healthy=lambda port: False, root=self.root), 0)
        self.assertIn('没有在运行', out.getvalue())
        now = iter(range(0, 100, 10))
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(launch.stop_site(8765, sleep=lambda _: None, clock=lambda: next(now),
                                              healthy=lambda port: True, root=self.root), 1)
        self.assertFalse(launch.stop_request_file(self.root).exists())
        self.assertIn('旧版带窗口', out.getvalue())

    def test_supervisor_honours_the_stop_request(self):
        spawned, stopped = [], []
        def spawn(port):
            spawned.append(FakeChild(port)); return spawned[-1]
        request = self.root / 'data' / '.reload' / 'stop-site'
        def sleep(_):
            request.parent.mkdir(parents=True, exist_ok=True); request.write_text('stop')
        with patch.object(launch, 'reuse_service', return_value=False), patch.object(launch, 'ROOT', self.root), \
                patch('sys.stdout', new_callable=io.StringIO) as out:
            code = launch.supervise(SimpleNamespace(port=8765, no_browser=True), sleep=sleep, spawn=spawn,
                                    stop=stopped.append, snapshot=lambda: {}, healthy=lambda port: True,
                                    stalled=lambda child: False, max_cycles=5)
        self.assertEqual(code, 0)
        self.assertEqual(stopped, [spawned[0]])
        self.assertFalse(request.exists())
        self.assertIn('收到停止请求', out.getvalue())

    def test_background_crash_is_reported_in_a_message_box(self):
        with patch.dict(launch.os.environ, {launch.DETACHED_ENV: '1'}), patch.object(launch.os, 'name', 'nt'), \
                patch('sys.stdout', new_callable=io.StringIO):
            box = Mock()
            fake = SimpleNamespace(windll=SimpleNamespace(user32=SimpleNamespace(MessageBoxW=box)))
            with patch.dict(sys.modules, {'ctypes': fake}):
                launch.notify('网站后台已退出', wait=True)
        self.assertIn('网站后台已退出', box.call_args.args[1])
