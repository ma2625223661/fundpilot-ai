"""Current official index membership for disclosed stock classification.

This is a current mapping observation, not evidence of membership on a fund's
historical reporting date and not evidence that a fund tracks an index.  Names
of funds are deliberately absent from the API.  Partial lists prove membership
only for the securities actually supplied by the official source.
"""
import copy
import gzip
import io
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

CHINA = timezone(timedelta(hours=8))
TIMEOUT = 7
MAX_BYTES = 2_000_000
CACHE_TTL = 12 * 3600
ERROR_CACHE_TTL = 300
MAX_MAPPING_AGE_DAYS = 7
PROVIDER = '恒生指数公司官方成分'
BASE_URL = ('https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/'
            'v1/product-data/pub/')
CATALOG_URL = BASE_URL + 'indexes/metadata/v2?data=allIndexes&language=en-hk'
MAPPING_SCOPE = '披露股票按最新官方成分映射；不代表披露报告日成分或基金实时仓位'
INDEX_CONFIG = {
    'hsi': {'index_code': '00001.00', 'index_name': 'Hang Seng Index', 'kind': 'rt',
            'boards': ['overseas_hang_seng']},
    'hstech': {'index_code': '02083.00', 'index_name': 'Hang Seng TECH Index', 'kind': 'rt',
               'boards': ['overseas_hang_seng_technology']},
    'hshdyi': {'index_code': '01067.00', 'index_name': 'Hang Seng High Dividend Yield Index',
               'kind': 'top10', 'boards': ['overseas_hk_dividend']},
    'hshylv': {'index_code': '02033.00',
               'index_name': 'Hang Seng SCHK High Dividend Low Volatility Index',
               'kind': 'top10', 'boards': ['overseas_hk_dividend', 'style_dividend_low_volatility']},
    'hsscid': {'index_code': '02204.00', 'index_name': 'Hang Seng SCHK Innovative Drug Index',
               'kind': 'top10', 'boards': ['overseas_hk_innovative_drug', 'sector_innovative_drug']},
    'hshci': {'index_code': '02017.00', 'index_name': 'Hang Seng Healthcare Index',
              'kind': 'top10', 'boards': ['overseas_healthcare']},
    'consumer_discretionary': {'series_code': 'industry', 'index_code': '00011.12',
               'index_name': 'Hang Seng Composite Industry Index - Consumer Discretionary',
               'kind': 'top10', 'boards': ['sector_consumer', 'overseas_hugangshen_consumer']},
    'consumer_staples': {'series_code': 'industry', 'index_code': '00011.13',
               'index_name': 'Hang Seng Composite Industry Index - Consumer Staples',
               'kind': 'top10', 'boards': ['sector_consumer', 'overseas_hugangshen_consumer']},
}
_cache = {}
_cache_lock = threading.Lock()
_url_locks = {}


def _day(value=None):
    if value is None:
        return datetime.now(CHINA).date()
    if isinstance(value, datetime):
        return value.astimezone(CHINA).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _source_day(value, as_of):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?', value):
        raise ValueError('官方成分缺少有效来源日期')
    if len(value) > 10:
        datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    observed = _day(value)
    age = (_day(as_of) - observed).days
    if age < 0 or age > MAX_MAPPING_AGE_DAYS:
        raise ValueError('官方成分日期在未来或超过七天')
    return observed.isoformat()


def _official_hk_code(value):
    # Only source rows explicitly labelled as Hong Kong securities reach here.
    text = str(value)
    if not re.fullmatch(r'\d{1,5}', text) or int(text) == 0:
        raise ValueError('官方成分证券代码无效')
    return text.zfill(5)


def _holding_hk_code(value):
    # Never strip the leading zero from a six-digit mainland security code.
    text = str(value or '').strip().upper()
    match = re.fullmatch(r'(\d{5})|HK(\d{5})|(\d{5})\.HK', text)
    return next((part for part in match.groups() if part), '') if match else ''


def _config(key):
    if key not in INDEX_CONFIG:
        raise ValueError('未配置的官方成分指数')
    config = INDEX_CONFIG[key]
    return {**config, 'series_code': config.get('series_code', key)}


def _url(key):
    config = _config(key)
    params = {'data': config['kind'], 'language': 'en-hk'}
    params['seriesCode' if config['kind'] == 'rt' else 'indexCode'] = (
        config['series_code'] if config['kind'] == 'rt' else config['index_code'])
    return BASE_URL + 'constituent/metadata/v2?' + urllib.parse.urlencode(params)


