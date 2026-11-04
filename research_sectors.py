"""Direct sector/index research, with no fund universe or portfolio dependency.

Public quote interfaces are best-effort sources. A sector without an exact,
declared reference index remains visible with unknown metrics. Related sector
names, product titles and broad market quotes are never substituted for it.
"""
from __future__ import annotations

import copy
import json
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlencode

from research_categories import BOARDS
from research_data import (CHINA, MARKET_URL, POLICY_URL, fetch_policy,
                           fetch_text, now_iso, parse_market, timestamp_iso)
from research_quant import build_sentiment
from research_market_sentiment import build_market_sentiment
from research_market_liquidity import build_market_liquidity
from research_sector_references import VERIFIED_REFERENCES, collect_cached_references as collect_verified_references
from research_bond_model import score_bond, METHOD as BOND_SCORE_METHOD
from research_convertible_model import score_convertible, METHOD as CONVERTIBLE_SCORE_METHOD
from research_macro_risk import collect_cached_macro_risk as collect_macro_risk
from research_strategy import _pressure, _regime
from research_numbers import parse_number as _number, clamp as _clamp

SECTOR_SCHEMA_VERSION = 1
CATALOG_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
HISTORY_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
PAGE_SIZE = 100
MAX_PAGES = 8
MAX_WORKERS = 5
HISTORY_BUDGET_SECONDS = 30
MIN_HISTORY = 61
RESEARCH_INTERVAL = 1800

# These are declared reference series, not inferred relationships. An exact
# provider name/alias match is required. Ambiguous missing names stay unknown.
QUOTE_NAMES = {
    'sector_liquor': ['白酒', '白酒Ⅱ', '白酒Ⅲ'],
    'sector_cxo': ['医疗研发外包', 'CRO'],
    'sector_food_beverage': ['食品饮料'],
    'sector_innovative_drug': ['创新药'],
    'sector_brain_computer': ['脑机接口'],
    'sector_medical': ['医疗器械'],
    'sector_home_appliances': ['家用电器', '家电行业'],
    'sector_eldercare': ['养老概念', '养老产业'],
    'sector_consumer_electronics': ['消费电子'],
    'sector_gold_equity': ['黄金概念', '黄金股'],
    'sector_compute_leasing': ['算力租赁'],
    'sector_nuclear_fusion': ['可控核聚变'],
    'sector_cloud_computing': ['云计算'],
    'sector_domestic_computing': ['国产算力'],
    'sector_memory_chip': ['存储芯片'],
    'sector_semiconductor_equipment': ['半导体设备', '半导体材料设备'],
    'sector_semiconductor': ['半导体', '芯片概念'],
    'sector_pcb': ['PCB', 'PCB概念'],
    'sector_cpo': ['CPO概念', 'CPO'],
    'sector_mlcc': ['MLCC'],
    'sector_ai_application': ['AI应用'],
    'sector_ai': ['人工智能'],
    'sector_robotics': ['机器人概念', '机器人'],
    'sector_communication': ['通信', '通信设备'],
    'sector_solid_state_battery': ['固态电池'],
    'sector_energy_storage': ['储能'],
    'sector_photovoltaic': ['光伏设备', '光伏'],
    'sector_renewable': ['新能源'],
    'sector_healthcare': ['医药生物', '医药制造'],
    'sector_consumer': ['消费风格'],
    'sector_fintech': ['互联金融', '金融科技'],
    'sector_financial_real_estate': ['金融地产风格'],
    'sector_diversified_finance': ['多元金融'],
    'sector_nonbank': ['非银金融'],
    'sector_banking': ['银行'],
    'sector_securities': ['证券', '券商概念'],
    'sector_insurance': ['保险', '保险Ⅱ'],
    'sector_commercial_aerospace': ['商业航天'],
    'sector_defense': ['国防军工', '航天航空'],
    'sector_real_estate': ['房地产', '房地产开发'],
    'sector_infrastructure': ['基建概念', '工程建设'],
    'sector_agriculture': ['农林牧渔', '农牧饲渔'],
    'sector_environment': ['环保', '环保行业'],
    'sector_grid_equipment': ['电网设备'],
    'sector_power': ['电力', '电力行业'],
    'sector_utilities': ['公用事业'],
    'sector_transport': ['交通运输'],
    'sector_media': ['传媒', '文化传媒'],
    'sector_travel': ['旅游酒店', '旅游及景区'],
    'sector_auto_vehicle': ['汽车整车'],
    'sector_automotive': ['汽车'],
    'sector_construction_machinery': ['工程机械'],
    'sector_advanced_manufacturing': ['高端装备'],
    'sector_manufacturing': ['机械设备', '通用设备'],
    'sector_chemicals': ['基础化工', '化学制品'],
    'sector_oil_gas': ['油气开采', '石油石化'],
    'sector_coal': ['煤炭'],
    'sector_lithium_mining': ['锂矿', '锂'],
    'sector_steel': ['钢铁'],
    'sector_rare_earth_magnet': ['稀土永磁'],
    'sector_nonferrous': ['有色金属', '小金属'],
    'dividend': ['红利股'],
    'style_cashflow': ['自由现金流'],
    'style_bluechip': ['蓝筹股'],
    'style_microcap': ['微盘股'],
}

DIRECT_INDICES = {
    'index_sse50': ('sh000016', '上证50', '1.000016'),
    'index_csi300': ('sh000300', '沪深300', '1.000300'),
    'index_csi500': ('sh000905', '中证500', '1.000905'),
    'index_chinext': ('sz399006', '创业板指', '0.399006'),
    'index_star': ('sh000688', '科创50', '1.000688'),
    'index_beijing': ('bj899050', '北证50', None),
    'overseas_hang_seng': ('hkHSI', '恒生指数', None),
    'overseas_hang_seng_technology': ('hkHSTECH', '恒生科技指数', None),
    'overseas_sp500': ('us.INX', '标普500', None),
    'overseas_nasdaq': ('us.IXIC', '纳斯达克综合指数', None),
    'sector_liquor': ('sz399997', '中证白酒', 'tencent:sz399997'),
    'sector_consumer': ('sh000932', '中证消费', 'tencent:sh000932'),
    'sector_healthcare': ('sh000933', '中证医药', 'tencent:sh000933'),
    'sector_financial_real_estate': ('sh000934', '中证金融', 'tencent:sh000934'),
    'sector_technology': ('sh000998', '中证TMT', 'tencent:sh000998'),
    'sector_communication': ('sh000936', '800通信', 'tencent:sh000936'),
    'sector_utilities': ('sh000937', '800公用', 'tencent:sh000937'),
    'sector_nonferrous': ('sh000819', '有色金属', 'tencent:sh000819'),
    'sector_banking': ('sz399986', '中证银行', 'tencent:sz399986'),
    'sector_securities': ('sz399975', '证券公司', 'tencent:sz399975'),
    'sector_media': ('sz399971', '中证传媒', 'tencent:sz399971'),
    'sector_infrastructure': ('sz399995', '基建工程', 'tencent:sz399995'),
    'dividend': ('sh000922', '中证红利', 'tencent:sh000922'),
    'sector_coal': ('sz399998', '中证煤炭', 'tencent:sz399998'),
    'sector_defense': ('sz399967', '中证军工', 'tencent:sz399967'),
    'sector_renewable': ('sz399808', '中证新能', 'tencent:sz399808'),
    'sector_environment': ('sh000827', '中证环保', 'tencent:sh000827'),
}
# Domestic direct index histories use the same provider as their verified quote.
for _identity, (_symbol, _title, _secid) in list(DIRECT_INDICES.items()):
    if _symbol.startswith(('sh', 'sz', 'bj')):
        DIRECT_INDICES[_identity] = (_symbol, _title, 'tencent:' + _symbol)
EXTRA_INDEX_URL = 'https://qt.gtimg.cn/q=' + ','.join(row[0] for row in DIRECT_INDICES.values())

SCORE_METHOD = ('0–100 分板块研究指数为固定启发式规则，非收益概率，未经交易回测。'
                '基准50分；日涨跌幅×4（±15分）；上涨家数比例偏离50%×20（±10分）；'
                '5日收益×1（±10分）；20日收益×0.7（±12分）；20日均线方向±6分；'
                '60日年化波动超过30%扣至多12分；窗口回撤绝对值×0.4扣至多15分。'
                '至少61个近期历史点，且有效数据、明确映射、专用模型三项均满足才生成综合分；'
                '此分仅用于参考走势；大盘风险独立展示，不截断走势分；不套用公司综合研究档位。')


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)
    except (ValueError, TypeError):
        return None


def _fresh(value, reference):
    stamp, now = _timestamp(value), _timestamp(reference)
    if stamp is None or now is None:
        return False
    hours = 90 if now.weekday() == 0 and now.hour < 10 else (72 if now.weekday() > 4 else 36)
    return 0 <= (now - stamp).total_seconds() <= hours * 3600


# Official index publishers post the day's close in the evening.
PUBLISHER_DAILY_HOUR = 20


