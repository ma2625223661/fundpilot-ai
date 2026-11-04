"""Manual launcher that reuses the site's existing password-protected backend."""
import argparse
from http.client import HTTPException
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime


ROOT = Path(__file__).resolve().parent
WATCH_INTERVAL = 1.0
CHILD_STOP_TIMEOUT = 20
CHILD_BIND_RETRY_SECONDS = 15
HEARTBEAT_SECONDS = 5
STALL_DUMP_SECONDS = 60       # child prints every thread's stack if its serve loop stops this long
STALL_RESTART_SECONDS = 90    # supervisor restarts a child whose heartbeat is this old
STARTUP_GRACE_SECONDS = 180   # first heartbeat may wait for imports and port release


def running_service(port):
    # Identify the application, not its selected AI provider or model.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
            if response.geturl() != f'http://127.0.0.1:{port}/api/health':
                return False
            raw = response.read(65537)
        if len(raw) > 65536:
            return False
        value = json.loads(raw)
        return (isinstance(value, dict) and value.get('ok') is True
                and type(value.get('version')) is int and value['version'] >= 6
                and value.get('research_scope') == 'sectors'
                and value.get('login_required') is True
                and value.get('automatic_research') is True)
    except (OSError, ValueError, HTTPException):
        return False


def open_site(url, no_browser):
    if not no_browser:
        try:
            if not webbrowser.open(url):
                print('请在浏览器打开上方地址。', flush=True)
        except OSError:
            print('未能自动打开浏览器，请手动访问上方地址。', flush=True)


def reuse_service(port, no_browser):
    if not running_service(port):
        return False
    url = f'http://127.0.0.1:{port}/index.html'
    print(f'网站后台已在运行：{url}', flush=True)
    print('已复用现有网站，无需重复启动。请保留原后台窗口。', flush=True)
    open_site(url, no_browser)
    return True


def self_check():
    portable = (ROOT / 'runtime' / 'python.exe').is_file()
    if not portable and (ROOT / '.vendor').is_dir():
        sys.path.insert(0, str(ROOT / '.vendor'))
    packages = {'baostock': 'baostock', 'pandas': 'pandas', 'numpy': 'numpy',
                'xlrd': 'xlrd', 'pypdf': 'pypdf', 'dateutil': 'python-dateutil',
                'tzdata': 'tzdata', 'six': 'six'}
    for name, distribution in packages.items():
        module = importlib.import_module(name)
        if portable and not Path(module.__file__).resolve().is_relative_to(ROOT):
            raise RuntimeError(f'{name} 未使用压缩包中的依赖')
        print(f'  {distribution}: {importlib.metadata.version(distribution)}')
    for file in sorted(ROOT.glob('research_*.py')):
        importlib.import_module(file.stem)
    importlib.import_module('server')
    from zoneinfo import ZoneInfo
    ZoneInfo('Asia/Shanghai')
    ZoneInfo('America/New_York')
    for file in ('index.html', 'styles.css', 'sector-history.js',
                 'sector-research.js', 'sector-research.css', 'responsive.css', 'device-access.js'):
        if not (ROOT / 'dist' / file).is_file():
            raise RuntimeError(f'缺少网页文件：{file}')
    print('环境检查通过；未发送数据请求，也未调用 AI。')
    return 0


LOG_KEEP_DAYS = 14


