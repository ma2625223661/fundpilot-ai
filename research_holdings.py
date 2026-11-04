"""Published stock holdings and explicit provider theme membership, never live positions.

The fund disclosure and the securities classification are separate observations.
Only known, matched stock rows contribute to a conservative exposure test.
"""
import copy
import gzip
import html
import io
import json
import math
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from research_etf_evidence import fetch_holdings_evidence
from research_market_membership import (INDEX_CONFIG, MAX_MAPPING_AGE_DAYS,
    fetch_membership_context, membership_for_security)

CHINA = timezone(timedelta(hours=8))
TIMEOUT = 5
MAX_BYTES = 2_000_000
CACHE_TTL = 12 * 3600
MAX_DISCLOSURE_AGE_DAYS = 180
MIN_MATCH_DISCLOSED_PCT = 50
HOLDINGS_RULE_VERSION = 'single_board_holdings_rank_v4'
_cache = {}
_cache_lock = threading.Lock()
_security_locks = {}
_network_slots = threading.BoundedSemaphore(8)

# Exact provider tags; broad tags never stand in for a narrower concept.
# Provider's industry/concept directories: https://data.eastmoney.com/rzrq/hy.html
# and https://data.eastmoney.com/center/ . Membership still must be returned by
# the issuer-matched security endpoint; a directory label alone is no evidence.
BOARD_TAGS = {
    'sector_liquor': {'白酒', '白酒Ⅱ'},
    'sector_cxo': {'CRO', 'CXO', '创新药服务', '医药外包'},
    'sector_food_beverage': {'食品饮料', '食品加工', '饮料乳品', '白酒', '白酒Ⅱ', '非白酒'},
    'sector_medical': {'医疗服务', '医疗器械', '医疗美容'},
    'sector_healthcare': {'化学制药', '中药', '生物制品', '医药商业'},
    'sector_innovative_drug': {'创新药'},
    'sector_oil_gas': {'石油石化', '油气开采', '油服工程', '油气设服', '石油行业', '石油天然气'},
    'sector_consumer': {'食品饮料', '食品加工', '饮料乳品', '白酒', '白酒Ⅱ', '非白酒', '家用电器', '商贸零售', '纺织服饰', '社会服务', '美容护理', '家电行业'},
    'sector_transport': {'交通运输', '物流', '航运港口', '航空机场', '铁路公路', '航运', '航空运输'},
    'sector_consumer_electronics': {'消费电子'},
    'sector_gold_equity': {'黄金', '黄金概念'},
    'sector_compute_leasing': {'算力租赁'},
    'sector_nuclear_fusion': {'可控核聚变', '核聚变'},
    'sector_cloud_computing': {'云计算', '云计算概念'},
    'sector_semiconductor': {'半导体'},
    'sector_domestic_computing': {'国产算力', '自主可控算力'},
    'sector_ai': {'人工智能'},
    'sector_semiconductor_equipment': {'半导体设备', '半导体材料', '半导体材料设备'},
    'sector_communication': {'通信', '通信设备', '通信服务'},
    'sector_pcb': {'PCB', 'PCB概念', '印制电路板'},
    'sector_ai_application': {'AI应用', '人工智能应用'},
    'sector_media': {'传媒', '游戏', '影视院线', '广告营销', '出版', '文化传媒', '互联网服务'},
    'sector_fintech': {'金融科技', '互联网金融', '数字金融'},
    'sector_cpo': {'CPO', 'CPO概念'},
    'sector_robotics': {'机器人', '机器人概念'},
    'sector_technology': {'计算机', '电子', '通信', '软件开发', 'IT服务', '半导体', '消费电子'},
    'sector_renewable': {'新能源', '光伏设备', '风电设备', '电池', '新能源车', '储能'},
    'sector_defense': {'国防军工', '军工', '军工电子', '航空装备', '航天装备'},
    'sector_real_estate': {'房地产', '房地产开发', '房地产服务'},
    'sector_infrastructure': {'建筑装饰', '建筑材料', '基础建设', '工程建设'},
    'sector_agriculture': {'农林牧渔', '农业种植', '养殖业', '农牧饲渔'},
    'sector_environment': {'环保', '环境治理', '环保行业'},
    'sector_utilities': {'公用事业', '电力', '燃气', '水务'},
    'sector_travel': {'旅游及景区', '酒店餐饮', '旅游酒店'},
    'sector_automotive': {'汽车', '汽车零部件', '乘用车', '商用车'},
    'sector_manufacturing': {'机械设备', '通用设备', '专用设备', '自动化设备'},
    'sector_chemicals': {'基础化工', '化学原料', '化学制品', '化学纤维'},
    'sector_resources': {'有色金属', '煤炭', '钢铁', '石油石化', '工业金属', '能源金属', '小金属'},
    'sector_banking': {'银行', '国有大型银行', '股份制银行', '城商行', '农商行'},
    'sector_securities': {'证券', '证券Ⅱ'},
    'sector_insurance': {'保险', '保险Ⅱ'},
    'sector_nonbank': {'非银金融', '证券', '证券Ⅱ', '保险', '保险Ⅱ', '多元金融'},
    'sector_finance': {'银行', '非银金融', '证券', '证券Ⅱ', '保险', '保险Ⅱ', '多元金融'},
    'sector_diversified_finance': {'多元金融'},
    'sector_financial_real_estate': {'银行', '非银金融', '证券', '保险', '多元金融', '房地产', '房地产开发'},
    'sector_brain_computer': {'脑机接口'},
    'sector_home_appliances': {'家用电器', '家电行业', '白色家电', '黑色家电', '厨卫电器', '小家电', '其他家电Ⅱ', '家电零部件Ⅱ'},
    'sector_coal': {'煤炭', '煤炭行业', '煤炭开采', '焦煤', '动力煤', '焦炭Ⅱ'},
    'sector_eldercare': {'养老产业', '养老服务', '养老概念', '银发经济'},
    'sector_lithium_mining': {'锂矿', '锂矿概念'},
    'sector_solid_state_battery': {'固态电池'},
    'sector_steel': {'钢铁', '钢铁行业', '普钢', '特钢Ⅱ', '冶钢原料'},
    'sector_rare_earth_magnet': {'稀土永磁'},
    'sector_nonferrous': {'有色金属', '有色金属行业', '工业金属', '能源金属', '小金属', '小金属概念', '贵金属', '金属新材料'},
    'sector_auto_vehicle': {'汽车整车', '乘用车', '商用车'},
    'sector_power': {'电力', '电力行业', '绿色电力'},
    'sector_energy_storage': {'储能', '储能概念'},
    'sector_photovoltaic': {'光伏', '光伏概念', '光伏设备'},
    'sector_construction_machinery': {'工程机械', '工程机械概念'},
    'sector_grid_equipment': {'电网设备'},
    'sector_commercial_aerospace': {'商业航天'},
    'sector_advanced_manufacturing': {'先进制造', '先进制造风格'},
    'sector_memory_chip': {'存储芯片'},
    'sector_mlcc': {'MLCC'},
}


