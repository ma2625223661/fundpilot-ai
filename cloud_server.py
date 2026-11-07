"""Multi-account cloud entry point. The original local server stays independent."""
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sqlite3
import threading
from functools import partial
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from server import BoundedThreadingHTTPServer, Handler, ROOT
from research_accounts import AccountError, AccountStore, SESSION_SECONDS
from research_captcha import CaptchaStore
from research_phone_auth import PhoneAuth
from research_ai_config import AIConfigStore, _validate_key, _validate_model, validate_schedule, validate_cost_controls, validate_reasoning_effort, DEFAULT_COST_CONTROLS, DEFAULT_REASONING_EFFORT
from research_auto import AutoResearchEngine, client_report_view
from research_categories import BOARDS
from research_free_config import FreeDataConfigStore
from research_frontend import resolve_frontend
from research_public_config import PublicDataConfigStore
from research_schedule import default_market_schedule
from research_sector_ai import enrich_sector_report
from research_responses import validate_base_url
from research_proxy import client_ip, parse_trusted_proxies
from research_sectors import run_sector_research
from research_scarcity import project_member_report
from research_data import CHINA
from datetime import datetime

COOKIE = 'fundpilot_session'


class CloudAIConfigStore(AIConfigStore):
    """The service key exists only in its environment, never in a browser or DB."""
    def __init__(self, path, environ=None, probe=None):
        self.environment = os.environ if environ is None else environ
        self.environment_key = (self.environment.get('FUNDPILOT_AI_API_KEY') or self.environment.get('DEEPSEEK_API_KEY', '')).strip()
        if self.environment_key:
            _validate_key(self.environment_key)
        super().__init__(path, probe=probe)

    def _load(self):
        self._state['key'] = self.environment_key
        self._state['model'] = _validate_model(self.environment.get('FUNDPILOT_AI_MODEL', 'deepseek-flash'))
        self._state['reasoning_effort'] = validate_reasoning_effort(self.environment.get('FUNDPILOT_AI_REASONING_EFFORT', DEFAULT_REASONING_EFFORT))
        self._state['responses_base_url'] = self.https_endpoint(self.environment.get('FUNDPILOT_AI_BASE_URL', ''))
        self._state['schedule'] = default_market_schedule()
        self._state['enabled'] = bool(self.environment_key and self.environment.get('FUNDPILOT_AI_ENABLED') == '1')
        if self.environment_key:
            self._state['verification'] = 'unverified'
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > 65536:
                raise ValueError()
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self._state.update(model=_validate_model(value['model']), reasoning_effort=validate_reasoning_effort(value.get('reasoning_effort', DEFAULT_REASONING_EFFORT)), schedule=validate_schedule(value['schedule']),
                               responses_base_url=self.https_endpoint(value.get('responses_base_url', self._state['responses_base_url'])),
                               enabled=bool(value.get('enabled') and self.environment_key),
                               cost_controls=validate_cost_controls(value.get('cost_controls', DEFAULT_COST_CONTROLS)))
            if (self.environment_key and value.get('key_fingerprint') == hashlib.sha256(self.environment_key.encode()).hexdigest()
                    and value.get('verification') == 'verified' and self._state['model'] in value.get('available_models', [])):
                self._state.update(verification='verified', available_models=value['available_models'],
                                   last_verified_at=value.get('last_verified_at'))
        except (ValueError, OSError, KeyError, TypeError):
            self._state.update(enabled=False, error='云端模型设置读取失败，请管理员重新保存设置')

    def _save(self, state):
        self.https_endpoint(state.get('responses_base_url', ''))
        document = {key: value for key, value in state.items() if key != 'key'}
        document['key_fingerprint'] = hashlib.sha256(state['key'].encode()).hexdigest() if state['key'] else ''
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.tmp-' + secrets.token_hex(6))
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(document, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def status(self):
        return {**super().status(), 'storage': 'cloud-environment'}

    def configure(self, key=None, **kwargs):
        if key is not None:
            raise ValueError('AI 密钥由托管平台环境变量管理')
        if 'responses_base_url' in kwargs:
            kwargs['responses_base_url'] = self.https_endpoint(kwargs['responses_base_url'])
        return super().configure(**kwargs)

    @staticmethod
    def https_endpoint(value):
        value = validate_base_url(value)
        if value and urlsplit(value).scheme != 'https':
            raise ValueError('云端 AI 接口必须使用 HTTPS 地址，请向服务商确认正式接口域名')
        return value


class CloudHandler(Handler):
    def client_ip(self):
        return client_ip(self.client_address[0], self.headers,
                         getattr(self.server, 'trusted_proxies', ()))

    def manual_research(self):
        if getattr(self.server, 'manual_ai', None) is None:
            with self.server.manual_ai_lock:
                if self.server.manual_ai is None:
                    from research_manual_ai import ManualSectorResearch
                    self.server.manual_ai = ManualSectorResearch(self.server.accounts,
                        lambda:self.server.auto_engine, self.server.ai_config.snapshot,
                        connection_checker=self.server.ai_config.connect_for_research,
                        configuration_lock=self.server.ai_config._lock)
        return self.server.manual_ai

    def member_report(self, report, user, *, historical=False):
        subscriptions = self.server.accounts.subscriptions
        report = self.manual_research().overlay(report,historical=historical,user_id=user['id'])
        filtered = subscriptions.project_report(report, user['id'])
        status = subscriptions.summary(user['id'])['status']
        return project_member_report(filtered, status,
                                     datetime.fromtimestamp(self.server.accounts.clock(), CHINA),
                                     historical=historical)

    def request_origin(self):
        return self.server.public_url

    def settings_allowed(self, user):
        return user['role'] == 'admin'

    def setup_without_token(self):
        return self.server.development

    def setup_permitted(self):
        return True

    def access_status(self, user):
        return {'can_manage_settings': self.settings_allowed(user),
            'can_trigger_research': user['role'] == 'admin', 'scope': 'cloud', 'lan_urls': [],
            'site_url': self.request_origin() + '/index.html', 'preview': self.server.development}

    def ai_action(self, path, value):
        if path == '/api/ai/config':
            if set(value) - {'model', 'enabled', 'schedule', 'cost_controls', 'responses_base_url', 'reasoning_effort'}:
                raise AccountError('AI 密钥请在托管平台环境变量中设置')
            previous = self.server.ai_config.status()
            config = self.server.ai_config.configure(**value)
            if config != previous:
                self.server.auto_engine.config_changed(schedule_only=config['model'] == previous['model']
                    and config.get('responses_base_url') == previous.get('responses_base_url')
                    and config.get('reasoning_effort') == previous.get('reasoning_effort')
                    and config['enabled'] == previous['enabled'])
            return self.reply(200, {'config': config})
        config = self.server.ai_config.verify()
        self.server.auto_engine.config_changed()
        return self.reply(200, {'config': config, 'connection': {
            'ok': config.get('verification') == 'verified', 'error': config.get('error') or ''}})

    def data_action(self, path, value):
        if path == '/api/data/public/test':
            return self.reply(200, {'supplemental': self.server.public_data_config.verify()})
        return self.reply(200, {'config': self.server.data_config.verify()})

    def valid_host(self):
        hosts = self.headers.get_all('Host', [])
        return len(hosts) == 1 and hosts[0].lower() == urlsplit(self.server.public_url).netloc.lower()

    def end_headers(self):
        self.send_header('X-Frame-Options', 'DENY')
        if self.server.secure:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        return super().end_headers()

    def token(self):
        try:
            values = self.headers.get_all('Cookie', [])
            if len(values) > 1:
                return ''
            cookie = SimpleCookie()
            if sum(part.strip().startswith(COOKIE + '=') for part in (values[0] if values else '').split(';')) != 1:
                return ''
            cookie.load(values[0] if values else '')
            return cookie[COOKIE].value if COOKIE in cookie else ''
        except Exception:
            return ''

    def identity(self):
        return self.server.accounts.session(self.token())

    def cookie(self, token='', expired=False):
        return (f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; '
                f'Max-Age={0 if expired else SESSION_SECONDS}' + ('; Secure' if self.server.secure else ''))

    def bytes_reply(self, status, data, content_type, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(data)
            except (OSError, TimeoutError):
                pass

    def redirect_login(self):
        return self.bytes_reply(302, b'', 'text/plain', {'Location': '/login.html'})

    def require_captcha(self, captcha):
        """Password login, registration and admin setup each consume one image challenge."""
        if not self.server.captcha.verify(*captcha):
            raise AccountError('图片验证码不正确或已过期，请输入新的验证码')

    def read_json(self):
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
            raise AccountError('请求长度无效')
        try:
            size = int(lengths[0])
        except ValueError:
            raise AccountError('请求长度无效') from None
        if not 2 <= size <= 8192 or self.headers.get_content_type() != 'application/json':
            raise AccountError('请发送有效的 JSON 请求')
        try:
            body = self.read_body(size)
            value = json.loads(body) if len(body) == size else None
        except (ValueError, UnicodeError):
            raise AccountError('请求内容无效') from None
        if not isinstance(value, dict):
            raise AccountError('请求内容无效')
        return value

    def do_HEAD(self):
        if urlsplit(self.path).path == '/api/health':
            return self.reply(200, {'ok': True, 'mode': 'cloud'})
        if not self.valid_host():
            return self.reply(403, {'error': '访问地址无效'})
        if urlsplit(self.path).path.startswith('/api/'):
            return self.reply(405, {'error': '请使用 GET 请求'})
        return self.do_GET()

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path == '/api/health':
            # The hosting platform may use an internal Host for health probes.
            return self.reply(200, {'ok': True, 'mode': 'cloud', 'research_scope': 'sectors'})
        if not self.valid_host():
            return self.reply(403, {'error': '访问地址无效'})
        if path == '/api/auth/status':
            return self.reply(200, {'needs_setup': self.server.accounts.needs_setup(),
                                   'setup_token_required': not self.setup_without_token(),
                                   'setup_available': self.setup_permitted(),
                                   'registration_open': self.server.registration_open,
                                   'phone_auth': self.server.phone_auth.status(),
                                   'captcha_required': True})
        if path == '/api/auth/captcha':
            try:
                self.server.accounts.rate_limit('captcha-ip:' + self.client_ip(), 60, 600)
            except AccountError as error:
                return self.reply(error.status, {'error': str(error)})
            return self.reply(200, self.server.captcha.issue())
        if path.startswith('/') and path[1:] in self.server.frontend.public:
            return super().do_HEAD() if self.command == 'HEAD' else super().do_GET()
        user = self.identity()
        if not user:
            if path.startswith('/api/') or path == '/session-context.js':
                return self.reply(401, {'error': '请先登录'})
            return self.redirect_login()
        if path == '/api/auth/me':
            return self.reply(200, user)
        if path == '/api/me/phone':
            return self.reply(200, self.server.phone_auth.summary(user['id']))
        if path == '/session-context.js':
            context = {**user, 'mode': getattr(self.server, 'auth_mode', 'cloud'), 'preview': self.server.development}
            script = ('window.FundPilotCloud=' + json.dumps(context, ensure_ascii=True) + ';').encode()
            return self.bytes_reply(200, script, 'application/javascript; charset=utf-8')
        if path == '/api/access':
            return self.reply(200, self.access_status(user))
        if path == '/api/me/watchlist':
            return self.reply(200, {'items': self.server.accounts.watchlist(user['id'])})
        if path == '/api/me/ai-research':
            try:
                query = parse_qs(parsed.query)
                if set(query) - {'job_id'} or 'job_id' in query and len(query['job_id']) != 1:
                    raise AccountError('推理任务参数无效')
                jobs = self.manual_research()
                result = jobs.status(user['id'], query['job_id'][0]) if query.get('job_id') else jobs.pending(user['id'])
                return self.reply(200, result)
            except AccountError as error:
                return self.reply(error.status, {'error':str(error)})
        if path == '/api/me/ai-subscription':
            subscriptions = self.server.accounts.subscriptions
            return self.reply(200, {'subscription':subscriptions.summary(user['id']),
                                   'items':subscriptions.ledger(user['id'])})
        if path == '/api/me/history':
            return self.reply(200, {'items': self.server.accounts.history(user['id'])})
        if path == '/api/me/cycle':
            from research_cycle import project_cycle
            state = self.server.auto_engine.status()
            return self.reply(200, project_cycle(self.server.accounts, user['id'], state.get('report') or {},
                                                report_stale=state.get('report_stale') is True))
        if path == '/api/me/reviews':
            # Local evidence projection only: opening/refreshing never starts AI
            # and this included subscription feature has no credit debit path.
            state = self.server.auto_engine.status()
            report = state.get('report') or {}
            read_histories = getattr(self.server.auto_engine, 'review_histories', None)
            histories = read_histories(report.get('as_of')) if callable(read_histories) else None
            if isinstance(histories, dict):
                report = {**report, '_quote_histories':histories}
            config = self.server.ai_config.snapshot()
            return self.reply(200, self.server.accounts.reviews.project(user['id'], report, config,
                                                                      report_stale=state.get('report_stale') is True))
        if path == '/api/me/history/report':
            report_id = parse_qs(parsed.query).get('as_of', [''])[0]
            try:
                report = self.server.accounts.historical_report(user['id'], report_id)
                return self.reply(200, {'report': self.member_report(report, user, historical=True)})
            except AccountError as error:
                return self.reply(error.status, {'error': str(error)})
        if path == '/api/admin/users':
            if user['role'] != 'admin':
                return self.reply(403, {'error': '仅管理员可管理账号'})
            with self.server.accounts.connection() as db:
                users = [dict(row) for row in db.execute('SELECT id,username,role,disabled,created FROM users ORDER BY created')]
            for item in users:
                item['created_at'] = item.pop('created')
                item['password_status'] = '已设置（不可查看）'
                item['ai_subscription'] = self.server.accounts.subscriptions.summary(item['id'])
            return self.reply(200, {'items': users})
        if path in ('/api/auto/status', '/api/auto/report'):
            summary = path == '/api/auto/status' and parse_qs(parsed.query).get('summary') == ['1']
            value = self.server.auto_engine.status(include_report=not summary)
            if isinstance(value.get('report'), dict):
                self.server.accounts.archive_report(value['report'])
            if user['role'] != 'admin':
                # Public model status is useful, service credential hints are not.
                value = dict(value)
                if isinstance(value.get('ai_config'), dict):
                    value['ai_config'] = {**value['ai_config'], 'key_hint': ''}
            if isinstance(value.get('report'), dict):
                value = dict(value)
                value['report'] = client_report_view(self.member_report(value['report'], user),
                                                     compact_sources=getattr(getattr(self.server, 'frontend', None), 'kind', None) == 'react')
            value = dict(value)
            value['ai_subscription'] = self.server.accounts.subscriptions.summary(user['id'])
            if value.get('report_version'):
                # A renewal, pause or unlock refreshes a member's report projection.
                version = hashlib.sha256(json.dumps(value['ai_subscription'], sort_keys=True).encode()).hexdigest()[:16]
                value['report_version'] = str(value['report_version']) + ':' + version
            return self.reply(200, value)
        if path == '/api/ai/config':
            value = self.server.ai_config.status()
            if user['role'] != 'admin':
                value['key_hint'] = ''
            return self.reply(200, value)
        if path == '/api/data/config':
            return self.reply(200, {'config': self.server.data_config.status(),
                                   'supplemental': self.server.public_data_config.status()})
        if path in ('/', '/index.html'):
            frontend = self.server.frontend
            html = (frontend.folder / 'index.html').read_text(encoding='utf-8')
            if not frontend.injects_cloud_scripts:
                # The React build finds its mode through /api/access and /session-context.js.
                return self.bytes_reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
            html = html.replace('报告保存在当前浏览器，最多保留20份。', '个人记录保存到当前账号，最多保留20份。')
            html = html.replace('<script src="sector-history.js"', '<script src="session-context.js" defer></script><script src="cloud-session.js" defer></script><script src="sector-history.js"')
            html = html.replace('</head>', '<link rel="stylesheet" href="cloud-account.css?v=20261102-phone1"><link rel="stylesheet" href="ai-subscription.css?v=20261102-clickresearch3"><script src="ai-subscription.js?v=20261102-clickresearch3" defer></script><script src="phone-verification.js?v=20261102-phone1" defer></script><script src="phone-account.js?v=20261102-phone1" defer></script><script src="cloud-account.js?v=20261102-phone1" defer></script></head>')
            return self.bytes_reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        # Exact asset names only: no directory listings, alternate index spelling,
        # symlink traversal, private state or retired backend APIs.
        filename = path.lstrip('/')
        if filename in self.server.assets and path == '/' + filename:
            return super().do_HEAD() if self.command == 'HEAD' else super().do_GET()
        return self.reply(404, {'error': '页面不存在'})

    def do_POST(self):
        if not self.valid_host() or self.headers.get_all('Origin', []) != [self.request_origin()]:
            self.close_connection = True
            return self.reply(403, {'error': '只接受当前网站的请求'})
        path = urlsplit(self.path).path
        public = path in ('/api/auth/login', '/api/auth/register', '/api/auth/setup',
                          '/api/auth/sms/send', '/api/auth/sms/login')
        user = None if public else self.identity()
        if not public and not user:
            self.close_connection = True
            return self.reply(401, {'error': '请先登录'})
        csrf_values = self.headers.get_all('X-CSRF-Token', [])
        if not public and (len(csrf_values) != 1 or not hmac.compare_digest(csrf_values[0].encode(), user['csrf_token'].encode())):
            self.close_connection = True
            return self.reply(403, {'error': '登录校验已过期，请刷新页面'})
        try:
            if public:
                ip = self.client_ip()
                self.server.accounts.rate_limit('auth-ip:' + ip, 150, 600)
            value = self.read_json()
            if public:
                # Strip before the strict field-set checks below; verified per action.
                captcha = (value.pop('captcha_id', None), value.pop('captcha_code', None))
                if path == '/api/auth/sms/send':
                    if set(value) != {'phone', 'purpose'} or value['purpose'] not in ('register', 'login'):
                        raise AccountError('短信请求参数无效')
                    if value['purpose'] == 'register':
                        if not self.server.registration_open:
                            raise AccountError('当前未开放注册，请联系管理员', 403)
                        if self.server.accounts.needs_setup():
                            raise AccountError('请先完成管理员初始化', 409)
                    self.require_captcha(captcha)
                    return self.reply(200, self.server.phone_auth.send(value['phone'], value['purpose'], ip))
                if path == '/api/auth/setup':
                    if not self.setup_permitted():
                        raise AccountError('请先在运行后台的电脑上创建管理员账号', 403)
                    self.server.accounts.rate_limit('setup', 10, 600)
                    self.require_captcha(captcha)
                    supplied = value.get('setup_token', '')
                    supplied = supplied if isinstance(supplied, str) else ''
                    valid = self.setup_without_token() or hmac.compare_digest(
                        hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(self.server.setup_token.encode()).digest())
                    if not valid:
                        raise AccountError('初始化口令不正确', 403)
                    account = self.server.accounts.create_user(value.get('username'), value.get('password'), admin=True)
                elif path == '/api/auth/register':
                    if not self.server.registration_open:
                        raise AccountError('当前未开放注册，请联系管理员', 403)
                    self.server.accounts.rate_limit('registration-ip:' + ip, 5, 3600)
                    self.server.accounts.rate_limit('registration-global', 200, 3600)
                    self.require_captcha(captcha)
                    phone_fields = {'phone', 'challenge_id', 'code'}
                    if self.server.phone_auth.required or phone_fields.intersection(value):
                        if set(value) != {'username', 'password', *phone_fields}:
                            raise AccountError('请填写手机号并完成验证码验证')
                        account = self.server.phone_auth.register(value['username'], value['password'],
                            value['phone'], value['challenge_id'], value['code'])
                    else:
                        account = self.server.accounts.create_user(value.get('username'), value.get('password'))
                elif path == '/api/auth/sms/login':
                    if set(value) != {'phone', 'challenge_id', 'code'}:
                        raise AccountError('短信登录参数无效')
                    account, (token, csrf) = self.server.phone_auth.login(value['phone'], value['challenge_id'], value['code'])
                else:
                    self.require_captcha(captcha)
                    account, (token, csrf) = self.server.accounts.login(value.get('username'), value.get('password'), with_session=True)
                if self.token():
                    self.server.accounts.logout(self.token())
                if path not in ('/api/auth/login', '/api/auth/sms/login'):
                    token, csrf = self.server.accounts.issue_session(account['id'])
                return self.reply(200, {'user': account, 'csrf_token': csrf}, {'Set-Cookie': self.cookie(token)})
            if path == '/api/auth/logout':
                self.server.accounts.logout(self.token())
                return self.reply(200, {'ok': True}, {'Set-Cookie': self.cookie(expired=True)})
            if path == '/api/auth/password':
                self.server.accounts.rate_limit('password:' + user['id'], 8, 600)
                self.server.accounts.change_password(user['id'], value.get('old_password'), value.get('new_password'))
                return self.reply(200, {'ok': True}, {'Set-Cookie': self.cookie(expired=True)})
            if path == '/api/me/phone/send':
                if set(value) != {'phone'}:
                    raise AccountError('短信请求参数无效')
                return self.reply(200, self.server.phone_auth.send(value['phone'], 'bind', self.client_ip(), user['id']))
            if path == '/api/me/phone/bind':
                if set(value) != {'phone', 'challenge_id', 'code', 'password'}:
                    raise AccountError('手机号绑定参数无效')
                self.server.accounts.rate_limit('phone-bind:' + user['id'], 8, 600)
                return self.reply(200, self.server.phone_auth.bind(user['id'], value['password'],
                    value['phone'], value['challenge_id'], value['code']))
            if path == '/api/me/watchlist':
                board_id, action = value.get('board_id'), value.get('action')
                if board_id not in BOARDS or action not in ('add', 'remove'):
                    raise AccountError('板块或操作无效')
                return self.reply(200, {'items': self.server.accounts.watchlist(user['id'], board_id, action)})
            if path == '/api/me/history':
                if not isinstance(value.get('report_ids'), list):
                    raise AccountError('请提供研究记录列表')
                return self.reply(200, {'items': self.server.accounts.history(user['id'], value.get('report_ids'))})
            if path == '/api/me/ai-research':
                if set(value) != {'sector_id','report_id','reasoning_effort'}:
                    raise AccountError('请提供当前板块、报告版本及推理强度')
                self.server.accounts.rate_limit('manual-ai:' + user['id'], 12, 60)
                result = self.manual_research().start(user['id'],value['sector_id'],value['report_id'],value['reasoning_effort'])
                return self.reply(202 if result['status'] == 'running' else 200, result)
            if path == '/api/me/ai-unlock':
                if set(value) != {'sector_id', 'content_id', 'report_id'} or not all(
                        isinstance(value[k], str) for k in value):
                    raise AccountError('请提供要解锁的板块和报告版本')
                report = self.server.auto_engine.status(include_report=True).get('report')
                historical = not isinstance(report, dict) or report.get('as_of') != value['report_id']
                if historical:
                    report = self.server.accounts.historical_report(user['id'], value['report_id'])
                subscriptions = self.server.accounts.subscriptions
                report = self.manual_research().overlay(report,historical=historical,user_id=user['id'])
                result = subscriptions.unlock(user['id'], report, value['sector_id'], value['content_id'])
                projected = self.member_report(report, user, historical=historical)
                sector = next(s for s in projected['sector_analysis'] if s['id'] == value['sector_id'])
                return self.reply(200, {**result, 'sector':sector, 'report_id':report['as_of']})
            if path == '/api/me/ai-preference':
                if set(value) != {'reasoning_effort'}:
                    raise AccountError('个人推理选项参数无效')
                result = self.server.accounts.subscriptions.preference(user['id'], value['reasoning_effort'])
                return self.reply(200, {'subscription':result})
            if user['role'] != 'admin':
                raise AccountError('此操作仅限管理员，个人关注和记录不受影响', 403)
            if path == '/api/admin/ai-subscription':
                if set(value) - {'user_id', 'action', 'request_id', 'credits', 'days', 'note'}:
                    raise AccountError('订阅操作参数无效')
                subscriptions = self.server.accounts.subscriptions
                result = subscriptions.manage(user['id'], value.get('user_id'), value.get('action'),
                    value.get('request_id'), value.get('credits', 0), value.get('days', 0), value.get('note', ''))
                return self.reply(200, {'subscription':result, 'items':subscriptions.ledger(value['user_id'])})
            if path == '/api/admin/create-admin':
                if set(value) != {'username', 'password'}:
                    raise AccountError('管理员账号参数无效')
                account = self.server.accounts.create_admin_account(value.get('username'), value.get('password'))
                return self.reply(200, {'user': account, 'message': '第二个管理员账号已创建。密码仅在创建时使用，后台不会显示明文。'})
            if path == '/api/admin/reset-password':
                if set(value) != {'user_id', 'new_password'}:
                    raise AccountError('重置密码参数无效')
                if value.get('user_id') == user['id']:
                    raise AccountError('请使用账号设置修改自己的密码')
                self.server.accounts.rate_limit('admin-reset-password:' + user['id'], 8, 600)
                self.server.accounts.reset_password_by_admin(user['id'], value.get('user_id'), value.get('new_password'))
                return self.reply(200, {'ok': True, 'message': '密码已重置，旧登录已退出；明文密码不会保存或展示。'})
            if path == '/api/auto/refresh':
                self.server.accounts.rate_limit('refresh', 1, 30)
                self.server.auto_engine.request_scan(refresh=True, public_only=True)
                return self.reply(202, self.server.auto_engine.status(include_report=False))
            if path == '/api/admin/user-state':
                user_id, disabled = value.get('user_id'), value.get('disabled')
                if user_id == user['id'] or not isinstance(disabled, bool):
                    raise AccountError('不能停用当前管理员')
                with self.server.accounts.connection() as db:
                    result = db.execute("UPDATE users SET disabled=? WHERE id=? AND role='member'", (disabled, user_id))
                    if not result.rowcount:
                        raise AccountError('账号不存在', 404)
                    db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
                return self.reply(200, {'ok': True})
            if path in ('/api/ai/config', '/api/ai/test', '/api/ai/clear'):
                if not self.settings_allowed(user):
                    raise AccountError('请在运行后台的电脑上管理模型设置', 403)
                if path == '/api/ai/clear' and getattr(self.server, 'auth_mode', 'cloud') != 'local':
                    raise AccountError('云端密钥由托管平台管理', 403)
                return self.ai_action(path, value)
            if path in ('/api/data/config', '/api/data/test', '/api/data/public/test'):
                if not self.settings_allowed(user):
                    raise AccountError('请在运行后台的电脑上检查数据源', 403)
                return self.data_action(path, value)
            raise AccountError('接口不存在', 404)
        except AccountError as error:
            return self.reply(error.status, {'error': str(error)})
        except (TimeoutError, OSError, sqlite3.Error):
            self.close_connection = True
            return self.reply(503, {'error': '服务暂时繁忙，请稍后重试'})
        except (ValueError, TypeError):
            return self.reply(400, {'error': '参数无效，请检查输入内容'})


def create_cloud_server(port=8080, state_dir=None, public_url=None, development=False, environ=None, runner=None,
                        frontend=None):
    environment = os.environ if environ is None else environ
    frontend = frontend or resolve_frontend(ROOT, environment)
    folder = Path(state_dir or environment.get('FUNDPILOT_STATE_DIR', ROOT / 'data' / 'cloud')).resolve()
    if not development and not state_dir and not environment.get('FUNDPILOT_STATE_DIR'):
        raise RuntimeError('云端启动需要 FUNDPILOT_STATE_DIR 指向持久卷目录')
    trusted_proxies = parse_trusted_proxies(environment.get('FUNDPILOT_TRUSTED_PROXIES', ''))
    bind_host = '127.0.0.1' if development else environment.get('FUNDPILOT_BIND_HOST', '0.0.0.0')
    if bind_host not in ('127.0.0.1', '0.0.0.0'):
        raise RuntimeError('FUNDPILOT_BIND_HOST 仅支持 127.0.0.1 或 0.0.0.0')
    service = BoundedThreadingHTTPServer((bind_host, port),
        partial(CloudHandler, directory=str(frontend.folder)))
    try:
        service.trusted_proxies = trusted_proxies
        origin = public_url or environment.get('FUNDPILOT_PUBLIC_URL')
        if not origin and environment.get('RAILWAY_PUBLIC_DOMAIN'):
            origin = 'https://' + environment['RAILWAY_PUBLIC_DOMAIN']
        if development:
            origin = f'http://127.0.0.1:{service.server_port}'
        parsed = urlsplit(origin or '')
        if (not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or parsed.username or parsed.password or not development and parsed.scheme != 'https'):
            raise RuntimeError('请设置 HTTPS 的 FUNDPILOT_PUBLIC_URL，或使用托管平台提供的域名')
        service.public_url = origin.rstrip('/')
        service.development, service.secure = development, parsed.scheme == 'https'
        service.setup_token = environment.get('FUNDPILOT_SETUP_TOKEN', '')
        service.accounts = AccountStore(folder / 'accounts.sqlite3')
        service.phone_auth = PhoneAuth(service.accounts, environment)
        service.captcha = CaptchaStore()
        service.manual_ai, service.manual_ai_lock = None, threading.Lock()
        if not development and service.accounts.needs_setup() and len(service.setup_token) < 32:
            raise RuntimeError('首次上线请在平台设置至少 32 个字符的随机 FUNDPILOT_SETUP_TOKEN')
        service.registration_open = environment.get('FUNDPILOT_REGISTRATION_OPEN', '1') == '1'
        service.frontend = frontend
        service.assets = frontend.assets
        service.allowed_hosts = {parsed.netloc}
        service.research_scope = 'sectors'
        service.ai_config = CloudAIConfigStore(folder / 'ai-settings.json', environment)
        service.data_config = FreeDataConfigStore()
        service.public_data_config = PublicDataConfigStore()
        def run(**kwargs):
            return run_sector_research(**kwargs, data_config={**service.data_config.snapshot(),
                'secondary_provider': 'public_multisource'}, include_events=True)
        from research_personal_ai import personalized_runner
        service.auto_engine = AutoResearchEngine(folder / 'sector-report.json', runner=runner or run,
            config_provider=service.ai_config.snapshot,
            ai_runner=personalized_runner(service.accounts.subscriptions), research_scope='sectors')
        return service
    except BaseException:
        service.server_close()
        raise


def main():
    development = os.environ.get('FUNDPILOT_CLOUD_DEV') == '1'
    service = create_cloud_server(int(os.environ.get('PORT', '8877' if development else '8080')), development=development)
    # One process owns the shared schedule and persistent database.
    service.auto_engine.start()
    def stop(signum, frame):
        threading.Thread(target=service.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f'FundPilot {"本地多人预览" if development else "云端多人网站"}: {service.public_url}/login.html', flush=True)
    try:
        service.serve_forever()
    finally:
        service.auto_engine.close()
        service.server_close()


if __name__ == '__main__':
    main()