class DailyLog:
    """Tee console output into data/logs/fundpilot-YYYY-MM-DD.log (kept LOG_KEEP_DAYS).

    The console stays the primary view; the file keeps a record after the window
    is closed. Both the supervisor and the site process append to the same file."""

    def __init__(self, stream, folder, clock=datetime.now):
        self.stream, self.folder, self.clock = stream, Path(folder), clock
        self._day, self._file, self._lock = None, None, threading.Lock()

    def _target(self):
        day = self.clock().strftime('%Y-%m-%d')
        if day != self._day:
            if self._file:
                self._file.close()
            self.folder.mkdir(parents=True, exist_ok=True)
            self._file = open(self.folder / f'fundpilot-{day}.log', 'a', encoding='utf-8')
            self._day = day
            for old in sorted(self.folder.glob('fundpilot-*.log'))[:-LOG_KEEP_DAYS]:
                try:
                    old.unlink()
                except OSError:
                    pass
        return self._file

    def write(self, text):
        written = self.stream.write(text)
        try:
            with self._lock:
                target = self._target()
                target.write(text)
                target.flush()
        except OSError:
            pass  # a full or locked disk must never stop the website
        return written

    def flush(self):
        self.stream.flush()

    def fileno(self):
        return self.stream.fileno()

    def isatty(self):
        return self.stream.isatty()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def enable_log_file(root=ROOT):
    folder = Path(root) / 'data' / 'logs'
    if not isinstance(sys.stdout, DailyLog):
        sys.stdout = DailyLog(sys.stdout, folder)
    if not isinstance(sys.stderr, DailyLog):
        sys.stderr = DailyLog(sys.stderr, folder)


def watched_files(root=ROOT):
    """Backend sources by mtime, plus the set of page files.

    Page content (dist/*) is read from disk on every request, so editing it needs
    no restart; only adding or removing a page file does (the asset list is built
    at startup). Tests are not watched."""
    files = {}
    for path in root.glob('*.py'):
        if not path.name.startswith('test_'):
            try:
                files[path.name] = path.stat().st_mtime_ns
            except OSError:
                pass
    for path in (root / 'dist').glob('*'):
        if path.is_file():
            files['dist/' + path.name] = 'present'
    return files


def changed_files(before, after):
    return sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))


class Backend:
    """A hot-reload child plus the two files it shares with the supervisor.

    The child never reads stdin: on Windows a thread blocked reading an
    anonymous pipe can stall the whole process, so stop requests are a file the
    child polls, and liveness is a heartbeat file touched by its serve loop."""

    def __init__(self, process, control):
        self.process, self.stop_file, self.heartbeat = process, control / 'stop', control / 'heartbeat'
        self.control, self.started = control, time.monotonic()

    def poll(self):
        return self.process.poll()

    @property
    def returncode(self):
        return self.process.returncode


def spawn_backend(port, local_only=False):
    control = ROOT / 'data' / '.reload' / f'{os.getpid()}-{time.monotonic_ns()}'
    control.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', str(ROOT / 'launch.py'), '--child', '--no-browser', '--port', str(port),
               '--control', str(control), '--parent-pid', str(os.getpid())] + (['--local-only'] if local_only else [])
    # Output shares this window; stdin is detached on purpose (see Backend).
    return Backend(subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.DEVNULL), control)


def stop_backend(child, timeout=CHILD_STOP_TIMEOUT):
    if child is None:
        return
    try:
        child.stop_file.write_text('stop', encoding='utf-8')
    except OSError:
        pass
    try:
        child.process.wait(timeout)
    except subprocess.TimeoutExpired:
        child.process.kill()
        child.process.wait()
    for path in (child.stop_file, child.heartbeat):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        child.control.rmdir()
    except OSError:
        pass


def clean_stale_controls(root=ROOT, max_age=600):
    """Remove control folders left by a supervisor that was killed before cleaning up."""
    import shutil
    for folder in (root / 'data' / '.reload').glob('*'):
        beat = folder / 'heartbeat'
        try:
            newest = max(path.stat().st_mtime for path in (folder, beat) if path.exists())
        except (OSError, ValueError):
            continue
        if time.time() - newest > max_age:
            shutil.rmtree(folder, ignore_errors=True)


def backend_stalled(child, now=None):
    """True when a running child stopped beating (its serve loop is stuck)."""
    now = time.monotonic() if now is None else now
    if child is None or child.poll() is not None:
        return False
    try:
        age = time.time() - child.heartbeat.stat().st_mtime
    except OSError:
        return now - child.started > STARTUP_GRACE_SECONDS
    return age > STALL_RESTART_SECONDS