def _clean(value, limit=300):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()[:limit]


def _fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 FundPilotLocalResearch/1.0',
        'Referer': 'https://fundf10.eastmoney.com/', 'Accept': 'application/json,text/html,*/*', 'Accept-Encoding': 'identity'})
    with _network_slots, urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('持仓数据响应超过限制')
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('持仓数据响应超过限制')
    return raw.decode('utf-8-sig')


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_holdings(text, code):
    """Decode only the provider's quoted HTML string, then parse newest table."""
    marker = re.search(r'\bcontent\s*:\s*', text)
    if not marker:
        raise ValueError('持仓来源结构变化')
    content = json.JSONDecoder().raw_decode(text[marker.end():])[0]
    if not isinstance(content, str):
        raise ValueError('持仓来源结构变化')
    parts = re.findall(r'(<h4\b[^>]*>.*?</h4>)\s*.*?(<table\b[^>]*>.*?</table>)', content, re.S | re.I)
    tables = []
    for heading, table in parts:
        identity = re.search(r'fund\.eastmoney\.com/(\d{6})\.html', heading)
        timestamp = re.search(r'20\d{2}-\d{2}-\d{2}', heading)
        if not identity or identity.group(1) != code or not timestamp:
            continue
        report_date = _day(timestamp.group()).isoformat()
        headers = [_clean(cell) for cell in re.findall(r'<th\b[^>]*>(.*?)</th>', table, re.S | re.I)]
        weight_index = next((index for index, label in enumerate(headers) if '占净值' in label and '比例' in label), None)
        # Only this provider's explicit stock disclosure can establish that a
        # security row is a stock. Generic asset tables must not acquire that
        # identity merely because their names do not contain "ETF".
        if weight_index is None or len(headers) < 3 or '股票代码' not in headers[1] or '股票名称' not in headers[2]:
            continue
        rows, seen, invalid_rows = [], set(), 0
        for raw in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S | re.I):
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', raw, re.S | re.I)
            if len(cells) <= weight_index or len(cells) < 3:
                if len(cells) >= 3:
                    invalid_rows += 1
                continue
            stock_code, name = _clean(cells[1]), _clean(cells[2])
            weight_text = _clean(cells[weight_index])
            if not re.fullmatch(r'\d{5,6}|[A-Z][A-Z0-9.\-]{0,11}', stock_code) or stock_code in seen:
                invalid_rows += 1
                continue
            if not re.fullmatch(r'\d+(?:\.\d+)?%', weight_text):
                invalid_rows += 1
                continue
            weight = float(weight_text[:-1])
            if not name or not 0 < weight <= 100:
                invalid_rows += 1
                continue
            seen.add(stock_code)
            instrument_type = ('fund' if re.search(r'ETF|基金|信托|REIT', name, re.I) else
                               'bond' if re.search(r'债券|转债|国债|国开债', name) else 'stock')
            rows.append({'code': stock_code, 'name': name, 'weight_pct': weight,
                         'instrument_type': instrument_type})
        if rows:
            if sum(row['weight_pct'] for row in rows) > 101:
                raise ValueError('披露持仓比例异常')
            tables.append((report_date, rows[:10], invalid_rows))
    if not tables:
        raise ValueError('未取得有日期及权重的股票持仓；ETF联接或非股票资产不作穿透假设')
    report_date, rows, invalid_rows = max(tables, key=lambda item: item[0])
    return {'status': 'ok', 'report_date': report_date, 'rows': rows,
            'invalid_row_count': invalid_rows,
            'disclosed_weight_pct': float(sum((Decimal(str(row['weight_pct'])) for row in rows
                                               if row['instrument_type'] == 'stock'), Decimal(0))),
            'scope': '公开定期报告前十大股票持仓，占基金净值比例；不是完整资产配置或实时仓位',
            'source_id': 'holdings:' + code, 'source_url': f'https://fundf10.eastmoney.com/ccmx_{code}.html',
            'provider': '天天基金披露持仓', 'error': ''}


