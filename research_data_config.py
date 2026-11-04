"""Independent data-source settings with an optional free BaoStock provider."""
import base64
import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from research_ai_config import encrypt_key, decrypt_key
from research_data import now_iso
from research_tushare import probe_tushare
from research_free_data import probe_baostock, provider_status


def _token(value):
    if not isinstance(value, str):
        raise ValueError('Tushare Token 格式无效')
    value = value.strip()
    if not value or len(value) > 512 or not value.isascii() or any(c.isspace() or not c.isprintable() for c in value):
        raise ValueError('Tushare Token 格式无效')
    return value


def _safe_capabilities(value):
    allowed_statuses = {'available', 'empty', 'permission', 'rate_limit', 'network', 'format', 'authentication', 'provider', 'budget', 'not_installed'}
    known = {'daily', 'daily_basic', 'index_member_all', 'index_classify', 'fina_indicator', 'trade_cal',
             'stock_basic', 'stock_industry', 'financial'}
    messages = {'available': '已取得样本数据', 'empty': '接口返回空数据，尚不能确认数据覆盖',
                'permission': '当前账号没有此接口权限或积分不足', 'rate_limit': '当前接口调用频率或配额已达限制',
                'authentication': 'Tushare Token 无效，请重新保存', 'network': 'Tushare 服务连接失败或超时',
                'format': 'Tushare 返回的数据格式无效', 'provider': 'Tushare 数据服务暂未完成请求',
                'budget': '本轮数据请求预算已用完', 'not_installed': '免费数据源未安装'}
    output = {}
    if not isinstance(value, dict):
        return output
    for api_name, record in value.items():
        if api_name not in known or not isinstance(record, dict) or record.get('status') not in allowed_statuses:
            continue
        status = record['status']
        count = record.get('count')
        count = count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 10_000 else 0
        if status == 'available' and not count:
            status = 'empty'
        output[api_name] = {'status': status, 'count': count,
                            'message': messages[status], 'checked_at': _safe_time(record.get('checked_at'))}
    return output


