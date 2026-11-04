"""Dated public mobile holdings and conservative one-level ETF look-through.

The investment percentage is read from an actual periodic report table. The
contract's investment minimum and a product title can never substitute for it.
The resulting denominator covers the disclosed stocks only, including the
target ETF's disclosed top ten scaled by the fund's actual ETF investment.
"""
import copy
import html
import json
import math
import re
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

CHINA = timezone(timedelta(hours=8))
TIMEOUT = 6
MAX_BYTES = 2_000_000
CACHE_TTL = 12 * 3600
MAX_AGE_DAYS = 180
_cache = {}
_cache_lock = threading.Lock()
_slots = threading.BoundedSemaphore(4)


def mobile_url(code):
    return ('https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition'
            f'?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0')


def periodic_url(code):
    return f'https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=3&type=3'


def announcement_url(article):
    return ('https://np-cnotice-stock.eastmoney.com/api/content/ann'
            f'?client_source=web&show_all=1&art_code={article}')


def _fetch(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 FundPilotLocalResearch/1.0',
        'Referer': 'https://fundf10.eastmoney.com/', 'Accept': 'application/json',
        'Accept-Encoding': 'identity'})
    with _slots, urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('持仓证据响应超过限制')
    return raw.decode('utf-8-sig')


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _period(value, as_of=None):
    day = _day(value)
    now = _day(as_of) if as_of is not None else datetime.now(CHINA).date()
    if not 0 <= (now - day).days <= MAX_AGE_DAYS:
        raise ValueError('披露报告期为未来或距研究日期超过180天')
    return day.isoformat()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('股票权重无效')
    if isinstance(value, str) and not re.fullmatch(r'\d+(?:\.\d+)?', value):
        raise ValueError('股票权重无效')
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 100:
        raise ValueError('股票权重无效')
    return number


def parse_mobile_position(payload, code, as_of=None):
    """Parse only the provider's explicit fundStocks table, never product names."""
    if payload.get('Success') is not True or payload.get('ErrCode') != 0:
        raise ValueError('公开持仓接口未成功')
    data = payload.get('Datas')
    if not isinstance(data, dict) or not isinstance(data.get('fundStocks'), list):
        raise ValueError('公开股票持仓结构变化')
    period = _period(payload.get('Expansion'), as_of)
    source = mobile_url(code)
    if len(data['fundStocks']) > 10:
        raise ValueError('股票披露行数超过接口前十名范围')
    result, seen = [], set()
    for row in data['fundStocks'][:10]:
        if not isinstance(row, dict):
            raise ValueError('股票披露行无效')
        identity, name = str(row.get('GPDM') or ''), str(row.get('GPJC') or '').strip()
        if (not re.fullmatch(r'\d{5,6}|[A-Z][A-Z0-9.\-]{0,11}', identity)
                or identity in seen or not name or re.search(r'ETF|基金|信托|REIT|债券|转债', name, re.I)):
            raise ValueError('股票身份、证券类型或重复记录无效')
        seen.add(identity)
        weight = _number(row.get('JZBL'))
        industry = str(row.get('INDEXNAME') or '').strip()
        known = bool(industry and industry != '--' and len(industry) <= 80)
        observed = datetime.now(CHINA).isoformat(timespec='seconds')
        result.append({'code': identity, 'name': name, 'weight_pct': weight,
                       'instrument_type': 'stock', 'tag_status': 'ok' if known else 'unknown',
                       'tags': [industry] if known else [], 'industry_tags': [industry] if known else [],
                       'tag_source_url': source, 'industry_source_url': source, 'tag_fetched_at': observed,
                       'tag_evidence': [{'kind': 'industry', 'security_code': identity,
                           'tags': [industry], 'source_url': source, 'source_field': 'INDEXNAME', 'observed_at': observed,
                           'holdings_report_date': period,
                           'scope': '公开股票持仓接口明确行业；采集时标签，不冒充报告日或官方指数成分'}] if known else [],
                       'tag_scope': '公开持仓接口逐只股票明确行业；不是官方指数成份或概念业务收入证明'})
    if sum(Decimal(str(row['weight_pct'])) for row in result) > 101:
        raise ValueError('股票披露合计比例异常')
    target = data.get('ETFCODE') or None
    if target is not None and (not isinstance(target, str) or not re.fullmatch(r'\d{6}', target) or target == code):
        raise ValueError('目标ETF身份无效')
    return {'report_date': period, 'rows': result, 'target_code': target,
            'source_url': source}