def _security_symbol(code):
    if re.fullmatch(r'6\d{5}', code):
        return 'SH' + code
    if re.fullmatch(r'(?:00[0-3]|30[01])\d{3}', code):
        return 'SZ' + code
    return None


def parse_security_tags(data, code):
    if not isinstance(data, dict) or not isinstance(data.get('ssbk'), list):
        raise ValueError('股票板块资料结构变化')
    tags = []
    for row in data['ssbk']:
        if not isinstance(row, dict) or str(row.get('SECURITY_CODE')) != code:
            raise ValueError('股票身份与板块响应不一致')
        tag = _clean(row.get('BOARD_NAME'), 80)
        if tag and tag not in tags:
            tags.append(tag)
    if not tags:
        raise ValueError('股票没有可核验的板块资料')
    return tags[:120]


def fetch_security_tags(code, refresh=False):
    symbol = _security_symbol(code)
    if not symbol:
        return {'tag_status': 'unknown', 'tags': [], 'tag_reason': '未接入该市场或证券类型的可核验板块资料'}
    key = ('security', code)
    with _cache_lock:
        lock = _security_locks.setdefault(code, threading.Lock())
    with lock:
        with _cache_lock:
            cached = _cache.get(key)
            if cached and not refresh and time.monotonic() - cached[0] < CACHE_TTL:
                return copy.deepcopy(cached[1])
        url = 'https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=' + symbol
        try:
            tags = parse_security_tags(json.loads(_fetch(url)), code)
            result = {'tag_status': 'ok', 'tags': tags, 'tag_source_url': url,
                      'tag_fetched_at': datetime.now(CHINA).isoformat(timespec='seconds'),
                      'tag_scope': '东方财富当前行业/概念标签；非指数官方成份资格，不能证明概念业务收入占比'}
            result['tag_evidence'] = [{'kind': 'industry_and_concept', 'security_code': code,
                'tags': list(tags), 'source_url': url, 'observed_at': result['tag_fetched_at'],
                'scope': result['tag_scope']}]
        except Exception:
            result = {'tag_status': 'unknown', 'tags': [], 'tag_source_url': url,
                      'tag_reason': '股票板块资料未取得或身份校验未通过'}
        with _cache_lock:
            _cache[key] = (time.monotonic(), copy.deepcopy(result))
        return result


