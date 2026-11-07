"""Sina Beijing dailies with separately identified forward-adjustment factors.

Use one complete provider series; never stitch prices or guess old BJ symbols.
Factors follow Sina's close/factor convention, normalized to the study cutoff.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from research_data import CHINA, now_iso
from research_transport import fetch_bytes
from research_trading_calendar import last_closed_trading_day, is_trading_day

METHOD = ('新浪北交所日线及同证券前复权因子；按日期匹配因子，'
          '前复权收盘=原始收盘/当日因子×研究截止日因子。'
          '另核对同代码实时证券身份及最近完整交易日收盘；整段替换，不与其他来源拼接。')


def urls(code):
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}\.BJ', code):
        raise ValueError('仅接受明确的北交所证券代码')
    symbol = 'bj' + code[:6]
    return {
        'url': 'https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData?'
               + 'symbol=' + symbol + '&scale=240&ma=no&datalen=121',
        'factor_url': 'https://finance.sina.com.cn/realstock/company/' + symbol + '/qfq.js',
        'identity_url': 'https://hq.sinajs.cn/list=' + symbol,
    }


def _positive(value):
    if isinstance(value, bool):
        raise ValueError('价格或因子非有效正数')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('价格或因子非有效正数') from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError('价格或因子非有效正数')
    return number


def parse_history(prices_text, factors_text, identity_text, code, name, as_of):
    urls(code)
    symbol = 'bj' + code[:6]
    cutoff = last_closed_trading_day(as_of)
    if cutoff is None:
        raise ValueError('无法核验最近完整交易日')
    quote = re.fullmatch(r'\s*var hq_str_' + re.escape(symbol) + r'="([^"\r\n]*)";\s*', identity_text)
    fields = quote[1].split(',') if quote else []
    if len(fields) < 32 or fields[0].replace(' ', '') != name.replace(' ', ''):
        raise ValueError('北交所行情证券代码或名称不一致')
    quote_day = fields[30]
    if (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', quote_day)
            or not cutoff <= quote_day <= as_of[:10]
            or not is_trading_day(datetime.fromisoformat(quote_day).date())):
        raise ValueError('证券身份行情日期无效或过期')
    match = re.fullmatch(r'\s*(?:/\*.*?\*/\s*)?var=\((\[.*\])\);?\s*', prices_text, re.S)
    if not match:
        raise ValueError('北交所日线格式无效')
    raw = json.loads(match[1])
    if not isinstance(raw, list) or len(raw) > 500:
        raise ValueError('北交所日线数量无效')
    prefix = re.match(r'\s*var\s+' + re.escape(symbol) + r'qfq\s*=\s*', factors_text)
    if not prefix:
        raise ValueError('复权因子证券身份不一致')
    data, end = json.JSONDecoder().raw_decode(factors_text[prefix.end():])
    tail = factors_text[prefix.end()+end:].strip().lstrip(';').strip()
    if tail and not re.fullmatch(r'/\*.*\*/', tail, re.S):
        raise ValueError('复权因子尾部格式无效')
    items = data.get('data') if isinstance(data, dict) else None
    if (not isinstance(items, list) or not items or len(items) > 2000
            or data.get('total') != len(items)):
        raise ValueError('复权因子缺失或截断')
    factors = {}
    for item in items:
        day = item['d']
        datetime.strptime(day, '%Y-%m-%d')
        factor = _positive(item['f'])
        if day in factors:
            raise ValueError('复权因子日期重复')
        factors[day] = factor

    def factor_on(day):
        available = [d for d in factors if d <= day]
        if not available:
            raise ValueError('历史日期没有对应复权因子')
        return factors[max(available)]

    rows = {}
    lower = (datetime.fromisoformat(cutoff).date()-timedelta(days=240)).isoformat()
    for item in raw:
        day = item['day']
        datetime.strptime(day, '%Y-%m-%d')
        if day > cutoff or day < lower or not is_trading_day(datetime.fromisoformat(day).date()):
            continue
        close = _positive(item['close'])
        if day in rows:
            raise ValueError('北交所日线日期重复')
        rows[day] = close
    if not rows or max(rows) != cutoff:
        raise ValueError('北交所日线未覆盖最近完整交易日')
    expected = _positive(fields[3] if quote_day == cutoff else fields[2])
    if abs(rows[cutoff]-expected) > .0051:
        raise ValueError('日线收盘与独立证券身份行情不一致')
    anchor = factor_on(cutoff)
    return [{'date': day, 'close': rows[day]/factor_on(day)*anchor} for day in sorted(rows)][-121:]


def _fetch(url, encoding):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://finance.sina.com.cn/'})
    return fetch_bytes(request, timeout=8, max_bytes=500_000).decode(encoding)


def fetch_histories(companies, as_of, budget_seconds=22):
    if len(companies) > 60:
        raise ValueError('北交所备用批次过大')
    requests = {row['ts_code']: row['name'] for row in companies}
    for code in requests:
        urls(code)

    def one(code):
        locations = urls(code)
        prices = _fetch(locations['url'], 'utf-8')
        factors = _fetch(locations['factor_url'], 'utf-8')
        identity = _fetch(locations['identity_url'], 'gbk')
        rows = parse_history(prices, factors, identity, code, requests[code], as_of)
        return {**locations, 'rows': rows, 'fetched_at': now_iso(),
                'adjustment': 'forward_adjusted', 'method': METHOD}

    result = {}
    pool = ThreadPoolExecutor(max_workers=6)
    futures = {pool.submit(one, code): code for code in requests}
    try:
        for future in as_completed(futures, timeout=min(22, max(.01, budget_seconds))):
            code = futures[future]
            try:
                result[code] = future.result()
            except Exception as error:
                result[code] = {**urls(code), 'rows': [], 'fetched_at': now_iso(),
                                'error': type(error).__name__ + '：' + str(error)[:200]}
    except TimeoutError:
        pass
    finally:
        for future, code in futures.items():
            if code not in result:
                future.cancel()
                result[code] = {**urls(code), 'rows': [], 'fetched_at': now_iso(), 'error': '北交所备用历史采集超时'}
        pool.shutdown(wait=False, cancel_futures=True)
    return result
