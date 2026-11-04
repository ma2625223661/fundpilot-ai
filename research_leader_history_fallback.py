"""Bounded BaoStock forward-adjusted company history fallback.

BaoStock keeps its socket in process-global state. Each batch therefore uses a
short-lived child process rather than sharing that session across web workers.
The child only reads public daily prices; it has no API credentials.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from research_data import CHINA, now_iso
from research_trading_calendar import is_trading_day

SOURCE_URL = 'https://www.baostock.com/mainContent?fileName=history_A_stock_k_data.md'
MAX_BATCH = 60
MAX_SECONDS = 35


def _cutoff(as_of):
    when = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    when = when.replace(tzinfo=CHINA) if when.tzinfo is None else when.astimezone(CHINA)
    day = when.date() - timedelta(days=1 if when.hour < 15 else 0)
    for _ in range(30):
        opened = is_trading_day(day)
        if opened is None:
            raise ValueError('无法核验最近收盘交易日')
        if opened:
            return day
        day -= timedelta(days=1)
    raise ValueError('近期没有可核验收盘交易日')


def parse_a_share_history(raw, code, as_of):
    """Validate per-row code, completed trade date and finite adjusted close."""
    if not re.fullmatch(r'\d{6}\.(?:SH|SZ)', str(code)):
        raise ValueError('BaoStock 日线备用仅支持沪深A股')
    cutoff = _cutoff(as_of)
    expected_code = code[-2:].lower() + '.' + code[:6]
    days = {}
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or row.get('code') != expected_code:
            continue
        try:
            day = datetime.strptime(str(row.get('date')), '%Y-%m-%d').date()
            close = float(row.get('close'))
        except (TypeError, ValueError):
            continue
        if (day > cutoff or (cutoff-day).days > 270 or not is_trading_day(day)
                or not math.isfinite(close) or close <= 0):
            continue
        days[day.isoformat()] = {'date': day.isoformat(), 'close': close}
    return [days[day] for day in sorted(days)][-121:]


def fetch_a_share_histories(codes, as_of, seconds=MAX_SECONDS):
    """Return code -> {rows, url, fetched_at, error, adjustment} in <=35s.

    Prefer this batch API after the primary provider has completed. It uses one
    isolated BaoStock session for all codes, with a hard parent-side timeout.
    A batch timeout produces no partial, unverifiable process output.
    """
    codes = list(dict.fromkeys(codes))
    if len(codes) > MAX_BATCH or any(not re.fullmatch(r'\d{6}\.(?:SH|SZ)', str(c)) for c in codes):
        raise ValueError('BaoStock 备用请求需为最多60个沪深A股证券代码')
    if not codes:
        return {}
    cutoff = _cutoff(as_of)
    start = cutoff - timedelta(days=260)
    output = {code: {'rows': [], 'url': SOURCE_URL, 'fetched_at': now_iso(),
                     'adjustment': 'forward_adjusted', 'error': ''} for code in codes}
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--worker'],
            input=json.dumps({'codes': codes, 'start': start.isoformat(), 'end': cutoff.isoformat()}),
            text=True, encoding='utf-8', capture_output=True, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            timeout=max(.1, min(float(seconds), MAX_SECONDS)))
        if len(process.stdout) > 2_000_000:
            raise ValueError('备用日线响应超过大小限制')
        payload = json.loads(process.stdout)
        if not isinstance(payload, dict):
            raise ValueError('备用日线响应结构不符')
        for code in codes:
            raw = payload.get(code) or {}
            rows = parse_a_share_history(raw.get('rows'), code, as_of)
            output[code].update(rows=rows, error='' if rows else str(raw.get('error') or '未取得有效前复权日线')[:160])
    except subprocess.TimeoutExpired:
        for result in output.values():
            result['error'] = 'BaoStock 备用日线采集超时'
    except Exception as error:
        for result in output.values():
            result['error'] = type(error).__name__ + '：BaoStock 备用日线未取得'
    return output


def fetch_a_share_history(code, as_of):
    """Single-code convenience API; returns rows and exact source metadata."""
    return fetch_a_share_histories([code], as_of)[code]


def _worker():
    import contextlib
    import io
    import baostock as bs
    request = json.loads(sys.stdin.read(100_000))
    results = {}
    # BaoStock emits login messages on stdout; keep the protocol JSON-only.
    with contextlib.redirect_stdout(io.StringIO()):
        login = bs.login()
        try:
            if str(login.error_code) != '0':
                raise RuntimeError('BaoStock 登录失败')
            for code in request['codes']:
                symbol = code[-2:].lower() + '.' + code[:6]
                try:
                    value = bs.query_history_k_data_plus(symbol, 'date,code,close',
                        request['start'], request['end'], frequency='d', adjustflag='2')
                    if str(value.error_code) == '10001001':
                        # Public sessions can expire while another local
                        # capability worker finishes; retry this read once.
                        login = bs.login()
                        if str(login.error_code) == '0':
                            value = bs.query_history_k_data_plus(symbol, 'date,code,close',
                                request['start'], request['end'], frequency='d', adjustflag='2')
                    rows = []
                    while value.error_code == '0' and value.next():
                        rows.append(dict(zip(value.fields, value.get_row_data())))
                    if value.error_code != '0':
                        raise RuntimeError('BaoStock 日线查询未成功')
                    results[code] = {'rows': rows, 'error': ''}
                except Exception as error:
                    results[code] = {'rows': [], 'error': type(error).__name__ + '：日线查询未成功'}
        finally:
            # This isolated process exits immediately. Closing its socket avoids
            # an explicit anonymous logout invalidating another reader's login.
            try:
                import baostock.common.context as context
                if context.default_socket is not None:
                    context.default_socket.close()
            except (AttributeError, OSError):
                pass
    # ASCII JSON keeps the subprocess protocol independent of the Windows
    # console code page (including Chinese provider error messages).
    sys.stdout.write(json.dumps(results, ensure_ascii=True))


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    _worker()