def parse_target_investment(payload, article, code, target, report_date, as_of=None):
    """Read a single actual target investment, bound to codes and report period.

    Multiple target tables are deliberately rejected. A single table row is
    connected to the target code by the report's target basic-information block.
    No industry classification is derived from the fund's displayed name.
    """
    period = _period(report_date, as_of)
    data = payload.get('data')
    if payload.get('success') not in (True, 1) or not isinstance(data, dict) or data.get('art_code') != article:
        raise ValueError('定期报告身份不一致')
    securities = data.get('security')
    if not isinstance(securities, list) or code not in {str(row.get('stock')) for row in securities if isinstance(row, dict)}:
        raise ValueError('定期报告与基金代码不一致')
    text = html.unescape(re.sub(r'<[^>]+>', ' ', str(data.get('notice_content') or ''))).replace('\r\n', '\n')
    if not text or len(text) > MAX_BYTES:
        raise ValueError('未取得完整可解析定期报告正文')
    # The first cover date must agree with the dated holdings feed.
    cover = re.search(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text[:800])
    if not cover or date(*map(int, cover.groups())).isoformat() != period:
        raise ValueError('定期报告与持仓报告期不一致')
    target_block = re.search(r'目标基金基本情况(.*?)(?:\n\s*\d+(?:\.\d+)+\s|目标基金产品说明)', text, re.S)
    if not target_block:
        raise ValueError('定期报告未提供目标ETF基本资料')
    target_codes = re.findall(r'基金(?:主代码|代码)\s*(\d{6})\b', target_block.group(1))
    if target_codes != [target]:
        raise ValueError('定期报告目标ETF代码与公开持仓接口不一致')
    table_start = re.search(r'期末投资目标基金明细', text)
    if not table_start:
        raise ValueError('定期报告未提供实际目标ETF投资明细')
    tail = text[table_start.end():]
    stop = re.search(r'\n\s*\d+(?:\.\d+)+\s', tail)
    table = tail[:stop.start()] if stop else tail[:3500]
    compact = re.sub(r'\s+', '', table)
    if not re.search(r'占基金.{0,180}?资产净.{0,180}?值比例', compact) or '公允价值' not in compact:
        raise ValueError('目标ETF投资表未明确占基金净值口径')
    rows = list(re.finditer(r'(?:^|\n)[ \t]*(\d{1,2})[ \t]+[^\n]*?([\d,]+\.\d{2})[ \t]+(\d+(?:\.\d+)?)[ \t]*(?=\n|$)', table))
    if len(rows) != 1 or rows[0].group(1) != '1':
        raise ValueError('目标ETF投资表行数或结构不明确')
    market_value = Decimal(rows[0].group(2).replace(',', ''))
    weight = _number(rows[0].group(3))
    if market_value <= 0:
        raise ValueError('目标ETF实际投资市值无效')
    return {'target_code': target, 'target_weight_pct': weight, 'report_date': period,
            'article_id': article, 'market_value': float(market_value),
            'source_url': f'https://fund.eastmoney.com/gonggao/{code},{article}.html',
            'content_source_url': announcement_url(article),
            'evidence_excerpt': re.sub(r'\s+', ' ', table).strip()[:1200]}


def _target_report(fetch, code, target, period, as_of):
    listing = json.loads(fetch(periodic_url(code)))
    if listing.get('ErrCode') != 0 or not isinstance(listing.get('Data'), list):
        raise ValueError('未取得定期报告列表')
    now = _day(as_of) if as_of is not None else datetime.now(CHINA).date()
    attempts = 0
    for row in listing['Data'][:3]:
        if not isinstance(row, dict) or str(row.get('FUNDCODE')) != code or str(row.get('NEWCATEGORY')) != '3':
            continue
        article = str(row.get('ID') or '')
        if not re.fullmatch(r'AN\d{10,30}', article):
            continue
        try:
            published = _day(row.get('PUBLISHDATEDesc') or row.get('PUBLISHDATE'))
            if published > now or published < _day(period):
                continue
        except (ValueError, TypeError):
            continue
        attempts += 1
        try:
            return parse_target_investment(json.loads(fetch(announcement_url(article))), article,
                                           code, target, period, as_of)
        except (ValueError, TypeError, KeyError):
            if attempts >= 2:
                break
    raise ValueError('未取得与当前持仓报告期一致的实际目标ETF权重')


