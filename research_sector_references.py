"""Verified public index references for sectors without a board quote.

The index identity and scope below were checked against the index publisher on
2026-10-31. Collection uses the publisher's public daily series, never a product
price. Daily dates are preserved as dates; no publication time is invented.
"""
from __future__ import annotations

import copy
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time
from pathlib import Path
from urllib.parse import urlencode

from research_data import CHINA, fetch_text, now_iso
from research_evidence_cache import load_record, save_record

CACHE_PATH=Path(__file__).resolve().parent/'data'/'verified-reference-cache.json'


CSI_BASE = 'https://www.csindex.com.cn/csindex-home/'
CNI_BASE = 'https://www.cnindex.com.cn/'
METHOD_BASE = ('https://oss-ch.csindex.com.cn/static/html/csindex/public/'
               'uploads/indices/detail/files/zh_CN/')
MAX_HISTORY = 121
LOOKBACK_DAYS = 210
COLLECTION_BUDGET_SECONDS = 12
MAX_WORKERS = 6


def _csi(code, title, name, scope_note, asset_type='equity', return_type='price'):
    return {'provider': 'csindex', 'code': code, 'title': title, 'name': name,
            'aliases': [title, name], 'asset_type': asset_type, 'return_type': return_type,
            'scope_note': scope_note,
            'official_url': CSI_BASE + 'indexInfo/index-basic-info/' + code,
            # These exact files were fetched successfully; other identities
            # rely on the publisher's checked basic-info endpoint instead.
            'methodology_url': (METHOD_BASE + code + '_Index_Methodology_cn.pdf'
                                if code in {'000944', '931479', 'H11001', '931310'} else None),
            'verified_on': '2026-10-31'}


VERIFIED_REFERENCES = {
    'sector_cloud_computing': _csi(
        '930851', '中证云计算与大数据主题指数', '云计算',
        '以云计算与大数据服务及相关硬件设备上市公司为样本；作为云计算主题参考，不代表全部科技股。'),
    'sector_resources': _csi(
        '000944', '中证内地资源主题指数', '内地资源',
        '境内资源股主题参考，反映相关上市公司股票表现；不代表商品现货或期货价格。'),
    'sector_nonbank': _csi(
        '931479', '中证证券保险领先指数', '证券保险',
        '选取证券保险行业规模较大、业务领先或估值相对较低的代表性上市公司；不含银行，不代表所有非银公司。'),
    'bond': _csi(
        'H11001', '中证全债指数', '中证全债',
        '境内国债、地方债、金融债及信用债等综合参考；以净价、应计利息及派息计算，'
        '非单纯净价，亦非另列的N11001利息再投资指数。',
        asset_type='bond', return_type='full_price_with_coupon'),
    'long_bond': _csi(
        '931310', '中证国债及政策性金融债7-10年指数', '国债及政金债7-10',
        '7–10年国债及政策性金融债参考；编制方案入样剩余期限为6.5年以上、10年及以下，'
        '不是实际久期，也不覆盖所有中长债。含应计利息及派息，非另列的N31310利息再投资指数。',
        asset_type='bond', return_type='full_price_with_coupon'),
    'convertible_bond': _csi(
        '000832', '中证可转换债券指数', '中证转债',
        '样本为沪深证券交易所上市的可转换债券，作为境内转债市场参考；不是普通国债、股票或基金。'
        '本轮已核对官方指数身份和日线；编制方案PDF未取得，派息与利息再投资细节尚未核实，'
        '不将指数变动解释为到期收益率。发行人信用评级、转股溢价及强赎回售条款尚未接入。',
        asset_type='convertible_bond', return_type='publisher_index'),
    'sector_ai_application': {
        'provider': 'cnindex', 'code': '980112', 'title': '国证AI应用指数', 'name': 'AI应用',
        'aliases': ['国证AI应用指数', 'AI应用'], 'asset_type': 'equity', 'return_type': 'price',
        'scope_note': '采用国证AI应用主题指数作为应用层参考；不以广义人工智能或传媒行业指数替代。',
        'official_url': CNI_BASE + 'index/selectIndexByCode?codeValue=980112',
        'methodology_url': CNI_BASE + 'module/index-detail.html?act_menu=1&indexCode=980112',
        'verified_on': '2026-10-31',
    },
}

