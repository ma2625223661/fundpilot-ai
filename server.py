"""FundPilot local automatic research server, Python standard library only."""
import json
import gzip
import ipaddress
import os
import socket
import shutil
import threading
import time
from datetime import datetime
from functools import partial, wraps
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from research_service import DEFAULT_CODES, parse_codes, run_research, validate_prefs, validate_request
from research_auto import AutoResearchEngine
from research_ai_config import AIConfigStore
from research_sectors import run_sector_research
from research_sector_ai import enrich_sector_report
from research_free_config import FreeDataConfigStore
from research_public_config import PublicDataConfigStore
from research_schedule import default_market_schedule

ROOT = Path(__file__).resolve().parent
REQUEST_READ_TIMEOUT = 10
MAX_HTTP_WORKERS = 32


def lan_addresses():
    """Only advertise private IPv4 addresses assigned to this computer."""
    try:
        values = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    addresses = set()
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and address.is_private and not (
                address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast):
            addresses.add(str(address))
    return sorted(addresses)


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Bound active HTTP connections before creating their worker threads."""
    daemon_threads = True

    def __init__(self, *args, max_workers=MAX_HTTP_WORKERS,
                 request_read_timeout=REQUEST_READ_TIMEOUT, **kwargs):
        self._request_slots = threading.BoundedSemaphore(max_workers)
        self.request_read_timeout = request_read_timeout
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if os.name == 'nt':
            # On Windows SO_REUSEADDR can let multiple processes bind the same
            # port, leaving browsers connected to an arbitrary old backend.
            # Exclude both same-address and wildcard-address duplicate binds.
            # Keep the platform's existing reuse behavior everywhere else.
            self.allow_reuse_address = False
            self.allow_reuse_port = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            # A slow rejected peer must not stall the sole accept loop.
            try:
                request.setblocking(False)
                body = b'{"error":"Service busy; please retry"}'
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n'
                    b'Content-Type: application/json\r\nContent-Length: ' + str(len(body)).encode('ascii') + b'\r\n\r\n' + body)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def apply_market_plan(root, store):
    """Apply the user's new plan once, preserving credentials and enable state."""
    marker = Path(root) / 'data' / 'market-plan-v1.json'
    if marker.exists():
        return
    store.configure(schedule=default_market_schedule())
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'version': 1, 'mode': 'market_sessions',
        'times': ['09:10', '14:30'], 'timezone': 'Asia/Shanghai', 'event_threshold': 40}), encoding='utf-8')


