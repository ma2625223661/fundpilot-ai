"""Read-only, bounded bootstrap of today's historical numeric AI usage.

The report archive is queried only for the reports table. No account, session,
credential, provider or network interface is involved.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from research_ai_cost import CHINA


MAX_RECORDS = 40
MAX_REPORT_BYTES = 24_000_000
MAX_COMPRESSED_BYTES = 24_000_000
IMPORT_ERROR = '历史AI用量核验失败，已暂停新调用。'
_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens')
_MAX_INT = 2**63 - 1


def _number(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_INT


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('invalid metadata')
    return value


def _usage(meta):
    raw = meta.get('usage')
    if raw is None or raw == {}:
        return {key: 0 for key in _FIELDS}, False
    if not isinstance(raw, dict):
        raise ValueError('invalid usage')
    if any(key in raw and not _number(raw[key]) for key in _FIELDS):
        raise ValueError('invalid usage number')
    if all(key in raw for key in _FIELDS):
        if raw['prompt_tokens'] + raw['completion_tokens'] != raw['total_tokens']:
            raise ValueError('inconsistent usage')
        return {key: raw[key] for key in _FIELDS}, meta.get('usage_complete') is True
    # Preserve a known input/output subtotal when an old archive omitted its
    # total. A standalone total cannot be attributed without inventing numbers.
    if 'total_tokens' in raw:
        raise ValueError('unattributable partial usage')
    prompt, completion = raw.get('prompt_tokens', 0), raw.get('completion_tokens', 0)
    if prompt + completion > _MAX_INT:
        raise ValueError('usage overflow')
    return {'prompt_tokens': prompt, 'completion_tokens': completion,
            'total_tokens': prompt + completion}, False


def _requests(meta, usage):
    value = meta.get('request_count', meta.get('requests_attempted'))
    if value is None:
        return int(usage['total_tokens'] > 0)
    if not _number(value):
        raise ValueError('invalid request count')
    if value == 0 and usage['total_tokens']:
        raise ValueError('usage without counted request')
    return value


def _fingerprint(kind, at, revision, usage, requests, retained=False):
    value = [kind, at, revision, usage, requests, bool(retained)]
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return 'historical-usage-v1:' + hashlib.sha256(data).hexdigest()


def _time(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError('missing round time')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    stamp = stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)
    return stamp.isoformat()


def _exists(path):
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False


def _records(report):
    if not isinstance(report, dict):
        raise ValueError('invalid report')
    ai = _metadata(report.get('ai_research'))
    if ai.get('cost_ledger_recorded') is True:
        return []
    event = _metadata(report.get('event_analysis'))
    all_usage, all_complete = _usage(ai)
    event_usage, event_complete = _usage(event)
    all_count, event_count = _requests(ai, all_usage), _requests(event, event_usage)
    retained = event.get('retained') is True
    # Ordinary ai_research totals already contain the event assessor. Retained
    # events belong to their original round and are not in this round's totals.
    deduct_event = bool(ai) and not retained
    sector_usage = {key: all_usage[key] - (event_usage[key] if deduct_event else 0)
                    for key in _FIELDS}
    sector_count = all_count - (event_count if deduct_event else 0)
    if sector_count < 0 or any(value < 0 for value in sector_usage.values()):
        raise ValueError('event usage exceeds aggregate')
    if sector_usage['total_tokens'] and sector_count == 0:
        raise ValueError('sector usage without request count')
    rows = []
    if sector_count:
        at = _time(ai.get('as_of') or report.get('as_of'))
        ident = _fingerprint('sector', at, ai.get('revision'), sector_usage, sector_count, retained)
        rows.append((ident, 'sector', sector_usage, sector_count, at, all_complete))
    if event_count:
        at = _time(event.get('as_of') or report.get('as_of'))
        # Do not include the outer report identity: a retained event may appear
        # in several archived reports but represents only one paid request.
        ident = _fingerprint('events', at, event.get('revision'), event_usage, event_count)
        rows.append((ident, 'events', event_usage, event_count, at, event_complete))
    return rows


def _recorded_today(report, day):
    """Detect a report that claims new paid work is already in today's ledger."""
    if not isinstance(report, dict):
        raise ValueError('invalid report')
    ai = _metadata(report.get('ai_research'))
    if ai.get('cost_ledger_recorded') is not True:
        return False
    count = ai.get('request_count', ai.get('requests_attempted', 0))
    if not _number(count):
        raise ValueError('invalid recorded request count')
    # A zero-request scheduled report may merely retain an older event, so its
    # marker does not claim any new charges occurred in this report's round.
    return bool(count and _time(ai.get('as_of') or report.get('as_of'))[:10] == day)


def _decode(data, compressed=False):
    if compressed:
        if not isinstance(data, bytes) or len(data) > MAX_COMPRESSED_BYTES:
            raise ValueError('invalid archive payload')
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb') as stream:
            data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError('report exceeds byte limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('invalid report document')
    return value


def _archive_reports(path):
    if not _exists(path):
        return
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        row = db.execute("SELECT type FROM sqlite_master WHERE name='reports'").fetchone()
        if row is None or row[0] != 'table':
            raise ValueError('missing reports table')
        columns = {row[1]: row[2].upper() for row in db.execute('PRAGMA table_info(reports)')}
        if not {'id', 'payload', 'summary', 'sectors', 'created'}.issubset(columns):
            raise ValueError('unsupported reports schema')
        if columns['payload'] != 'BLOB':
            raise ValueError('unsupported payload type')
        # Avoid materializing an oversized blob even before gzip bounds apply.
        cursor = db.execute('''SELECT length(payload),
            CASE WHEN length(payload)<=? THEN payload ELSE NULL END
            FROM reports ORDER BY created DESC,id DESC LIMIT ?''',
            (MAX_COMPRESSED_BYTES, MAX_RECORDS))
        for size, payload in cursor:
            if not isinstance(size, int) or size > MAX_COMPRESSED_BYTES or payload is None:
                raise ValueError('oversized archive payload')
            yield _decode(payload, compressed=True)
    finally:
        db.close()


def bootstrap_usage(guard, state_path):
    """Import archived/current numeric usage idempotently, or pause on failure.

    Missing sources are normal for a fresh installation. Existing but unreadable
    sources, malformed paid usage and decompression/size failures stop new paid
    requests; their original exceptions and payloads are never returned.
    """
    if state_path is None:
        return None
    examined = imported = 0
    try:
        path = Path(state_path)
        archive = path.parent / 'accounts.sqlite3'
        if not _exists(path) and not _exists(archive):
            return None
        ledger_existed = _exists(guard.path)
        initial = guard.summary()
        if initial.get('blocked') or initial.get('requests') is None:
            raise ValueError('ledger unavailable')
        pending = []
        def examine(report):
            if (_recorded_today(report, initial['beijing_day'])
                    and (not ledger_existed or initial['requests'] == 0)):
                raise ValueError('recorded usage ledger missing')
            pending.extend(_records(report))
        for report in _archive_reports(archive):
            examined += 1
            examine(report)
        if _exists(path):
            with path.open('rb') as stream:
                data = stream.read(MAX_REPORT_BYTES + 1)
            current = _decode(data)
            report = current.get('report', current)
            examined += 1
            examine(report)
        # Validate every source before changing usage totals. A damaged source
        # cannot leave a partial bootstrap that masks a missing ledger later.
        for args in pending:
            imported += int(guard.import_usage(*args))
        return {'status': 'ok', 'reports_examined': examined, 'records_imported': imported}
    except Exception:
        guard.block(IMPORT_ERROR)
        return {'status': 'error', 'error': IMPORT_ERROR}