# Publisher identities and descriptions checked through index-basic-info on
# 2026-10-31. These are declared references, never inferred from fund names.
for _board, _code, _title, _short, _scope in (
    ('sector_food_beverage', '000815', '中证细分食品饮料产业主题指数', '细分食品', '食品饮料细分行业中规模较大、流动性较好的公司，不使用包含其他必选消费行业的综合消费指数代替。'),
    ('sector_ai', '930713', '中证人工智能主题指数', 'CS人工智', '人工智能基础资源、技术及应用支持公司；不作为AI应用细分方向的替代。'),
    ('sector_innovative_drug', '931152', '中证创新药产业指数', 'CS创新药', '主营涉及创新药研发的代表性上市公司，不代表整个医药行业。'),
    ('sector_photovoltaic', '931151', '中证光伏产业指数', '光伏产业', '主营涉及光伏产业链上中下游的代表性公司。'),
    ('sector_robotics', 'H30590', '中证机器人指数', '机器人', '机器人系统、自动化设备及零部件等相关上市公司。'),
    ('sector_chemicals', '000813', '中证细分化工产业主题指数', '细分化工', '化工细分行业规模较大、流动性较好的股票；不覆盖全部化工企业。'),
    ('sector_advanced_manufacturing', '930599', '中证高端装备制造指数', '中证高装', '通信、电力设备、机械、航空国防、电子、半导体及汽车零部件等高端装备代表公司。'),
    ('sector_semiconductor', '931865', '中证半导体产业指数', '中证半导', '半导体材料、设备与应用等核心产业；不代替存储芯片或材料设备专属方向。'),
    ('sector_gold_equity', '931238', '中证沪深港黄金产业股票指数', 'SSH黄金股票', '内地与香港黄金采掘、冶炼及销售股票；非黄金现货，A股公司样本不覆盖港股成分。'),
    ('sector_automotive', '931008', '中证全指汽车指数', '汽车指数', '整车与汽车零部件产业参考，不代替汽车整车专属板块。'),
    ('sector_transport', '000945', '中证内地运输主题指数', '内地运输', '沪深内地运输主题股票参考，不以商品运输价格或单一航运公司代替。'),
    ('sector_home_appliances', '930697', '中证全指家用电器指数', '家用电器', '中证全指样本中的家用电器行业；不以整个消费行业代替。'),
    ('sector_eldercare', '399812', '中证养老产业指数', '养老产业', '80只涉及健康管理、休闲旅游、人寿保险等养老产业相关业务的股票；不代表养老账户产品或纯养老服务业。'),
    ('sector_steel', '930606', '中证钢铁指数', '中证钢铁', '归属于钢铁行业的相关上市公司股票参考。'),
    ('style_bluechip', '000903', '中证A100指数', '中证A100', '选取100只市值较大、流动性较好且具有行业代表性的股票，作为核心龙头蓝筹参考，不宣称覆盖全部蓝筹公司。'),
    ('sector_fintech', '930986', '中证金融科技主题指数', '金融科技', '产品与服务涉及金融科技领域的上市公司；不以所有金融公司代替。'),
    ('style_cashflow', '932365', '中证全指自由现金流指数', '中证现金流', '选取100只自由现金流率较高的股票，作为现金流风格参考；指数身份不能替代每家公司的最新财务核验。'),
    ('sector_travel', '930633', '中证旅游主题指数', '中证旅游', '不超过50家涉及旅游住宿、游览、购物、娱乐、出行及综合服务等产业链的公司；不只覆盖酒店。'),
    ('style_dividend_low_volatility', 'H30269', '中证红利低波动指数', '红利低波', '50只连续分红、股息率较高且波动率低的股票，采用股息率加权；作为红利低波风格参考。'),
    ('sector_finance', '932075', '中证全指金融指数', '全指金融', '中证全指金融行业中符合市值与流动性筛选条件的代表公司，覆盖综合金融口径；不混入房地产。'),
    ('index_beijing', '899050', '北证50成份指数', '北证50', '北交所规模大、流动性好的50只代表股票，作为北证市场参考，不代表全部北交所股票。'),
):
    VERIFIED_REFERENCES[_board] = _csi(_code, _title, _short, _scope)