def _snapshot(key, members, dates, complete):
    config = _config(key)
    if len(set(dates)) != 1:
        raise ValueError('官方成分行的日期不一致')
    return {'status': 'ok', 'series_code': config['series_code'],
            'index_code': config['index_code'], 'index_name': config['index_name'],
            'boards': list(config['boards']), 'members': members, 'complete': complete,
            'source_date': dates[0], 'source_url': _url(key), 'provider': PROVIDER,
            'mapping_scope': MAPPING_SCOPE,
            'list_scope': '完整现时成分' if complete else '官方前十大成分，仅能证明已列股票',
            'fetched_at': datetime.now(CHINA).isoformat(timespec='seconds')}


def parse_hsi_membership(payload, key, as_of=None):
    """Validate a complete live list, including index identity and declared count."""
    config = _config(key)
    if config['kind'] != 'rt':
        raise ValueError('该指数未配置为完整成分来源')
    if not isinstance(payload, dict) or str(payload.get('code')) != '0':
        raise ValueError('官方成分响应失败')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('numOfConsList'), list):
        raise ValueError('官方完整成分响应结构变化')
    declarations = [row for row in data['numOfConsList']
                    if isinstance(row, dict) and row.get('indexCode') == config['index_code']]
    if len(declarations) != 1 or declarations[0].get('indexName') != config['index_name']:
        raise ValueError('官方成分指数身份不一致')
    count = declarations[0].get('count')
    details = data.get('viewConsDetail')
    rows = details.get(config['index_code']) if isinstance(details, dict) else None
    if (not isinstance(count, int) or isinstance(count, bool) or count <= 0 or
            not isinstance(rows, list) or len(rows) != count):
        raise ValueError('官方未提供完整成分，不能视为空列表')
    members, dates = {}, []
    for row in rows:
        if (not isinstance(row, dict) or row.get('indexCode') != config['index_code'] or
                row.get('indexName') != config['index_name'] or row.get('stockType') != 'HK' or
                row.get('exchangeListed') != 'Hong Kong Stock Exchange' or row.get('isDummy') != 'N'):
            raise ValueError('官方成分指数、市场或证券身份不一致')
        code = _official_hk_code(row.get('stockCode'))
        name = row.get('stockName')
        if code in members or not isinstance(name, str) or not name.strip():
            raise ValueError('官方成分重复或缺少证券名称')
        observed = _source_day(row.get('dateTime'), as_of)
        members[code] = {'name': name.strip(), 'source_date': observed}
        dates.append(observed)
    return _snapshot(key, members, dates, True)