def build_lookthrough(code, direct, target, investment):
    """Scale actual dated target holdings and merge repeated stock identities."""
    if (direct['report_date'] != target['report_date'] or target['target_code'] is not None
            or investment['report_date'] != direct['report_date']):
        raise ValueError('ETF穿透须为同一报告期且只允许一层')
    if not target['rows']:
        raise ValueError('目标ETF未提供披露股票')
    merged = {}
    for origin, rows, scale in [('direct', direct['rows'], Decimal(1)),
                                ('target_etf', target['rows'], Decimal(str(investment['target_weight_pct'])) / 100)]:
        for row in rows:
            weight = Decimal(str(row['weight_pct'])) * scale
            item = merged.setdefault(row['code'], {**copy.deepcopy(row), 'weight_pct': 0,
                'lookthrough_components': [], '_exact_weight': Decimal(0)})
            item['_exact_weight'] += weight
            item['lookthrough_components'].append({'origin': origin,
                'fund_code': code if origin == 'direct' else investment['target_code'],
                'weight_pct': float(weight)})
            if row.get('tag_status') == 'ok':
                item['tags'] = sorted(set(item.get('tags', [])) | set(row.get('tags', [])))
                item['industry_tags'] = sorted(set(item.get('industry_tags', [])) | set(row.get('industry_tags', [])))
                for evidence in row.get('tag_evidence', []):
                    if evidence not in item.setdefault('tag_evidence', []):
                        item['tag_evidence'].append(copy.deepcopy(evidence))
                item['tag_status'] = 'ok'
    if not 0 < sum(row['_exact_weight'] for row in merged.values()) <= 101:
        raise ValueError('穿透股票权重合计异常')
    result = []
    for row in merged.values():
        row['weight_pct'] = float(row.pop('_exact_weight'))
        result.append(row)
    result.sort(key=lambda row: (-row['weight_pct'], row['code']))
    return {'status': 'ok', 'report_date': direct['report_date'], 'rows': result,
            'invalid_row_count': 0, 'disclosed_weight_pct': sum(row['weight_pct'] for row in result),
            'source_id': 'holdings:' + code, 'source_url': investment['source_url'],
            'source_urls': [direct['source_url'], investment['source_url'], target['source_url']],
            'provider': '天天基金转载定期报告与公开披露持仓',
            'scope': '同报告期直接披露股票及目标ETF前十大股票按实际投资权重穿透；仅代表已披露穿透部分，不是完整或实时持仓',
            'lookthrough': {**investment, 'target_stock_source_url': target['source_url'],
                            'target_stock_report_date': target['report_date'],
                            'row_limit': 20, 'method': '原基金实际ETF权重×目标ETF披露股票占净值权重÷100'},
            'fetched_at': datetime.now(CHINA).isoformat(timespec='seconds'), 'error': ''}


def fetch_holdings_evidence(code, refresh=False, as_of=None, fetcher=None, security_classifier=None):
    """Public fallback for direct stocks or one documented target ETF.

    ``fetcher`` and ``security_classifier`` are injectable test/host boundaries.
    The production fetcher is bounded, fixed-host and uses no credentials.
    """
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        raise ValueError('基金代码须为六位数字')
    use_cache = fetcher is None and security_classifier is None
    if use_cache:
        with _cache_lock:
            cached = _cache.get(code)
            if cached and not refresh and time.monotonic() - cached[0] < CACHE_TTL:
                _period(cached[1]['report_date'], as_of)
                return copy.deepcopy(cached[1])
    fetch = fetcher or _fetch
    direct = parse_mobile_position(json.loads(fetch(mobile_url(code))), code, as_of)
    target_code = direct['target_code']
    if target_code:
        investment = _target_report(fetch, code, target_code, direct['report_date'], as_of)
        target = parse_mobile_position(json.loads(fetch(mobile_url(target_code))), target_code, as_of)
        result = build_lookthrough(code, direct, target, investment)
    elif direct['rows']:
        result = {'status': 'ok', 'report_date': direct['report_date'], 'rows': direct['rows'],
                  'invalid_row_count': 0, 'disclosed_weight_pct': sum(row['weight_pct'] for row in direct['rows']),
                  'source_id': 'holdings:' + code, 'source_url': direct['source_url'],
                  'provider': '天天基金公开披露股票持仓',
                  'scope': '公开接口前十大股票及逐只明确行业，占基金净值比例；不是完整资产配置或实时持仓',
                  'fetched_at': datetime.now(CHINA).isoformat(timespec='seconds'), 'error': ''}
    else:
        raise ValueError('公开持仓接口未提供股票或可核验目标ETF')
    if security_classifier:
        for row in result['rows']:
            detail = security_classifier(row['code'], refresh=refresh)
            if isinstance(detail, dict) and detail.get('tag_status') == 'ok':
                tags = sorted(set(row.get('tags', [])) | set(detail.get('tags', [])))
                industries = sorted(set(row.get('industry_tags', [])) | set(detail.get('industry_tags', [])))
                provenance = copy.deepcopy(row.get('tag_evidence', []))
                provenance.extend(copy.deepcopy(detail.get('tag_evidence', [])))
                row.update(detail)
                row['tags'] = tags
                row['industry_tags'] = industries
                row['tag_evidence'] = provenance
    if use_cache:
        with _cache_lock:
            _cache[code] = (time.monotonic(), copy.deepcopy(result))
            if len(_cache) > 512:
                for identity in sorted(_cache, key=lambda key: _cache[key][0])[:128]:
                    del _cache[identity]
    return result
