"""Optional free data providers for sector company evidence.

The project keeps Tushare as an optional, higher coverage provider.  This
module adds a no-token fallback around BaoStock when the package is installed.
It deliberately does not collect news, announcements, or policy documents;
those remain handled by :mod:`research_official_events`.

BaoStock is a public, free API and its industry labels and financial endpoints
are useful for a best-effort sector report.  The adapter never treats a
company name as evidence of sector membership and labels samples as
``free-provider sample`` because BaoStock does not expose the same complete
Shenwan membership and market-cap ranking used by the Tushare path.
"""
from __future__ import annotations

import copy
import importlib
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from research_data import CHINA
from research_sample_policy import MAX_SAMPLES
from research_tushare import board_ids_for_member


PROVIDER = 'baostock'
SOURCE_BASE = 'https://www.baostock.com'
_CACHE_PATH = Path(__file__).resolve().parent / 'data' / 'free-company-cache.json'
_cache_lock = threading.RLock()
_session_lock = threading.Lock()
_datasets = {}
_capabilities = {}
_rotation = 0
INDUSTRY_TTL = 7 * 86400
DAILY_TTL = 6 * 3600
FINANCIAL_TTL = 24 * 3600


def _now():
    return datetime.now(CHINA).isoformat(timespec='seconds')


def _remember(key, rows, ttl, capability=None):
    record = {'rows': copy.deepcopy(rows), 'expires': time.time() + ttl,
              'fetched_at': _now()}
    with _cache_lock:
        _datasets[key] = record
        if capability:
            _capabilities[capability] = {'status': 'available' if rows else 'empty',
                'count': len(rows), 'checked_at': record['fetched_at'],
                'note': '已取得有效样本' if rows else '接口返回空数据'}
        if len(_datasets) > 1024:
            for old in list(_datasets):
                if _datasets[old]['expires'] < time.time():
                    _datasets.pop(old, None)
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = _CACHE_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps({'version': 1, 'datasets': _datasets,
                                       'capabilities': _capabilities}, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, _CACHE_PATH)
        except OSError:
            pass
    return rows


def _cached(key):
    with _cache_lock:
        row = _datasets.get(key)
        return copy.deepcopy(row) if row and row['expires'] > time.time() else None


def capability_snapshot():
    with _cache_lock:
        out = copy.deepcopy(_capabilities)
        for key in ('industry', 'daily', 'financial'):
            live = [row for name, row in _datasets.items() if name.startswith(key + ':')
                    and row.get('expires', 0) > time.time()]
            valid = [row for row in live if row.get('rows')]
            if valid:
                last_cache = max(r['fetched_at'] for r in valid)
                current = out.get(key, {})
                if current.get('status') in {'timeout', 'error', 'unverified', 'checking'} and str(current.get('checked_at') or '') >= last_cache:
                    current.update(cache_available=True, cache_as_of=last_cache)
                    continue
                out[key] = {**out.get(key, {}), 'status': 'available', 'count': sum(len(r['rows']) for r in valid),
                            'checked_at': max(max(r['fetched_at'] for r in valid), out.get(key, {}).get('checked_at') or ''),
                            'note': out.get(key, {}).get('note') or '已取得有效样本'}
            elif live:
                out[key] = {'status': 'empty', 'count': 0,
                            'checked_at': max(r['fetched_at'] for r in live), 'note': '接口返回空数据'}
            elif out.get(key, {}).get('status') in {'available', 'empty'}:
                out[key].update(status='unverified', note='已有样本已过缓存时效，等待重新检查')
        return out


def _load_cache():
    try:
        if _CACHE_PATH.stat().st_size > 12_000_000:
            return
        doc = json.loads(_CACHE_PATH.read_text(encoding='utf-8'))
        if doc.get('version') != 1:
            return
        for key, row in doc.get('datasets', {}).items():
            if isinstance(row, dict) and isinstance(row.get('rows'), list) and isinstance(row.get('expires'), (int, float)):
                if row['expires'] > time.time():
                    _datasets[key] = row
        if isinstance(doc.get('capabilities'), dict):
            _capabilities.update(doc['capabilities'])
    except (OSError, ValueError, TypeError, AttributeError):
        pass


_load_cache()


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _date(value):
    text = str(value or '')
    if re.fullmatch(r'\d{8}', text):
        return text[:4] + '-' + text[4:6] + '-' + text[6:]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return text
    return ''


