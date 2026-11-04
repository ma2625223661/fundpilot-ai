"""Durable, conservative admission budgets for optional paid AI requests.

Only request metadata and numeric usage are stored. Request bodies, responses,
credentials and configuration documents never enter the ledger. ``send`` is a
zero-argument callable so callers retain control of their provider adapter.
"""
from __future__ import annotations

import hashlib
import errno
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


CHINA = timezone(timedelta(hours=8))
DEFAULT_COST_CONTROLS = {
    'daily_request_limit': 28,
    'daily_token_limit': 8_000_000,
    'reuse_enabled': True,
}
MAX_INPUT_BYTES = 300_000
IMPORTED_UNKNOWN_RESERVATION = 6_500
SCHEMA_VERSION = 2
_MAX_SQLITE_INT = 2**63 - 1
_USAGE_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens')
_KINDS = ('sector', 'events')
_LEDGER_ERROR = 'AI 费用账本暂不可用，已阻止新调用；请检查账本文件与磁盘后重试。'
_SETTLEMENT_ERROR = 'AI 费用记录结算失败，已保留预算预留并暂停新调用。'
_IMPORT_ERROR = '历史AI用量核验失败，已暂停新调用。'


def _reasoning_multiplier(config):
    """Return the billing multiplier for the selected reasoning effort."""
    return 1.5 if isinstance(config, dict) and config.get('reasoning_effort') == 'xhigh' else 1.0


def _weighted_tokens(tokens, multiplier):
    if not _integer(tokens) or not isinstance(multiplier, (int, float)) or not math.isfinite(multiplier):
        raise CostLimitError('AI Token 计费折算无效，已阻止本次调用。', 'invalid_payload')
    value = math.ceil(tokens * multiplier)
    if value > _MAX_SQLITE_INT:
        raise CostLimitError('AI 请求预算超出有效范围，已阻止本次调用。', 'invalid_payload')
    return value


class CostLimitError(RuntimeError):
    """A safe, user-facing reason for refusing a new paid request."""

    def __init__(self, reason, code='cost_limit'):
        self.reason = reason
        self.code = code
        super().__init__(reason)


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_SQLITE_INT


def _limits(config):
    supplied = config.get('cost_controls', {}) if isinstance(config, dict) else {}
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict):
        raise CostLimitError('AI 费用保护设置无效，已阻止新调用。', 'invalid_limits')
    result = {**DEFAULT_COST_CONTROLS, **{key: supplied[key] for key in DEFAULT_COST_CONTROLS if key in supplied}}
    if (not _integer(result['daily_request_limit']) or not _integer(result['daily_token_limit'])
            or not isinstance(result['reuse_enabled'], bool)):
        raise CostLimitError('AI 费用保护设置无效，已阻止新调用。', 'invalid_limits')
    return result


def _reservation(payload):
    maximum = payload.get('max_output_tokens', payload.get('max_tokens')) if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not _integer(maximum) or maximum == 0:
        raise CostLimitError('AI 请求必须设置有效的最大输出长度，已阻止本次调用。', 'invalid_payload')
    try:
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                              separators=(',', ':')).encode('utf-8'))
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise CostLimitError('AI 请求内容无法计量，已阻止本次调用。', 'invalid_payload') from None
    if size > MAX_INPUT_BYTES:
        raise CostLimitError('本次 AI 输入超过 300000 字节上限，请先精简证据，避免大额无效调用。', 'input_limit')
    # UTF-8 bytes upper-bound the ordinary text tokenization used by these
    # requests. This is an admission reservation, not a precise tokenizer bill.
    reserved = size + maximum
    if reserved > _MAX_SQLITE_INT:
        raise CostLimitError('AI 请求预算超出有效范围，已阻止本次调用。', 'invalid_payload')
    return size, reserved


