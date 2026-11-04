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


ROOT = Path(__file__).resolve().parent
WATCH_INTERVAL = 1.0
CHILD_STOP_TIMEOUT = 20
CHILD_BIND_RETRY_SECONDS = 15


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


def spawn_backend(port):
    command = [sys.executable, '-B', str(ROOT / 'launch.py'), '--child', '--no-browser', '--port', str(port)]
    # The child stops when it reads a line or EOF on stdin, so it also exits if
    # this supervisor dies; its output shares this window.
    return subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.PIPE, text=True)


def stop_backend(child, timeout=CHILD_STOP_TIMEOUT):
    if child is None:
        return
    for action in (lambda: child.stdin.write('stop\n'), lambda: child.stdin.flush(), lambda: child.stdin.close()):
        try:
            action()
        except (OSError, ValueError):
            pass
    try:
        child.wait(timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def supervise(args, *, sleep=time.sleep, spawn=spawn_backend, stop=stop_backend, snapshot=watched_files,
              healthy=running_service, max_cycles=None):
    """Hot reload: run the site in a child process and restart it when code changes."""
    url = f'http://127.0.0.1:{args.port}/index.html'
    if reuse_service(args.port, args.no_browser):
        return 0
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
            if not opened and child is not None and healthy(args.port):
                open_site(url, False)
                opened = True
    except KeyboardInterrupt:
        print('\n正在停止网站后台…', flush=True)
    finally:
        stop(child)
    return 0


def stop_on_parent_signal(server, stream=None):
    """Child side of hot reload: shut down cleanly on 'stop' or when the supervisor exits."""
    def wait():
        try:
            (stream or sys.stdin).readline()
        except (OSError, ValueError):
            pass
        server.shutdown()
    thread = threading.Thread(target=wait, name='fundpilot-reload-stop', daemon=True)
    thread.start()
    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(description='FundPilot AI 手动启动')
    parser.add_argument('--check', action='store_true', help='只检查便携环境，不采集数据')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    parser.add_argument('--port', type=int, default=int(os.environ.get('FUNDPILOT_PORT', '8765')))
    parser.add_argument('--reload', action='store_true', help='热更新：修改 .py 文件后自动重启后台')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('端口须为 1～65535 的整数')
    if args.check:
        return self_check()
    if args.reload and not args.child:
        return supervise(args)
    url = f'http://127.0.0.1:{args.port}/index.html'
    if not args.child and reuse_service(args.port, args.no_browser):
        return 0
    from server import create_server
    try:
        server = create_child_server(create_server, args.port) if args.child else create_server(args.port)
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
        stop_on_parent_signal(server)
    else:
        print('请保持本窗口运行，可最小化。关闭窗口或关机会停止网站。', flush=True)
        print('按 Ctrl+C 可停止；下次开机请再次双击 start.cmd。', flush=True)
        print('首次打开请自己创建管理员账号和密码；以后先登录才能使用。', flush=True)
    try:
        server.auto_engine.start()
        open_site(url, args.no_browser)
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止网站后台…', flush=True)
    finally:
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