def _safe_time(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError:
        return None


class DataConfigStore:
    def __init__(self, path, encrypt=None, decrypt=None, probe=None):
        self.path = Path(path)
        self._encrypt = encrypt or encrypt_key
        self._decrypt = decrypt or decrypt_key
        self._probe = probe or probe_tushare
        self._lock = threading.RLock()
        self._state = self._empty()
        self._load()

    @staticmethod
    def _empty():
        return {'provider': 'baostock', 'token': '', 'revision': uuid.uuid4().hex, 'verification': 'unconfigured',
                'capabilities': {}, 'error': '', 'last_verified_at': None}

    def status(self):
        with self._lock:
            state = self._state
            free = provider_status()
            selected = state.get('provider') or ('tushare' if state['token'] else 'baostock')
            provider_state = free.get('status') if selected == 'baostock' else state.get('verification', 'unconfigured')
            configured = bool(state['token']) if selected == 'tushare' else state.get('verification') in ('verified', 'partial')
            error = state.get('error', '')
            if selected == 'baostock' and free.get('status') == 'not_installed' and not error:
                error = free.get('message', '免费数据源未安装')
            return {'provider': selected, 'status': provider_state, 'provider_status': provider_state,
                    'configured': configured,
                    'free_provider': free,
                    'token_hint': '••••' + state['token'][-4:] if len(state['token']) >= 8 else '••••' if state['token'] else '',
                    **copy.deepcopy({key: state[key] for key in ('revision', 'verification', 'capabilities', 'last_verified_at')}),
                    'error': error,
                    'storage': 'windows-dpapi'}

    def snapshot(self):
        with self._lock:
            value = copy.deepcopy(self._state)
            value['free_provider'] = provider_status()
            return value

    def configure(self, token=None, provider=None):
        # A blank browser field preserves the existing token.
        if token is not None and token != '':
            token = _token(token)
        if provider not in (None, '', 'baostock', 'tushare'):
            raise ValueError('数据源类型无效')
        with self._lock:
            # Legacy callers pass a token as the first positional argument;
            # preserve that meaning as an explicit Tushare selection.
            selected = provider or ('tushare' if token not in (None, '') else self._state.get('provider') or 'baostock')
            if token in (None, ''):
                token = self._state['token']
            if selected == self._state.get('provider') and token == self._state['token']:
                return self.status()
            candidate = {**self._empty(), 'provider': selected, 'token': token,
                         'verification': 'unverified'}
            self._save(candidate)
            self._state = candidate
            return self.status()

    def verify(self):
        with self._lock:
            observed = copy.deepcopy(self._state)
        if observed.get('provider') == 'baostock':
            try:
                result = probe_baostock()
                capabilities = _safe_capabilities(result.get('capabilities')) if isinstance(result, dict) else {}
                verification = result.get('verification', 'failed') if isinstance(result, dict) else 'failed'
                error = result.get('error', '') if isinstance(result, dict) else '免费数据源检查未完成'
            except Exception:
                capabilities, verification = {}, 'failed'
                error = '免费数据源检查未完成，请稍后重试'
        elif not observed['token']:
            return self.status()
        else:
            try:
                result = self._probe(observed['token'])
                capabilities = _safe_capabilities(result.get('capabilities')) if isinstance(result, dict) else {}
                available = sum(record['status'] == 'available' and record['count'] > 0 for record in capabilities.values())
                verification = 'verified' if len(capabilities) == 6 and available == 6 else 'partial' if available else 'failed'
                error = '' if verification == 'verified' else '部分数据接口尚未取得有效数据，请查看各项权限状态'
            except Exception:
                capabilities, verification = {}, 'failed'
                error = 'Tushare 权限检查未完成，请稍后重试'
        with self._lock:
            if self._state['revision'] != observed['revision']:
                return self.status()
            candidate = {**self._state, 'capabilities': capabilities, 'verification': verification,
                         'error': error, 'last_verified_at': now_iso(), 'revision': uuid.uuid4().hex}
            self._save(candidate)
            self._state = candidate
            return self.status()

    def clear(self):
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                raise RuntimeError('数据源配置删除失败') from None
            self._state = self._empty()
            return self.status()

    def _save(self, state):
        temporary = self.path.with_name(self.path.name + '.tmp-' + uuid.uuid4().hex)
        try:
            encrypted = self._encrypt(state['token'].encode()) if state['token'] else b''
            if not isinstance(encrypted, bytes) or (state['token'] and not encrypted):
                raise ValueError()
            document = {key: value for key, value in state.items() if key != 'token'}
            document.update(version=1, encrypted_token=base64.b64encode(encrypted).decode('ascii'))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open('xb') as stream:
                stream.write(json.dumps(document, ensure_ascii=False).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            raise RuntimeError('Tushare 配置加密保存失败，请检查本机账户与数据目录') from None
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self):
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > 65_536:
                raise ValueError()
            document = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(document, dict) or document.get('version') != 1 or 'token' in document:
                raise ValueError()
            encrypted = base64.b64decode(document['encrypted_token'], validate=True)
            token = _token(self._decrypt(encrypted).decode()) if encrypted else ''
            revision = document['revision']
            if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{32}', revision):
                raise ValueError()
            verification = document['verification']
            if verification not in ('unconfigured', 'unverified', 'verified', 'partial', 'failed'):
                raise ValueError()
            capabilities = _safe_capabilities(document.get('capabilities'))
            # Persisted status does not grant an interface permission: actual
            # requests still evaluate provider results independently.
            provider = document.get('provider') or ('tushare' if token else 'baostock')
            if provider not in ('baostock', 'tushare'):
                raise ValueError()
            self._state = {'provider': provider, 'token': token, 'revision': revision, 'verification': verification if (token or provider == 'baostock') else 'unconfigured',
                           'capabilities': capabilities, 'last_verified_at': _safe_time(document.get('last_verified_at')),
                           'error': '' if verification in ('verified', 'unverified', 'unconfigured') else '部分数据接口尚未取得有效数据，请查看各项权限状态'}
        except Exception:
            self._state = self._empty()
            self._state.update(verification='failed', error='本机加密数据源配置无法读取，请重新保存 Token')