def supervise(args, *, sleep=time.sleep, spawn=spawn_backend, stop=stop_backend, snapshot=watched_files,
              healthy=running_service, stalled=backend_stalled, max_cycles=None):
    """Hot reload: run the site in a child process and restart it when code changes."""
    url = f'http://127.0.0.1:{args.port}/index.html'
    if reuse_service(args.port, args.no_browser):
        return 0
    clean_stale_controls()
    print('热更新已开启：保存 .py 文件后，后台会在几秒内自动重启，无需再双击 start.cmd。', flush=True)
    print('网页文件（dist 文件夹）修改后刷新浏览器即可生效。关闭本窗口或按 Ctrl+C 停止网站。', flush=True)
    seen = snapshot()
    child, opened, cycles = spawn(args.port), args.no_browser, 0
    try:
        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            sleep(WATCH_INTERVAL)
            current = snapshot()
            changed = changed_files(seen, current)
            if changed:
                sleep(0.5)  # let editors finish multi-file saves
                if snapshot() != current:
                    continue
                seen = current
                shown = '、'.join(changed[:4]) + (f' 等 {len(changed)} 个文件' if len(changed) > 4 else '')
                print(f'\n检测到修改：{shown}。正在重启网站后台…', flush=True)
                stop(child)
                child = spawn(args.port)
                continue
            if child is not None and child.poll() is not None:
                print(f'\n网站后台已退出（代码 {child.returncode}）。请查看上方报错；'
                      '修复并保存文件后会自动重新启动。', flush=True)
                child = None
                continue
            if stalled(child):
                print(f'\n网站后台超过 {STALL_RESTART_SECONDS} 秒没有响应，正在自动重启…'
                      '（上方 Timeout 开头的线程堆栈可用于排查卡住的位置）', flush=True)
                stop(child)
                child = spawn(args.port)
                continue
            if not opened and child is not None and healthy(args.port):
                open_site(url, False)
                opened = True
    except KeyboardInterrupt:
        print('\n正在停止网站后台…', flush=True)
    finally:
        stop(child)
    return 0


def parent_alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied still means it exists
        try:
            return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    return os.getppid() == pid


def watch_supervisor(server, control, parent_pid, *, interval=.5, alive=parent_alive):
    """Child side of hot reload: stop on the supervisor's stop file or when it is gone."""
    stop_file = Path(control) / 'stop'

    def wait():
        while not stop_file.exists() and alive(parent_pid):
            time.sleep(interval)
        server.shutdown()
    thread = threading.Thread(target=wait, name='fundpilot-reload-watch', daemon=True)
    thread.start()
    return thread


def install_stall_diagnostics(server, control, *, clock=time.monotonic):
    """Heartbeat from the serve loop itself, plus a GIL-independent stack dump if it stalls."""
    import faulthandler
    heartbeat, original, last = Path(control) / 'heartbeat', server.service_actions, [None]

    def service_actions():
        try:
            # The real console handle: sys.stderr may be the DailyLog wrapper.
            faulthandler.dump_traceback_later(STALL_DUMP_SECONDS, exit=False, file=sys.__stderr__)
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass  # stderr without a file descriptor: skip the dump, keep the heartbeat
        now = clock()
        if last[0] is None or now - last[0] >= HEARTBEAT_SECONDS:
            try:
                heartbeat.write_text(str(time.time()), encoding='utf-8')
                last[0] = now
            except OSError:
                pass
        original()
    server.service_actions = service_actions
    return service_actions