def fetch_holdings(code, refresh=False):
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        raise ValueError('基金代码必须为六位数字')
    key = ('fund', code)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < CACHE_TTL:
            return copy.deepcopy(cached[1])
    url = f'https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10&year=&month='
    try:
        result = fetch_holdings_evidence(code, refresh=refresh, fetcher=_fetch,
                                         security_classifier=fetch_security_tags)
    except Exception:
        result = parse_holdings(_fetch(url), code)
        result['fetched_at'] = datetime.now(CHINA).isoformat(timespec='seconds')
        for row in result['rows']:
            if row['instrument_type'] == 'stock':
                row.update(fetch_security_tags(row['code'], refresh=refresh))
            else:
                row.update(tag_status='unknown', tags=[], tag_reason='未取得同报告期实际ETF投资权重及目标股票，不把ETF当成行业股票')
    with _cache_lock:
        _cache[key] = (time.monotonic(), copy.deepcopy(result))
        if len(_cache) > 3000:
            oldest = sorted(_cache, key=lambda item: _cache[item][0])[:500]
            for item in oldest:
                del _cache[item]
    return result


def collect_holdings(snapshot, refresh=False, progress=None, preflight=False):
    """Attach up to 96 published portfolios with eight bounded collection workers.

    ``preflight`` is used before full NAV research: a public ranking row may
    qualify from its own recent, positive NAV and NAV date when no history was
    collected yet. It never creates or backfills a ``history`` field. The
    default path retains the stricter existing history requirement.
    """
    result = copy.deepcopy(snapshot)

    def eligible(fund):
        if not isinstance(fund, dict) or not re.fullmatch(r'\d{6}', str(fund.get('code', ''))):
            return False
        # Missing product type is normal for the manual NAV feed. Only explicit
        # non-stock types skip this stock-only collector.
        if re.search(r'货币|纯债|短债', str(fund.get('fund_type') or '')):
            return False
        history = fund.get('history')
        if isinstance(history, list) and history:
            for row in history:
                if not isinstance(row, dict):
                    continue
                nav = row.get('nav')
                if isinstance(nav, bool) or not isinstance(nav, (int, float)) or not math.isfinite(nav) or nav <= 0:
                    continue
                try:
                    if _day(row.get('date')) <= datetime.now(CHINA).date():
                        return True
                except (ValueError, TypeError):
                    continue
            return False
        if not preflight:
            return False
        # Ranking rows are allowed only when both fields are real finite
        # values, the date is not future, and it is no more than seven days old.
        nav = fund.get('nav')
        if isinstance(nav, bool) or not isinstance(nav, (int, float)) or not math.isfinite(nav) or nav <= 0:
            return False
        try:
            age = (datetime.now(CHINA).date() - _day(fund.get('nav_date'))).days
        except (ValueError, TypeError):
            return False
        return 0 <= age <= 7

    rows = {fund['code']: fund for fund in result.get('funds', [])
            if eligible(fund)}
    codes = list(rows)[:96]
    notify = progress or (lambda stage, details=None: None)
    notify('正在核验基金披露持仓与板块匹配', {'holdings_done': 0, 'holdings_total': len(codes)})
    result.setdefault('sources', [])
    result.setdefault('warnings', [])
    # Fetch public membership once for this collection, never from verify_board.
    # Stock holdings remain useful if an official membership source is offline.
    membership_context = {}
    if codes:
        try:
            membership_context = fetch_membership_context(refresh=refresh)
        except Exception:
            membership_context = {}
        for key, entry in membership_context.get('indices', {}).items():
            if not isinstance(entry, dict) or entry.get('status') != 'ok':
                continue
            result['sources'].append({'id': 'membership:' + key, 'name': entry.get('index_name', key),
                'url': entry.get('source_url', ''), 'fetched_at': entry.get('fetched_at'),
                'as_of': entry.get('source_date'), 'status': 'ok', 'count': len(entry.get('members', {})),
                'scope': entry.get('mapping_scope', '') + '；' + entry.get('list_scope', '')})
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix='fundpilot-holdings') as pool:
        tasks = {pool.submit(fetch_holdings, code, refresh): code for code in codes}
        for done, task in enumerate(as_completed(tasks), 1):
            code = tasks[task]
            source = {'id': 'holdings:' + code, 'name': f'基金 {code} 披露股票持仓',
                      'url': f'https://fundf10.eastmoney.com/ccmx_{code}.html',
                      'fetched_at': datetime.now(CHINA).isoformat(timespec='seconds'),
                      'as_of': None, 'status': 'error', 'count': 0}
            try:
                holdings = copy.deepcopy(task.result())
                for row in holdings.get('rows', []):
                    if isinstance(row, dict) and row.get('instrument_type') == 'stock':
                        membership = compact_membership_evidence(membership_for_security(row.get('code'), membership_context))
                        if membership:
                            row['market_membership'] = membership
                        else:
                            row.pop('market_membership', None)
                rows[code]['holdings'] = holdings
                source.update(status='ok', as_of=holdings['report_date'], count=len(holdings['rows']),
                              url=holdings.get('source_url', source['url']))
                known = sum(row.get('tag_status') == 'ok' for row in holdings['rows'])
                if known != len(holdings['rows']):
                    source.update(status='partial', error=f'{len(holdings["rows"]) - known} 只披露证券未取得可核验板块资料，不作主题归属假设')
                source['scope'] = holdings['scope']
            except Exception:
                # Do not expose remote response bodies, paths or arbitrary errors.
                rows[code]['holdings'] = {'status': 'error', 'report_date': None, 'rows': [],
                    'source_id': source['id'], 'source_url': source['url'],
                    'error': '未取得有效股票披露或同报告期实际ETF穿透证据，继续补采；不按基金名称推断持仓'}
                source['error'] = rows[code]['holdings']['error']
            rows[code]['holdings_checked_at'] = datetime.now(CHINA).isoformat(timespec='seconds')
            result['sources'].append(source)
            notify(f'正在核验披露持仓 {done} / {len(codes)}', {'holdings_done': done, 'holdings_total': len(codes)})
    result['warnings'].append('板块匹配使用有日期的股票披露；ETF联接仅在同报告期实际投资权重可核验时穿透。行业/概念标签与最新官方成分分别保留来源和日期；仅代表披露股票部分，不代表完整或实时仓位。')
    return result


