"""Discover a broad public fund universe before detailed, bounded research.

Coverage is the Eastmoney public catalog/ranking feed, never an asserted Alipay
sale list. Source types and returns are preliminary screening evidence; broker
availability, personal suitability and all redemption restrictions remain unverified.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import re
import threading
import time
import urllib.parse

from research_data import CHINA, clean_text, explain_error, fetch_text, now_iso, number
from research_categories import board_for, boards_for, BOARDS, catalog_synchronized
from research_selection import (_classify as classify_asset, _family as fund_family,
                                MAX_RESEARCH_PER_BOARD, MAX_DISPLAY_PER_BOARD)

CATALOG_URL = 'https://fund.eastmoney.com/js/fundcode_search.js'
RANK_PAGE_URL = 'https://fund.eastmoney.com/data/fundranking.html'
CATALOG_SOURCE_ID = 'universe:catalog'
RANK_SOURCE_ID = 'universe:ranking'
ALIPAY_PUBLIC_HOME = 'https://www.fund123.cn/'
PAGE_SIZE = 1000
MAX_PAGES = 60
CACHE_TTL = 900
_cache = None
_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()


def rank_url(page, page_size=PAGE_SIZE):
    today = datetime.now(CHINA).date()
    params = {'op': 'ph', 'dt': 'kf', 'ft': 'all', 'rs': '', 'gs': 0,
              'sc': '6yzf', 'st': 'desc', 'sd': (today - timedelta(days=365)).isoformat(),
              'ed': today.isoformat(), 'qdii': '', 'tabSubtype': ',,,,,',
              'pi': page, 'pn': page_size, 'dx': 1}
    return 'https://fund.eastmoney.com/data/rankhandler.aspx?' + urllib.parse.urlencode(params)


def parse_catalog(text):
    match = re.search(r'\bvar\s+r\s*=\s*', text)
    if not match:
        raise ValueError('基金目录字段已变化')
    values = json.JSONDecoder().raw_decode(text[match.end():])[0]
    if not isinstance(values, list):
        raise ValueError('基金目录不是列表')
    result = {}
    for item in values:
        if isinstance(item, list) and len(item) >= 4 and re.fullmatch(r'\d{6}', str(item[0])):
            result[item[0]] = {'code': item[0], 'name': clean_text(item[2], 160), 'fund_type': clean_text(item[3], 100)}
    if not result:
        raise ValueError('未取得基金目录')
    return result


def parse_rank_page(text):
    # The feed uses JS property names; decode only its JSON datas array.
    match = re.search(r'\bdatas\s*:\s*', text)
    if not match:
        raise ValueError('基金排行字段已变化')
    data = json.JSONDecoder().raw_decode(text[match.end():])[0]
    if not isinstance(data, list):
        raise ValueError('排行数据不是列表')
    metadata = {}
    for key in ('allRecords', 'pageIndex', 'pageNum', 'allPages'):
        field = re.search(r'\b' + key + r'\s*:\s*(\d+)', text)
        if not field:
            raise ValueError(f'排行缺少分页字段 {key}')
        metadata[key] = int(field.group(1))
    records, malformed = [], 0
    for value in data:
        if not isinstance(value, str):
            malformed += 1
            continue
        fields = value.split(',')
        if len(fields) < 18 or not re.fullmatch(r'\d{6}', fields[0]):
            malformed += 1
            continue
        nav_date = fields[3] if re.fullmatch(r'\d{4}-\d{2}-\d{2}', fields[3]) else None
        # Field offsets verified against operator's jskrank frontend table.
        row = {'code': fields[0], 'name': clean_text(fields[1], 160), 'nav_date': nav_date,
               'nav': number(fields[4]), 'return_1d': number(fields[6]), 'return_1w': number(fields[7]),
               'return_1m': number(fields[8]), 'return_3m': number(fields[9]), 'return_6m': number(fields[10]),
               'return_1y': number(fields[11]), 'inception_date': fields[16],
               'provider_purchase_flag': fields[17],
               'purchase_status': '平台交易状态待核验', 'alipay_available': 'unverified',
               'source_url': f'https://fund.eastmoney.com/{fields[0]}.html', 'source_id': RANK_SOURCE_ID,
               'redemption_terms': '未逐只核验完整赎回、限购及费用规则'}
        # Operator UI considers these flags buyable on its own site. This never
        # transfers to Alipay and even these flags can include purchase limits.
        row['provider_purchase_status'] = '来源平台显示可购买，限额待核验' if fields[17] in ('1', '2', '3', '8', '9') else '来源平台未显示可购买'
        records.append(row)
    return {'funds': records, 'malformed': malformed, **metadata}


def classify(row):
    name, fund_type = row.get('name', ''), row.get('fund_type', '')
    reasons = []
    if not fund_type:
        reasons.append('缺少基金类型')
    if re.search(r'封闭|定开|定期开放|持有|滚动|[一二三四五六七八九十两\d]+\s*(?:个)?月|[一二三四五六七八九十两\d]+年', name):
        reasons.append('名称含封闭、定开或持有期限，未证实适合 7 天起的流动性要求')
    day_match = re.search(r'(\d+)天', name)
    if day_match and int(day_match.group(1)) > 7:
        reasons.append('名称中的最短期限超过 7 天')
    if 'ETF' in name.upper() and '联接' not in name:
        reasons.append('场内 ETF，不能假定可在支付宝场外申购')
    # LOF is a listing structure, not evidence that an equity index share is
    # exchange-only. The public provider must still report a purchase channel;
    # this screening result never confirms Alipay availability or full terms.
    researchable_index_lof = fund_type == '指数型-股票' and bool(re.search(r'LOF', name, re.I))
    if re.search(r'REIT', name, re.I) or (re.search(r'LOF', name, re.I) and not researchable_index_lof):
        reasons.append('LOF/REIT 交易规则需单独核验')
    if re.search(r'后端|分级|场内|养老金|养老目标|养老.*FOF|专享|机构|Y$', name, re.I):
        reasons.append('特殊份额或账户/交易限制待核验')
    if row.get('provider_purchase_flag') not in ('1', '2', '3', '8', '9'):
        reasons.append('来源平台未显示可购买')
    try:
        age = (datetime.now(CHINA).date() - datetime.strptime(row['nav_date'], '%Y-%m-%d').date()).days
        if age < 0 or age > 7:
            reasons.append('净值日期异常或超过 7 个自然日')
    except (TypeError, ValueError):
        age = None
        reasons.append('净值日期缺失')
    if not any(row.get(k) is not None for k in ('return_1m', 'return_3m')):
        reasons.append('缺少中期收益数据')
    if '货币' in fund_type:
        bucket = 'defensive'
        group = '货币'
    elif ('债券' in fund_type or '固收' in fund_type) and not re.search(r'转债|混合二级', fund_type + name):
        bucket = 'defensive'
        group = '短债' if re.search(r'短债|超短|中短|短期', name + fund_type) else '债券'
    elif '债券' in fund_type or '固收' in fund_type:
        bucket, group = 'medium_high', '可转债或二级债'
    elif 'QDII' in fund_type.upper():
        bucket, group = 'medium_high', '海外'
    elif re.search(r'黄金|白银|商品', name + fund_type):
        bucket, group = 'medium_high', '黄金商品'
    elif '指数' in fund_type:
        bucket, group = 'medium_high', '指数'
    elif '股票' in fund_type:
        bucket, group = 'medium_high', '股票'
    elif '混合' in fund_type:
        bucket, group = 'medium_high', '混合'
    else:
        bucket, group = 'unsupported', '其他'
        reasons.append('此类产品尚无初筛规则')
    board = board_for(row, classify_asset(row, {})[0])
    return {'eligible': not reasons, 'exclusion_reasons': reasons, 'universe_bucket': bucket,
            'screen_group': group, 'nav_age_days': age,
            'board_id': board['id'], 'board_label': board['label'], 'board_group': board['group'],
            'classification_basis': board['classification_basis'],
            'risk_classification': '按基金类型粗分，非平台正式风险评级',
            'minimum_horizon_days': 7, 'holding_rule_verified': False}


def _collect():
    started = now_iso()
    sources, warnings = [], []
    catalog = {}
    first = None
    def fetch_catalog():
        return parse_catalog(fetch_text(CATALOG_URL))
    def fetch_first():
        return parse_rank_page(fetch_text(rank_url(1)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {'catalog': pool.submit(fetch_catalog), 'rank': pool.submit(fetch_first)}
        for name, future in jobs.items():
            try:
                if name == 'catalog':
                    catalog = future.result()
                    sources.append({'id': CATALOG_SOURCE_ID, 'name': '天天基金公开基金目录', 'url': CATALOG_URL, 'status': 'ok', 'count': len(catalog), 'as_of': None, 'fetched_at': now_iso()})
                else:
                    first = future.result()
            except Exception as error:
                warnings.append(f'{name}：{explain_error(error)}')
                sources.append({'id': CATALOG_SOURCE_ID if name == 'catalog' else RANK_SOURCE_ID, 'name': '公开基金目录' if name == 'catalog' else '公开基金排行', 'url': CATALOG_URL if name == 'catalog' else RANK_PAGE_URL, 'status': 'error', 'error': explain_error(error), 'as_of': None, 'fetched_at': now_iso()})
    pages, failed_pages, metadata_changes = {}, [], False
    expected_total = first['allRecords'] if first else 0
    expected_pages = first['allPages'] if first else 0
    if first:
        if first['pageIndex'] != 1:
            failed_pages.append(1)
        else:
            pages[1] = first
        count = min(expected_pages, MAX_PAGES)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(lambda page=page: parse_rank_page(fetch_text(rank_url(page)))): page for page in range(2, count + 1)}
            for future in as_completed(jobs):
                page = jobs[future]
                try:
                    payload = future.result()
                    if payload['pageIndex'] != page:
                        raise ValueError('响应页码不匹配')
                    if payload['allRecords'] != expected_total or payload['allPages'] != expected_pages:
                        metadata_changes = True
                    pages[page] = payload
                except Exception as error:
                    failed_pages.append(page)
                    warnings.append(f'基金排行第 {page} 页：{explain_error(error)}')
        if expected_pages > MAX_PAGES:
            warnings.append(f'排行超过本次最大分页数 {MAX_PAGES}，覆盖不完整')
    dedup, duplicate_count, malformed = {}, 0, 0
    for page in sorted(pages):
        malformed += pages[page]['malformed']
        for row in pages[page]['funds']:
            if row['code'] in dedup:
                duplicate_count += 1
                continue
            detail = catalog.get(row['code'], {})
            row['fund_type'] = detail.get('fund_type', '')
            row['catalog_name'] = detail.get('name')
            row.update(classify(row))
            dedup[row['code']] = row
    funds = list(dedup.values())
    complete = bool(first and catalog and len(pages) == expected_pages and not failed_pages and not metadata_changes and not malformed and not duplicate_count and len(funds) >= expected_total)
    eligible = [row for row in funds if row['eligible']]
    coverage = {'catalog_count': len(catalog), 'screened_count': len(funds), 'ranking_expected_count': expected_total,
                'eligible_count': len(eligible), 'medium_high_count': sum(row['universe_bucket'] == 'medium_high' for row in eligible),
                'defensive_count': sum(row['universe_bucket'] == 'defensive' for row in eligible),
                'complete': complete, 'complete_scope': '来源公开排行分页覆盖完整，不等于支付宝全部在售基金覆盖',
                'catalog_without_ranking_count': len(set(catalog) - set(dedup)), 'missing_type_count': sum(not row['fund_type'] for row in funds),
                'failed_pages': sorted(failed_pages), 'pages_loaded': len(pages), 'pages_expected': expected_pages,
                'duplicate_count': duplicate_count, 'malformed_count': malformed, 'metadata_changed': metadata_changes,
                'stale_count': sum(row['nav_age_days'] is None or not 0 <= row['nav_age_days'] <= 7 for row in funds),
                'alipay_verified_count': 0, 'alipay_total_count': None, 'alipay_complete': False}
    if first:
        dates = [row['nav_date'] for row in funds if row['nav_date']]
        sources.append({'id': RANK_SOURCE_ID, 'name': '天天基金公开开放式基金排行', 'url': RANK_PAGE_URL,
                        'status': 'ok' if complete else 'partial', 'count': len(funds), 'as_of': max(dates) if dates else None,
                        'fetched_at': now_iso(), 'error': '' if complete else '分页缺失、去重/字段异常或目录不可用，覆盖不完整'})
    sources.append({'id': 'universe:alipay', 'name': '支付宝在售范围核验', 'url': ALIPAY_PUBLIC_HOME,
                    'status': 'partial', 'count': 0, 'as_of': None,
                    'error': '未取得可验证的支付宝完整在售基金清单；公开目录不能证明支付宝可买'})
    warnings.extend([
        '研究范围为公开基金目录与排行，支付宝是否在售、限购及实际交易费率均未逐只验证。',
        '初筛剔除名称可识别的封闭/持有期、场内 ETF、LOF 等；名称不含限制不代表已核验全部赎回条款。',
        '7 天是研究持有期限下限，不代表 7 天后保本或免赎回费；中高风险基金仍可能显著回撤。',
        '广泛初筛依据 1 周、1 月、3 月等已披露收益，之后仅对分散候选进行完整净值、新闻和公告研究。',
    ])
    return {'as_of': started, 'funds': funds, 'sources': sources, 'warnings': warnings, 'coverage': coverage, 'cache_hit': False,
            'selection_method': '类别内中期收益分位排序；板块轮询优先上轮有合法样本但未深研的方向，未形成结论时优先其他未尝试份额家族；披露持仓复核归类后，每板块最多深研3只，缺少替代时复核原样本。'}


def collect_universe(refresh=False):
    global _cache
    with _cache_lock:
        if _cache and not refresh and time.monotonic() - _cache[0] < CACHE_TTL:
            result = deepcopy(_cache[1])
            result['cache_hit'] = True
            return result
    # Simultaneous initial clients share the refresh rather than multiplying requests.
    with _refresh_lock:
        with _cache_lock:
            if _cache and not refresh and time.monotonic() - _cache[0] < CACHE_TTL:
                result = deepcopy(_cache[1]); result['cache_hit'] = True
                return result
        result = _collect()
        with _cache_lock:
            _cache = (time.monotonic(), deepcopy(result))
        return result


def _theme(row, as_of=None):
    return board_for(row, classify_asset(row, {})[0], as_of=as_of)['id']


def _family(row):
    return fund_family(row)


def pick_holdings_preflight_codes(universe, limit=96, preferred_codes=None):
    """A separate, bounded discovery queue for portfolios still missing evidence.

    Repeatedly collecting the same already-proven portfolios must not consume
    the opportunity to inspect unseen funds. Recent failures/partial responses
    wait for the 12-hour source cache to expire; their check time is persisted
    by the caller's holdings index. Discovery hints never assign a board.
    """
    limit = max(0, min(int(limit), 96))
    if not limit:
        return []
    try:
        now = datetime.fromisoformat(str(universe.get('as_of')).replace('Z', '+00:00'))
        if now.tzinfo is None:
            now = now.replace(tzinfo=CHINA)
    except (ValueError, TypeError):
        now = datetime.now(CHINA)
    preferred = {code: position for position, code in enumerate(preferred_codes or []) if isinstance(code, str)}
    queues = {}
    for row in universe.get('funds', []):
        if (not isinstance(row, dict) or not row.get('eligible')
                or row.get('universe_bucket') != 'medium_high'
                or not re.fullmatch(r'\d{6}', str(row.get('code', '')))):
            continue
        asset_id = classify_asset(row, {})[0]
        if asset_id in {'money', 'short_bond', 'bond', 'secondary_bond',
                        'convertible_bond', 'overseas_bond', 'gold', 'commodities'}:
            continue
        holdings = row.get('holdings') if isinstance(row.get('holdings'), dict) else {}
        checked = row.get('holdings_checked_at') or holdings.get('fetched_at')
        try:
            checked_time = datetime.fromisoformat(str(checked).replace('Z', '+00:00'))
            if checked_time.tzinfo is None:
                checked_time = checked_time.replace(tzinfo=CHINA)
            check_age = (now - checked_time).total_seconds()
        except (ValueError, TypeError):
            check_age = None
        try:
            report_age = (now.date() - datetime.fromisoformat(str(holdings.get('report_date'))[:10]).date()).days
            valid_period = 0 <= report_age <= 180
        except (ValueError, TypeError):
            valid_period = False
        current = holdings.get('status') == 'ok' and valid_period and isinstance(holdings.get('rows'), list) and bool(holdings['rows'])
        if check_age is not None and 0 <= check_age < 12 * 3600:
            continue
        # A valid portfolio without an explicit collection timestamp is useful
        # evidence, rather than a reason to repeatedly spend network requests.
        complete = (current and not holdings.get('invalid_row_count')
                    and all(isinstance(stock, dict) and stock.get('instrument_type') == 'stock'
                            and stock.get('tag_status') == 'ok' and stock.get('tags')
                            for stock in holdings['rows']))
        if complete and check_age is None:
            continue
        unseen = check_age is None
        identity = row.get('screen_group') or str(row.get('fund_type') or 'unknown')
        # Spread unseen samples across codes instead of concentrating the queue
        # in the same high-return theme. No product title enters this ordering.
        stable_spread = (int(row['code']) * 2654435761) % 4294967296
        key = (row['code'] not in preferred, preferred.get(row['code'], 10**6),
               not unseen, not (holdings and not valid_period),
               str(checked or ''), stable_spread, row['code'])
        queues.setdefault(identity, []).append((key, row))
    for rows in queues.values():
        rows.sort(key=lambda item: item[0])
    keys = sorted(queues, key=lambda identity: queues[identity][0][0])
    selected, families = [], set()
    while len(selected) < limit:
        changed = False
        for identity in keys:
            rows = queues[identity]
            while rows:
                _, row = rows.pop(0)
                family = _family(row)
                if family in families:
                    continue
                selected.append(row['code'])
                families.add(family)
                changed = True
                break
            if len(selected) >= limit:
                break
        if not changed:
            break
    return selected


def cap_research_codes(codes, funds, as_of=None):
    """Cap each board, preserving candidates from an explicit source list."""
    return plan_research_codes(codes, funds, as_of)['selected_codes']


@catalog_synchronized
def plan_research_codes(codes, funds, as_of=None, limit=96):
    """Allocate at most three targets, with user-selected candidates first."""
    limit = max(0, min(int(limit), 96))
    by_code = {fund.get('code'): fund for fund in funds if isinstance(fund, dict) and fund.get('code')}
    selected, seen, queues, targets, local_families = [], set(), {}, {}, {}
    for position, code in enumerate(dict.fromkeys(codes)):
        if code not in by_code:
            continue
        fund = by_code[code]
        boards = boards_for(fund, classify_asset(fund, {})[0], as_of=as_of)
        for board in boards:
            ratio = board.get('board_match', {}).get('matched_disclosed_pct', -1)
            if not isinstance(ratio, (int, float)) or not math.isfinite(ratio):
                ratio = -1
            reference = fund.get('reference_candidate')
            reference_first = (isinstance(reference, dict)
                               and reference.get('source_kind') in ('user_reference', 'yangjibao')
                               and reference.get('requested_board_id') == board['id'])
            queues.setdefault(board['id'], []).append((0 if reference_first else 1, -ratio, position, code))
    for queue in queues.values():
        queue.sort()
    positions = {identity: index for index, identity in enumerate(BOARDS)}
    identities = sorted(queues, key=lambda key: (key == 'holdings_unclassified', positions[key]))
    for _ in range(MAX_RESEARCH_PER_BOARD):
        for identity in identities:
            queue = queues[identity]
            while queue:
                _, _, _, code = queue.pop(0)
                family = _family(by_code[code])
                if family in local_families.get(identity, set()):
                    continue
                if code not in seen:
                    if len(selected) >= limit:
                        break
                    selected.append(code)
                    seen.add(code)
                targets.setdefault(identity, []).append(code)
                local_families.setdefault(identity, set()).add(family)
                break
    return {'selected_codes': selected, 'board_targets': targets}


def pick_research_codes(universe, limit=96, previous_coverage=None, preferred_codes=None):
    """Choose by known holdings; explore missing portfolios without name themes.

    This is a bounded portfolio preflight queue, not the final deep-research
    allocation. The post-disclosure cap is applied before NAV/AI research.
    """
    limit = max(1, min(int(limit), 96))
    eligible = [row for row in universe.get('funds', []) if row.get('eligible')
                and row.get('universe_bucket') in ('medium_high', 'defensive')]
    preferred = set(preferred_codes or [])
    previous = {row['id']: row for row in previous_coverage if isinstance(row, dict)
                and isinstance(row.get('id'), str) and row['id'] in BOARDS} if isinstance(previous_coverage, list) else {}
    attempted = set()
    by_code = {row['code']: row for row in eligible}
    for prior in previous.values():
        if prior.get('status') not in ('holdings_pending', 'holdings_mismatch', 'insufficient'):
            continue
        gap = prior.get('research_gap')
        for example in gap.get('examples', []) if isinstance(gap, dict) and isinstance(gap.get('examples'), list) else []:
            code = example.get('code') if isinstance(example, dict) else None
            if isinstance(code, str) and code in by_code:
                attempted.add(_family(by_code[code]))
    groups = {}
    for row in eligible:
        groups.setdefault(row.get('screen_group', 'unknown'), []).append(row)
    scores = {}
    for rows in groups.values():
        accum = {row['code']: [0., 0.] for row in rows}
        for field, weight in [('return_1w', .2), ('return_1m', .4), ('return_3m', .4)]:
            ranked = sorted([row for row in rows if number(row.get(field)) is not None], key=lambda row: row[field])
            for position, row in enumerate(ranked):
                accum[row['code']][0] += position / max(1, len(ranked) - 1) * weight
                accum[row['code']][1] += weight
        for code, (score, used) in accum.items():
            scores[code] = score / used if used else -1
    buckets = {}
    for row in eligible:
        board = board_for(row, classify_asset(row, {})[0], as_of=universe.get('as_of'))
        identity = board['id']
        # Unknown holdings rotate across source asset types; titles do not
        # narrow the exploratory pool or exclude active diversified products.
        key = 'explore:' + str(row.get('screen_group', 'unknown')) if identity == 'holdings_unclassified' else identity
        buckets.setdefault(key, []).append(row)
    def rank(row):
        board = board_for(row, classify_asset(row, {})[0], as_of=universe.get('as_of'))
        missing = not previous.get(board['id'], {}).get('displayed_count')
        ratio = board.get('board_match', {}).get('matched_disclosed_pct', -1)
        return (not missing, -ratio, _family(row) in attempted, row['code'] not in preferred, str(row.get('holdings_checked_at') or ''),
                -scores[row['code']], row['code'])
    for rows in buckets.values():
        rows.sort(key=rank)
    positions = {identity: i for i, identity in enumerate(BOARDS)}
    def researched(identity):
        count = previous.get(identity, {}).get('deep_count')
        return isinstance(count, (int, float)) and not isinstance(count, bool) and math.isfinite(count) and count > 0
    visited = [positions[key] for key in previous if researched(key)]
    cursor = (max(visited) + 1) % len(positions) if visited else 0
    keys = sorted(buckets, key=lambda key: (not any(r['universe_bucket'] == 'defensive' for r in buckets[key]),
                                             key.startswith('explore:'), researched(key), bool(previous.get(key, {}).get('displayed_count')),
                                             (positions.get(key, 0) - cursor) % len(positions), key))
    selected, families, counts = [], set(), {}
    while len(selected) < limit:
        changed = False
        for key in keys:
            # Reserve exploration space even when already known sectors can
            # provide many alternatives. Final deep limits remain separate.
            if not key.startswith('explore:') and counts.get(key, 0) >= MAX_RESEARCH_PER_BOARD:
                continue
            rows = buckets[key]
            while rows:
                row = rows.pop(0)
                if _family(row) in families:
                    continue
                selected.append(row['code'])
                families.add(_family(row))
                counts[key] = counts.get(key, 0) + 1
                changed = True
                break
            if len(selected) >= limit:
                break
        if not changed:
            break
    return selected