def prefer_company_indicator(board, bundle, leaders, reference_complete, as_of):
    """Choose the self-built company sample over the official reference series.

    A broad market index (沪深300, 中证500, 科创50 ...) is represented by its own
    official quotes and history whenever they are complete: an equal-weight basket
    of at most eight constituents cannot stand in for hundreds of index members and
    can even move the other way on the day. Industry and theme directions keep the
    sample, which carries the company fundamentals. Without a complete official
    series the sample remains the fallback for every group."""
    if not reference_complete:
        return True
    if board.get('group') == 'broad':
        return False
    return bool(bundle['meta']['ready'] and all(_company_financial_ready(r, as_of) for r in leaders))


def _quote_fresh(quote, as_of):
    if quote.get('reference_market_daily'):
        from research_sector_references import reference_daily_quote_fresh
        return reference_daily_quote_fresh(quote, as_of)
    if quote.get('reference_timezone') or quote.get('reference_members'):
        from research_overseas import reference_quote_fresh
        return reference_quote_fresh(quote, as_of)
    if quote.get('is_custom') and quote.get('market') in {'HK', 'US'}:
        from research_overseas import last_complete_session
        expected = last_complete_session(quote['market'], as_of)
        return bool(expected and quote.get('trade_date') == expected
                    and str(quote.get('as_of', ''))[:10] == expected)
    if str(quote.get('code', '')).startswith(('hk', 'us.')):
        return _fresh(quote.get('as_of'), as_of)
    from research_trading_calendar import a_share_quote_fresh
    daily = quote.get('data_frequency') == 'daily'
    publisher = daily and str(quote.get('history_secid', '')).startswith('official:')
    return a_share_quote_fresh(quote.get('as_of'), as_of, daily=daily,
                               published_hour=PUBLISHER_DAILY_HOUR if publisher else None)


def _history_fresh(history, quote, as_of):
    if not history:
        return False
    if quote.get('reference_market_daily'):
        return history[-1].get('date') == quote.get('trade_date') and _quote_fresh(quote, as_of)
    if quote.get('reference_timezone') or quote.get('reference_members'):
        return history[-1].get('date') == str(quote.get('as_of', ''))[:10] and _quote_fresh(quote, as_of)
    if quote.get('is_custom') and quote.get('market') in {'HK', 'US'}:
        return history[-1].get('date') == quote.get('trade_date') and _quote_fresh(quote, as_of)
    if quote.get('is_custom'):
        from research_leader_index import last_close_day
        return history[-1].get('date') == last_close_day(as_of) and _quote_fresh(quote, as_of)
    day, now = _timestamp(history[-1].get('date')), _timestamp(as_of)
    if quote.get('data_frequency') == 'daily' and quote.get('as_of_precision') == 'date':
        return bool(day and history[-1]['date'] == quote.get('as_of') and _quote_fresh(quote, as_of))
    from research_trading_calendar import last_closed_trading_day
    return bool(day and now and history[-1]['date'] == last_closed_trading_day(as_of))


def _company_financial_ready(row, as_of):
    financial = row.get('financials') or {}
    published, end, now = (_timestamp(financial.get('ann_date')),
                           _timestamp(financial.get('end_date')), _timestamp(as_of))
    return bool(published and end and now and end.date() <= published.date() < now.date()
                and 0 <= (now.date()-end.date()).days <= 550
                and any(_number(financial.get(key)) is not None for key in
                        ('roe', 'eps', 'netprofit_yoy', 'tr_yoy', 'grossprofit_margin')))


def enforce_score_requirements(sector):
    """Publish a composite score only when all three declared gates pass."""
    requirements = {r.get('id'): r for r in sector.get('requirements', [])}
    unmet = [key for key in ('data', 'mapping', 'model')
             if requirements.get(key, {}).get('status') != 'ok']
    if not unmet:
        return True
    sector.update(score=None, recommendation_index=None, signal='neutral')
    if sector.get('score_model') == 'company_research_v2':
        from research_balanced_score import research_tier
        sector.update(research_score=None, confirmed_score=None, score_status='unavailable',
                      research_tier=research_tier(None,None,None,None,False))
    if sector.get('status') == 'ok':
        sector['status'] = 'partial'
    if sector.get('severity') != 'critical':
        sector['indicator_reason'] = ''
    labels = '、'.join(requirements.get(key, {}).get('label', key) for key in unmet)
    sector['summary'] = f'{sector.get("trend", "等待数据")}；{labels}尚未满足，暂不生成综合研究分数。'
    gaps = sector.setdefault('data_gaps', [])
    if not any(gap.get('code') == 'score_requirements_unmet' for gap in gaps):
        gaps.append({'code': 'score_requirements_unmet', 'message': labels + '尚未满足；保留已取得数据与真实分项，综合研究分数保持未知。', 'source_ids': []})
    return False


def sector_catalog():
    excluded = {'equity_active', 'equity_index', 'overseas_equity', 'overseas_mixed',
                'unclassified', 'holdings_unclassified', 'secondary_bond', 'fixed_income_plus',
                'style_quant', 'style_small_micro_quant', 'overseas_bond'}
    renamed = {'money': '货币市场', 'bond': '债券市场', 'short_bond': '短久期债券',
               'long_bond': '中长久期债券', 'convertible_bond': '可转债', 'commodities': '大宗商品·资源企业股票'}
    rows = []
    for identity, board in list(BOARDS.items()):
        if identity in excluded or identity.endswith('_mixed'):
            continue
        label = renamed.get(identity, board.get('label', identity))
        if identity.startswith('overseas_') and identity.endswith('_equity'):
            label = label.split(' · ')[0]
        rows.append({'id': identity, 'title': label, 'label': label,
                     'group': board.get('group', 'other'),
                     'aliases': list(board.get('aliases') or []),
                     'description': f'{label}板块；研究行业成分、公司财务、板块行情、公开公告与官方政策。',
                     'display_priority': board.get('display_priority', 999)})
    return rows


def _catalog_request(kind, page):
    query = urlencode({'pn': page, 'pz': PAGE_SIZE, 'po': 1, 'np': 1, 'fltt': 2,
                       'invt': 2, 'fid': 'f3', 'fs': f'm:90+t:{kind}',
                       'fields': 'f2,f3,f8,f12,f14,f20,f104,f105,f124'})
    return CATALOG_URL + '?' + query


def parse_sector_quotes(data, source_id):
    payload = data.get('data') if isinstance(data, dict) else None
    raw = payload.get('diff') if isinstance(payload, dict) else None
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raise ValueError('板块行情源未返回有效列表')
    result = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        code, name = str(row.get('f12') or ''), str(row.get('f14') or '').strip()
        if not re.fullmatch(r'BK\d{4,6}', code) or not name:
            continue
        up, down = _number(row.get('f104')), _number(row.get('f105'))
        result.append({'code': code, 'name': name[:100], 'last': _number(row.get('f2')),
                       'change_pct': _number(row.get('f3')), 'turnover_rate': _number(row.get('f8')),
                       'up_count': int(up) if up is not None and up >= 0 else None,
                       'down_count': int(down) if down is not None and down >= 0 else None,
                       'as_of': timestamp_iso(row.get('f124')), 'source_id': source_id,
                       'source_url': f'https://quote.eastmoney.com/bk/90.{code}.html',
                       'history_secid': '90.' + code})
    return result


def collect_sector_quotes():
    rows, sources = [], []
    for kind, title in ((2, '行业'), (3, '概念')):
        identity = 'sector_quotes_' + ('industry' if kind == 2 else 'concept')
        source = {'id': identity, 'name': f'东方财富 · {title}板块行情',
                  'url': _catalog_request(kind, 1), 'fetched_at': now_iso(), 'as_of': None,
                  'status': 'ok', 'count': 0, 'scope': '直接板块参考指数与成分涨跌家数；不含产品数据'}
        fetched, errors, total = [], [], None
        try:
            data = json.loads(fetch_text(source['url']))
            fetched.extend(parse_sector_quotes(data, identity))
            total = int((data.get('data') or {}).get('total') or 0)
            pages = min(MAX_PAGES, max(1, math.ceil(total / PAGE_SIZE)))
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending = {pool.submit(fetch_text, _catalog_request(kind, page)): page
                           for page in range(2, pages + 1)}
                for future in as_completed(pending):
                    try:
                        fetched.extend(parse_sector_quotes(json.loads(future.result()), identity))
                    except Exception:
                        errors.append(f'第{pending[future]}页未取得')
        except Exception:
            errors.append('公开行情连接失败或响应格式发生变化')
        unique = {row['code']: row for row in fetched}
        fetched = list(unique.values())
        source.update(count=len(fetched), total_count=total,
                      as_of=max((row['as_of'] for row in fetched if row.get('as_of')), default=None))
        if errors or (total is not None and len(fetched) < total):
            source.update(status='partial' if fetched else 'error',
                          error='；'.join(errors) or '公开板块列表覆盖不完整')
        if not fetched:
            source['status'] = 'error'
            source.setdefault('error', '本次未取得有效板块行情')
        rows.extend(fetched)
        sources.append(source)
    return rows, sources