def archive_legacy_fund_state(root):
    """Remove retired fund lists/reports from active storage, keeping recovery local."""
    root = Path(root)
    old_schedule = root / 'data' / 'automatic-report.schedule.json'
    new_schedule = root / 'data' / 'sector-report.schedule.json'
    if old_schedule.is_file() and not new_schedule.exists():
        shutil.copy2(old_schedule, new_schedule)
    legacy = [root / 'data' / 'automatic-report.json', old_schedule,
              root / 'config' / 'board-candidates.json']
    existing = [path for path in legacy if path.is_file()]
    if not existing:
        return
    backup = root / 'backups' / ('before-sector-only-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True, exist_ok=False)
    for source in existing:
        shutil.move(str(source), str(backup / source.name))


class Handler(SimpleHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(getattr(self.server, 'request_read_timeout', REQUEST_READ_TIMEOUT))

    def handle_one_request(self):
        """Bound the complete request line and headers, even for byte drips."""
        timeout = getattr(self.server, 'request_read_timeout', REQUEST_READ_TIMEOUT)
        state = {'active': True, 'expired': False, 'lock': threading.Lock()}
        self._header_read_state = state

        def expire_headers():
            with state['lock']:
                if not state['active']:
                    return
                state['expired'] = True
                try:
                    # Interrupt a buffered readline without closing the write
                    # half, so a parsed request can receive a small 408 reply.
                    self.connection.shutdown(socket.SHUT_RD)
                except OSError:
                    pass

        timer = threading.Timer(timeout, expire_headers)
        timer.daemon = True
        state['timer'] = timer
        timer.start()
        try:
            return super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # Windows may abort a pending recv when the deadline shuts down
            # its read half. The request must close without dispatching.
            self.close_connection = True
            return
        finally:
            self.finish_header_deadline()

    def finish_header_deadline(self):
        state = getattr(self, '_header_read_state', None)
        if state is None:
            return False
        with state['lock']:
            state['active'] = False
            state['timer'].cancel()
            return state['expired']

    def parse_request(self):
        parsed = super().parse_request()
        expired = self.finish_header_deadline()
        if expired:
            self.close_connection = True
            if parsed:
                self.reply(408, {'error': '请求头读取超时，请重试'})
            return False
        return parsed

    def read_body(self, size):
        """Use a total body deadline so byte-by-byte drips cannot renew it."""
        timeout = getattr(self.server, 'request_read_timeout', REQUEST_READ_TIMEOUT)
        deadline, parts, left = time.monotonic() + timeout, [], size
        try:
            while left:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('request body deadline exceeded')
                self.connection.settimeout(remaining)
                read = getattr(self.rfile, 'read1', self.rfile.read)
                part = read(min(left, 65536))
                if not part:
                    break
                parts.append(part)
                left -= len(part)
            return b''.join(parts)
        finally:
            self.connection.settimeout(timeout)

    def valid_host(self):
        hosts = self.headers.get_all('Host', [])
        if len(hosts) != 1:
            return False
        if hosts[0] in self.server.allowed_hosts:
            return True
        # Wi-Fi DHCP can change after startup. Only accept an address actually
        # assigned to this machine, never a client-supplied arbitrary hostname.
        return hosts[0] in {f'{address}:{self.server.server_port}' for address in lan_addresses()}

    def local_client(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def ai_config_changed(self, schedule_only=False):
        engine = getattr(self.server, 'auto_engine', None)
        if engine is not None:
            engine.config_changed(schedule_only=schedule_only)

    def ai_response(self, config, connection=None):
        engine = getattr(self.server, 'auto_engine', None)
        return {'config': config, 'connection': connection,
                'status': engine.status(include_report=False) if engine is not None else None}

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def reply(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        accepts_gzip = False
        for entry in self.headers.get('Accept-Encoding', '').lower().split(','):
            name, *options = entry.split(';')
            if name.strip() != 'gzip':
                continue
            try:
                quality = next((float(part.strip()[2:]) for part in options if part.strip().startswith('q=')), 1)
            except ValueError:
                quality = 0
            accepts_gzip = quality > 0
            if accepts_gzip:
                break
        compressed = len(body) >= 4096 and accepts_gzip
        if compressed:
            body = gzip.compress(body, compresslevel=3, mtime=0)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass

    def do_HEAD(self):
        if not self.valid_host():
            return self.reply(403, {'error': '访问地址无效，请使用电脑的本机或局域网地址'})
        if urlsplit(self.path).path.startswith('/api/'):
            return self.reply(405, {'error': '此接口不接受 HEAD 请求'}, headers={'Allow': 'GET, POST'})
        return super().do_HEAD()

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': '访问地址无效，请使用电脑的本机或局域网地址'})
        parsed = urlsplit(self.path)
        if parsed.path == '/api/access':
            return self.reply(200, {
                'can_manage_settings': self.local_client(),
                'lan_urls': [f'http://{address}:{self.server.server_port}/index.html'
                             for address in lan_addresses()],
                'scope': 'same_network',
            })
        if parsed.path == '/api/health':
            sectors_only = getattr(self.server, 'research_scope', None) == 'sectors'
            return self.reply(200, {'ok': True, 'provider': 'DeepSeek', 'version': 6 if sectors_only else 5,
                                   'research_scope': 'sectors' if sectors_only else 'funds',
                                   'defaults': [] if sectors_only else list(DEFAULT_CODES),
                                   'automatic_research': True})
        if parsed.path == '/api/ai/config':
            store = getattr(self.server, 'ai_config', None)
            if store is None:
                return self.reply(503, {'error': 'AI 配置服务尚未初始化'})
            return self.reply(200, store.status())
        if parsed.path == '/api/data/config':
            store = getattr(self.server, 'data_config', None)
            if store is None:
                return self.reply(503, {'error': '数据源配置服务尚未初始化'})
            return self.reply(200, {'config': store.status(), 'supplemental': self.server.public_data_config.status()})
        if parsed.path in ('/api/auto/status', '/api/auto/report'):
            engine = getattr(self.server, 'auto_engine', None)
            if engine is None:
                return self.reply(503, {'error': '自动扫描服务尚未初始化'})
            engine.start()
            summary = parsed.path == '/api/auto/status' and parse_qs(parsed.query).get('summary') == ['1']
            return self.reply(200, engine.status(include_report=False) if summary else engine.status())
        if parsed.path == '/api/research':
            if getattr(self.server, 'research_scope', None) == 'sectors':
                return self.reply(410, {'error': '基金研究已移除；当前仅研究板块，请使用 /api/auto/report',
                                        'research_scope': 'sectors'})
            try:
                params = parse_qs(parsed.query)
                codes = parse_codes(params.get('codes', [''])[0])
                prefs = validate_prefs({key: params[key][0] for key in ('risk', 'pos', 'min') if key in params})
                result = run_research(codes, prefs, refresh=params.get('refresh', ['0'])[0] == '1')
                return self.reply(200, result)
            except ValueError as error:
                return self.reply(400, {'error': str(error)})
            except Exception:
                return self.reply(503, {'error': '自动研究暂时不可用，请稍后刷新；已有报告仍可回看'})
        if parsed.path.startswith('/api/'):
            return self.reply(404, {'error': '接口不存在'})
        super().do_GET()

    def do_POST(self):
        if self.path not in ('/api/analyze', '/api/auto/refresh', '/api/ai/config', '/api/ai/test', '/api/ai/clear',
                             '/api/data/config', '/api/data/test', '/api/data/clear', '/api/data/public/test'):
            return self.reply(404, {'error': '接口不存在'})
        if not self.valid_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
            return self.reply(403, {'error': '只接受当前站点页面的请求'})
        if self.path == '/api/analyze' and getattr(self.server, 'research_scope', None) == 'sectors':
            return self.reply(410, {'error': '基金研究已移除；当前仅研究板块', 'research_scope': 'sectors'})
        if self.path.startswith(('/api/data/', '/api/ai/')) and not self.local_client():
            return self.reply(403, {'error': '请在运行服务的电脑上管理数据与 API 配置；局域网可查看报告'})
        try:
            # Read once with a finite socket deadline, after Host/Origin and
            # local credential-management admission. Never wait for body bytes
            # from an unauthorized cross-site or LAN configuration request.
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) > 1 or self.headers.get('Transfer-Encoding'):
                raise ValueError('不支持分块或重复长度的请求')
            size = int(lengths[0]) if lengths else 0
            maximum = 4096 if self.path.startswith(('/api/data/', '/api/ai/')) else 1000 if self.path == '/api/auto/refresh' else 100000
            allow_empty = self.path.startswith('/api/data/') or self.path == '/api/auto/refresh'
            if not 0 <= size <= maximum or not allow_empty and size == 0:
                raise ValueError('请求内容过大或为空')
            raw = self.read_body(size) if size else b''
            if len(raw) != size:
                raise ValueError('请求内容未完整发送')
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError('请求内容必须为对象')
        except (socket.timeout, TimeoutError):
            self.close_connection = True
            return self.reply(408, {'error': '请求内容读取超时，请重试'})
        except (ValueError, TypeError, UnicodeError):
            self.close_connection = True
            return self.reply(400, {'error': '请求内容或长度无效，请重新检查'})
        if self.path.startswith('/api/data/'):
            if not self.local_client():
                return self.reply(403, {'error': '请在运行服务的电脑上检查免费数据源'})
            store = getattr(self.server, 'data_config', None)
            if store is None:
                return self.reply(503, {'error': '数据源配置服务尚未初始化'})
            try:
                if not isinstance(data, dict) or set(data) - {'token', 'provider'}:
                    raise ValueError()
                if self.path == '/api/data/public/test':
                    return self.reply(200, {'supplemental': self.server.public_data_config.verify()})
                if self.path == '/api/data/clear':
                    value = store.clear()
                else:
                    if self.path == '/api/data/config':
                        # BaoStock requires no token.  Legacy token/provider
                        # fields are accepted for old clients but ignored.
                        store.configure()
                    value = store.verify()
                return self.reply(200, {'config': value})
            except (ValueError, TypeError, UnicodeError):
                return self.reply(400, {'error': '免费数据源检查参数无效，请重新检查'})
            except Exception:
                return self.reply(503, {'error': '免费数据源检查暂时不可用，请稍后重试'})
        if self.path.startswith('/api/ai/'):
            if not self.local_client():
                return self.reply(403, {'error': '请在运行服务的电脑上管理 API Key；手机可查看自动研究报告'})
            store = getattr(self.server, 'ai_config', None)
            if store is None:
                return self.reply(503, {'error': 'AI 配置服务尚未初始化'})
            try:
                if self.path == '/api/ai/clear':
                    config = store.clear()
                    self.ai_config_changed()
                    return self.reply(200, self.ai_response(config))
                if self.path == '/api/ai/config':
                    previous = store.status()
                    replacement = data.get('key')
                    if isinstance(replacement, str) and not replacement.strip():
                        replacement = None
                    changes = {'key': replacement, 'model': data.get('model'), 'enabled': data.get('enabled')}
                    if 'schedule' in data:
                        changes['schedule'] = data['schedule']
                    config = store.configure(**changes)
                    # Updating the run schedule is independent of credentials.
                    # A schedule-only save must not make a provider request.
                    credential_change = (replacement is not None or config.get('model') != previous.get('model')
                                         or (config.get('enabled') and not previous.get('enabled')))
                    verify_enabled = credential_change or 'schedule' not in data
                else:
                    config = store.status()
                    verify_enabled = True
                connection = {'ok': False, 'skipped': True, 'error': ''}
                if config.get('configured') and ((config.get('enabled') and verify_enabled) or self.path == '/api/ai/test'):
                    config = store.verify()
                    connection = {'ok': config.get('verification') == 'verified', 'error': config.get('error') or ''}
                self.ai_config_changed(schedule_only=(self.path == '/api/ai/config' and 'schedule' in data and not credential_change))
                return self.reply(200, self.ai_response(config, connection))
            except (ValueError, TypeError, UnicodeError):
                return self.reply(400, {'error': 'AI 配置无效，请检查 API Key、模型、自动研究开关及运行时间'})
            except Exception:
                return self.reply(503, {'error': 'AI 配置暂时不可用，请重试；密钥不会返回到页面'})
        if self.path == '/api/auto/refresh':
            engine = getattr(self.server, 'auto_engine', None)
            if engine is None:
                return self.reply(503, {'error': '自动扫描服务尚未初始化'})
            engine.request_scan(refresh=False, public_only=True)
            return self.reply(202, engine.status(include_report=False))
        try:
            codes, prefs, key, model, context = validate_request(data)
            if 'use_saved_key' in data and not isinstance(data['use_saved_key'], bool):
                raise ValueError('已保存密钥选项无效')
            store = getattr(self.server, 'ai_config', None)
            if not key and data.get('use_saved_key', True) and store is not None:
                saved = store.snapshot()
                if saved.get('enabled'):
                    key, model = saved['key'], saved['model']
        except (ValueError, TypeError, UnicodeError) as error:
            return self.reply(400, {'error': str(error) or '参数无效，请检查观察池与策略设置'})
        try:
            result = run_research(codes, prefs, key=key, model=model, context=context, refresh=data.get('refresh', False))
            return self.reply(200, result)
        except Exception:
            return self.reply(503, {'error': '自动研究暂时不可用，请稍后重试；已有报告仍可回看'})


def create_server(port=8765, *, require_login=True):
    server = BoundedThreadingHTTPServer(('0.0.0.0', port), partial(Handler, directory=str(ROOT / 'dist')))
    addresses = {'127.0.0.1', 'localhost'}
    addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    server.allowed_hosts = {f'{address}:{server.server_port}' for address in addresses}
    server.research_scope = 'sectors'
    archive_legacy_fund_state(ROOT)
    server.ai_config = AIConfigStore(ROOT / 'data' / 'deepseek-config.dpapi.json')
    server.data_config = FreeDataConfigStore(
        on_complete=lambda: server.auto_engine.request_scan(refresh=True, public_only=True))
    server.public_data_config = PublicDataConfigStore(
        on_complete=lambda: server.auto_engine.request_scan(refresh=True, public_only=True))
    apply_market_plan(ROOT, server.ai_config)
    @wraps(run_sector_research)
    def sector_runner(**kwargs):
        return run_sector_research(**kwargs, data_config={**server.data_config.snapshot(),
            'secondary_provider': 'public_multisource'}, include_events=True)
    server.auto_engine = AutoResearchEngine(ROOT / 'data' / 'sector-report.json',
                                          runner=sector_runner, ai_runner=enrich_sector_report,
                                          config_provider=server.ai_config.snapshot, research_scope='sectors')
    if require_login:
        try:
            from research_local_auth import enable_local_accounts
            enable_local_accounts(server, ROOT)
        except BaseException:
            server.auto_engine.close()
            server.server_close()
            raise
    return server


if __name__ == '__main__':
    port = int(os.environ.get('FUNDPILOT_PORT', '8765'))
    server = create_server(port)
    server.auto_engine.start()
    print(f'FundPilot 自动研究: http://127.0.0.1:{port}/index.html', flush=True)
    try:
        server.serve_forever()
    finally:
        server.auto_engine.close()
        server.server_close()