VERIFIED_REFERENCES['short_bond'] = _csi(
    'H11015', '中证短债指数', '中证短债',
    '一年期以下国债、金融债、企业债、央票及短期融资券参考；不是货币基金或存款。'
    '本轮已核对官方身份和日线，派息与再投资细节未核实，不将指数涨跌解释为到期收益率。',
    asset_type='bond', return_type='publisher_index')
VERIFIED_REFERENCES['index_chinext'] = {
    'provider': 'cnindex', 'code': '399006', 'title': '创业板指数', 'name': '创业板指',
    'aliases': ['创业板指数', '创业板指'], 'asset_type': 'equity', 'return_type': 'price',
    'scope_note': '深圳证券信息有限公司发布的创业板指数日线；不是科创板或双创50参考。',
    'official_url': CNI_BASE + 'index/selectIndexByCode?codeValue=399006',
    'methodology_url': CNI_BASE + 'module/index-detail.html?act_menu=1&indexCode=399006',
    'verified_on': '2026-10-31',
}

VERIFIED_REFERENCES['overseas_hk_dividend'] = dict(_csi(
    '930914', '中证港股通高股息投资指数', '港股通高股息',
    '30只符合港股通条件、流动性好、连续分红且股息率较高的香港股票，采用股息率加权。'
    '港元价格参考，不是全部港股、股息收益率或包含股息再投资的收益；未纳入公司财务。'),
    currency='HKD', reference_market='HK')
VERIFIED_REFERENCES['overseas_hugangshen_consumer'] = dict(_csi(
    '931663', '中证沪港深消费龙头指数', 'SHS消费龙头',
    '内地与香港市场50只市值较大、市占率较高、经营状况良好的消费公司股票参考；'
    '人民币计价价格指数，不代替全部消费股票。采用当前已发布指数日线，不推造公司财务。'),
    currency='CNY', reference_market='CN_HK')


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        raise ValueError('参考指数采集时间无效') from None
    return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _daily_cutoff(as_of):
    stamp = _timestamp(as_of)
    return stamp.date() if stamp.hour >= 15 else stamp.date() - timedelta(days=1)


def last_completed_reference_day(market, as_of):
    """Completed native sessions; a cross-market series uses the open-day union.

    CSI 931663 publishes on HK-only and mainland-only sessions. Its displayed
    daily observation is consumed after 16:30 China time, a conservative local
    session boundary, not an invented publisher timestamp.
    """
    if market == 'HK':
        from research_overseas import last_complete_session
        return last_complete_session('HK', as_of)
    if market != 'CN_HK':
        return None
    from research_overseas import is_session, session_close
    from research_trading_calendar import is_trading_day
    now = _timestamp(as_of)
    day = now.date()
    for _ in range(370):
        cn, hk = is_trading_day(day), is_session('HK', day)
        if cn is None or hk is None:
            return None
        # The full CSI cross-market observation is used only after both
        # markets' ordinary close, including half-day HK sessions.
        boundary = datetime.combine(day, time(16, 30), CHINA)
        if (cn or hk) and now >= boundary:
            return day.isoformat()
        day -= timedelta(days=1)
    return None