def parse_direct_indices(text):
    result = []
    for match in re.finditer(r'v_([\w.]+)="([^"]+)"', text):
        fields = match.group(2).split('~')
        if len(fields) < 33:
            continue
        last, change = _number(fields[3]), _number(fields[32])
        if last is None or last <= 0 or change is None:
            continue
        stamp = None
        for fmt in ('%Y%m%d%H%M%S', '%Y/%m/%d %H:%M:%S'):
            try:
                stamp = datetime.strptime(fields[30], fmt).replace(tzinfo=CHINA).isoformat()
                break
            except ValueError:
                pass
        if match.group(1).startswith('us.'):
            try:
                from zoneinfo import ZoneInfo
                stamp = datetime.strptime(fields[30], '%Y-%m-%d %H:%M:%S').replace(
                    tzinfo=ZoneInfo('America/New_York')).astimezone(CHINA).isoformat()
            except (ValueError, KeyError, ImportError):
                stamp = None
        result.append({'code': match.group(1), 'name': fields[1][:100], 'last': last,
                       'change_pct': change, 'as_of': stamp, 'source_id': 'sector_indices_tencent',
                       'source_url': f'https://gu.qq.com/{match.group(1)}/zs',
                       'up_count': None, 'down_count': None})
    return result


def collect_sector_market():
    """Fetch common market evidence without entering any product collector."""
    result = {'as_of': now_iso(), 'market': [], 'news': [], 'sources': [], 'warnings': []}
    jobs = [
        ('market_tencent', '腾讯财经 · 四大市场指数', MARKET_URL, 'market',
         lambda: parse_market(fetch_text(MARKET_URL, 'gbk'))),
        ('policy_csrc', '中国证监会 · 监管发布', POLICY_URL, 'news', fetch_policy),
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(job[4]): job for job in jobs}
        for future in as_completed(pending):
            identity, name, url, target, _ = pending[future]
            source = {'id': identity, 'name': name, 'url': url, 'status': 'ok',
                      'fetched_at': now_iso(), 'as_of': None, 'count': 0}
            try:
                rows = future.result()
                result[target].extend(rows)
                source.update(count=len(rows), as_of=max((row.get('as_of') or row.get('published_at')
                    for row in rows if row.get('as_of') or row.get('published_at')), default=None))
                if not rows:
                    source.update(status='partial', error='未返回可用记录，不能据此判断市场没有事件')
            except Exception:
                source.update(status='error', error='公开源连接失败或数据格式变化')
                result['warnings'].append(name + '：本次未取得有效数据。')
            result['sources'].append(source)
    seen = set()
    result['news'] = [row for row in sorted(result['news'], key=lambda row: str(row.get('published_at') or ''), reverse=True)
                      if row.get('url') and not (row['url'] in seen or seen.add(row['url']))]
    return result


def _history_url(secid):
    if secid.startswith('tencent:'):
        return 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + secid.split(':', 1)[1] + ',day,,,121,qfq'
    return HISTORY_URL + '?' + urlencode({'secid': secid, 'klt': 101, 'fqt': 1,
        'lmt': 121, 'end': '20500101', 'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'})


def parse_sector_history(data, as_of):
    now = _timestamp(as_of)
    payload = data.get('data') if isinstance(data, dict) else None
    raw = payload.get('klines') if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise ValueError('板块历史行情未返回有效序列')
    rows = {}
    for text in raw:
        fields = text.split(',') if isinstance(text, str) else []
        if len(fields) < 9 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fields[0]):
            continue
        try:
            day = datetime.strptime(fields[0], '%Y-%m-%d').date()
        except ValueError:
            continue
        close = _number(fields[2])
        if now is None or day > now.date() or close is None or close <= 0:
            continue
        rows[fields[0]] = {'date': fields[0], 'close': close,
                            'return_pct': _number(fields[8])}
    return [rows[key] for key in sorted(rows)][-121:]


def parse_tencent_history(data, symbol, as_of):
    now = _timestamp(as_of)
    payload = data.get('data', {}).get(symbol, {}) if isinstance(data, dict) else {}
    raw = payload.get('day') or payload.get('qfqday')
    if not isinstance(raw, list):
        raise ValueError('直接指数日线未返回有效序列')
    rows = {}
    for item in raw:
        if not isinstance(item, list) or len(item) < 3:
            continue
        try:
            day = datetime.strptime(str(item[0]), '%Y-%m-%d').date()
        except ValueError:
            continue
        close = _number(item[2])
        if now is None or day > now.date() or close is None or close <= 0:
            continue
        rows[day.isoformat()] = {'date': day.isoformat(), 'close': close, 'return_pct': None}
    ordered = [rows[key] for key in sorted(rows)][-121:]
    for index in range(1, len(ordered)):
        ordered[index]['return_pct'] = (ordered[index]['close'] / ordered[index - 1]['close'] - 1) * 100
    return ordered


def collect_sector_histories(matches, as_of, progress=None, cached=None):
    wanted = {quote['history_secid']: quote for quote in matches.values()
              if quote.get('history_secid') and _quote_fresh(quote, as_of)}
    histories, sources = {}, []
    from research_trading_calendar import last_closed_trading_day
    cutoff = last_closed_trading_day(as_of)
    for secid, item in (cached or {}).items():
        rows = item.get('rows', [])
        if (secid in wanted and rows and cutoff and rows[-1].get('date') == cutoff
                and item.get('source', {}).get('status') == 'ok'):
            histories[secid] = copy.deepcopy(rows)
            sources.append(copy.deepcopy(item['source']))
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = {}
    try:
        futures = {pool.submit(fetch_text, _history_url(secid)): secid for secid in wanted if secid not in histories}
        for done, future in enumerate(as_completed(futures, timeout=HISTORY_BUDGET_SECONDS), 1):
            secid = futures[future]
            source = {'id': 'sector_history:' + secid, 'name': wanted[secid]['name'] + ' · 日线历史',
                      'url': _history_url(secid), 'fetched_at': now_iso(), 'status': 'ok',
                      'as_of': None, 'count': 0}
            try:
                payload = json.loads(future.result())
                rows = (parse_tencent_history(payload, secid.split(':', 1)[1], as_of)
                        if secid.startswith('tencent:') else parse_sector_history(payload, as_of))
                if cutoff:
                    rows = [r for r in rows if r['date'] <= cutoff]
                histories[secid] = rows
                source.update(count=len(rows), as_of=rows[-1]['date'] if rows else None)
                if len(rows) < MIN_HISTORY:
                    source.update(status='partial', error='历史有效点少于61个，短期观察不代替完整趋势研究')
            except Exception as error:
                from research_transport import source_error
                source.update(status='error', error=source_error(error, '历史行情未取得'))
            sources.append(source)
            if progress:
                progress('正在计算板块历史趋势与风险', {'sector_done': done, 'sector_total': len(wanted),
                                                     'deep_done': done, 'deep_total': len(wanted)})
    except TimeoutError:
        completed_ids = {source['id'] for source in sources}
        for future, secid in futures.items():
            if 'sector_history:' + secid in completed_ids:
                continue
            future.cancel()
            sources.append({'id': 'sector_history:' + secid, 'name': wanted[secid]['name'] + ' · 日线历史',
                            'url': _history_url(secid), 'fetched_at': now_iso(), 'status': 'partial',
                            'as_of': None, 'count': 0, 'error': '达到本轮30秒历史采集预算，后续轮次继续更新'})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return histories, sources


def _normal_name(value):
    return re.sub(r'[\s_\-·ⅡⅢⅠ]+', '', str(value or '')).casefold()