def _usage(response):
    raw = response.get('usage', {}) if isinstance(response, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    values = {key: raw.get(key) if _integer(raw.get(key)) else None for key in _USAGE_FIELDS}
    complete = (all(values[key] is not None for key in _USAGE_FIELDS)
                and values['prompt_tokens'] + values['completion_tokens'] == values['total_tokens'])
    if all(values[key] is not None for key in _USAGE_FIELDS) and not complete:
        # An inconsistent total is not a usable billing number. Keep the valid
        # input/output observations while retaining the entire reservation.
        values['total_tokens'] = None
    hit, miss = raw.get('prompt_cache_hit_tokens'), raw.get('prompt_cache_miss_tokens')
    details = raw.get('prompt_tokens_details')
    if not _integer(hit) and isinstance(details, dict):
        hit = details.get('cached_tokens')
    prompt = values['prompt_tokens']
    hit = hit if _integer(hit) and prompt is not None and hit <= prompt else None
    miss = miss if _integer(miss) and prompt is not None and miss <= prompt else None
    if hit is not None and miss is None:
        miss = prompt - hit
    elif miss is not None and hit is None:
        hit = prompt - miss
    if hit is not None and miss is not None and hit + miss != prompt:
        hit = miss = None
    values.update(prompt_cache_hit_tokens=hit, prompt_cache_miss_tokens=miss)
    return values, complete


class AICostGuard:
    """A dedicated SQLite ledger with atomic admission before provider I/O.

    ``tokens_reserved`` in :meth:`summary` is today's budget occupation: known
    actual totals after settlement plus full reservations for unknown/in-flight
    requests. ``tokens_unsettled`` exposes only the latter portion.
    """

    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(CHINA))
        self._fault = None
        self._fault_lock = threading.Lock()
        self._transaction_lock = threading.RLock()

    def _now(self):
        try:
            value = self.clock()
            if isinstance(value, datetime):
                return value.replace(tzinfo=CHINA) if value.tzinfo is None else value.astimezone(CHINA)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                return datetime.fromtimestamp(value, CHINA)
        except Exception:
            pass
        raise CostLimitError('AI 费用保护无法确认北京时间，已阻止新调用。', 'clock_unavailable')

    def _block(self, reason=_LEDGER_ERROR):
        with self._fault_lock:
            self._fault = reason

    def _check_fault(self):
        with self._fault_lock:
            if self._fault:
                raise CostLimitError(self._fault, 'ledger_unavailable')

    def block(self, reason=None):
        """Pause new paid requests, exposing only a recognized safe message."""
        self._block(reason if reason in (_LEDGER_ERROR, _SETTLEMENT_ERROR, _IMPORT_ERROR) else _LEDGER_ERROR)

    @contextmanager
    def _transaction(self):
        # A SQLite writer lock alone is insufficient for first creation: a
        # second connection can acquire BEGIN before the O_EXCL file creator
        # does, see the creator's empty file, and incorrectly fault the guard.
        # Keep creation, schema validation and the transaction under an OS file
        # lock. It coordinates independent guards/processes as well as threads.
        with self._transaction_lock:
            self._check_fault()
            with self._ledger_file_lock():
                with self._transaction_locked() as db:
                    yield db

    @contextmanager
    def _ledger_file_lock(self):
        descriptor, locked = None, False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(self.path.name + '.lock')
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            if os.name == 'nt':
                import msvcrt
                def acquire():
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                def release():
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                def acquire():
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release():
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            deadline = time.monotonic() + 15
            while True:
                try:
                    acquire()
                    locked = True
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            # Byte-range locks may extend beyond EOF. Initialize this harmless
            # marker only after locking: a competing first writer could already
            # hold byte zero, so writing before acquire would itself race.
            if os.fstat(descriptor).st_size == 0:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b'\0')
            yield
        except OSError:
            self._block()
            raise CostLimitError(_LEDGER_ERROR, 'ledger_unavailable') from None
        finally:
            if descriptor is not None:
                try:
                    if locked:
                        release()
                except OSError:
                    self._block()
                    raise CostLimitError(_LEDGER_ERROR, 'ledger_unavailable') from None
                finally:
                    try:
                        os.close(descriptor)
                    except OSError:
                        self._block()
                        raise CostLimitError(_LEDGER_ERROR, 'ledger_unavailable') from None
            # Never unlink the lock file: replacing its identity while another
            # process holds an open handle could create two independent locks.

    @contextmanager
    def _transaction_locked(self):
        self._check_fault()
        db = None
        created = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                created = True
            db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if created and not tables:
                db.execute('CREATE TABLE ledger_meta (version INTEGER NOT NULL)')
                db.execute('INSERT INTO ledger_meta VALUES (?)', (SCHEMA_VERSION,))
                db.execute('''CREATE TABLE ai_calls (
                    id TEXT PRIMARY KEY,
                    beijing_day TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('sector','events')),
                    admitted_at TEXT NOT NULL,
                    input_bytes INTEGER NOT NULL CHECK (input_bytes>=0 AND input_bytes<=300000),
                    original_reservation INTEGER NOT NULL CHECK (original_reservation>=0),
                    budget_tokens INTEGER NOT NULL CHECK (budget_tokens>=0),
                    unsettled_tokens INTEGER NOT NULL CHECK (unsettled_tokens>=0),
                    request_count INTEGER NOT NULL CHECK (request_count>0),
                    unknown_requests INTEGER NOT NULL CHECK (unknown_requests>=0 AND unknown_requests<=request_count),
                    state TEXT NOT NULL CHECK (state IN ('reserved','completed','unknown')),
                    usage_complete INTEGER NOT NULL CHECK (usage_complete IN (0,1)),
                    prompt_tokens INTEGER CHECK (prompt_tokens>=0),
                    completion_tokens INTEGER CHECK (completion_tokens>=0),
                    total_tokens INTEGER CHECK (total_tokens>=0),
                    prompt_cache_hit_tokens INTEGER CHECK (prompt_cache_hit_tokens>=0),
                    prompt_cache_miss_tokens INTEGER CHECK (prompt_cache_miss_tokens>=0),
                    billing_units REAL NOT NULL DEFAULT 1,
                    cost_multiplier REAL NOT NULL DEFAULT 1)''')
                db.execute('CREATE INDEX ai_calls_day ON ai_calls(beijing_day)')
                # The schema must survive a later admission refusal (for
                # example a deliberate zero budget on the first request).
                db.execute('COMMIT')
                db.execute('BEGIN IMMEDIATE')
            versions = [row[0] for row in db.execute('SELECT version FROM ledger_meta')]
            if versions == [1]:
                db.execute('ALTER TABLE ai_calls ADD COLUMN billing_units REAL NOT NULL DEFAULT 1')
                db.execute('ALTER TABLE ai_calls ADD COLUMN cost_multiplier REAL NOT NULL DEFAULT 1')
                db.execute('UPDATE ledger_meta SET version=?', (SCHEMA_VERSION,))
                versions = [SCHEMA_VERSION]
            if versions != [SCHEMA_VERSION] or db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('unsupported or damaged ledger')
            # Do not silently recreate a missing table or accept malformed rows
            # from a truncated/partially replaced existing database.
            db.execute('SELECT id,beijing_day,kind,admitted_at,input_bytes,original_reservation,budget_tokens,'
                       'unsettled_tokens,request_count,unknown_requests,'
                       'state,usage_complete,prompt_tokens,completion_tokens,total_tokens,'
                       'prompt_cache_hit_tokens,prompt_cache_miss_tokens,billing_units,cost_multiplier FROM ai_calls LIMIT 1').fetchall()
            yield db
            db.execute('COMMIT')
        except CostLimitError:
            if db is not None and db.in_transaction:
                db.execute('ROLLBACK')
            raise
        except (sqlite3.Error, OSError, OverflowError, ValueError, TypeError):
            if db is not None and db.in_transaction:
                try:
                    db.execute('ROLLBACK')
                except sqlite3.Error:
                    pass
            self._block()
            raise CostLimitError(_LEDGER_ERROR, 'ledger_unavailable') from None
        finally:
            if db is not None:
                db.close()

    def _admit(self, kind, size, reserved, limits, now, multiplier):
        ident = uuid.uuid4().hex
        with self._transaction() as db:
            rows = db.execute('SELECT request_count,budget_tokens,billing_units FROM ai_calls '
                              'WHERE beijing_day=?', (now.date().isoformat(),)).fetchall()
            units = sum(row['billing_units'] for row in rows)
            if units + multiplier > limits['daily_request_limit']:
                raise CostLimitError('今日 AI 请求数已达到保护上限，已停止新增调用，明日北京时间零点重新计数。', 'request_limit')
            if sum(row['budget_tokens'] for row in rows) + reserved > limits['daily_token_limit']:
                raise CostLimitError('今日 AI Token 预算余量不足，已停止新增调用；未知用量仍保留预留额度。', 'token_limit')
            db.execute('''INSERT INTO ai_calls
                (id,beijing_day,kind,admitted_at,input_bytes,original_reservation,budget_tokens,
                 unsettled_tokens,request_count,unknown_requests,state,usage_complete,billing_units,cost_multiplier)
                VALUES (?,?,?,?,?,?,?,?,1,1,'reserved',0,?,?)''',
                (ident, now.date().isoformat(), kind, now.isoformat(timespec='seconds'),
                 size, reserved, reserved, reserved, multiplier, multiplier))
        return ident

    def _settle(self, ident, response=None, failed=False):
        values, complete = _usage(response)
        try:
            with self._transaction() as db:
                row = db.execute('SELECT original_reservation,cost_multiplier FROM ai_calls WHERE id=?', (ident,)).fetchone()
                if row is None:
                    raise sqlite3.DatabaseError('missing admitted request')
                budget = _weighted_tokens(values['total_tokens'], row['cost_multiplier']) if complete and not failed else row['original_reservation']
                known = complete and not failed
                db.execute('''UPDATE ai_calls SET budget_tokens=?,unsettled_tokens=?,unknown_requests=?,state=?,usage_complete=?,
                    prompt_tokens=?,completion_tokens=?,total_tokens=?,prompt_cache_hit_tokens=?,
                    prompt_cache_miss_tokens=? WHERE id=?''',
                    (budget, 0 if known else row[0], 0 if known else 1,
                     'unknown' if failed else 'completed', int(known),
                     *(values[key] for key in (*_USAGE_FIELDS, 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')), ident))
        except CostLimitError:
            self._block(_SETTLEMENT_ERROR)
            raise CostLimitError(_SETTLEMENT_ERROR, 'ledger_unavailable') from None

    def invoke(self, kind, payload, config, send):
        """Reserve durably, execute ``send()``, then settle numeric provider usage.

        Every admitted attempt counts, including timeouts and malformed or
        missing usage. There is no retry and no response cache in this module.
        """
        if kind not in _KINDS or not callable(send):
            raise CostLimitError('AI 调用类型无效，已阻止本次调用。', 'invalid_request')
        limits = _limits(config)
        size, reserved = _reservation(payload)
        multiplier = _reasoning_multiplier(config)
        weighted_reserved = _weighted_tokens(reserved, multiplier)
        ident = self._admit(kind, size, weighted_reserved, limits, self._now(), multiplier)
        try:
            response = send()
        except BaseException:
            try:
                self._settle(ident, failed=True)
            except CostLimitError:
                # The original reservation is already durable. Preserve the
                # provider exception without exposing ledger internals.
                pass
            raise
        self._settle(ident, response)
        return response

    def import_usage(self, record_id, kind, usage, requests, at, usage_complete=True):
        """Import archived usage for today's Beijing date once, without sending.

        Returns ``True`` for a newly imported record and ``False`` for an
        existing, invalid or non-current record. ``usage`` is a provider-style
        numeric usage dict with a valid prompt/completion/total triple; use a
        zero triple when no tokens are known. An incomplete historical round
        keeps all its known tokens plus a 6500-token unknown reservation and
        one unknown request. Imports may exceed limits to reflect actual spend.
        Only a hash of ``record_id`` and ``kind`` is stored.
        """
        if (not isinstance(record_id, str) or not record_id.strip() or len(record_id) > 1024
                or kind not in _KINDS or not _integer(requests) or requests == 0
                or not isinstance(usage_complete, bool) or not isinstance(usage, dict)):
            return False
        values, valid = _usage({'usage': usage})
        if not valid:
            return False
        try:
            when = at
            if isinstance(when, str):
                when = datetime.fromisoformat(when.replace('Z', '+00:00'))
            if isinstance(when, datetime):
                when = when.replace(tzinfo=CHINA) if when.tzinfo is None else when.astimezone(CHINA)
            elif isinstance(when, (int, float)) and not isinstance(when, bool) and math.isfinite(when):
                when = datetime.fromtimestamp(when, CHINA)
            else:
                return False
        except (ValueError, TypeError, OverflowError, OSError):
            return False
        if when.date() != self._now().date():
            return False
        unsettled = 0 if usage_complete else IMPORTED_UNKNOWN_RESERVATION
        budget = values['total_tokens'] + unsettled
        if budget > _MAX_SQLITE_INT:
            return False
        material = json.dumps([record_id, kind], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        ident = 'import:' + hashlib.sha256(material).hexdigest()
        with self._transaction() as db:
            cursor = db.execute('''INSERT OR IGNORE INTO ai_calls
                (id,beijing_day,kind,admitted_at,input_bytes,original_reservation,budget_tokens,
                 unsettled_tokens,request_count,unknown_requests,state,usage_complete,
                 prompt_tokens,completion_tokens,total_tokens,prompt_cache_hit_tokens,prompt_cache_miss_tokens,
                 billing_units,cost_multiplier)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ident, when.date().isoformat(), kind, when.isoformat(timespec='seconds'),
                 0, budget, budget, unsettled, requests, int(not usage_complete),
                 'completed' if usage_complete else 'unknown', int(usage_complete),
                 *(values[key] for key in (*_USAGE_FIELDS, 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')),
                 requests, 1.0))
            return cursor.rowcount == 1

    @staticmethod
    def _totals(rows):
        usage = {key: sum(row[key] or 0 for row in rows) for key in _USAGE_FIELDS}
        cached = {key: sum(row[key] or 0 for row in rows)
                  for key in ('prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')}
        unknown = [row for row in rows if not row['usage_complete']]
        return {'requests': sum(row['request_count'] for row in rows),
                'request_units': round(sum(row['billing_units'] for row in rows), 2),
                'usage': usage, **cached,
                'usage_complete': not unknown,
                'cache_usage_complete': all(row['prompt_cache_hit_tokens'] is not None
                                          and row['prompt_cache_miss_tokens'] is not None for row in rows),
                'tokens_reserved': sum(row['budget_tokens'] for row in rows),
                'tokens_unsettled': sum(row['unsettled_tokens'] for row in rows),
                'unknown_requests': sum(row['unknown_requests'] for row in rows),
                'in_flight_requests': sum(row['request_count'] for row in rows if row['state'] == 'reserved')}

    def summary(self, config=None):
        """Return safe Beijing-day usage and limits; failures are explicitly blocked."""
        day = None
        limits = None
        try:
            limits = _limits(config)
            day = self._now().date().isoformat()
            with self._transaction() as db:
                rows = db.execute('SELECT * FROM ai_calls WHERE beijing_day=? ORDER BY admitted_at,id', (day,)).fetchall()
            totals = self._totals(rows)
            return {'status': 'ok', 'blocked': False, 'beijing_day': day, 'timezone': 'Asia/Shanghai',
                    'limits': {**limits, 'max_input_bytes': MAX_INPUT_BYTES}, **totals,
                    'remaining_requests': max(0, limits['daily_request_limit'] - totals['request_units']),
                    'remaining_tokens': max(0, limits['daily_token_limit'] - totals['tokens_reserved']),
                    'reasoning_multiplier': _reasoning_multiplier(config),
                    'by_kind': {kind: self._totals([row for row in rows if row['kind'] == kind]) for kind in _KINDS},
                    'reservation_method': '请求 JSON 的 UTF-8 字节数加最大输出 Token，并按推理强度倍率折算；属于保守预留，非精确账单。'}
        except CostLimitError as error:
            return {'status': 'blocked', 'blocked': True, 'beijing_day': day, 'timezone': 'Asia/Shanghai',
                    'limits': {**limits, 'max_input_bytes': MAX_INPUT_BYTES} if limits else None,
                    'error': error.reason, 'error_code': error.code, 'requests': None, 'usage': None,
                    'tokens_reserved': None, 'tokens_unsettled': None, 'unknown_requests': None,
                    'request_units': None,
                    'by_kind': {}}
