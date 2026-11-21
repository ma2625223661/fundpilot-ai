"""Account gate for the existing Windows/LAN service and its saved research."""
from functools import partial
import threading
from urllib.parse import urlsplit

from cloud_server import CloudHandler
from research_accounts import AccountError, AccountStore
from research_captcha import CaptchaStore
from research_phone_auth import PhoneAuth
from server import Handler, lan_addresses


class LocalAccountHandler(CloudHandler):
    def valid_host(self):
        return Handler.valid_host(self)

    def request_origin(self):
        # Callers validate Host against the actual machine before using this.
        return 'http://' + self.headers.get('Host', '')

    def settings_allowed(self, user):
        return user['role'] == 'admin' and self.local_client()

    def setup_permitted(self):
        return self.local_client()

    def setup_without_token(self):
        return self.local_client()

    def access_status(self, user):
        return {'can_manage_settings':self.settings_allowed(user),
            'can_trigger_research':user['role'] == 'admin', 'scope':'account_local',
            'lan_urls':[] if getattr(self.server, 'local_only', False) else
                [f'http://{address}:{self.server.server_port}/index.html' for address in lan_addresses()],
            'site_url':self.request_origin() + '/index.html', 'preview':False,
            'local_only':bool(getattr(self.server, 'local_only', False))}

    def do_GET(self):
        if urlsplit(self.path).path == '/api/health':
            if not self.valid_host():
                return self.reply(403, {'error':'访问地址无效'})
            config = self.server.ai_config.status()
            return self.reply(200, {'ok':True,
                'provider':'Responses' if config.get('model') == 'gpt-6.1-sol' else 'DeepSeek',
                'model':config.get('model'), 'reasoning_effort':config.get('reasoning_effort'),
                'version':6, 'research_scope':'sectors','defaults':[],
                'automatic_research':True,'login_required':True})
        return super().do_GET()

    def ai_action(self, path, value):
        store = self.server.ai_config
        if path == '/api/ai/clear':
            config = store.clear()
            self.server.auto_engine.config_changed()
            return self.reply(200, self.ai_response(config))
        connection = {'ok':False,'skipped':True,'error':''}
        schedule_only = False
        if path == '/api/ai/config':
            if set(value) - {'key','model','enabled','schedule','cost_controls','responses_base_url','reasoning_effort'}:
                raise AccountError('模型设置参数无效')
            changes = dict(value)
            if not changes.get('key'):
                changes.pop('key',None)
            previous = store.status()
            config = store.configure(**changes)
            credential_change = ('key' in changes or config['model'] != previous['model']
                                 or config.get('reasoning_effort') != previous.get('reasoning_effort')
                                 or config.get('responses_base_url') != previous.get('responses_base_url')
                                 or config['enabled'] and not previous['enabled'])
            schedule_only = not credential_change and config['enabled'] == previous['enabled']
            should_verify = config['enabled'] and credential_change
        else:
            config = store.status()
            should_verify = True
        if config.get('configured') and should_verify:
            config = store.verify()
            connection = {'ok':config.get('verification') == 'verified','error':config.get('error') or ''}
        self.server.auto_engine.config_changed(schedule_only=schedule_only)
        return self.reply(200, self.ai_response(config,connection))


def enable_local_accounts(service, root):
    service.accounts = AccountStore(root / 'data' / 'accounts.sqlite3')
    service.phone_auth = PhoneAuth(service.accounts)
    service.captcha = CaptchaStore()
    service.manual_ai, service.manual_ai_lock = None, threading.Lock()
    from research_personal_ai import personalized_runner
    service.auto_engine.ai_runner = personalized_runner(service.accounts.subscriptions)
    service.auth_mode = 'local'
    service.public_url = f'http://127.0.0.1:{service.server_port}'
    service.development = False
    service.secure = False
    service.setup_token = ''
    service.registration_open = True
    # The frontend was chosen when the server was created; only the handler changes.
    service.assets = service.frontend.assets
    service.RequestHandlerClass = partial(LocalAccountHandler,directory=str(service.frontend.folder))