def compact_membership_evidence(context):
    """Retain confirmed membership facts; absence from a partial list stays unknown."""
    if not isinstance(context, dict):
        return None
    memberships = {}
    for board, entry in context.get('memberships', {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get('sources'), list):
            continue
        sources = [copy.deepcopy(source) for source in entry['sources']
                   if isinstance(source, dict) and (source.get('matched') is True
                       or (source.get('matched') is False and source.get('complete') is True))]
        if sources:
            memberships[board] = {'sources': sources}
    if not memberships:
        return None
    return {'code': str(context.get('code')), 'region': context.get('region', ''),
            'memberships': memberships}


def supported_board_ids():
    """Directions with a stock-level verification rule, including dynamic industries."""
    return set(BOARD_TAGS) | {board for config in INDEX_CONFIG.values() for board in config['boards']}


def holdings_row_limit(holdings):
    """Accept twenty rows only for fully documented, same-period ETF look-through."""
    evidence = holdings.get('lookthrough') if isinstance(holdings, dict) else None
    if not isinstance(evidence, dict):
        return 10
    code, article = str(evidence.get('target_code', '')), str(evidence.get('article_id', ''))
    weight, value = evidence.get('target_weight_pct'), evidence.get('market_value')
    period = holdings.get('report_date')
    if (evidence.get('row_limit') != 20 or not re.fullmatch(r'\d{6}', code)
            or not re.fullmatch(r'AN\d{10,30}', article)
            or any(isinstance(number, bool) or not isinstance(number, (int, float))
                   or not math.isfinite(number) or number <= 0 for number in (weight, value))
            or weight > 100 or evidence.get('report_date') != period
            or evidence.get('target_stock_report_date') != period
            or not re.fullmatch(r'https://fund\.eastmoney\.com/gonggao/\d{6},' + article + r'\.html',
                                str(evidence.get('source_url', '')))
            or evidence.get('content_source_url') != ('https://np-cnotice-stock.eastmoney.com/api/content/ann'
                '?client_source=web&show_all=1&art_code=' + article)
            or evidence.get('target_stock_source_url') != ('https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition'
                f'?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0')
            or evidence.get('method') != '原基金实际ETF权重×目标ETF披露股票占净值权重÷100'):
        return 10
    return 20


def _official_match(row, board_id, as_of):
    """Consume attached official evidence only; membership lookups never network here."""
    context = row.get('market_membership')
    if not isinstance(context, dict) or str(context.get('code')) != str(row.get('code')):
        return None, []
    entry = context.get('memberships', {}).get(board_id)
    if not isinstance(entry, dict) or not isinstance(entry.get('sources'), list):
        return None, []
    allowed = {config['index_code'] for config in INDEX_CONFIG.values() if board_id in config['boards']}
    sources = []
    for source in entry['sources']:
        if not isinstance(source, dict) or source.get('index_code') not in allowed:
            continue
        if not str(source.get('source_url', '')).startswith('https://www.hsi.com.hk/'):
            continue
        try:
            age = (_day(as_of) if as_of is not None else datetime.now(CHINA).date()) - _day(source.get('source_date'))
            if not 0 <= age.days <= MAX_MAPPING_AGE_DAYS:
                continue
        except (ValueError, TypeError):
            continue
        matched = source.get('matched')
        if matched is not True and not (matched is False and source.get('complete') is True):
            # Positive-only official top ten can never establish non-membership.
            continue
        sources.append(copy.deepcopy(source))
    if any(source['matched'] is True for source in sources):
        return True, sources
    # Preserve unknown sources: one complete list absent is insufficient if a
    # second configured index is partial or unavailable for a combined board.
    expected = len([config for config in INDEX_CONFIG.values() if board_id in config['boards']])
    if sources and len({source['index_code'] for source in sources}) == expected and all(source['matched'] is False for source in sources):
        return False, sources
    return None, sources


def _stock_tags(row):
    tags = row.get('tags')
    valid = (row.get('tag_status') == 'ok' and isinstance(tags, list) and bool(tags)
             and all(isinstance(tag, str) and tag for tag in tags))
    result = set(tags[:120]) if valid else set()
    industries = row.get('industry_tags')
    # Industry fields retain their own provenance even when a concept endpoint
    # fails. Only code-bound public position rows can establish this evidence.
    if isinstance(industries, list) and all(isinstance(tag, str) and tag for tag in industries):
        for item in row.get('tag_evidence', []) if isinstance(row.get('tag_evidence'), list) else []:
            if (isinstance(item, dict) and item.get('kind') == 'industry'
                    and str(item.get('security_code')) == str(row.get('code'))
                    and str(item.get('source_url', '')).startswith('https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?')
                    and isinstance(item.get('tags'), list)):
                result.update(tag for tag in industries[:120] if tag in item['tags'])
    return result


def verify_board(fund, board_id, as_of=None):
    """Explain whether disclosed stocks support a board, without deriving live weights."""
    holdings = fund.get('holdings') if isinstance(fund, dict) else None
    holdings = holdings if isinstance(holdings, dict) else {}
    result = {'status': 'unknown', 'weight_pct': None, 'matched_weight_pct': None, 'disclosed_weight_pct': None,
              'matched_disclosed_pct': None, 'rule_version': HOLDINGS_RULE_VERSION,
              'coverage_pct': None, 'ratio_is_lower_bound': None,
              'unclassified_weight_pct': None, 'unclassified_disclosed_pct': None,
              'matched_names': [], 'stock_evidence': [], 'report_date': holdings.get('report_date'),
              'source_url': holdings.get('source_url', ''), 'source_id': holdings.get('source_id', ''),
              'mapping_source_dates': [], 'classification_sources': [],
              'board_id': board_id,
              'rule': '大部分符合指已确认板块股票权重 / 已披露股票总权重超过一半（>50%）；取消75%限制，比例越高越优先选择。不设主题占基金净值最低比例，仅代表已披露股票部分；未知标签仍计入分母，比例为已确认下限。',
              'reason': '未取得有报告期、股票身份及权重的持仓证据，不能只凭基金名称确认板块。',
              'limitations': '定期披露存在滞后，仅覆盖前十大股票；主题占比不代表基金完整股票或资产配置，不代表实时仓位；当前概念标签不代表报告期标签，也非官方指数成份核验。'}
    # The registry decides whether verification is required. In particular,
    # new style/index/bond-duration IDs must never bypass the gate merely
    # because they do not use the sector_/overseas_ naming convention.
    from research_categories import BOARDS
    board = BOARDS.get(board_id)
    if board is None:
        result.update(rule='板块须在研究目录注册，并提供该方向所需的可核验证据。',
                      reason='该板块尚无已注册的证据核验规则，保持待核验。')
        return result
    if board.get('requires_holdings_match') is False:
        result.update(status='not_required', rule='此资产分类不适用股票主题权重匹配。',
                      reason='研究目录将此方向列为普通资产类别，不要求股票主题匹配；其净值、流动性及风险门槛仍需单独核验。')
        return result
    if board_id == 'holdings_unclassified':
        result.update(rule='持仓须有有效报告期、证券身份、权重及标签；至少一个板块的已确认匹配比例超过已披露股票的一半。',
                      reason='尚无板块通过独立持仓核验；继续采集股票与标签，不按基金名称推断归属。')
        return result
    official_board = board_id in {board for config in INDEX_CONFIG.values() for board in config['boards']}
    tags = BOARD_TAGS.get(board_id)
    if board_id == 'overseas_hugangshen_consumer':
        tags = BOARD_TAGS['sector_consumer']
    if tags is None and not official_board:
        if board_id == 'long_bond':
            result.update(rule='需有报告期的债券持仓、期限分布或组合久期证据。',
                          reason='尚未接入债券期限分布及组合久期证据，不能仅凭名称或股票行业标签确认中长债。')
        elif board_id == 'fixed_income_plus':
            result.update(rule='需有报告期的完整资产配置及权益、转债等风险资产比例证据。',
                          reason='尚未接入债券、股票、转债等完整资产配置证据，前十大股票不能单独证明固收+配置。')
        elif board_id.startswith('index_'):
            result.update(rule='需核验对应日期的官方指数成分、权重及基金直接或目标ETF穿透暴露。',
                          reason='尚未完成官方指数成分与基金暴露核验；行业、概念或交易板标签不能代替指数组成证据。')
        elif board_id.startswith('style_') or board_id == 'dividend':
            result.update(rule='需有风格定义、适用报告期及组合层面的股息、波动、市值、现金流或量化策略证据。',
                          reason='尚未接入可复核的组合风格及策略证据；基金名称或个别股票概念标签不能证明蓝筹、红利、低波、微盘或量化风格。')
        elif board_id.startswith('overseas_'):
            result.update(rule='需核验海外证券身份、地域或官方指数成分，并核验目标ETF穿透与组合暴露。',
                          reason='当前海外股票、地域及对应指数成分证据未齐备；不能用A股概念标签替代海外地域或指数组成核验。')
        else:
            result.update(rule='需该方向的明确持仓或资产暴露证据，缺少专属规则时不放行。',
                          reason='该板块要求持仓匹配，但当前尚未接入专属核验规则，保持待核验。')
        return result
    if holdings.get('status') != 'ok':
        return result
    try:
        age = (_day(as_of) if as_of is not None else datetime.now(CHINA).date()) - _day(holdings.get('report_date'))
        if not 0 <= age.days <= MAX_DISCLOSURE_AGE_DAYS:
            result['reason'] = '持仓报告期晚于研究日期或距研究日期超过180天，等待有效披露。'
            return result
    except (ValueError, TypeError):
        return result
    rows = holdings.get('rows')
    if not isinstance(rows, list) or not rows:
        return result
    row_limit = holdings_row_limit(holdings)
    if len(rows) > row_limit:
        result['reason'] = '披露股票行数超出已核验来源范围；不能截去其余股票后提高匹配占比，等待重新采集。'
        return result
    if holdings.get('lookthrough'):
        result['lookthrough'] = copy.deepcopy(holdings['lookthrough'])
        result['limitations'] = '同报告期直接股票与目标ETF前十大股票按实际投资权重穿透，仅代表已披露穿透部分；非完整或实时仓位。行业标签与官方成分采用各自采集日期，不冒充持仓报告日。'
    elif official_board:
        result['limitations'] = '仅覆盖定期披露股票；官方成分采用单独标注的最新映射日期，不代表披露报告日成分或基金实时仓位。官方前十大成分缺席不能证明不属于该方向。'
    total, known, matched = Decimal(0), Decimal(0), Decimal(0)
    names, evidence, seen, invalid_evidence = [], [], set(), bool(holdings.get('invalid_row_count'))
    mapping_dates, classification_sources = set(), []
    matched_regions = set()
    for row in rows:
        if not isinstance(row, dict):
            invalid_evidence = True
            continue
        instrument = row.get('instrument_type')
        if isinstance(instrument, str) and instrument in {'fund', 'etf', 'bond', 'cash', 'trust', 'derivative'}:
            # Funds, target ETFs, bonds and cash do not enter the stock-only
            # denominator, nor do their names/tags establish look-through.
            continue
        if instrument != 'stock':
            # Old cached rows without an explicit stock identity need a new
            # disclosure. Dropping them and passing from the remainder would
            # silently inflate the ratio.
            invalid_evidence = True
            continue
        weight = row.get('weight_pct') if isinstance(row, dict) else None
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 < weight <= 100:
            invalid_evidence = True
            continue
        identity = str(row.get('code', ''))
        if not re.fullmatch(r'\d{5,6}|[A-Z][A-Z0-9.\-]{0,11}', identity) or identity in seen:
            invalid_evidence = True
            continue
        seen.add(identity)
        if re.search(r'ETF|基金|信托|REIT|债券|转债|国债|国开债', str(row.get('name') or ''), re.I):
            invalid_evidence = True
            continue
        exact_weight = Decimal(str(weight))
        total += exact_weight
        detail = {'code': identity, 'name': str(row.get('name') or identity),
                  'nav_weight_pct': float(exact_weight), 'matched': False,
                  'tag_status': 'unknown', 'classification_known': False, 'matched_tags': [],
                  'tag_source_url': row.get('tag_source_url', ''),
                  'industry_tags': copy.deepcopy(row.get('industry_tags', [])),
                  'tag_evidence': copy.deepcopy(row.get('tag_evidence', [])),
                  'membership_sources': []}
        evidence.append(detail)
        row_tags = _stock_tags(row)
        tag_matches = row_tags.intersection(tags or set())
        # Some securities carry a broad "白酒" concept while their explicit
        # industry is 非白酒/其他酒类 (e.g. yellow-wine producer 601579).
        # Keep every original tag and its source, but an explicit conflicting
        # industry must take precedence for this narrowly defined board.
        # The row remains in the denominator and in broader consumption boards.
        liquor_exclusions = row_tags.intersection({'非白酒', '其他酒类'}) if board_id == 'sector_liquor' else set()
        if liquor_exclusions:
            tag_matches = set()
            detail.update(excluded_by_industry_tags=sorted(liquor_exclusions),
                          match_exclusion_reason='明确行业为非白酒或其他酒类；行业分类优先于白酒概念，本行不计入白酒匹配权重。')
        official, sources = _official_match(row, board_id, as_of) if official_board else (None, [])
        detail['membership_sources'] = sources
        for source in sources:
            mapping_dates.add(source['source_date'])
            if source not in classification_sources:
                classification_sources.append(source)
        region = 'hk' if re.fullmatch(r'\d{5}', identity) else ('cn' if re.fullmatch(r'\d{6}', identity) else '')
        if tags is None:
            is_known, is_match = official is not None, official is True
        elif board_id == 'overseas_hugangshen_consumer':
            is_known = region in {'cn', 'hk'} and (bool(row_tags) or official is not None)
            is_match = region in {'cn', 'hk'} and (bool(tag_matches) or official is True)
        elif board_id == 'sector_innovative_drug' and region == 'hk':
            is_match = bool(tag_matches) or official is True
            is_known = is_match or official is False
        else:
            is_known = bool(row_tags) or official is not None
            is_match = bool(tag_matches) or official is True
        if not is_known:
            continue
        detail['tag_status'] = 'ok'
        detail['classification_known'] = True
        known += exact_weight
        if is_match:
            if region:
                matched_regions.add(region)
            matched += exact_weight
            names.append(str(row.get('name') or row.get('code')))
            detail.update(matched=True, matched_tags=sorted(tag_matches),
                          match_method='官方指数成分' if official is True else '逐只股票明确行业/概念')
    if not 0 < total <= 101:
        return result
    ratio = matched / total * 100
    incomplete = known < total
    qualifier = '已确认至少 ' if incomplete else ''
    result.update(weight_pct=float(matched), matched_weight_pct=float(matched), disclosed_weight_pct=float(total),
                  matched_disclosed_pct=float(ratio), coverage_pct=round(float(known / total * 100), 2),
                  ratio_is_lower_bound=incomplete,
                  unclassified_weight_pct=float(total - known),
                  unclassified_disclosed_pct=float((total - known) / total * 100),
                  mapping_source_dates=sorted(mapping_dates), classification_sources=classification_sources,
                  matched_names=names, stock_evidence=[{**row,
                      'disclosed_stock_weight_pct': float(Decimal(str(row['nav_weight_pct'])) / total * 100)} for row in evidence])
    if invalid_evidence:
        result['reason'] = '披露行存在证券类型不明、股票身份或权重无效、重复记录等问题，不能删去不明行后提高主题占比；等待重新采集核验。'
    elif board_id == 'overseas_hugangshen_consumer' and not {'cn', 'hk'}.issubset(matched_regions):
        result.update(status='unknown', reason='沪港深消费须同时有内地及港股消费股票的已确认披露证据；单一市场不能证明跨市场投向。已披露股票匹配比例仍保留供核验。')
    elif matched * 100 > total * MIN_MATCH_DISCLOSED_PCT:
        result.update(status='matched', reason=f'报告期匹配主题股票占基金净值 {qualifier}{matched:.2f}%，占已披露股票权重 {qualifier}{ratio:.4f}%；已确认大部分符合本板块，按匹配比例由高到低优先选择；仅代表已披露股票部分。')
    elif matched + (total - known) <= total * Decimal('.5'):
        result.update(status='mismatch', reason=f'匹配主题股票占基金净值 {qualifier}{matched:.2f}%，占已披露股票权重 {qualifier}{ratio:.4f}%；未达到大部分符合（>50%），不列入本板块优选；仅代表已披露股票部分。')
    else:
        result['reason'] = f'已披露股票合计占基金净值 {total:.2f}%，其中 {known:.2f}% 已取得板块资料；证据尚不足以确认该主题，保持待核验。'
    return result
