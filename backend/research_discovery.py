"""Bounded public discovery of fund candidates for empty research directions.

Search hits never establish eligibility, holdings, Alipay availability or a trade
recommendation. Each candidate's identity is checked against the operator's fund
product page before the existing universe/holdings/strategy gates may consider it.
No account, API key, HTML/JavaScript execution or paid service is used.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from research_categories import BOARDS
from research_data import clean_text, explain_error, now_iso
from research_selection import _family

SEARCH_ENDPOINT = 'https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx'
BING_ENDPOINT = 'https://www.bing.com/search'
MAX_BOARDS = 3
MAX_CANDIDATES = 3
TIMEOUT = 6
BOARD_TIMEOUT = 18
MAX_BYTES = 500_000
CACHE_TTL = 1800
GAP_STATUSES = {'no_match', 'excluded', 'holdings_pending', 'holdings_mismatch', 'insufficient'}
_cache = {}
_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()

# Search vocabulary is candidate discovery only. These queries never prove
# sector allocation; actual disclosed portfolios must still pass the gate.
SEARCH_FALLBACK_QUERIES = {
    'sector_cxo': '医疗',
    'sector_brain_computer': '医疗器械',
    'overseas_hk_dividend': '港股通高股息',
    'overseas_hugangshen_consumer': '沪港深',
    'sector_compute_leasing': '云计算',
    'sector_nuclear_fusion': '核电',
    'sector_domestic_computing': '计算机',
    'sector_mlcc': '电子',
    'sector_memory_chip': '半导体',
}


def _cap(value, maximum):
    return max(0, min(value, maximum)) if type(value) is int else maximum


def _normal_name(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', clean_text(value, 200)))


def product_url(url):
    """Accept only operator product pages, never arbitrary six-digit body text."""
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname != 'fund.eastmoney.com'
                or parsed.username or parsed.password or parsed.port is not None
                or parsed.query or parsed.fragment):
            return None
        match = re.fullmatch(r'/([0-9]{6})\.html', parsed.path)
        return f'https://fund.eastmoney.com/{match[1]}.html' if match else None
    except (TypeError, ValueError, AttributeError):
        return None


def _fetch_text(url, timeout=TIMEOUT):
    expected = urllib.parse.urlsplit(url).hostname
    allowed = {expected}
    if expected == 'www.bing.com':
        allowed.add('cn.bing.com')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 FundPilotLocalResearch/1.0',
        'Accept': 'application/json,application/rss+xml,text/html,*/*',
    })
    with urllib.request.urlopen(request, timeout=min(TIMEOUT, timeout)) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname not in allowed:
            raise ValueError('公开来源重定向至未核验域名')
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('公开搜索响应超过大小限制')
        return body.decode('utf-8-sig')


def parse_search(text):
    """Read the official search's fund records; stocks/indices are excluded."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or payload.get('ErrCode') != 0 or not isinstance(payload.get('Datas'), list):
        raise ValueError('公开基金搜索字段已变化')
    result, seen = [], set()
    for item in payload['Datas'][:60]:
        if not isinstance(item, dict) or str(item.get('CATEGORY')) != '700':
            continue
        code, name, base = item.get('CODE'), item.get('NAME'), item.get('FundBaseInfo')
        if (not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code)
                or not isinstance(name, str) or not name.strip() or not isinstance(base, dict)
                or base.get('FCODE') != code or _normal_name(base.get('SHORTNAME')) != _normal_name(name)
                or code in seen):
            continue
        seen.add(code)
        result.append({'code': code, 'name': clean_text(name, 160),
                       'fund_type': clean_text(base.get('FTYPE'), 100),
                       'source_url': f'https://fund.eastmoney.com/{code}.html',
                       'search_title': clean_text(name, 200)})
    return result


def parse_bing_rss(text):
    """Search titles are provenance only; identity comes from the product page."""
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('公开搜索响应含不支持的 XML 声明')
    root = ET.fromstring(text)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('公开搜索未返回 RSS 结果')
    result, seen = [], set()
    for item in root.findall('./channel/item')[:20]:
        url = product_url((item.findtext('link') or '').strip())
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({'code': url.rsplit('/', 1)[-1][:-5], 'source_url': url,
                       'search_title': clean_text(item.findtext('title'), 200)})
    return result


def _prioritize_hits(hits):
    """Spend page checks on diverse, potentially OTC products before ETFs.

    These name clues only order discovery requests. They never establish that
    a product is eligible or available through a particular trading platform.
    """
    def order(item):
        name = item.get('name', '')
        exchange = bool(re.search(r'ETF', name, re.I) and '联接' not in name)
        restricted = bool(re.search(r'LOF|REIT|封闭|持有|定开|养老金|养老目标', name, re.I))
        return exchange or restricted, 0 if name.endswith('C') else 1
    result, families = [], set()
    for hit in sorted(hits, key=order):
        family = _family(hit) if hit.get('name') else hit['code']
        if family in families:
            continue
        families.add(family)
        result.append(hit)
    return result


