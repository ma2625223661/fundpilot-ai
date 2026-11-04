"""Manual launcher that reuses the site's existing password-protected backend."""
import argparse
from http.client import HTTPException
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parent


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


def main(argv=None):
    parser = argparse.ArgumentParser(description='FundPilot AI 手动启动')
    parser.add_argument('--check', action='store_true', help='只检查便携环境，不采集数据')
    parser.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    parser.add_argument('--port', type=int, default=int(os.environ.get('FUNDPILOT_PORT', '8765')))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('端口须为 1～65535 的整数')
    if args.check:
        return self_check()
    url = f'http://127.0.0.1:{args.port}/index.html'
    if reuse_service(args.port, args.no_browser):
        return 0
    from server import create_server
    try:
        server = create_server(args.port)
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


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'启动失败：{type(error).__name__}；请运行“检查环境.cmd”查看环境。', file=sys.stderr)
        raise SystemExit(1)