def reference_daily_quote_fresh(quote, as_of):
    """Keep native-market CSI dailies separate from the A-share calendar."""
    market = quote.get('market')
    if (quote.get('reference_market_daily') is not True or market not in {'HK', 'CN_HK'}
            or quote.get('currency') != ('HKD' if market == 'HK' else 'CNY')
            or quote.get('score_scope') != 'reference_trend'):
        return False
    expected = last_completed_reference_day(market, as_of)
    return bool(expected and quote.get('trade_date') == expected and quote.get('as_of') == expected)


def _reference_cutoff(reference, as_of):
    market = reference.get('reference_market')
    if not market:
        return _daily_cutoff(as_of)
    cutoff = last_completed_reference_day(market, as_of)
    if not cutoff:
        raise ValueError('参考指数当地交易日历超出已核验范围')
    return datetime.fromisoformat(cutoff).date()


def reference_history_url(reference, as_of):
    end = _timestamp(as_of).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    if reference['provider'] == 'csindex':
        return CSI_BASE + 'perf/index-perf?' + urlencode({
            'indexCode': reference['code'], 'startDate': start.strftime('%Y%m%d'),
            'endDate': end.strftime('%Y%m%d')})
    if reference['provider'] == 'cnindex':
        return CNI_BASE + 'market/market/getIndexDailyData?' + urlencode({
            'indexCode': reference['code'], 'startDate': start.isoformat(), 'endDate': end.isoformat()})
    raise ValueError('不支持的参考指数来源')


def _payload(data):
    if not isinstance(data, dict) or str(data.get('code')) != '200':
        raise ValueError('官方指数源返回错误或无效格式')
    return data.get('data')


def _check_identity(code, name, reference):
    if str(code) != reference['code'] or name not in reference['aliases']:
        raise ValueError('官方指数代码或名称与已核实的参考指数不一致')


def _finish_history(rows):
    ordered = [rows[key] for key in sorted(rows)][-MAX_HISTORY:]
    if not ordered:
        raise ValueError('官方指数源没有有效日线记录')
    return ordered


def parse_csindex_history(data, reference, as_of):
    """CSI changePct is already percent; index identity must match exactly."""
    raw, cutoff = _payload(data), _reference_cutoff(reference, as_of)
    if not isinstance(raw, list):
        raise ValueError('中证指数源未返回日线列表')
    rows = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        _check_identity(item.get('indexCode'), item.get('indexNameCnAll') or item.get('indexNameCn'), reference)
        try:
            day = datetime.strptime(str(item.get('tradeDate')), '%Y%m%d').date()
        except (ValueError, TypeError):
            continue
        close, change = _number(item.get('close')), _number(item.get('changePct'))
        if day > cutoff or close is None or close <= 0:
            continue
        rows[day.isoformat()] = {'date': day.isoformat(), 'close': close, 'return_pct': change}
    return _finish_history(rows)


def parse_cnindex_history(data, reference, as_of):
    """CNI item names define column order; percent is a ratio, not percent."""
    raw, cutoff = _payload(data), _reference_cutoff(reference, as_of)
    if not isinstance(raw, dict):
        raise ValueError('国证指数源未返回有效数据对象')
    _check_identity(raw.get('indexCode'), raw.get('indexName'), reference)
    columns, values = raw.get('item'), raw.get('data')
    if (not isinstance(columns, list) or not isinstance(values, list)
            or not {'timestamp', 'close', 'percent'}.issubset(columns)):
        raise ValueError('国证指数日线字段无效')
    positions = {name: columns.index(name) for name in ('timestamp', 'close', 'percent')}
    rows = {}
    for item in values:
        if not isinstance(item, list) or len(item) <= max(positions.values()):
            continue
        millis = _number(item[positions['timestamp']])
        if millis is None:
            continue
        try:
            day = datetime.fromtimestamp(millis / 1000, CHINA).date()
        except (ValueError, OverflowError, OSError):
            continue
        close = _number(item[positions['close']])
        ratio = _number(item[positions['percent']])
        if day > cutoff or close is None or close <= 0:
            continue
        rows[day.isoformat()] = {'date': day.isoformat(), 'close': close,
                                'return_pct': ratio * 100 if ratio is not None else None}
    return _finish_history(rows)