class _FundPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.header_depth = None
        self.header = []
        self.in_title = False
        self.title = []
        self.in_cell = False
        self.cell = []
        self.cells = []

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            self.depth += 1
            if 'fundDetail-tit' in dict(attrs).get('class', '').split() and self.header_depth is None:
                self.header_depth = self.depth
        elif tag == 'title':
            self.in_title = True
        elif tag == 'td':
            self.in_cell, self.cell = True, []

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.header_depth == self.depth:
                self.header_depth = None
            self.depth = max(0, self.depth - 1)
        elif tag == 'title':
            self.in_title = False
        elif tag == 'td' and self.in_cell:
            self.cells.append(''.join(self.cell))
            self.in_cell = False

    def handle_data(self, data):
        if self.header_depth is not None:
            self.header.append(data)
        if self.in_title:
            self.title.append(data)
        if self.in_cell:
            self.cell.append(data)


def parse_product_page(text, expected_code):
    """Require code/name in both the fund header and matching product title."""
    if not isinstance(expected_code, str) or not re.fullmatch(r'[0-9]{6}', expected_code):
        raise ValueError('基金产品代码格式无效')
    page = _FundPage()
    page.feed(text)
    header = unicodedata.normalize('NFKC', clean_text(''.join(page.header), 220))
    # The operator adds a related-ETF link inside the same title container on
    # ETF/feeder pages. It is navigation, not part of the fund's identity.
    match = re.fullmatch(r'(.+?)\s*\(\s*([0-9]{6})\s*\)\s*(?:查看相关ETF(?:联接)?\s*>?)?', header)
    if not match or match[2] != expected_code:
        raise ValueError('基金产品页未提供一致的代码及名称')
    name = clean_text(match[1], 160)
    title = _normal_name(''.join(page.title))
    if not title.startswith(_normal_name(name) + '(' + expected_code + ')基金'):
        raise ValueError('基金产品页标题与产品身份不一致')
    fund_type = ''
    for cell in page.cells:
        kind = re.match(r'\s*类型\s*[：:]\s*([^|]+)', cell)
        if kind:
            fund_type = clean_text(kind[1], 100)
            break
    return {'code': expected_code, 'name': name, 'fund_type': fund_type,
            'source_url': f'https://fund.eastmoney.com/{expected_code}.html'}


def _search_board(board_id, maximum):
    board = BOARDS[board_id]
    label, started = board['label'], now_iso()
    deadline = time.monotonic() + BOARD_TIMEOUT
    attempts, candidates, seen = [], [], set()
    page_count = 0

    def request(url, provider, query, kind, parser, title=None):
        stamp = now_iso()
        attempt = {'id': f'discovery:{board_id}:{provider}:{len(attempts) + 1}',
                   'name': '天天基金公开基金搜索' if provider == 'eastmoney_search' else 'Bing 公开网页搜索' if provider == 'bing_rss' else '天天基金产品页身份核验',
                   'provider': provider, 'kind': kind, 'query': query, 'url': url,
                   'title': title or label, 'searched_at': stamp, 'fetched_at': stamp,
                   'attempted': False, 'success': False, 'status': 'error', 'count': 0}
        attempts.append(attempt)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('本板块公开搜索时间预算已用完')
            attempt['attempted'] = True
            result = parser(_fetch_text(url, timeout=min(TIMEOUT, remaining)))
            attempt.update(success=True, status='ok', count=len(result) if isinstance(result, list) else 1)
            return result
        except Exception as error:
            attempt['error'] = explain_error(error)
            return [] if kind == 'search' else None

    aliases = board.get('aliases') if isinstance(board.get('aliases'), list) else []
    fallback = SEARCH_FALLBACK_QUERIES.get(board_id) or next((value for value in aliases if isinstance(value, str) and value.strip() and value != label), None)
    queries = [('eastmoney_search', label)]
    if fallback:
        queries.append(('eastmoney_search', fallback))
    queries.append(('bing_rss', f'{label} 基金 site:fund.eastmoney.com'))
    for provider, query in queries:
        if candidates or page_count >= maximum or time.monotonic() >= deadline:
            break
        url = (SEARCH_ENDPOINT + '?' + urllib.parse.urlencode({'m': 1, 'key': query})
               if provider == 'eastmoney_search' else BING_ENDPOINT + '?' + urllib.parse.urlencode({'format': 'rss', 'q': query}))
        hits = request(url, provider, query, 'search', parse_search if provider == 'eastmoney_search' else parse_bing_rss)
        for hit in _prioritize_hits(hits):
            code = hit['code']
            if code in seen:
                continue
            if page_count >= maximum or time.monotonic() >= deadline:
                break
            seen.add(code)
            page_count += 1
            fund = request(hit['source_url'], 'eastmoney_product', query, 'product',
                           lambda text, identity=code: parse_product_page(text, identity), hit['search_title'])
            if not fund:
                continue
            if hit.get('name') and _normal_name(hit['name']) != _normal_name(fund['name']):
                attempts[-1].update(success=False, status='error', count=0, error='公开搜索与产品页基金名称不一致')
                continue
            if not fund['fund_type']:
                fund['fund_type'] = hit.get('fund_type', '')
            fund.update(search_url=url, search_title=hit['search_title'], search_provider=provider,
                        searched_at=started, status='discovery_only',
                        note='仅为公开发现候选；尚未通过当前排行初筛、披露持仓及策略核验，支付宝在售情况未核验。')
            candidates.append(fund)
            if len(candidates) >= maximum:
                break
    errors = [item for item in attempts if item['status'] == 'error']
    status = ('partial' if errors else 'ok') if candidates else 'error' if errors else 'empty'
    return {'board_id': board_id, 'label': label, 'query': f'{label} 基金', 'status': status,
            'attempted': any(item['attempted'] for item in attempts), 'success': bool(candidates),
            'searched_at': started, 'cache_hit': False, 'attempted_this_run': bool(attempts),
            'candidates': candidates, 'attempts': attempts,
            'error': '；'.join(dict.fromkeys(item['error'] for item in errors))[:360] if errors else None}


