"""Encrypted, revisioned DeepSeek configuration for unattended research."""
import base64
import ctypes
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_service import MODEL_ALIASES, MODELS, probe_deepseek_key
from research_responses import is_responses, validate_base_url, probe_responses_key
from research_schedule import DEFAULT_SCHEDULE


TZ = timezone(timedelta(hours=8))
SCHEDULE_INTERVALS = range(1, 1441)
DEFAULT_COST_CONTROLS = {'reuse_enabled': True, 'daily_request_limit': 28, 'daily_token_limit': 8_000_000}
REASONING_EFFORTS = ('medium', 'xhigh')
DEFAULT_REASONING_EFFORT = 'xhigh'
_UNSET = object()
_MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
_SAFE_ERRORS = {
    'API Key 无效，请重新配置', 'DeepSeek 余额不足',
    '请求频率过高，请稍后重试', 'DeepSeek 连接失败或超时',
    'DeepSeek 返回的数据格式无效',
    'AI 服务商余额不足', 'AI 服务商连接失败或超时', 'AI 服务商返回的数据格式无效',
    '请先配置服务商接口地址',
}


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, protect):
    """Use the current Windows account; never fall back to plaintext storage."""
    if os.name != 'nt':
        raise RuntimeError('当前系统不支持 Windows 加密存储')
    if not isinstance(data, bytes):
        raise TypeError('加密数据格式无效')
    from ctypes import wintypes
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    if protect:
        operation = crypt32.CryptProtectData
        operation.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
                              ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        description = 'Fund research DeepSeek credential'
    else:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
                              ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        description = None
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Windows 加密存储失败')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def encrypt_key(data):
    return _dpapi(data, True)


def decrypt_key(data):
    return _dpapi(data, False)


def _validate_key(value):
    if not isinstance(value, str):
        raise ValueError('API Key 格式无效')
    value = value.strip()
    if not value or len(value) > 512 or not value.isascii() or any(not c.isprintable() or c.isspace() for c in value):
        raise ValueError('API Key 格式无效')
    return value


def _validate_model(value):
    if not isinstance(value, str):
        raise ValueError('不支持的分析模型')
    value = MODEL_ALIASES.get(value, value)
    if value not in MODELS:
        raise ValueError('不支持的分析模型')
    return value


def validate_reasoning_effort(value):
    if value not in REASONING_EFFORTS:
        raise ValueError('推理强度只支持中度或极高')
    return value