def _collect_one(board_id, reference, as_of):
    url = reference_history_url(reference, as_of)
    data = json.loads(fetch_text(url))  # research_data: verified TLS, 8s timeout, 4MB cap.
    history = (parse_csindex_history(data, reference, as_of) if reference['provider'] == 'csindex'
               else parse_cnindex_history(data, reference, as_of))
    last = history[-1]
    if last['return_pct'] is None:
        raise ValueError('最新官方日线缺少涨跌幅，不能生成当日行情')
    history_id = 'official:' + reference['provider'] + ':' + reference['code']
    quote = {
        'board_id': board_id, 'sector_id': board_id, 'code': reference['code'], 'name': reference['name'],
        'full_name': reference['title'], 'last': last['close'], 'change_pct': last['return_pct'],
        'as_of': last['date'], 'as_of_precision': 'date', 'data_frequency': 'daily',
        'source_id': 'sector_reference:' + board_id, 'source_url': url,
        'history_secid': history_id, 'up_count': None, 'down_count': None,
        'asset_type': reference['asset_type'], 'return_type': reference['return_type'],
        'score_scope': 'reference_trend',
        'scope_note': reference['scope_note'], 'official_url': reference['official_url'],
        'methodology_url': reference['methodology_url'],
        'mapping_basis': '官方参考指数：' + reference['title'] + '。' + reference['scope_note'],
    }
    if reference.get('reference_market'):
        quote.update(reference_market_daily=True, market=reference['reference_market'],
                     currency=reference['currency'], trade_date=last['date'])
    return quote, history


def _cached_one(board_id,reference,as_of):
    record=load_record(CACHE_PATH,board_id)
    if not isinstance(record,dict):return None
    quote,history=record.get('quote'),record.get('history')
    if not isinstance(quote,dict) or not isinstance(history,list) or len(history)<61:return None
    expected='official:'+reference['provider']+':'+reference['code']
    if (quote.get('code')!=reference['code'] or quote.get('full_name')!=reference['title']
            or quote.get('history_secid')!=expected or quote.get('source_id')!='sector_reference:'+board_id
            or not _number(quote.get('last')) or _number(quote.get('change_pct')) is None):return None
    if reference.get('reference_market'):
        fresh=reference_daily_quote_fresh(quote,as_of)
    else:
        from research_trading_calendar import a_share_quote_fresh
        fresh=a_share_quote_fresh(quote.get('as_of'),as_of,daily=True)
    if not fresh:return None
    try:
        dates=[r['date'] for r in history]
        if (dates!=sorted(set(dates)) or dates[-1]!=quote['as_of'] or any(
            _number(r.get('close')) is None or r['close']<=0 for r in history)
            or abs(history[-1]['close']-quote['last'])>1e-6):return None
    except (KeyError,TypeError,ValueError):return None
    source=_source(board_id,reference,as_of)
    source.update(status='ok',as_of=quote['as_of'],count=len(history),cache_used=True,
        fetched_at=record.get('fetched_at'),checked_at=now_iso(),note='使用仍符合最新完整交易日要求的已核验官方日线缓存，保留原始数据日期。')
    return copy.deepcopy(quote),copy.deepcopy(history),source


def collect_cached_references(as_of,**kwargs):
    return collect_verified_references(as_of,use_cache=True,**kwargs)