def match_sector_quotes(catalog, quotes, direct_indices, reference_quotes=()):
    names = {}
    for quote in quotes:
        names.setdefault(_normal_name(quote.get('name')), []).append(quote)
    direct = {row['code']: row for row in direct_indices}
    matched = {}
    for board in catalog:
        identity = board['id']
        if identity in DIRECT_INDICES and not identity.startswith('sector_') and identity != 'dividend':
            symbol, title, secid = DIRECT_INDICES[identity]
            if symbol in direct and (_normal_name(direct[symbol]['name']) == _normal_name(title)
                    or identity == 'overseas_nasdaq' and direct[symbol]['name'] == '纳斯达克'):
                matched[identity] = dict(direct[symbol], history_secid=secid,
                                         mapping_basis='明确对应的公开参考指数：' + title)
            continue
        for name in QUOTE_NAMES.get(identity, [board['title']]):
            candidates = names.get(_normal_name(name), [])
            if candidates:
                # Prefer the exact provider label, then industry series over
                # concept series; never choose by the largest daily return.
                candidates = sorted(candidates, key=lambda row: (
                    row['name'] != name, row.get('source_id') != 'sector_quotes_industry', row['code']))
                matched[identity] = copy.deepcopy(candidates[0])
                matched[identity]['mapping_basis'] = f'公开参考系列“{candidates[0]["name"]}”；明确名称映射'
                break
        if identity not in matched and identity in DIRECT_INDICES:
            symbol, title, secid = DIRECT_INDICES[identity]
            if symbol in direct and _normal_name(direct[symbol]['name']) == _normal_name(title):
                matched[identity] = dict(direct[symbol], history_secid=secid,
                                         mapping_basis='明确对应的公开参考指数：' + title)
    catalog_ids = {row['id'] for row in catalog}
    for quote in reference_quotes:
        identity = quote.get('board_id')
        reference = VERIFIED_REFERENCES.get(identity)
        if (identity in catalog_ids and identity not in matched and reference
                and quote.get('code') == reference['code']
                and quote.get('name') in reference['aliases']
                and quote.get('source_id') == 'sector_reference:' + identity):
            matched[identity] = copy.deepcopy(quote)
    for identity, scope in {
        'sector_consumer': '中证主要消费指数（800消费）参考，涵盖必选消费相关行业，不能代表全部可选消费。',
        'sector_healthcare': '中证医药卫生指数（800医卫）参考，包含医药与医疗相关公司，不等同于创新药细分指数。',
        'sector_financial_real_estate': '中证金融地产指数（800金地）参考，包含金融与房地产，不用作纯金融板块的替代。',
    }.items():
        if identity in matched and matched[identity].get('source_id') == 'sector_indices_tencent':
            matched[identity]['scope_note'] = scope
    for quote in matched.values():
        quote.setdefault('asset_type', 'equity_index')
        when = _timestamp(quote.get('as_of'))
        from research_trading_calendar import is_trading_day
        if (when and not str(quote.get('code', '')).startswith(('hk','us.'))
                and is_trading_day(when.date()) is True and (9,30) <= (when.hour,when.minute) < (15,0)
                and quote.get('as_of_precision') != 'date' and not quote.get('reference_market_daily')):
            quote.setdefault('data_frequency', 'intraday')
    return matched


def history_metrics(history, as_of):
    metrics = {'sample_count': len(history), 'history_date': history[-1]['date'] if history else None,
               'return_5d': None, 'return_20d': None, 'return_60d': None,
               'annual_volatility': None, 'max_drawdown': None, 'rsi_14': None, 'ma20_gap': None}
    closes = [row['close'] for row in history]
    for period in (5, 20, 60):
        if len(closes) > period:
            metrics[f'return_{period}d'] = round((closes[-1] / closes[-1-period] - 1) * 100, 3)
    if len(closes) >= 20:
        metrics['ma20_gap'] = round((closes[-1] / statistics.mean(closes[-20:]) - 1) * 100, 3)
    changes = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    if len(changes) >= 60:
        metrics['annual_volatility'] = round(statistics.stdev(changes[-60:]) * math.sqrt(252) * 100, 3)
    if len(closes) >= 2:
        peak, worst = closes[0], 0.0
        for price in closes:
            peak = max(peak, price)
            worst = min(worst, price / peak - 1)
        metrics['max_drawdown'] = round(worst * 100, 3)
    if len(changes) >= 14:
        diffs = [closes[index] - closes[index - 1] for index in range(len(closes) - 14, len(closes))]
        gain = sum(max(value, 0) for value in diffs) / 14
        loss = sum(max(-value, 0) for value in diffs) / 14
        metrics['rsi_14'] = round(100 - 100 / (1 + gain / loss), 3) if loss else (100 if gain else 50)
    return metrics


def mark_to_market_history(history, quote, as_of):
    """Append one provisional quote; never accumulate intraday bars as days."""
    now, when = _timestamp(as_of), _timestamp((quote or {}).get('as_of'))
    live = (quote or {}).get('data_frequency') == 'intraday'
    price = (quote or {}).get('last')
    if (not live or not now or not when or when.date() != now.date()
            or not _quote_fresh(quote, as_of) or not _number(price) or price <= 0):
        return history
    points = [r for r in history if r['date'] < now.date().isoformat()]
    if not points:
        return history
    return points + [{'date': now.date().isoformat(), 'close': price,
                      'return_pct': (price / points[-1]['close'] - 1) * 100,
                      'provisional': True}]


def _related_news(board, news, as_of):
    now = _timestamp(as_of)
    terms = list(dict.fromkeys([board['title']] + list(board.get('aliases') or [])))
    result = []
    for row in news:
        text = str(row.get('title') or '') + ' ' + str(row.get('summary') or '')
        stamp = _timestamp(row.get('published_at'))
        if now is None or stamp is None or not 0 <= (now - stamp).total_seconds() <= 3 * 86400:
            continue
        if any(len(term) >= 2 and term.casefold() in text.casefold() for term in terms):
            result.append(copy.deepcopy(row))
    return result[:5]


ASSET_REFERENCE_NOTES = {
    'money': '货币市场利率或短期现金管理参考；须明确利率与价格的区别',
    'bond': '债券价格或全收益指数；不能用股票行业行情代替',
    'short_bond': '明确期限范围的短久期债券价格或全收益指数',
    'long_bond': '明确期限范围的中长久期债券价格或全收益指数',
    'convertible_bond': '可转债价格或全收益指数',
}
COMPANY_REFERENCE_NOTES = {
    'commodities': '已核验金属采矿与油气业务的资源企业股票等权样本指标；不是商品现货或期货价格',
}


def sector_data_diagnostics(board, quote, history, sources, as_of):
    """Explain actual collection gaps without turning an outage into a signal."""
    identity = board['id']
    source_map = {item.get('id'): item for item in sources}
    expected = (quote or {}).get('name') or (
        DIRECT_INDICES.get(identity, (None, None, None))[1]) or (
        VERIFIED_REFERENCES.get(identity, {}).get('title')) or (
        COMPANY_REFERENCE_NOTES.get(identity)) or (
        ASSET_REFERENCE_NOTES.get(identity)) or ' / '.join(QUOTE_NAMES.get(identity, []))
    attached, gaps = set(), []

    def gap(code, message, ids=()):
        ids = [value for value in ids if value in source_map]
        attached.update(ids)
        gaps.append({'code': code, 'message': message, 'source_ids': ids})

    if quote:
        attached.add(quote.get('source_id'))
        if not _quote_fresh(quote, as_of) or _number(quote.get('change_pct')) is None:
            gap('quote_stale', '参考行情时间缺失、已过期或无有效涨跌幅，当前不评分。', [quote.get('source_id')])
        else:
            history_id = 'sector_history:' + str(quote.get('history_secid'))
            attached.add(history_id)
            fresh = _history_fresh(history, quote, as_of)
            if len(history) < MIN_HISTORY or not fresh:
                failed = source_map.get(history_id, {}).get('status') in {'error', 'timeout'}
                gap('history_source_failed' if failed else 'history_missing',
                    '已取得报价，但历史行情采集失败，暂只作短期观察。' if failed else
                    '已取得报价，尚缺至少61个有效交易日的近期历史，暂只作短期观察。', [history_id])
        summary = gaps[0]['message'] if gaps else quote.get('name', '参考指数') + ' · 行情与近期历史已取得'
    elif identity in COMPANY_REFERENCE_NOTES:
        ids = [key for key in source_map if key.startswith('public:business:') and key.endswith(':' + identity)]
        gap('company_evidence_unavailable', '资源企业股票样本的业务归属、有效报价或共同历史尚未齐备；补齐公司数据后计算股票样本指标。', ids)
        summary = '资源企业股票样本数据待补齐'
    elif (identity in ASSET_REFERENCE_NOTES and identity not in DIRECT_INDICES
          and identity not in VERIFIED_REFERENCES):
        gap('asset_source_missing', '尚未接入此资产的专属参考行情；股票行业与概念榜不能提供该指标。')
        summary = '专属资产行情尚未接入'
    else:
        ids = (['sector_indices_tencent'] if identity in DIRECT_INDICES else [])
        if identity in VERIFIED_REFERENCES:
            ids.append('sector_reference:' + identity)
        if identity in QUOTE_NAMES:
            ids += ['sector_quotes_industry', 'sector_quotes_concept']
        known_mapping = identity in QUOTE_NAMES or identity in DIRECT_INDICES or identity in VERIFIED_REFERENCES
        failed_ids = [key for key in ids if source_map.get(key, {}).get('status') in {'error', 'timeout', 'partial'}]
        if not known_mapping:
            gap('quote_mapping_missing', '尚未配置与此方向范围明确对应的参考行情；需要先核对指标口径。')
            summary = '专属参考指标尚未配置'
        elif failed_ids:
            gap('quote_source_failed', '关联行情来源本次采集失败或覆盖不完整，未取得本方向有效报价。', ids)
            summary = '行情来源采集失败，等待有效报价'
        else:
            gap('quote_not_returned', '已配置参考指标，但本次来源未返回名称与时点均有效的对应报价。', ids)
            summary = '本次未返回对应的有效报价'
    return {'data_gaps': gaps, 'data_status_summary': summary,
            'reference_expected': expected or '待核对与本方向直接对应的参考指标',
            'sources': [copy.deepcopy(item) for item in sources if item.get('id') in attached]}


