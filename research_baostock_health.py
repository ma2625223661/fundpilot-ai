"""Independent, bounded public BaoStock capability checks.

Industry, daily prices and financial statements each run in their own process.
A slow interface therefore cannot prevent the other two from being checked.
Sample checks establish connectivity only, not whole-market completeness.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from research_data import CHINA, now_iso
from research_trading_calendar import is_trading_day

SAMPLE_CODE = 'sh.600519'
CAPABILITIES = ('industry', 'daily', 'financial')
TIMEOUT_SECONDS = 23


def _date_context(as_of):
    now = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    now = now.replace(tzinfo=CHINA) if now.tzinfo is None else now.astimezone(CHINA)
    day = now.date() - timedelta(days=1 if now.hour < 15 else 0)
    for _ in range(30):
        trading = is_trading_day(day)
        if trading is None:
            raise ValueError('交易日历没有最近收盘日期，尚未发起接口检查')
        if trading:
            return now, day
        day -= timedelta(days=1)
    raise ValueError('未找到最近已收盘交易日，尚未发起接口检查')


def _quarters(today):
    """Latest completed calendar quarter and its predecessor."""
    current = (today.month-1)//3 + 1
    year, quarter = (today.year, current-1) if current > 1 else (today.year-1, 4)
    return [(year, quarter), (year, quarter-1) if quarter > 1 else (year-1, 4)]


def _finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def _parse_date(value):
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _valid_rows(capability, rows, now, cutoff):
    valid = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get('code') != SAMPLE_CODE:
            continue
        if capability == 'industry':
            updated = _parse_date(row.get('updateDate'))
            if updated and updated <= cutoff and str(row.get('industry') or '').strip():
                valid.append(row)
        elif capability == 'daily':
            day = _parse_date(row.get('date'))
            if day == cutoff and _finite(row.get('close')) and float(row['close']) > 0:
                valid.append(row)
        elif capability == 'financial':
            published, reported = _parse_date(row.get('pubDate')), _parse_date(row.get('statDate'))
            numeric = any(_finite(row.get(k)) for k in ('roeAvg', 'npMargin', 'gpMargin', 'netProfit', 'epsTTM'))
            if published and reported and reported <= published < now.date() and (now.date()-reported).days <= 550 and numeric:
                valid.append(row)
    return valid


def _query_label(capability, context):
    if capability == 'industry':
        return f'query_stock_industry(code={SAMPLE_CODE},date={context["end"]})'
    if capability == 'daily':
        return f'query_history_k_data_plus(code={SAMPLE_CODE},start={context["start"]},end={context["end"]})'
    year, quarter = context['quarters'][0]
    return f'query_profit_data(code={SAMPLE_CODE},year={year},quarter={quarter}；空缺时回退前季)'


def _check_one(capability, context, timeout):
    base = {'status': 'unverified', 'count': 0, 'checked_at': now_iso(),
            'note': '', 'sample_code': SAMPLE_CODE, 'query': _query_label(capability, context)}
    raw_cache_rows = []
    with tempfile.TemporaryDirectory(prefix='baostock-health-') as folder:
        phase_path = Path(folder) / 'phase.json'
        request = {**context, 'capability': capability, 'phase_path': str(phase_path)}
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                input=json.dumps(request), capture_output=True, text=True, encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                timeout=timeout, check=True)
            if len(process.stdout) > 1_000_000:
                raise ValueError('接口检查响应超过大小限制')
            body = json.loads(process.stdout)
            if not isinstance(body, dict) or not isinstance(body.get('datasets'), list):
                raise ValueError('接口检查响应格式不符')
            now, cutoff = _date_context(context['as_of'])
            observations = []
            for dataset in body['datasets']:
                if not isinstance(dataset, dict):
                    continue
                query = str(dataset.get('query') or base['query'])
                error_code = str(dataset.get('error_code', ''))
                raw = dataset.get('rows') or []
                if error_code != '0':
                    observations.append(f'{query} 返回错误 {error_code}：{str(dataset.get("error_msg") or "未返回成功状态")[:120]}')
                    continue
                valid = _valid_rows(capability, raw, now, cutoff)
                if valid:
                    dates = [str(row.get('date') or row.get('statDate') or row.get('updateDate')) for row in valid]
                    base.update(status='available', count=len(valid), data_date=max(dates), query=query,
                        note=f'{query} 已返回{len(valid)}条有效公司样本；仅证明本接口样本可用，不代表全板块覆盖')
                    if dataset.get('reconnected'):
                        base['note'] += '；首次会话失效，重新连接后复查成功'
                    if dataset.get('cache_key'):
                        raw_cache_rows.append({'capability': capability, 'key': dataset['cache_key'],
                            'rows': valid, 'ttl': 300, 'sample_only': True})
                    return base, raw_cache_rows
                if capability == 'daily' and raw:
                    dates = sorted(str(row.get('date') or '') for row in raw if isinstance(row, dict))
                    observations.append(f'{query} 返回日线截至{dates[-1] if dates else "未知"}，未取得{cutoff.isoformat()}有效收盘价')
                elif capability == 'financial' and raw:
                    observations.append(f'{query} 未取得研究日前已披露、报告期及数值有效的财务样本')
                else:
                    observations.append(f'{query} 返回成功但未取得有效样本')
            errors = any(str(d.get('error_code')) != '0' for d in body['datasets'] if isinstance(d, dict))
            base.update(status='error' if errors else 'empty', note='；'.join(observations) or f'{base["query"]} 未返回数据')
        except subprocess.TimeoutExpired:
            phase = base['query']
            try:
                phase = str(json.loads(phase_path.read_text(encoding='utf-8')).get('query') or phase)
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            base.update(status='timeout', note=f'{phase} 超时（{timeout:g}秒），未取得该接口响应；其他能力独立检查')
        except (ModuleNotFoundError, ImportError):
            base.update(status='unverified', note=f'{base["query"]} 未检查：BaoStock客户端未安装')
        except Exception as error:
            # No raw child stderr is exposed: it can contain unrelated runtime
            # details. The interface and exception category are enough to act.
            base.update(status='error', note=f'{base["query"]} 检查异常：{type(error).__name__}')
    return base, raw_cache_rows


def probe_baostock_health(as_of=None, timeout=TIMEOUT_SECONDS):
    """Check three isolated interfaces concurrently within a maximum 25s each.

    `raw_cache_rows` contains dated, validated sample datasets with non-global
    cache keys. Callers may persist these without confusing one sample with the
    complete industry universe. No API credentials or account access is used.
    """
    as_of = as_of or now_iso()
    timeout = max(.1, min(float(timeout), 25))
    try:
        now, cutoff = _date_context(as_of)
    except (ValueError, TypeError) as error:
        return {'verification': 'unverified', 'capabilities': {
            cap: {'status': 'unverified', 'count': 0, 'checked_at': now_iso(), 'note': str(error)}
            for cap in CAPABILITIES}, 'error': str(error), 'raw_cache_rows': []}
    context = {'as_of': now.isoformat(), 'end': cutoff.isoformat(),
               'start': (cutoff-timedelta(days=10)).isoformat(), 'quarters': _quarters(now.date())}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {cap: pool.submit(_check_one, cap, context, timeout) for cap in CAPABILITIES}
        result = {cap: future.result() for cap, future in futures.items()}
    caps = {cap: item[0] for cap, item in result.items()}
    available = sum(row['status'] == 'available' for row in caps.values())
    verification = ('verified' if available == 3 else 'partial' if available
                    else 'timeout' if any(row['status'] == 'timeout' for row in caps.values())
                    else 'failed')
    return {'verification': verification, 'capabilities': caps,
        'error': '；'.join(row['note'] for row in caps.values() if row['status'] != 'available'),
        'raw_cache_rows': [cache for item in result.values() for cache in item[1]]}


def _worker():
    import contextlib
    import io
    import baostock as bs
    request = json.loads(sys.stdin.read(100_000))
    cap, datasets = request['capability'], []
    path = Path(request['phase_path'])
    def phase(label):
        path.write_text(json.dumps({'query': label}), encoding='utf-8')
    def collect(query, function, args=(), kwargs=None, cache_key=''):
        phase(query)
        value = function(*args, **(kwargs or {}))
        reconnected = False
        # Public anonymous sessions can be invalidated while other public
        # clients connect. Retry only this explicit session error, once.
        if str(value.error_code) == '10001001':
            phase('BaoStock login()重连：' + query)
            reconnect = bs.login()
            if str(reconnect.error_code) == '0':
                phase(query + '（会话重连后复查）')
                value = function(*args, **(kwargs or {}))
                reconnected = True
        rows = []
        while str(value.error_code) == '0' and value.next():
            rows.append(dict(zip(value.fields, value.get_row_data())))
        dataset = {'query': query, 'rows': rows, 'cache_key': cache_key,
                   'error_code': str(value.error_code), 'error_msg': str(value.error_msg),
                   'reconnected': reconnected}
        datasets.append(dataset)
        return rows
    with contextlib.redirect_stdout(io.StringIO()):
        phase('BaoStock login()：' + _query_label(cap, request))
        login = bs.login()
        try:
            if str(login.error_code) != '0':
                datasets.append({'query': 'BaoStock login()', 'rows': [], 'error_code': str(login.error_code),
                                 'error_msg': str(login.error_msg)})
            elif cap == 'industry':
                collect(_query_label(cap, request), bs.query_stock_industry,
                    kwargs={'code': SAMPLE_CODE, 'date': request['end']},
                    cache_key=f'industry:{SAMPLE_CODE}:{request["end"]}')
            elif cap == 'daily':
                collect(_query_label(cap, request), bs.query_history_k_data_plus,
                    (SAMPLE_CODE, 'date,code,close,pctChg,volume,amount', request['start'], request['end']),
                    {'frequency': 'd', 'adjustflag': '3'}, f'daily:{SAMPLE_CODE}:{request["end"]}')
            else:
                now, cutoff = _date_context(request['as_of'])
                for year, quarter in request['quarters']:
                    label = f'query_profit_data(code={SAMPLE_CODE},year={year},quarter={quarter})'
                    rows = collect(label, bs.query_profit_data, (SAMPLE_CODE, year, quarter),
                        cache_key=f'financial:{SAMPLE_CODE}:profit:{year}:{quarter}')
                    if _valid_rows(cap, rows, now, cutoff):
                        break
        finally:
            # Each worker owns a process-local socket and exits immediately.
            # Do not issue logout(): BaoStock's anonymous session may also be
            # used by another process, so explicit logout can invalidate an
            # otherwise independent simultaneous price/financial query.
            phase('BaoStock 本次接口检查结束：' + _query_label(cap, request))
    sys.stdout.write(json.dumps({'datasets': datasets}, ensure_ascii=True))


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    _worker()