def discover_public_candidates(board_coverage, *, limit_boards=MAX_BOARDS,
                               max_per_board=MAX_CANDIDATES, refresh=False):
    """Return discovery evidence for at most three empty, known board directions.

    Per board: at most three search requests and three product-page requests,
    within 18 seconds. Saved prior search timestamps keep rotation working
    after restarts; cached evidence retains its original attempt time.
    Caller must cross-check candidates against the existing universe and gates.
    """
    limit, maximum = _cap(limit_boards, MAX_BOARDS), _cap(max_per_board, MAX_CANDIDATES)
    result = {'as_of': now_iso(), 'boards': [], 'sources': [], 'warnings': [],
              'method': '公开搜索发现后核验天天基金产品页身份；不以搜索结果替代初筛、持仓或策略。'}
    if not limit or not maximum or not isinstance(board_coverage, list):
        return result
    eligible, seen = [], set()
    for position, row in enumerate(board_coverage):
        if not isinstance(row, dict):
            continue
        identity = row.get('id') or row.get('board_id')
        if (not isinstance(identity, str) or identity not in BOARDS or identity in seen
                or identity == 'holdings_unclassified'
                or row.get('status') not in GAP_STATUSES or row.get('displayed_count', 0)):
            continue
        seen.add(identity)
        previous_search = row.get('web_search') if isinstance(row.get('web_search'), dict) else {}
        try:
            previous_at = datetime.fromisoformat(str(previous_search.get('searched_at')).replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError, OverflowError):
            previous_at = None
        eligible.append((identity, row.get('status'), position, previous_at))
    if not eligible:
        return result
    with _refresh_lock:
        clock = time.monotonic()
        with _cache_lock:
            def order(item):
                identity, status, position, previous_at = item
                cached = _cache.get((identity, maximum))
                fresh = cached is not None and clock - cached[0] < CACHE_TTL
                if cached:
                    try:
                        cached_at = datetime.fromisoformat(str(cached[1].get('searched_at')).replace('Z', '+00:00')).timestamp()
                    except (ValueError, TypeError, OverflowError):
                        cached_at = time.time()
                    previous_at = max(previous_at or 0, cached_at)
                priority = {'no_match': 0, 'holdings_mismatch': 1, 'holdings_pending': 2, 'excluded': 3, 'insufficient': 4}[status]
                return previous_at is not None, previous_at or -1, fresh, priority, position
            selected = sorted(eligible, key=order)[:limit]
            ready, pending = {}, []
            for identity, _, _, _ in selected:
                cached = _cache.get((identity, maximum))
                if cached and not refresh and clock - cached[0] < CACHE_TTL:
                    item = deepcopy(cached[1])
                    item.update(cache_hit=True, attempted_this_run=False)
                    ready[identity] = item
                else:
                    pending.append(identity)
        if pending:
            with ThreadPoolExecutor(max_workers=min(MAX_BOARDS, len(pending))) as pool:
                futures = {pool.submit(_search_board, identity, maximum): identity for identity in pending}
                for future in as_completed(futures):
                    identity = futures[future]
                    try:
                        item = future.result()
                    except Exception as error:
                        item = {'board_id': identity, 'label': BOARDS[identity]['label'],
                                'query': f"{BOARDS[identity]['label']} 基金", 'status': 'error',
                                'attempted': False, 'attempted_this_run': False, 'success': False,
                                'searched_at': now_iso(), 'cache_hit': False, 'candidates': [],
                                'attempts': [], 'error': explain_error(error)}
                    ready[identity] = item
                    with _cache_lock:
                        _cache[(identity, maximum)] = (time.monotonic(), deepcopy(item))
        result['boards'] = [ready[identity] for identity, _, _, _ in selected]
    for board in result['boards']:
        result['sources'].extend(deepcopy(board['attempts']))
        if board.get('error'):
            result['warnings'].append(f"{board['label']}公开发现：{board['error']}")
    return result