def analyze_sector(board, quote, history, sources, news, as_of, regime):
    if quote and quote.get('asset_type') == 'money_rate':
        return analyze_money_sector(board, quote, history, sources, as_of)
    row = {**copy.deepcopy(board), 'status': 'missing', 'score': None, 'recommendation_index': None,
           'change_pct': None, 'trend': '资料待补充', 'risk': '资料不足', 'as_of': None,
           'severity': 'normal', 'signal': 'neutral', 'indicator_reason': '',
           'quote': None, 'metrics': history_metrics([], as_of), 'sources': [],
           'news': _related_news(board, news, as_of), 'score_components': {},
           'reasons': [], 'risks': [], 'next_steps': [], 'score_method': SCORE_METHOD,
           'analysis_scope': '板块参考指数；不代表全行业每只股票表现或可执行交易建议'}
    row.update(sector_data_diagnostics(board, quote, history, sources, as_of))
    if not quote:
        row.update(summary=row['data_gaps'][0]['message'],
                   reasons=[gap['message'] for gap in row['data_gaps']],
                   risks=['缺少有效整体行情，趋势、风险与研究指数尚不能评估。'],
                   next_steps=['核对本方向的专属参考指标与来源，并在取得有效行情后重新计算。'])
        return row
    row.update(quote=copy.deepcopy(quote), as_of=quote.get('as_of'), change_pct=quote.get('change_pct'))
    source_ids = {quote.get('source_id'), 'sector_history:' + str(quote.get('history_secid'))}
    row['sources'] = [copy.deepcopy(item) for item in sources if item.get('id') in source_ids]
    row['reasons'].append(f'参考系列：{quote["name"]}；该系列口径可能与本方向的全部覆盖范围不同。')
    if quote.get('scope_note'):
        row['reasons'].append(quote['scope_note'])
    if not _quote_fresh(quote, as_of) or _number(quote.get('change_pct')) is None:
        row.update(status='stale', trend='等待新行情', risk='行情时效不足',
                   summary='已找到对应系列，但行情时点缺失、过期或晚于采集时间，研究指数保持未知。',
                   risks=['旧行情不作为当前信号。'], next_steps=['等待该板块下一次有效行情披露后重新计算。'])
        return row
    history_fresh = _history_fresh(history, quote, as_of)
    marked = mark_to_market_history(history, quote, as_of)
    metrics = history_metrics(marked, as_of)
    metrics['is_intraday'] = bool(marked and marked[-1].get('provisional'))
    if not history_fresh:
        metrics = history_metrics([], as_of)
        history = []
    enough = len(history) >= MIN_HISTORY
    row.update(status='ok' if enough else 'partial', metrics=metrics)
    change = quote['change_pct']
    if quote.get('asset_type') == 'convertible_bond':
        result = score_convertible(metrics, change, regime) if enough else None
        high_risk = regime.get('mode', 'unknown') in {'defensive', 'unknown'} or change <= -2 or (
            metrics['annual_volatility'] is not None and metrics['annual_volatility'] >= 25) or (
            metrics['max_drawdown'] is not None and metrics['max_drawdown'] <= -12)
        row.update(status='ok' if result else 'partial', history_complete=enough,
            score_method=CONVERTIBLE_SCORE_METHOD, analysis_scope=quote.get('scope_note', '境内上市可转债指数参考'),
            trend=('近20日上行' if metrics['return_20d'] > 0 else '近20日下行' if metrics['return_20d'] < 0 else '近20日持平')
                  if metrics['return_20d'] is not None else '历史待补充',
            risk='股性与信用风险需关注' if high_risk else '转股、信用及条款风险未完整核验',
            asset_research={'asset_type': 'convertible_bond',
                'financial_applicability': '不采用股票龙头财务样本代替转债信用研究；本轮未接入各发行人最新财务和评级，不能据此认定信用安全。',
                'credit_data_status': 'unavailable', 'valuation_data_status': 'unavailable',
                'conversion_premium': None, 'yield_to_maturity': None, 'redemption_terms_status': 'unavailable',
                'coverage_note': '仅对官方可转债参考指数的历史走势评分；转股溢价、到期收益率、发行人信用及强赎回售条款未知，未纳入评分。'},
            data_status_summary='官方可转债参考指数 · ' + ('独立可转债趋势模型已计算' if result else '近期历史待补齐'))
        if result:
            row.update(score=result['raw_score'], recommendation_index=result['score'],
                score_components=result['components'], score_model='convertible_trend_v1', score_cap=result['score_cap'])
            if change <= -3 or metrics['return_20d'] <= -8 and metrics['max_drawdown'] <= -15:
                row.update(severity='critical', indicator_reason='可转债市场走势风险：日跌幅至少3%，或20日跌幅至少8%且窗口回撤至少15%；不是发行人违约或强赎判定。')
            elif result['score'] >= 75 and not high_risk and all(metrics[key] > 0 for key in ('return_5d', 'return_20d', 'ma20_gap')):
                row.update(signal='trend_excellent', indicator_reason='可转债趋势优：专用趋势分至少75，5日与20日上涨且高于均线；信用和估值仍需单独核验。')
        row['summary'] = ('可转债指数走势研究：' + row['trend'] +
            (f'，综合研究分数 {result["score"]}/100。' if result else '；近期历史不足，暂不评分。') +
            '信用、转股估值及强赎回售条款尚未核验。')
        row['reasons'].append(f'官方可转债指数最近日变动 {change:+.2f}%，日期 {quote["as_of"]}；历史 {len(history)} 点。')
        row['risks'] = ['转债同时受到正股走势、信用、利率和流动性影响；普通国债波动模型不适用。',
            '缺少发行人财务评级、转股溢价及条款数据，不能判断单只转债性价比、到期保障或强赎风险。',
            '本轮未取得编制方案PDF，利息和派息处理细节尚未核实；指数涨跌不是票面利率或到期收益率。']
        row['next_steps'] = ['更新同一官方可转债指数历史；补充发行人财务评级、转股溢价及强赎回售公告后，另行核验信用与估值。']
        return row
    if quote.get('asset_type') == 'bond':
        kind = {'total_return': '全收益指数', 'net_price': '净价指数',
                'full_price': '全价指数', 'full_price_with_coupon': '含息及派息指数'}.get(quote.get('return_type'), '债券参考指数')
        bond_score = score_bond(metrics) if enough else None
        row.update(status='ok' if bond_score else 'partial', history_complete=enough,
                   trend=('近20日上行' if metrics['return_20d'] > 0 else
                          '近20日下行' if metrics['return_20d'] < 0 else '近20日持平')
                         if metrics['return_20d'] is not None else '历史待补充',
                   risk='利率与久期风险',
                   score_method=BOND_SCORE_METHOD,
                   summary=f'已接入{quote["name"]}（{kind}），最新日变动 {change:+.2f}%；' +
                           (f'债券趋势研究指数 {bond_score["score"]}/100。' if bond_score else '近期历史不足61个有效点，暂不评分。'),
                   data_status_summary=f'{kind}行情已接入；' + ('独立债券趋势模型已计算' if bond_score else '历史不足，等待评分'))
        if bond_score:
            row.update(score=bond_score['score'], recommendation_index=bond_score['score'],
                       score_components=bond_score['components'], score_model='bond_trend_v1')
            if metrics['max_drawdown'] <= -5 and metrics['return_20d'] <= -2:
                row.update(severity='critical', indicator_reason='债券趋势风险：窗口回撤至少5%且20日跌幅至少2%；非信用违约判断。')
            elif bond_score['score'] >= 75 and metrics['return_5d'] > 0 and metrics['return_20d'] > 0 and metrics['ma20_gap'] > 0:
                row.update(signal='trend_excellent', indicator_reason='债券趋势优：完整近期历史、债券趋势指数至少75分，5日与20日上涨且高于均线；不代表保本。')
        row['reasons'].append(f'最新日变动 {change:+.2f}%，数据日期 {quote["as_of"]}。')
        if metrics['return_20d'] is not None:
            row['reasons'].append(f'近20个交易日 {metrics["return_20d"]:+.2f}%；窗口最大回撤 {metrics["max_drawdown"]:.2f}%。')
        row['risks'] = [f'此处为{kind}的历史变动，不能按债券到期收益率或银行存款利率解读。',
                        '利率上行会给债券价格带来压力，期限越长通常越敏感；历史趋势不能保证后续收益。']
        if quote.get('return_type') == 'total_return':
            row['risks'].append('全收益口径包含利息及再投资等编制规则影响，不等同于净价涨跌。')
        elif quote.get('return_type') == 'full_price_with_coupon':
            row['risks'].append('该系列含应计利息及派息，区别于单纯净价及另行发布的利息再投资系列。')
        row['next_steps'] = ['继续更新同一债券指数的日线，观察利率变化与久期风险。']
        return row
    up, down = quote.get('up_count'), quote.get('down_count')
    breadth = up / (up + down) if up is not None and down is not None and up + down > 0 else None
    components = {'base': 50.0, 'daily_change': round(_clamp(change * 4, -15, 15), 3)}
    if breadth is not None:
        components['breadth'] = round((breadth - .5) * 20, 3)
    if metrics['return_5d'] is not None:
        components['momentum_5d'] = round(_clamp(metrics['return_5d'], -10, 10), 3)
    if metrics['return_20d'] is not None:
        components['momentum_20d'] = round(_clamp(metrics['return_20d'] * .7, -12, 12), 3)
    if metrics['ma20_gap'] is not None:
        components['trend_20d'] = 6 if metrics['ma20_gap'] > 0 else (-6 if metrics['ma20_gap'] < 0 else 0)
    if metrics['annual_volatility'] is not None:
        components['volatility_penalty'] = round(-min(12, max(0, metrics['annual_volatility'] - 30) * .4), 3)
    if metrics['max_drawdown'] is not None:
        components['drawdown_penalty'] = round(-min(15, abs(metrics['max_drawdown']) * .4), 3)
    score = round(_clamp(sum(components.values()), 0, 100))
    cap_mode = regime.get('mode', 'unknown')
    row.update(score=score if enough else None, recommendation_index=score if enough else None, score_components=components,
               history_complete=enough, breadth_up_ratio=round(breadth * 100, 2) if breadth is not None else None)
    row['reasons'].append(f'最新日涨跌幅 {change:+.2f}%，时间 {quote["as_of"]}。')
    if breadth is not None:
        row['reasons'].append(f'参考板块上涨 {up} 家、下跌 {down} 家；上涨占有方向样本 {breadth * 100:.1f}%（不含平盘/停牌）。')
    if enough:
        row['trend'] = '趋势偏强' if metrics['return_20d'] > 0 and metrics['ma20_gap'] > 0 else (
            '趋势偏弱' if metrics['return_20d'] < 0 and metrics['ma20_gap'] < 0 else '趋势分化')
        row['reasons'].append(f'近20日 {metrics["return_20d"]:+.2f}%；近60日 {metrics["return_60d"]:+.2f}%；'
                              f'年化波动 {metrics["annual_volatility"]:.2f}%；窗口最大回撤 {metrics["max_drawdown"]:.2f}%。')
    else:
        row['trend'] = '日内偏强' if change > 0 else ('日内偏弱' if change < 0 else '日内持平')
        row['risks'].append('历史序列少于61个有效交易日，只能作短期观察，不能据此判断持续趋势。')
    risk_high = cap_mode in ('defensive', 'unknown') or change <= -3 or (
        metrics['annual_volatility'] is not None and metrics['annual_volatility'] >= 40) or (
        metrics['max_drawdown'] is not None and metrics['max_drawdown'] <= -15)
    row['risk'] = '高风险' if risk_high else ('波动需关注' if abs(change) >= 1.5 or cap_mode == 'cautious' else '常规波动')
    if change <= -5 or (enough and metrics['return_20d'] <= -10 and metrics['max_drawdown'] <= -25):
        row.update(severity='critical', indicator_reason='量化特大风险提示：日跌幅至少5%，或20日跌幅至少10%且窗口回撤至少25%。')
    elif (enough and row['recommendation_index'] >= 75 and not risk_high
          and metrics['return_5d'] > 0 and metrics['return_20d'] > 0 and metrics['ma20_gap'] > 0):
        row.update(signal='trend_excellent', indicator_reason='趋势优：历史样本完整、研究指数至少75分，5日及20日上涨且高于20日均线，未触发高风险。')
    row['summary'] = (f'{row["trend"]}，研究指数 {row["recommendation_index"]}/100；{row["risk"]}。' if enough else
                      f'{row["trend"]}；近期历史不足61个有效交易日，暂不评分；{row["risk"]}。')
    row['risks'] += ['板块日线为参考指数表现，不包含未知交易成本，也不保证未来收益。',
                     '消息仅采用公开公告和官方政策；关键词关联及已采集正文不代表完整事件覆盖。']
    if cap_mode in ('defensive', 'cautious', 'unknown'):
        row['risks'].append('市场处于' + regime.get('label', '资料不足') + '状态；市场风险独立提示，研究分数不代表风险已解除。')
    row['next_steps'] = ['下一交易日出现新报价后重新计算，核对趋势与板块内部涨跌是否同步改善。',
                         '出现政策变化、异常放量或参考指数跌回20日均线下方时及时复核。']
    return row