def collect_verified_references(as_of, *, budget_seconds=COLLECTION_BUDGET_SECONDS, board_ids=None,use_cache=False):
    """Return (quotes, sources, histories) within a bounded collection budget.

    histories uses each quote's history_secid. Each source retains its board id
    on failure, so a caller can show an exact missing-data diagnosis.
    """
    _timestamp(as_of)
    budget_seconds = min(COLLECTION_BUDGET_SECONDS, max(0.01, float(budget_seconds)))
    requested = set(board_ids) if board_ids is not None else None
    references = copy.deepcopy({k:v for k,v in VERIFIED_REFERENCES.items()
                                if requested is None or k in requested})
    quotes, sources, histories, completed = [], [], {}, set()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures={}
    pending=[]
    for board_id,reference in references.items():
        cached=_cached_one(board_id,reference,as_of) if use_cache else None
        if cached:
            quote,history,source=cached;quotes.append(quote);histories[quote['history_secid']]=history
            sources.extend([source,dict(source,id='sector_history:'+quote['history_secid'],name=source['name']+' · 日线历史')])
        else:pending.append((board_id,reference))
    if use_cache and requested is None and pending:
        # A failing first batch must not consume every scan's time budget and
        # permanently prevent later references from even starting. Persist the
        # next first item across restarts; cached observations stay date-checked.
        cursor=load_record(CACHE_PATH,'collection_cursor') or {}
        if not isinstance(cursor,dict):cursor={}
        ids=[board_id for board_id,_ in pending]
        start=ids.index(cursor.get('next_board_id')) if cursor.get('next_board_id') in ids else 0
        pending=pending[start:]+pending[:start]
        save_record(CACHE_PATH,'collection_cursor',{'next_board_id':pending[min(MAX_WORKERS,len(pending))%len(pending)][0]})
    for board_id,reference in pending:
        futures[pool.submit(_collect_one,board_id,reference,as_of)]=(board_id,reference)
    try:
        for future in as_completed(futures, timeout=budget_seconds):
            board_id, reference = futures[future]
            completed.add(board_id)
            source = _source(board_id, reference, as_of)
            try:
                quote, history = future.result()
                quotes.append(quote)
                histories[quote['history_secid']] = history
                source.update(status='ok', count=len(history), as_of=quote['as_of'])
                if len(history) < 61:
                    source.update(status='partial', error='官方历史有效点少于61个，仅能作短期观察')
                elif use_cache:
                    save_record(CACHE_PATH,board_id,{'quote':quote,'history':history,'fetched_at':source['fetched_at']})
                sources.append(dict(source, id='sector_history:' + quote['history_secid'],
                                    name=source['name'] + ' · 日线历史'))
            except Exception as exc:
                from research_transport import source_error
                source.update(status='error', error=source_error(exc, '官方指数日线未取得'))
            sources.append(source)
    except TimeoutError:
        pass
    finally:
        for future, (board_id, reference) in futures.items():
            if board_id not in completed:
                future.cancel()
                sources.append(dict(_source(board_id, reference, as_of), status='error',
                                    error='达到本轮官方参考指数采集时间预算，下一轮自动重试'))
        pool.shutdown(wait=False, cancel_futures=True)
    order = {board_id: i for i, board_id in enumerate(references)}
    quotes.sort(key=lambda row: order[row['board_id']])
    sources.sort(key=lambda row: (order[row['board_id']], row['id']))
    return quotes, sources, histories


def _source(board_id, reference, as_of):
    return {'id': 'sector_reference:' + board_id, 'board_id': board_id,
            'name': ('中证指数' if reference['provider'] == 'csindex' else '国证指数') + ' · ' + reference['title'],
            'url': reference_history_url(reference, as_of), 'official_url': reference['official_url'],
            'methodology_url': reference['methodology_url'], 'scope': reference['scope_note'],
            'asset_type': reference['asset_type'], 'return_type': reference['return_type'],
            'fetched_at': now_iso(), 'as_of': None, 'as_of_precision': 'date',
            'status': 'error', 'count': 0}