def main(argv=None):
    parser = argparse.ArgumentParser(description='FundPilot AI 手动启动')
    parser.add_argument('--check', action='store_true', help='只检查便携环境，不采集数据')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    parser.add_argument('--port', type=int, default=int(os.environ.get('FUNDPILOT_PORT', '8765')))
    parser.add_argument('--reload', action='store_true', help='热更新：修改 .py 文件后自动重启后台')
    parser.add_argument('--local-only', action='store_true',
                        default=os.environ.get('FUNDPILOT_LOCAL_ONLY') == '1',
                        help='只允许本机访问，手机和局域网其他设备无法打开')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--control', help=argparse.SUPPRESS)
    parser.add_argument('--parent-pid', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('端口须为 1～65535 的整数')
    if args.check:
        return self_check()
    if args.reload and not args.child:
        return supervise(args, spawn=lambda port: spawn_backend(port, local_only=args.local_only))
    url = f'http://127.0.0.1:{args.port}/index.html'
    if not args.child and reuse_service(args.port, args.no_browser):
        return 0
    from server import create_server
    try:
        make = (lambda port: create_server(port, local_only=True)) if args.local_only else create_server
        server = create_child_server(make, args.port) if args.child else make(args.port)
    except OSError as error:
        # Two double-clicks may race while the first backend is still starting.
        if getattr(error, 'winerror', None) in (10013, 10048) or error.errno in (13, 48, 98, 10013, 10048):
            for attempt in range(4):
                if reuse_service(args.port, args.no_browser):
                    return 0
                if attempt < 3:
                    time.sleep(.3)
        print(f'启动失败：无法使用端口 {args.port}。')
        if isinstance(error, (socket.gaierror,)):
            print('请检查电脑本机网络及主机名解析。')
        else:
            print('未能确认该端口上的服务是本网站；现有程序保持运行。')
            print(f'可在本目录运行 launch.py --port {8876 if args.port != 8876 else 8877}，使用其他端口。')
        return 1
    print(f'FundPilot AI 已启动：{url}', flush=True)
    if args.child:
        if args.control and args.parent_pid:
            install_stall_diagnostics(server, args.control)
            watch_supervisor(server, args.control, args.parent_pid)
    else:
        print('请保持本窗口运行，可最小化。关闭窗口或关机会停止网站。', flush=True)
        print('按 Ctrl+C 可停止；下次开机请再次双击 start.cmd。', flush=True)
        print('首次打开请自己创建管理员账号和密码；以后先登录才能使用。', flush=True)
    if args.local_only:
        print('已启用仅本机访问：手机和局域网其他设备无法打开本网站。', flush=True)
    try:
        server.auto_engine.start()
        if not getattr(server, 'skip_account_backup', False):
            from research_local_backup import start_daily_backup
            start_daily_backup(ROOT, log=lambda text: print(text, flush=True))
        open_site(url, args.no_browser)
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止网站后台…', flush=True)
    finally:
        if args.child:
            import faulthandler
            faulthandler.cancel_dump_traceback_later()
        server.auto_engine.close()
        server.server_close()
    return 0


def create_child_server(create_server, port, *, sleep=time.sleep, clock=time.monotonic):
    """A restarted child may briefly race the previous one for the port."""
    deadline = clock() + CHILD_BIND_RETRY_SECONDS
    while True:
        try:
            return create_server(port)
        except OSError as error:
            in_use = getattr(error, 'winerror', None) in (10013, 10048) or error.errno in (13, 48, 98, 10013, 10048)
            if not in_use or clock() >= deadline:
                raise
            sleep(.5)


if __name__ == '__main__':
    if '--check' not in sys.argv:
        enable_log_file()
    try:
        raise SystemExit(main())
    except Exception as error:
        if '--child' in sys.argv:
            # Hot reload: show where the edited code broke; the supervisor keeps waiting for a fix.
            import traceback
            traceback.print_exc()
            print('网站后台启动失败：请根据上面的报错修改代码并保存，热更新会自动重试。', file=sys.stderr)
        else:
            print(f'启动失败：{type(error).__name__}；请运行“检查环境.cmd”查看环境。', file=sys.stderr)
        raise SystemExit(1)