def analyze_money_sector(board, quote, history, sources, as_of):
    from research_reference_fallbacks import score_money_rate
    result = score_money_rate(history, as_of) if _quote_fresh(quote, as_of) else None
    ids = {quote.get('source_id'), 'sector_history:' + str(quote.get('history_secid'))}
    row = {**copy.deepcopy(board), 'quote': copy.deepcopy(quote), 'as_of': quote.get('as_of'),
        'status': 'ok' if result else 'partial', 'score': result['score'] if result else None,
        'recommendation_index': result['score'] if result else None,
        'score_scope': 'money_liquidity', 'score_label': '资金利率研究分数',
        'score_model': 'money_liquidity_v1', 'score_components': result['components'] if result else {},
        'score_method': result['method'] if result else '等待至少61个有效利率观测点。',
        'history_complete': bool(result), 'change_pct': None,
        'trend': result['trend'] if result else '利率历史待补齐', 'risk': result['risk'] if result else '流动性与利率风险',
        'severity': 'normal', 'signal': 'neutral', 'indicator_reason': '',
        'metrics': result['metrics'] if result else {'sample_count': len(history)},
        'analysis_scope': quote.get('scope_note', ''), 'sources': [copy.deepcopy(s) for s in sources if s.get('id') in ids],
        'news': [], 'reasons': [quote.get('scope_note', '')],
        'risks': ['本指标观察银行间资金利率变化，不是投资收益、货币产品净值或保本判断。'],
        'next_steps': ['继续更新同一利率期限的官方观测，核对资金松紧变化。'], 'data_gaps': [],
        'data_status_summary': '隔夜资金利率与专用流动性模型已接入' if result else '利率观测或近期历史仍待补齐',
        'reference_expected': quote.get('name', '')}
    row['summary'] = ('隔夜资金利率观察，研究分数 '+str(result['score'])+'/100；不代表资产回报。'
                      if result else '资金利率观测尚未达到专用模型条件，保持未评分。')
    return row


def mark_reference_score(sector):
    """A price-series score has an explicit scope, never company-composite status."""
    sector.update(score_scope='reference_trend', score_label='参考走势分数', score_model='reference_trend_v1')
    sector['score_method'] = ('参考指数走势专用模型；仅含已取得的价格趋势、波动、回撤；市场风险另列；'
        '公司业务、财务与重要事件未计入此分，不属于完整公司综合分。' + SCORE_METHOD)
    if sector.get('recommendation_index') is not None:
        sector['summary'] = (f'参考走势研究：{sector["trend"]}，走势分数 {sector["recommendation_index"]}/100；'
                             '公司财务尚未纳入，不作为完整公司综合结论。')
    sector['reasons'].append('当前评分仅对应明确标注的参考指数或有限市场样本；公司财务待单独核验。')