def _rows(result):
    """Convert a BaoStock ResultData or a test list into dictionaries."""
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, dict)]
    if hasattr(result, 'error_code') and str(getattr(result, 'error_code', '0')) not in ('0', '', 'None'):
        raise RuntimeError('BaoStock 接口返回错误 ' + str(getattr(result, 'error_code', '')))
    if hasattr(result, 'next') and hasattr(result, 'get_row_data'):
        values = []
        while result.next():
            values.append(dict(zip(getattr(result, 'fields', []) or [], result.get_row_data())))
        return values
    return []


def provider_status():
    """Return install status without importing or contacting a data provider."""
    try:
        module = importlib.import_module('baostock')
    except Exception:
        return {'provider': PROVIDER, 'name': 'BaoStock', 'status': 'not_installed',
                'message': '未安装 BaoStock；安装后可使用行业与财务数据。', 'sources': []}
    return {'provider': PROVIDER, 'name': 'BaoStock', 'status': 'available',
            'message': '已发现 BaoStock Python 客户端，尚未请求数据。',
            'version': str(getattr(module, '__version__', '') or ''), 'sources': []}


def probe_baostock():
    """Independently probe three bounded endpoints, even if one fails."""
    status = provider_status()
    if status['status'] != 'available':
        return {'verification': 'not_installed', 'capabilities': {},
                'error': status['message']}
    from research_baostock_health import probe_baostock_health
    outcome = probe_baostock_health()
    for item in outcome.pop('raw_cache_rows', []):
        # A one-company health probe must never replace a research dataset.
        key = item['capability'] + ':health-sample:' + item['key']
        _remember(key, item['rows'], item['ttl'])
    with _cache_lock:
        _capabilities.update(copy.deepcopy(outcome.get('capabilities') or {}))
    return outcome


class BaoStockAdapter:
    """Small adapter around the optional ``baostock`` package.

    Keeping the client behind this class makes the research engine testable
    without a network connection and prevents credentials from being needed.
    """

    def __init__(self, module=None):
        self.module = module or importlib.import_module('baostock')
        self.logged_in = False
        self._session_owned = False
        self._running = None
        self._cleanup_started = False
        self._broken = False
        self.deadline = None

    def _abort_socket(self):
        try:
            context = importlib.import_module('baostock.common.context')
            sock = getattr(context, 'default_socket', None)
            if sock is not None:
                try:
                    sock.shutdown(2)
                except OSError:
                    pass
                sock.close()
        except (ImportError, OSError, AttributeError):
            pass

    def _call(self, fn, *args, timeout=30, rows=False, **kwargs):
        """Call BaoStock without allowing a stalled public endpoint to hang the server."""
        if self._broken:
            raise TimeoutError('BaoStock 当前会话已超时，等待下轮重试')
        if self.deadline is not None:
            timeout = min(timeout, max(0, self.deadline - time.monotonic()))
            if timeout <= 0:
                raise TimeoutError('BaoStock 本轮采集预算已用完')
        box = {}

        def run():
            try:
                value = fn(*args, **kwargs)
                box['value'] = _rows(value) if rows else value
            except BaseException as error:
                box['error'] = error

        thread = threading.Thread(target=run, name='baostock-request', daemon=True)
        self._running = thread
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self._broken = True
            self._abort_socket()
            thread.join(.3)
            raise TimeoutError('BaoStock 请求超时')
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def login(self):
        if self.logged_in:
            return
        if self._broken or self._cleanup_started:
            raise TimeoutError('BaoStock 当前会话已结束，等待下轮重试')
        if not _session_lock.acquire(blocking=False):
            raise RuntimeError('BaoStock 正在更新同一份数据，当前使用缓存并等待完成')
        self._session_owned = True
        try:
            result = self._call(self.module.login, timeout=10)
            if str(getattr(result, 'error_code', '0')) not in ('0', 'None', ''):
                raise RuntimeError('BaoStock 登录失败')
            self.logged_in = True
        except Exception:
            self.logout()
            raise

    def logout(self):
        if not self._session_owned or self._cleanup_started:
            return
        self._cleanup_started = True
        self.logged_in = False
        running = self._running
        def release():
            if running and running.is_alive():
                running.join()
            self._abort_socket()
            self._session_owned = False
            _session_lock.release()
        if running and running.is_alive():
            threading.Thread(target=release, name='baostock-session-cleanup', daemon=True).start()
        else:
            release()

    def _query(self, key, fn, args=(), kwargs=None, ttl=300, capability=None):
        hit = _cached(key)
        if hit:
            return hit['rows']
        try:
            self.login()
            value = self._call(fn, *args, rows=True, timeout=30 if key.startswith('industry:') else 8,
                               **(kwargs or {}))
        except Exception as error:
            if capability:
                with _cache_lock:
                    _capabilities[capability] = {'status': 'timeout' if isinstance(error, TimeoutError) else 'error',
                        'count': 0, 'checked_at': _now(), 'note': '接口超时' if isinstance(error, TimeoutError) else '接口取数失败'}
            raise
        return _remember(key, value, ttl, capability)

    def stock_basic(self):
        return self._query('stock_basic:all', self.module.query_stock_basic, ttl=INDUSTRY_TTL)

    def stock_industry(self):
        return self._query('industry:all', self.module.query_stock_industry,
                           ttl=INDUSTRY_TTL, capability='industry')

    def daily(self, code, start_date, end_date):
        return self._query('daily:' + code + ':' + end_date, self.module.query_history_k_data_plus,
            (code, 'date,code,close,pctChg,volume,amount', start_date, end_date),
            {'frequency': 'd', 'adjustflag': '3'}, ttl=DAILY_TTL, capability='daily')

    def profit(self, code, year, quarter):
        return self._query(f'financial:{code}:profit:{year}:{quarter}', self.module.query_profit_data,
                           (code, year, quarter), ttl=FINANCIAL_TTL, capability='financial')

    def growth(self, code, year, quarter):
        return self._query(f'financial:{code}:growth:{year}:{quarter}', self.module.query_growth_data,
                           (code, year, quarter), ttl=FINANCIAL_TTL, capability='financial')

    def dupont(self, code, year, quarter):
        return self._query(f'financial:{code}:dupont:{year}:{quarter}', self.module.query_dupont_data,
                           (code, year, quarter), ttl=FINANCIAL_TTL, capability='financial')