def validate_schedule(value):
    """Return a detached, complete schedule; reject ambiguous timing input."""
    if not isinstance(value, dict) or set(value) - set(DEFAULT_SCHEDULE):
        raise ValueError('自动研究运行时间格式无效')
    if value.get('mode') not in ('interval', 'daily', 'scheduled_interval', 'market_sessions'):
        raise ValueError('自动研究运行模式无效')
    schedule = {**DEFAULT_SCHEDULE, **value}
    if schedule['mode'] == 'market_sessions':
        # The two A-share slots are fixed; hidden controls cannot move them.
        schedule.update(daily_time='09:20', end_time=None)
    interval = schedule['interval_minutes']
    if not isinstance(interval, int) or isinstance(interval, bool) or not 1 <= interval <= 1440:
        raise ValueError('研究间隔请输入 1 至 1440 之间的整数分钟')
    daily_time = schedule['daily_time']
    if not isinstance(daily_time, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', daily_time):
        raise ValueError('启动时间请使用 24 小时 HH:MM 格式')
    end_time = schedule['end_time']
    if end_time is not None:
        if not isinstance(end_time, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', end_time):
            raise ValueError('结束时间请使用 24 小时 HH:MM 格式，或留空')
        if end_time == daily_time:
            raise ValueError('启动时间与结束时间不能相同')
    if schedule['timezone'] != 'Asia/Shanghai':
        raise ValueError('自动研究仅支持北京时间 Asia/Shanghai')
    return schedule


def validate_cost_controls(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_COST_CONTROLS):
        raise ValueError('费用保护设置格式无效')
    controls = {**DEFAULT_COST_CONTROLS, **value}
    if not isinstance(controls['reuse_enabled'], bool):
        raise ValueError('证据复用开关格式无效')
    for key, lower, upper, message in (
            ('daily_request_limit', 1, 10_000, '每日请求上限请输入 1 至 10000 的整数'),
            ('daily_token_limit', 1_000, 1_000_000_000, '每日 Token 预算请输入 1000 至 1000000000 的整数')):
        number = controls[key]
        if not isinstance(number, int) or isinstance(number, bool) or not lower <= number <= upper:
            raise ValueError(message)
    return controls


def _safe_error(error):
    # Only locally authored messages may enter the public status or persisted file.
    message = str(error)
    if message in _SAFE_ERRORS or re.fullmatch(r'(?:DeepSeek 服务|AI 服务商)错误（\d{3}）', message):
        return message
    return 'DeepSeek 验证失败，请稍后重试'


class AIConfigStore:
    """Persist keys encrypted and expose only masked, non-secret status.

    ``enabled`` in public status is the user's saved preference. ``effective_enabled``
    and snapshot ``enabled`` require a verified credential and available model.
    Crypto/probe injection supports offline tests without touching real credentials.
    """

    def __init__(self, path, encrypt=None, decrypt=None, probe=None):
        self.path = Path(path)
        self._encrypt = encrypt or encrypt_key
        self._decrypt = decrypt or decrypt_key
        self._probe = probe or probe_deepseek_key
        self._lock = threading.RLock()
        self._manual_connection_lock = threading.Lock()
        self._manual_connection_attempt = None
        self._state = self._empty()
        self._load()

    @staticmethod
    def _empty():
        return {'key': '', 'model': MODELS[0], 'enabled': False,
                'reasoning_effort': DEFAULT_REASONING_EFFORT,
                'responses_base_url': '',
                'revision': uuid.uuid4().hex, 'verification': 'unconfigured',
                'last_verified_at': None, 'error': '', 'available_models': [],
                'schedule': dict(DEFAULT_SCHEDULE), 'cost_controls': dict(DEFAULT_COST_CONTROLS)}

    @staticmethod
    def _effective(state):
        return bool(state['key'] and state['enabled'] and state['verification'] == 'verified'
                    and (not is_responses(state) or state.get('responses_base_url')))

    def status(self):
        with self._lock:
            state = self._state
            return {'configured': bool(state['key']), 'enabled': state['enabled'],
                    'effective_enabled': self._effective(state), 'model': state['model'],
                    'provider':'responses' if is_responses(state) else 'deepseek',
                    'reasoning_effort':state.get('reasoning_effort') if is_responses(state) else None,
                    'responses_base_url':state.get('responses_base_url', ''),
                    # Never any characters of the key, not even the last few (issue #5).
                    'key_hint': '密钥（内容不显示）' if state['key'] else '',
                    'revision': state['revision'], 'verification': state['verification'],
                    'last_verified_at': state['last_verified_at'], 'error': state['error'],
                    'available_models': list(state['available_models']), 'storage': 'windows-dpapi',
                    'schedule': dict(state['schedule']), 'cost_controls': dict(state['cost_controls'])}

    def snapshot(self):
        """Internal only: callers must never serialize this object into an HTTP response."""
        with self._lock:
            return {'key': self._state['key'], 'model': self._state['model'],
                    'responses_base_url':self._state.get('responses_base_url', ''),
                    'reasoning_effort':self._state.get('reasoning_effort') if is_responses(self._state) else None,
                    'enabled': self._effective(self._state), 'requested_enabled':self._state['enabled'],
                    'revision': self._state['revision'],
                    'schedule': dict(self._state['schedule']), 'cost_controls': dict(self._state['cost_controls'])}

    def configure(self, key=None, model=None, enabled=None, schedule=_UNSET, cost_controls=_UNSET, responses_base_url=_UNSET, reasoning_effort=_UNSET):
        # Validate everything before any memory or disk changes.
        if key is not None:
            key = _validate_key(key)
        if model is not None:
            model = _validate_model(model)
        if responses_base_url is not _UNSET:
            responses_base_url = validate_base_url(responses_base_url)
        if reasoning_effort is not _UNSET:
            reasoning_effort = validate_reasoning_effort(reasoning_effort)
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError('自动 AI 开关格式无效')
        if schedule is not _UNSET:
            schedule = validate_schedule(schedule)
        if cost_controls is not _UNSET:
            cost_controls = validate_cost_controls(cost_controls)
        with self._lock:
            previous = self._state
            candidate = {**previous, 'available_models': list(previous['available_models']),
                         'schedule': dict(previous['schedule']), 'cost_controls': dict(previous['cost_controls'])}
            if key is not None:
                candidate['key'] = key
            if model is not None:
                candidate['model'] = model
            if responses_base_url is not _UNSET:
                candidate['responses_base_url'] = responses_base_url
            if reasoning_effort is not _UNSET:
                candidate['reasoning_effort'] = reasoning_effort
            if previous['key'] and key is None and is_responses(candidate) != is_responses(previous):
                raise ValueError('切换服务商时请重新填写对应服务商的 API Key')
            if enabled is not None:
                candidate['enabled'] = enabled
            if schedule is not _UNSET:
                candidate['schedule'] = schedule
            if cost_controls is not _UNSET:
                candidate['cost_controls'] = cost_controls
            if candidate['enabled'] and not candidate['key']:
                raise ValueError('请先配置 API Key')
            research_changed = any(candidate[field] != previous[field] for field in ('key', 'model', 'enabled', 'schedule', 'responses_base_url', 'reasoning_effort'))
            if not research_changed and candidate['cost_controls'] == previous['cost_controls']:
                return self.status()
            if any(candidate[field] != previous[field] for field in ('key', 'model', 'responses_base_url')):
                candidate.update(verification='unverified', last_verified_at=None, error='', available_models=[])
            if research_changed:
                candidate['revision'] = uuid.uuid4().hex
            self._save(candidate)
            self._state = candidate
            return self.status()

    def _connection_changes(self, observed):
        try:
            if is_responses(observed) and not observed.get('responses_base_url'):
                raise RuntimeError('请先配置服务商接口地址')
            if is_responses(observed) and self._probe is probe_deepseek_key:
                result = probe_responses_key(observed['key'], observed.get('responses_base_url', ''), observed['model'])
            else:
                result = self._probe(observed['key'], observed['model'])
            if not isinstance(result, dict) or not isinstance(result.get('models'), list):
                raise RuntimeError('DeepSeek 返回的数据格式无效')
            models = result['models']
            if len(models) > 200 or any(not isinstance(item, str) or not _MODEL_ID.fullmatch(item) or observed['key'] in item for item in models):
                raise RuntimeError('DeepSeek 返回的数据格式无效')
            models = list(dict.fromkeys(models))
            # Derive availability from actual returned model IDs, never a callback's claim.
            available = observed['model'] in models
            changes = {'verification': 'verified' if available else 'failed',
                       'error': '' if available else 'API Key 验证通过，但当前模型不可用，请选择可用模型',
                       'available_models': models,
                       'last_verified_at': datetime.now(TZ).isoformat()}
        except Exception as error:
            changes = {'verification': 'failed', 'error': _safe_error(error),
                       'available_models': [], 'last_verified_at': datetime.now(TZ).isoformat()}
        return changes

    def connect_for_research(self, expected_revision, can_connect=None):
        """Recheck saved credentials for an authorized manual job only.

        The bounded, single-flight check never edits the administrator's enable
        preference or advances its revision. Concurrent jobs share a successful
        check; failed checks have a one-minute cooldown for this configuration.
        """
        if not self._manual_connection_lock.acquire(timeout=20):
            raise RuntimeError('AI 连接检查仍在进行，请稍后重试')
        try:
            with self._lock:
                observed = dict(self._state)
                if observed['revision'] != expected_revision:
                    raise RuntimeError('AI 配置已变化，请刷新后重试')
                if not observed['key'] or not observed['enabled'] or not is_responses(observed) or not observed.get('responses_base_url'):
                    raise RuntimeError('AI 服务尚未配置或管理员已停用，请联系管理员')
                if self._effective(observed):
                    return self.snapshot()
                attempt = self._manual_connection_attempt
                if attempt and attempt[0] == expected_revision and time.monotonic()-attempt[1] < 60:
                    raise RuntimeError('AI 连接检查未通过，请稍后重试或联系管理员')
            # Subscription, balance, report and account can change while this
            # job waits for another connection check; recheck before any I/O.
            if can_connect is not None and not can_connect():
                raise RuntimeError('账号、订阅或板块证据已变化，请刷新后重试')
            self._manual_connection_attempt = (expected_revision,time.monotonic())
            changes = self._connection_changes(observed)
            with self._lock:
                if self._state['revision'] != expected_revision or not self._state['enabled']:
                    raise RuntimeError('AI 配置已变化，请刷新后重试')
                candidate = {**self._state, **changes}
                self._save(candidate)
                self._state = candidate
                if not self._effective(candidate):
                    raise RuntimeError(candidate['error'] or 'AI 连接检查未通过，请联系管理员')
                return self.snapshot()
        finally:
            self._manual_connection_lock.release()

    def verify(self):
        with self._lock:
            observed = dict(self._state)
            if not observed['key']:
                return self.status()
        changes = self._connection_changes(observed)
        with self._lock:
            # A delayed response cannot validate or disable a newer configuration.
            if (self._state['revision'] != observed['revision']
                    or self._state['last_verified_at'] != observed['last_verified_at']):
                return self.status()
            # An explicit recheck is a new credential generation even when the
            # key/model are unchanged: it invalidates old results and lets a
            # repaired/top-up account recover from a previous terminal block.
            candidate = {**self._state, **changes, 'revision': uuid.uuid4().hex}
            self._save(candidate)
            self._state = candidate
            return self.status()

    def clear(self):
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                raise RuntimeError('配置删除失败，请检查数据目录权限') from None
            self._state = self._empty()
            return self.status()

    def _save(self, state):
        temporary = self.path.with_name(self.path.name + '.tmp-' + uuid.uuid4().hex)
        try:
            encrypted = self._encrypt(state['key'].encode('utf-8')) if state['key'] else b''
            if not isinstance(encrypted, bytes) or (state['key'] and not encrypted):
                raise ValueError('加密结果无效')
            document = {name: value for name, value in state.items() if name != 'key'}
            document.update(version=1, encrypted_key=base64.b64encode(encrypted).decode('ascii'))
            payload = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open('xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            raise RuntimeError('配置加密保存失败，请检查 Windows 账户及数据目录权限') from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _load(self):
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > 65_536:
                raise ValueError()
            document = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(document, dict) or document.get('version') != 1 or 'key' in document:
                raise ValueError()
            encrypted = base64.b64decode(document['encrypted_key'], validate=True)
            key = _validate_key(self._decrypt(encrypted).decode('utf-8')) if encrypted else ''
            model = _validate_model(document['model'])
            reasoning_effort = validate_reasoning_effort(document.get('reasoning_effort', DEFAULT_REASONING_EFFORT))
            responses_base_url = validate_base_url(document.get('responses_base_url', ''))
            schedule = validate_schedule(document.get('schedule', DEFAULT_SCHEDULE))
            cost_controls = validate_cost_controls(document.get('cost_controls', DEFAULT_COST_CONTROLS))
            enabled = document['enabled']
            revision = document['revision']
            verification = document['verification']
            models = document.get('available_models', [])
            verified_at = document.get('last_verified_at')
            if not isinstance(enabled, bool) or not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{32}', revision):
                raise ValueError()
            if verification not in ('unconfigured', 'unverified', 'verified', 'failed'):
                raise ValueError()
            if not isinstance(models, list) or len(models) > 200 or any(not isinstance(item, str) or not _MODEL_ID.fullmatch(item) or (key and key in item) for item in models):
                raise ValueError()
            if verified_at is not None:
                if not isinstance(verified_at, str) or len(verified_at) > 64:
                    raise ValueError()
                datetime.fromisoformat(verified_at)
            if verification == 'verified' and (not key or model not in models or verified_at is None):
                raise ValueError()
            if verification == 'verified' and is_responses({'model':model}) and not responses_base_url:
                raise ValueError()
            error = document.get('error', '')
            if error and error != 'API Key 验证通过，但当前模型不可用，请选择可用模型':
                error = _safe_error(RuntimeError(error))
            self._state = {'key': key, 'model': model, 'enabled': bool(enabled and key),
                           'reasoning_effort': reasoning_effort,
                           'responses_base_url':responses_base_url,
                           'revision': revision, 'verification': verification if key else 'unconfigured',
                           'last_verified_at': verified_at, 'error': error, 'available_models': models,
                           'schedule': schedule, 'cost_controls': cost_controls}
        except Exception:
            self._state = self._empty()
            self._state.update(verification='failed', error='本机加密配置无法读取，请重新保存 API Key')