def run_sector_research(progress=None, previous=None, refresh=False, data_config=None, include_events=False):
    update = progress or (lambda stage, details=None: None)
    update('正在采集市场与板块直接行情', {'sector_done': 0, 'sector_total': 0})
    catalog = sector_catalog()
    prior_public = (previous or {}).get('_public_report', {})
    quote_only = bool((previous or {}).get('_public_only') and prior_public)
    with ThreadPoolExecutor(max_workers=5) as pool:
        common_future = pool.submit(collect_sector_market)
        quote_future = pool.submit(collect_sector_quotes)
        index_future = pool.submit(fetch_text, EXTRA_INDEX_URL, 'gbk')
        reference_future = pool.submit(collect_verified_references, now_iso())
        macro_future = pool.submit(collect_macro_risk, now_iso())
        snapshot = common_future.result()
        quotes, sources = quote_future.result()
        reference_quotes, reference_sources, reference_histories = reference_future.result()
        macro_evidence, macro_source = macro_future.result()
        index_source = {'id': 'sector_indices_tencent', 'name': '腾讯财经 · 板块基准指数',
                        'url': EXTRA_INDEX_URL, 'status': 'ok', 'fetched_at': now_iso()}
        try:
            indices = parse_direct_indices(index_future.result())
            index_source.update(count=len(indices), as_of=max((row['as_of'] for row in indices if row.get('as_of')), default=None))
            if not indices:
                index_source.update(status='partial', error='未取得有效基准指数')
        except Exception:
            indices = []
            index_source.update(status='error', count=0, as_of=None, error='基准指数行情连接失败')
    snapshot['scope'] = '只研究市场、板块行情、行业成分、公司财务及公开公告和官方政策；板块清单不代表数据已完整接入。'
    as_of = now_iso()
    snapshot['as_of'] = as_of
    snapshot['sources'].extend(sources + [index_source, macro_source] + reference_sources)
    matches = match_sector_quotes(catalog, quotes, indices, reference_quotes)
    histories, history_sources = collect_sector_histories(
        {key: quote for key, quote in matches.items()
         if not str(quote.get('history_secid', '')).startswith('official:')}, as_of, update,
        cached=prior_public.get('_quote_histories') if quote_only else None)
    histories.update(reference_histories)
    snapshot['sources'].extend(history_sources)
    # Replace the complete reference pair when a primary quote exists but its
    # own recent history is unavailable. Never splice two providers' levels.
    for quote in reference_quotes:
        identity = quote.get('board_id')
        current = matches.get(identity)
        old_history = histories.get((current or {}).get('history_secid'), [])
        new_history = histories.get(quote.get('history_secid'), [])
        if (identity in {b['id'] for b in catalog} and _quote_fresh(quote, as_of)
                and len(new_history) >= MIN_HISTORY and _history_fresh(new_history, quote, as_of)
                and (not current or len(old_history) < MIN_HISTORY or not _history_fresh(old_history, current, as_of))):
            matches[identity] = quote
    overseas_boards = [b for b in catalog if b.get('group') == 'overseas'
        and (not matches.get(b['id']) or not _history_fresh(histories.get(matches[b['id']].get('history_secid'), []), matches[b['id']], as_of)
             or len(histories.get(matches[b['id']].get('history_secid'), [])) < MIN_HISTORY)]
    if overseas_boards:
        from research_overseas import collect_overseas_references
        extra_quotes, extra_sources, extra_histories = collect_overseas_references(overseas_boards, as_of)
        snapshot['sources'].extend(extra_sources)
        # Composite inputs retain their own verified identities and dates even
        # when they are not independent catalog cards (e.g. Australia/Brazil).
        histories.update(extra_histories)
        for quote in extra_quotes:
            identity = quote.get('board_id') or quote.get('sector_id')
            if identity and _quote_fresh(quote, as_of) and len(extra_histories.get(quote.get('history_secid'), [])) >= MIN_HISTORY:
                matches[identity] = quote
                histories[quote['history_secid']] = extra_histories[quote['history_secid']]
    if any(b['id'] == 'money' for b in catalog) and not matches.get('money'):
        from research_reference_fallbacks import collect_money_reference
        extra_quotes, extra_sources, extra_histories = collect_money_reference(as_of)
        snapshot['sources'].extend(extra_sources)
        for quote in extra_quotes:
            matches['money'] = quote
        histories.update(extra_histories)
    if prior_public:
        from research_live_update import retain_reference_closes
        retain_reference_closes(matches,histories,snapshot['sources'],prior_public,as_of)
    # Free BaoStock is the default company-evidence provider.  The legacy
    # Tushare path remains available only when explicitly requested by a
    # caller that supplies ``provider=tushare``; the website no longer asks
    # users for a paid Tushare token.
    provider = str((data_config or {}).get('provider') or ('baostock' if isinstance(data_config, dict) else 'none')).lower()
    stable_company_at = prior_public.get('company_evidence_as_of') or prior_public.get('as_of', '')
    reuse_company = bool(quote_only and str(stable_company_at)[:10] == as_of[:10]
                         and prior_public.get('company_evidence', {}).get('sector_leaders'))
    if reuse_company:
        from research_live_update import refresh_company_quotes
        company = refresh_company_quotes(prior_public['company_evidence'], as_of)
        from research_sample_policy import financial_ready
        # A partial first scan must not freeze missing sectors for the rest of
        # the session. Retry only deficient directions, at most every 15 min.
        repair = [b for b in catalog if b.get('group') in {'industry', 'broad', 'style', 'overseas'}
                  and (len(company.get('sector_leaders', {}).get(b['id'], [])) < 2
                       or not all(financial_ready(r, as_of) for r in company['sector_leaders'].get(b['id'], [])))]
        attempted = company.get('recovery_attempt_at')
        from research_leader_index import stamp
        if repair and (not stamp(attempted) or (stamp(as_of) - stamp(attempted)).total_seconds() >= 900):
            from research_public_data import gather_public_company_evidence
            repaired = gather_public_company_evidence(repair, as_of)
            for identity, rows in repaired.get('sector_leaders', {}).items():
                if rows:
                    company['sector_leaders'][identity] = rows
            company['sources'].extend(repaired['sources'])
            company.setdefault('selection_universes', {}).update(repaired.get('selection_universes', {}))
            company['recovery_attempt_at'] = as_of
    elif provider in {'tushare', 'tushare_pro'} and (data_config or {}).get('token'):
        from research_tushare import gather_sector_company_evidence
        company = gather_sector_company_evidence(catalog, data_config, as_of)
    elif provider == 'baostock' and isinstance(data_config, dict):
        from research_free_data import gather_free_sector_company_evidence
        if data_config.get('secondary_provider') == 'public_multisource':
            from research_public_data import gather_public_company_evidence
            # Preserve the original connection, but avoid spending 45 seconds on
            # a failing industry endpoint when publisher members are available.
            company = gather_public_company_evidence(catalog, as_of)
            if not company['sector_leaders']:
                fallback = gather_free_sector_company_evidence(catalog, as_of)
                fallback['sources'] = company['sources'] + fallback['sources']
                fallback['warnings'] = company['warnings'] + fallback['warnings']
                company = fallback
        else:
            company = gather_free_sector_company_evidence(catalog, as_of)
    else:
        from research_tushare import gather_sector_company_evidence
        company = gather_sector_company_evidence(catalog, {}, as_of)
    # Quotes are observed after the scan starts. Validate their native dates
    # against collection completion rather than treating a new tick as future.
    as_of = now_iso()
    snapshot['as_of'] = as_of
    from research_evidence_resilience import retain_company_components, retain_closed_baskets, remember_company_evidence
    retain_company_components(company, prior_public.get('company_evidence', {}), as_of, catalog)
    snapshot['sources'].extend(company['sources'])
    snapshot['warnings'].extend(company['warnings'])
    from research_leader_index import collect_leader_histories, build_indicator, apply_indicator, refresh_custom_scores
    update('正在编制龙头样本独立指标：采集公司日线、核对等权历史', {'sector_total': len(catalog)})
    prior_company_source_count = len(company['sources'])
    collect_leader_histories(company, as_of)
    retain_closed_baskets(company, as_of)
    from research_sample_policy import finalize_company_samples
    finalize_company_samples(company, as_of)
    snapshot['sources'].extend(company['sources'][prior_company_source_count:])
    # Repeated quote ticks must not append the same evidence indefinitely.
    company['sources'] = list({s['id']: s for s in company['sources']}.values())
    remember_company_evidence(company, as_of)
    snapshot['sources'] = list({s['id']: s for s in snapshot['sources']}.values())
    custom = {}
    for board in catalog:
        leaders = company['sector_leaders'].get(board['id'], [])
        bundle = build_indicator(board, leaders, as_of)
        if bundle:
            snapshot['sources'].append(bundle['source'])
            reference = matches.get(board['id'])
            reference_history = histories.get((reference or {}).get('history_secid'), [])
            reference_complete = bool(reference and _quote_fresh(reference, as_of)
                and len(reference_history) >= MIN_HISTORY and _history_fresh(reference_history, reference, as_of))
            if prefer_company_indicator(board, bundle, leaders, reference_complete, as_of):
                custom[board['id']] = bundle
    official = {'events': [], 'sources': [], 'warnings': []}
    if include_events and quote_only:
        official = {'events': copy.deepcopy(prior_public.get('event_candidates', [])),
                    'sources': [], 'warnings': []}
        from research_event_ai import OFFICIAL_EVENT_SOURCES
        official['sources'] = [copy.deepcopy(s) for s in prior_public.get('snapshot', {}).get('sources', [])
                               if s.get('id') in OFFICIAL_EVENT_SOURCES]
        snapshot['sources'] = [s for s in snapshot['sources'] if s.get('id') not in OFFICIAL_EVENT_SOURCES]
        snapshot['sources'].extend(official['sources'])
        snapshot['news'] = copy.deepcopy(prior_public.get('snapshot', {}).get('news', []))
    elif include_events:
        from research_official_events import collect_official_events
        update('正在读取上市公司公告和官方产业政策正文', {'sector_total': len(catalog)})
        official = collect_official_events(catalog, leaders=company['sector_leaders'], as_of=as_of)
        snapshot['sources'].extend(official['sources'])
        snapshot['warnings'].extend(official['warnings'])
        # The raw evidence is kept private to the research pipeline; the page
        # shows only assessed material events, rather than an unfiltered feed.
        snapshot['news'].extend(official['events'])
    snapshot['sentiment'] = build_sentiment(snapshot)
    panic = _pressure(snapshot)
    prior = previous if isinstance(previous, dict) else {}
    prior_strategy = prior.get('strategy', prior)
    regime = _regime(panic, prior_strategy)
    update('正在生成各板块趋势、风险与研究理由', {'sector_done': len(matches), 'sector_total': len(catalog),
                                                'deep_done': len(matches), 'deep_total': len(catalog)})
    sectors = [analyze_sector(board, custom[board['id']]['quote'] if board['id'] in custom else matches.get(board['id']),
                             custom[board['id']]['history'] if board['id'] in custom else histories.get((matches.get(board['id']) or {}).get('history_secid'), []),
                             snapshot['sources'], snapshot['news'], as_of, regime)
               for board in catalog]
    for sector in sectors:
        sector['leaders'] = copy.deepcopy(company['sector_leaders'].get(sector['id'], []))
        if sector['id'] in custom:
            sector['reference_quote'] = copy.deepcopy(matches.get(sector['id']))
            apply_indicator(sector, custom[sector['id']], sector['leaders'], as_of)
        sector['sources'].extend(copy.deepcopy(source) for source in company['sources']
            if source['id'] in {source_id for leader in sector['leaders'] for source_id in leader.get('source_ids', [])})
        if not sector['leaders']:
            membership_failures = [source for source in company['sources']
                if source.get('id') == 'public:members:' + sector['id']
                and source.get('status') in {'error', 'timeout', 'partial'}]
            if membership_failures:
                sector['data_gaps'].append({'code': 'company_membership_unavailable',
                    'message': '本板块公司成分来源本次未成功，尚无法核对业务归属并编制公司研究样本；具体原因见对应数据来源。',
                    'source_ids': [source['id'] for source in membership_failures]})
                known_sources = {source.get('id') for source in sector['sources']}
                sector['sources'].extend(copy.deepcopy(source) for source in membership_failures
                    if source.get('id') not in known_sources)
        if sector['leaders'] and sector['status'] == 'missing':
            sector['summary'] = '已取得本行业代表公司的成分与收盘数据，可研究经营和事件；板块整体涨跌与推荐指数仍待板块行情。'
        elif sector.get('group') == 'industry' and not sector['leaders']:
            company_failures = [source for source in company['sources']
                                if source.get('id') == 'baostock:stock_industry'
                                and source.get('status') in {'error', 'timeout', 'partial'}]
            if company_failures:
                sector['data_gaps'].append({'code': 'company_evidence_unavailable',
                    'message': '公司行业成分来源本次未成功，尚无可核对的代表公司与财务样本；指数行情仍可单独观察。',
                    'source_ids': [source['id'] for source in company_failures]})
                sector['sources'].extend(copy.deepcopy(company_failures))
        if sector.get('group') == 'industry' and (not sector['leaders'] or not all(r.get('financials') for r in sector['leaders'])):
            if not any(gap['code'] in {'company_evidence_unavailable', 'company_membership_unavailable'}
                       for gap in sector['data_gaps']):
                sector['data_gaps'].append({'code': 'company_evidence_unavailable',
                    'message': '本方向公司成分或部分代表公司财务仍有缺口；可查看指数走势分项，综合研究分数须待三项条件全部满足。',
                    'source_ids': []})
        quote_ready = bool(sector.get('quote') and _quote_fresh(sector['quote'], as_of))
        company_needed = sector.get('group') in {'industry', 'broad', 'style', 'overseas'}
        companies_ready = bool(sector['leaders']) and all(_company_financial_ready(r, as_of) for r in sector['leaders'])
        reference_only = bool(company_needed and sector.get('quote')
            and sector['id'] not in custom and sector.get('quote', {}).get('mapping_basis')
            and sector.get('quote', {}).get('asset_type') in {'equity', 'equity_index'})
        if reference_only:
            mark_reference_score(sector)
            company_needed = False
        data_ready = quote_ready and sector.get('history_complete') and (companies_ready or not company_needed)
        sector['requirements'] = [
            {'id': 'data', 'label': '有效数据', 'status': 'ok' if data_ready else 'partial' if quote_ready or sector['leaders'] else 'missing',
             'note': '行情、近期历史与代表公司财务样本已取得' if data_ready and company_needed else
                     '仅参考走势所需报价与近期历史已取得；公司财务未纳入' if data_ready and reference_only else
                     '隔夜利率观测及专用历史已取得；非股票财务或产品回报' if data_ready and sector.get('score_scope') == 'money_liquidity' else
                      '可转债专属参考指数与近期历史已取得；信用、转股估值及条款未接入，不属于模型已核验范围' if data_ready and sector.get('quote', {}).get('asset_type') == 'convertible_bond' else
                     '债券专属行情与近期历史已取得；不使用股票公司财务' if data_ready else
                     '公司成分或财务样本仍有缺口' if quote_ready and company_needed and not companies_ready else '行情或近期历史仍需补齐'},
            {'id': 'mapping', 'label': '明确指标映射', 'status': 'ok' if quote_ready else 'partial' if sector.get('reference_expected') else 'missing',
             'note': sector['quote'].get('mapping_basis') or sector['quote'].get('name', '') if quote_ready else sector.get('reference_expected', '尚待核对')},
            {'id': 'model', 'label': '专用评分模型', 'status': 'ok' if sector.get('recommendation_index') is not None else 'partial',
             'note': '公司研究模型 v2，基础数据已满足，事件与评分覆盖另列' if sector.get('score_model') == 'company_research_v2' and sector.get('recommendation_index') is not None else
                     '参考走势专用模型，仅评价价格序列；未纳入公司财务' if reference_only else
                     '隔夜利率变化专用流动性模型' if sector.get('score_scope') == 'money_liquidity' else
                      '独立可转债趋势模型 v1，仅评分官方转债指数走势；未评估单券信用与估值' if sector.get('score_model') == 'convertible_trend_v1' else
                     '独立债券趋势模型 v1，已完成计算' if sector.get('score_model') == 'bond_trend_v1' else
                     '股票趋势与市场风险模型，已完成计算' if sector.get('recommendation_index') is not None else '等待有效行情与足够历史后计算'},
        ]
    refresh_custom_scores({'sector_analysis': sectors, 'strategy': {'regime': regime}, 'as_of': as_of})
    for sector in sectors:
        enforce_score_requirements(sector)
    coverage = {'sector_count': len(sectors), 'quoted_sector_count': sum(bool(row.get('quote')) for row in sectors),
                'reference_quoted_sector_count': len(matches),
                'scored_sector_count': sum(row['recommendation_index'] is not None for row in sectors),
                'complete_history_count': sum(row.get('history_complete') is True for row in sectors),
                'news_count': len(snapshot['news']), 'provider_sector_count': len(quotes),
                'source_count': len(snapshot['sources']),
                'source_ok_count': sum(source.get('status') == 'ok' for source in snapshot['sources']),
                'missing_sector_count': sum(row['status'] == 'missing' for row in sectors)}
    coverage['company_sector_count'] = sum(bool(row['leaders']) for row in sectors)
    coverage['financial_sector_count'] = sum(bool(row['leaders']) and all(_company_financial_ready(r, as_of) for r in row['leaders']) for row in sectors)
    coverage['bond_scored_count'] = sum(row.get('score_model') == 'bond_trend_v1' for row in sectors)
    coverage['convertible_bond_scored_count'] = sum(row.get('score_model') == 'convertible_trend_v1' and row.get('recommendation_index') is not None for row in sectors)
    coverage['fully_ready_sector_count'] = sum(all(r['status'] == 'ok' for r in row['requirements']) for row in sectors)
    coverage['custom_indicator_count'] = len(custom)
    coverage['custom_scored_count'] = sum(row.get('score_model') == 'company_research_v2' and row.get('recommendation_index') is not None for row in sectors)
    indices_overview = [{**row, 'value': row.get('last'), 'status': 'ok' if _quote_fresh(row, as_of) else 'stale'}
                        for row in snapshot.get('market', [])]
    strategy = {'schema_version': 1, 'panic': panic, 'regime': regime, 'macro_evidence': macro_evidence,
                'summary': panic['summary'], 'minimum_holding_days': 7,
                'trade_execution': False, 'research_scope': 'sectors'}
    report = {'research_scope': 'sectors', 'sector_schema_version': SECTOR_SCHEMA_VERSION, 'as_of': as_of,
            'snapshot': snapshot, 'sector_analysis': sectors, 'coverage': coverage, 'strategy': strategy,
            'company_evidence': company, 'event_candidates': official['events'],
            'company_evidence_as_of': stable_company_at if reuse_company else as_of,
            '_quote_histories': {key: {'rows': rows, 'source': next((s for s in snapshot['sources']
                if s['id'] == 'sector_history:' + key), {})} for key, rows in histories.items()
                if not key.startswith('leader:')},
            'market_overview': {'as_of': as_of, 'indices': indices_overview, 'scope': '市场指数与板块直接报价'},
            'analysis': {'summary': f'已整理{len(sectors)}个板块，{coverage["custom_indicator_count"]}个已建独立龙头样本指标，{coverage["scored_sector_count"]}个方向已有指标分或阶段分；完整公司研究档位与待评估状态另列。',
                         'market_view': panic['summary'], 'risks': ['板块研究指数为规则化观察工具，未知数据标注 *****。'],
                         'next_steps': ['按研究时间计划继续更新板块行情、趋势风险与相关事件。']},
            'model': '自建龙头样本指标 + 业绩证据 + 重要事件 + 市场风险研究', 'engine': 'automatic',
            'automatic': {'interval_seconds': RESEARCH_INTERVAL, 'minimum_holding_days': 7,
                          'paid_api_calls': False, 'runs_while_server_online': True,
                          'trade_execution': False, 'research_scope': 'sectors'}}
    refresh_custom_scores(report)
    report['market_sentiment'] = build_market_sentiment(report)
    report['market_liquidity'] = build_market_liquidity(report)
    return report