def _source(name, status, count=0, error=None, as_of=None, suffix='', fetched_at=None):
    row = {'id': 'baostock:' + name, 'name': 'BaoStock · ' + name,
           'url': SOURCE_BASE, 'status': status, 'count': count,
           'as_of': as_of, 'fetched_at': fetched_at or _now(),
           'scope': '免费公开 A 股行业、行情与财务数据；不含公告或政策'}
    if suffix:
        row['id'] += ':' + suffix
    if error:
        row['error'] = error
    return row


def _as_code(value):
    text = str(value or '').strip()
    if re.fullmatch(r'(?:sh|sz|bj)\.\d{6}', text.lower()):
        return text.lower()
    if re.fullmatch(r'\d{6}', text):
        prefix = 'sh' if text.startswith(('6', '68')) else 'sz'
        return prefix + '.' + text
    return ''


def _member(row):
    code = _as_code(row.get('code') or row.get('ts_code'))
    if not code:
        return None
    industry = str(row.get('industry') or row.get('industryClassification') or row.get('industry_name') or '').strip()
    name = str(row.get('code_name') or row.get('name') or code).strip()
    if not industry:
        return None
    market, number = code.split('.', 1)
    return {'ts_code': number + '.' + market.upper(), 'baostock_code': code.lower(),
            'name': name, 'l1_name': industry, 'l2_name': industry, 'l3_name': industry,
            'industry': industry, 'in_date': _date(row.get('updateDate') or row.get('in_date'))}


def _financial(rows, code, as_of=None):
    if not rows:
        return None
    today = _date(str(as_of or _now())[:10])
    usable = [r for r in rows if isinstance(r, dict)
              and _date(r.get('pubDate') or r.get('ann_date'))
              and _date(r.get('pubDate') or r.get('ann_date')) < today
              and _date(r.get('statDate') or r.get('end_date'))
              and _date(r.get('statDate') or r.get('end_date')) <= today]
    if not usable:
        return None
    fields_by_target = {
        'roe': ('roeAvg', 'dupontROE'),
        'eps': ('epsTTM', 'eps'),
        'netprofit_yoy': ('YOYNI',),
        'tr_yoy': ('YOYMBRevenue',),
        'grossprofit_margin': ('gpMargin', 'grossProfitMargin', 'grossprofit_margin'),
    }
    for period in sorted({_date(r.get('statDate') or r.get('end_date')) for r in usable}, reverse=True):
        period_rows = [r for r in usable if _date(r.get('statDate') or r.get('end_date')) == period]
        out = {'ts_code': code.upper(),
               'ann_date': max(_date(r.get('pubDate') or r.get('ann_date')) for r in period_rows),
               'end_date': period}
        merged = {}
        for item in sorted(period_rows, key=lambda r: _date(r.get('pubDate') or r.get('ann_date'))):
            # An empty cell in another endpoint must not erase a real value.
            merged.update({key: value for key, value in item.items() if value not in (None, '')})
        for target, fields in fields_by_target.items():
            for field in fields:
                value = _number(merged.get(field))
                if value is not None:
                    # BaoStock exposes these financial ratios as decimals.
                    out[target] = value * 100 if target != 'eps' else value
                    break
        if len(out) > 3:
            return out
    return None