def parse_hsi_top10(payload, key, as_of=None, catalog=None):
    """Validate positive-only top-ten evidence against the official index catalog."""
    config = _config(key)
    if config['kind'] != 'top10':
        raise ValueError('该指数未配置为前十大来源')
    if not isinstance(catalog, dict) or str(catalog.get('code')) != '0' or not isinstance(catalog.get('data'), list):
        raise ValueError('缺少官方指数目录，不能核对前十大指数身份')
    identity = [row for row in catalog['data'] if isinstance(row, dict) and
                row.get('indexCode') == config['index_code'] and row.get('indexType') == 'PI' and
                row.get('indexSeriesCode') == config['series_code'] and
                row.get('indexName') == config['index_name'] and row.get('regionName') == 'Hong Kong-listed']
    if len(identity) != 1:
        raise ValueError('官方目录与前十大指数身份不一致')
    if not isinstance(payload, dict) or str(payload.get('code')) != '0':
        raise ValueError('官方前十大成分响应失败')
    rows = payload.get('data')
    if not isinstance(rows, list) or len(rows) != 10:
        raise ValueError('官方前十大成分数量不足或结构变化')
    members, dates, orders = {}, [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('exchangeListed') != 'Hong Kong Stock Exchange':
            raise ValueError('官方前十大证券市场身份不一致')
        code = _official_hk_code(row.get('stockCode'))
        name, order = row.get('stockName'), row.get('weightOrder')
        if (code in members or not isinstance(name, str) or not name.strip() or
                not isinstance(order, int) or isinstance(order, bool) or order in orders or not 1 <= order <= 10):
            raise ValueError('官方前十大成分重复或证券身份无效')
        observed = _source_day(row.get('tradeDate'), as_of)
        members[code] = {'name': name.strip(), 'source_date': observed}
        dates.append(observed)
        orders.add(order)
    return _snapshot(key, members, dates, False)


def _fetch_json(url):
    if not url.startswith(BASE_URL):
        raise ValueError('官方成分来源地址不受支持')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 FundPilotLocalResearch/1.0',
                  'Referer': 'https://www.hsi.com.hk/', 'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname != 'www.hsi.com.hk':
            raise ValueError('官方成分来源跳转到未知站点')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('官方成分响应超过限制')
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('官方成分响应超过限制')
    return json.loads(raw.decode('utf-8-sig'))


def _cached_json(url, refresh=False):
    with _cache_lock:
        lock = _url_locks.setdefault(url, threading.Lock())
    with lock:
        with _cache_lock:
            entry = _cache.get(url)
            if entry and not refresh and time.monotonic() - entry['time'] < entry['ttl']:
                if entry.get('error'):
                    raise ValueError(entry['error'])
                return copy.deepcopy(entry['payload'])
        try:
            payload = _fetch_json(url)
        except Exception as error:
            with _cache_lock:
                _cache[url] = {'time': time.monotonic(), 'ttl': ERROR_CACHE_TTL, 'error': str(error)[:200]}
            raise
        with _cache_lock:
            _cache[url] = {'time': time.monotonic(), 'ttl': CACHE_TTL, 'payload': copy.deepcopy(payload),
                           'fetched_at': datetime.now(CHINA).isoformat(timespec='seconds')}
        return payload


def fetch_membership_context(as_of=None, refresh=False, board_ids=None):
    """Collect once per research run; no network request is made per stock.

    board_ids limits collection to configured evidence relevant to those boards.
    A missing/unavailable index remains an error, never a zero-member snapshot.
    """
    observed = _day(as_of).isoformat()
    requested = set(board_ids) if board_ids is not None else None
    selected = [key for key, cfg in INDEX_CONFIG.items()
                if requested is None or requested.intersection(cfg['boards'])]
    context = {'status': 'unavailable', 'indices': {}, 'errors': {}, 'as_of': observed,
               'mapping_scope': MAPPING_SCOPE}
    catalog, catalog_error = None, ''
    if any(INDEX_CONFIG[key]['kind'] == 'top10' for key in selected):
        try:
            catalog = _cached_json(CATALOG_URL, refresh)
        except Exception as error:
            catalog_error = str(error)[:200]

    def collect(key):
        config = _config(key)
        if config['kind'] == 'top10' and catalog_error:
            raise ValueError('官方指数目录获取失败：' + catalog_error)
        payload = _cached_json(_url(key), refresh)
        if config['kind'] == 'rt':
            snapshot = parse_hsi_membership(payload, key, observed)
        else:
            snapshot = parse_hsi_top10(payload, key, observed, catalog)
        with _cache_lock:
            entry = _cache.get(_url(key), {})
            if entry.get('fetched_at'):
                snapshot['fetched_at'] = entry['fetched_at']
        return snapshot

    if selected:
        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as pool:
            futures = {pool.submit(collect, key): key for key in selected}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    context['indices'][key] = future.result()
                except Exception as error:
                    context['errors'][key] = str(error)[:200]
    if context['indices']:
        context['status'] = 'partial' if context['errors'] else 'ok'
    return context


def membership_for_security(code, context):
    """Return tri-state board evidence: matched, not_member, or unknown.

    Full-list absence proves non-membership only for a recognized HK identity.
    Partial-list absence always remains unknown. Unknown classifiers must remain
    in the fund's disclosed-stock denominator and never create inferred weights.
    """
    hk_code = _holding_hk_code(code)
    result = {'code': str(code), 'region': '', 'memberships': {}}
    indices = context.get('indices', {}) if isinstance(context, dict) else {}
    boards = sorted({board for config in INDEX_CONFIG.values() for board in config['boards']})
    for board in boards:
        sources = []
        for snapshot in indices.values():
            if snapshot.get('status') != 'ok' or board not in snapshot.get('boards', []):
                continue
            member = snapshot.get('members', {}).get(hk_code) if hk_code else None
            matched = True if member else (False if hk_code and snapshot.get('complete') else None)
            sources.append({key: snapshot[key] for key in ('index_code', 'index_name', 'source_date',
                            'source_url', 'provider', 'complete', 'mapping_scope', 'list_scope')}
                           | {'matched': matched})
        matched = True if any(source['matched'] is True for source in sources) else (
            False if sources and all(source['matched'] is False for source in sources) else None)
        result['memberships'][board] = {'matched': matched,
            'status': 'matched' if matched is True else ('not_member' if matched is False else 'unknown'),
            'complete': bool(sources) and all(source['complete'] for source in sources),
            'source_date': max((source['source_date'] for source in sources), default=''),
            'mapping_scope': MAPPING_SCOPE, 'sources': sources}
        if matched is True:
            result['region'] = 'hk'
    return result