def _quarters(now):
    """Latest completed quarter followed by at most three earlier quarters."""
    ordinal = now.year * 4 + (now.month - 1) // 3 - 1
    return [((ordinal - offset) // 4, (ordinal - offset) % 4 + 1) for offset in range(4)]


def gather_free_sector_company_evidence(catalog, as_of, adapter=None):
    """Collect best-effort free company evidence with the shared report schema."""
    global _rotation
    result = {
        'status': 'not_installed', 'provider': PROVIDER, 'sources': [],
        'sector_leaders': {}, 'warnings': [], 'request_count': 0,
        'selection_method': 'BaoStock 行业标签归属；每个板块最多8个样本，免费来源不提供完整市值排序',
    }
    if adapter is None:
        try:
            adapter = BaoStockAdapter()
        except Exception:
            result['warnings'].append('未安装 BaoStock；可执行 E:\\python\\python.exe -m pip install baostock')
            result['sources'].append(_source('client', 'not_installed', error='未安装 BaoStock'))
            return result
    now = datetime.fromisoformat(str(as_of).replace('Z', '+00:00')) if as_of else datetime.now(CHINA)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CHINA)
    start = (now.date() - timedelta(days=90)).isoformat()
    end = now.date().isoformat()
    deadline = time.monotonic() + 45
    if isinstance(adapter, BaoStockAdapter):
        adapter.deadline = deadline
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError('BaoStock 本轮采集预算已用完')
        if not isinstance(adapter, BaoStockAdapter):
            adapter.login()
        industries = adapter.stock_industry()
        result['request_count'] += 1
    except Exception as error:
        result['status'] = 'unavailable'
        result['warnings'].append('BaoStock 连接失败：' + str(error)[:160])
        result['sources'].append(_source('stock_industry', 'timeout' if isinstance(error, TimeoutError) else 'error',
                                         error='查询超时' if isinstance(error, TimeoutError) else '连接失败'))
        try:
            adapter.logout()
        except Exception:
            pass
        return result
    industry_cache = _cached('industry:all') or {}
    industry_dates = [_date(row.get('updateDate')) for row in industries if _date(row.get('updateDate'))]
    result['sources'].append(_source('stock_industry', 'ok' if industries else 'empty', len(industries),
        as_of=max(industry_dates) if industry_dates else None, fetched_at=industry_cache.get('fetched_at')))
    grouped = {}
    for raw in industries:
        member = _member(raw)
        if not member or (member.get('in_date') and member['in_date'] > end):
            continue
        for board_id in board_ids_for_member(member, catalog):
            grouped.setdefault(board_id, {})[member['ts_code']] = member
    items = list(grouped.items())
    if items:
        with _cache_lock:
            position = _rotation % len(items)
            _rotation = (_rotation + 1) % len(items)
        items = items[position:] + items[:position]
    completed = 0
    # Preserve successful board samples while a later round spends its budget
    # on other boards. Cached rows keep their original quote and fetch times.
    for board_id, _ in items:
        cached = _cached('samples:' + end + ':' + board_id)
        if cached and cached['rows']:
            cached_board = cached['rows'][0]
            result['sector_leaders'][board_id] = cached_board.get('leaders', [])[:MAX_SAMPLES]
            result['sources'].extend(cached_board.get('sources', []))
    try:
        for board_id, members in items:
            if time.monotonic() >= deadline or getattr(adapter, '_broken', False):
                break
            leaders = []
            prior_board = _cached('samples:' + end + ':' + board_id)
            board_sources = list(prior_board['rows'][0].get('sources', [])) if prior_board and prior_board['rows'] else []
            for code, member in sorted(members.items())[:MAX_SAMPLES]:
                if time.monotonic() >= deadline:
                    result['warnings'].append('BaoStock 本轮采集达到45秒预算，剩余板块留待下轮。')
                    break
                try:
                    quote_rows = adapter.daily(member['baostock_code'], start, end)
                except TimeoutError:
                    break
                except Exception as error:
                    board_sources.append(_source('daily', 'error', suffix=code, error=str(error)[:160]))
                    continue
                result['request_count'] += 1
                usable_quotes = [q for q in quote_rows if _date(q.get('date')) and _date(q.get('date')) <= end]
                quote = max(usable_quotes, key=lambda q: q.get('date', '')) if usable_quotes else {}
                if not quote:
                    continue
                quote_date = _date(quote.get('date'))
                staleness_days = (now.date() - datetime.fromisoformat(quote_date).date()).days
                stale = staleness_days > 7
                daily_cache = _cached('daily:' + member['baostock_code'] + ':' + end) or {}
                daily_source = _source('daily', 'stale' if stale else 'ok', len(usable_quotes), as_of=quote_date,
                    suffix=code, fetched_at=daily_cache.get('fetched_at'))
                if stale:
                    daily_source['error'] = '最新日线距研究日超过7天，不能代表当期行情'
                board_sources.append(daily_source)
                fin_rows = []
                financial_fetched = []
                for year, quarter in _quarters(now):
                    if time.monotonic() >= deadline or getattr(adapter, '_broken', False):
                        break
                    for method in ('profit', 'growth'):
                        if time.monotonic() >= deadline or getattr(adapter, '_broken', False):
                            break
                        try:
                            fin_rows.extend(getattr(adapter, method)(member['baostock_code'], year, quarter))
                            result['request_count'] += 1
                            fin_cache = _cached(f'financial:{member["baostock_code"]}:{method}:{year}:{quarter}')
                            if fin_cache:
                                financial_fetched.append(fin_cache['fetched_at'])
                        except Exception:
                            continue
                    if _financial(fin_rows, code, as_of):
                        break
                financials = _financial(fin_rows, code, as_of)
                if financials:
                    board_sources.append(_source('financial', 'ok', len(fin_rows),
                        as_of=financials['ann_date'], suffix=code,
                        fetched_at=max(financial_fetched) if financial_fetched else None))
                leaders.append({
                    'ts_code': code, 'name': member['name'], 'industry': member['industry'],
                    'role': '免费数据源行业代表样本（主营龙头身份待核对）', 'leader_verified': False,
                    'selection_basis': 'BaoStock 行业标签；按代码稳定排序取最多8只',
                    'quote': {'trade_date': _date(quote.get('date')), 'close': _number(quote.get('close')),
                              'pct_chg': _number(quote.get('pctChg')), 'vol': _number(quote.get('volume')),
                              'amount': _number(quote.get('amount')), 'data_kind': 'daily_close',
                              'is_intraday': False, 'stale': stale, 'staleness_days': staleness_days,
                              'units': {'vol': '股', 'amount': '元'}},
                    'market_metrics': {}, 'financials': financials,
                    'financials_note': 'BaoStock 免费财务字段可能不完整；只读取研究日前已披露的报告，同日披露因无精确时刻暂不使用',
                    'membership_evidence': {'l1_name': member['l1_name'], 'l2_name': member['l2_name'],
                                           'l3_name': member['l3_name'], 'in_date': member['in_date'], 'out_date': ''},
                    'as_of': quote.get('date') or end,
                    'source_ids': ['baostock:stock_industry', daily_source['id']] + (
                        ['baostock:financial:' + code] if financials else []),
                })
            if leaders:
                previous = result['sector_leaders'].get(board_id, [])
                existing = {row['ts_code'] for row in leaders}
                leaders.extend(row for row in previous if row.get('ts_code') not in existing)
                result['sector_leaders'][board_id] = leaders[:MAX_SAMPLES]
                board_sources = list({row['id']: row for row in board_sources}.values())
                _remember('samples:' + end + ':' + board_id,
                    [{'leaders': leaders[:MAX_SAMPLES], 'sources': board_sources}], DAILY_TTL)
                completed += 1
            result['sources'].extend(board_sources)
    except Exception as error:
        result['warnings'].append('BaoStock 行业样本采集未完成：' + str(error)[:160])
    finally:
        try:
            adapter.logout()
        except Exception:
            pass
    result['status'] = 'partial' if result['sector_leaders'] else 'unavailable'
    result['sources'] = list({row['id']: row for row in result['sources']}.values())
    if time.monotonic() >= deadline or getattr(adapter, '_broken', False):
        result['warnings'].append('BaoStock 本轮采集达到时限，已保留成功样本并轮换后续板块。')
    result['coverage'] = {'matched_sector_count': len(grouped), 'sampled_sector_count': len(result['sector_leaders']),
                         'refreshed_sector_count': completed,
                         'rotating_start': items[0][0] if items else None}
    result['warnings'].append('免费数据源为公开接口最佳努力结果，板块成分覆盖和财务字段可能不完整；不含公告与政策。')
    return result


__all__ = ['BaoStockAdapter', 'gather_free_sector_company_evidence', 'probe_baostock',
           'provider_status', 'capability_snapshot']
