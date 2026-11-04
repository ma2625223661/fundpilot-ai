"""Bounded Tushare data access and evidence for industry representative stocks.

This module does not infer a business theme from a stock's display name.  Its
industry membership is provider evidence; size/liquidity selects representative
samples, not a claim that a company is the business leader of that industry.
"""
import copy
import hashlib
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from research_data import CHINA
from research_sample_policy import MAX_SAMPLES

API_URL = 'https://api.tushare.pro'
DOC_URL = 'https://tushare.pro/document/2?doc_id='
MAX_BYTES = 8_000_000
_cache = {}
_cache_lock = threading.RLock()
_rate_lock = threading.Lock()
_last_request = 0.0
DOCS = {'daily': 27, 'daily_basic': 32, 'index_member_all': 335,
        'index_classify': 181, 'fina_indicator': 79, 'trade_cal': 26,
        'stock_basic': 25}


class TushareError(Exception):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def _now():
    return datetime.now(CHINA).isoformat(timespec='seconds')


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed.astimezone(CHINA)
    except (ValueError, TypeError):
        return datetime.now(CHINA)


def _error_from_response(code, message):
    text = str(message)
    if any(word in text for word in ('token', 'TOKEN', 'Token', '认证', '无效凭证')):
        return TushareError('authentication', 'Tushare Token 无效，请重新保存')
    if any(word in text for word in ('权限', '积分', '访问该接口', '许可')):
        return TushareError('permission', '当前账号没有此接口权限或积分不足')
    if any(word in text for word in ('频率', '每分钟', '每小时', '频次', '访问次数', '流量')):
        return TushareError('rate_limit', '当前接口调用频率或配额已达限制')
    return TushareError('provider', 'Tushare 数据服务暂未完成请求')


def _transport(payload):
    request = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'FundPilotSectorResearch/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise TushareError('format', '数据响应超过大小限制')
        return json.loads(data.decode('utf-8'))
    except TushareError:
        raise
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise TushareError('authentication', 'Tushare 身份校验未通过') from None
        if error.code == 429:
            raise TushareError('rate_limit', '当前接口调用频率或配额已达限制') from None
        raise TushareError('network', 'Tushare 服务连接失败') from None
    except (TimeoutError, OSError):
        raise TushareError('network', 'Tushare 服务连接失败或超时') from None
    except (ValueError, UnicodeError):
        raise TushareError('format', 'Tushare 返回的数据格式无效') from None


class TushareClient:
    def __init__(self, token, transport=None, request_budget=40):
        if not isinstance(token, str) or not token.strip() or len(token) > 512:
            raise TushareError('authentication', '请先配置 Tushare Token')
        self._token = token.strip()
        self._fingerprint = hashlib.sha256(self._token.encode()).hexdigest()
        self._transport = transport or _transport
        self.request_budget = request_budget
        self.request_count = 0

    def query(self, api_name, params=None, fields='', ttl=300):
        global _last_request
        if api_name not in DOCS:
            raise TushareError('request', '不支持的数据接口')
        key = (self._fingerprint, api_name, json.dumps(params or {}, sort_keys=True), fields)
        now = time.monotonic()
        if ttl:
            with _cache_lock:
                hit = _cache.get(key)
                if hit and hit[0] > now:
                    return copy.deepcopy(hit[1])
        if self.request_count >= self.request_budget:
            raise TushareError('budget', '本轮数据请求预算已用完，未覆盖部分留待下轮')
        # Only actual HTTP requests wait. Test transports remain instantaneous.
        if self._transport is _transport:
            with _rate_lock:
                delay = 1.25 - (time.monotonic() - _last_request)
                if delay > 0:
                    time.sleep(delay)
                _last_request = time.monotonic()
        self.request_count += 1
        try:
            result = self._transport({'api_name': api_name, 'token': self._token,
                                      'params': params or {}, 'fields': fields})
        except TushareError:
            raise
        except Exception:
            # Provider errors and callbacks must never return arbitrary text
            # containing a credential into the report or configuration file.
            raise TushareError('network', 'Tushare 服务连接失败或超时') from None
        if not isinstance(result, dict) or not isinstance(result.get('code'), int) or isinstance(result.get('code'), bool):
            raise TushareError('format', 'Tushare 返回的数据格式无效')
        if result['code'] != 0:
            raise _error_from_response(result['code'], result.get('msg'))
        data = result.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('fields'), list) or not isinstance(data.get('items'), list):
            raise TushareError('format', 'Tushare 返回的数据格式无效')
        columns, items = data['fields'], data['items']
        if len(columns) > 200 or any(not isinstance(k, str) for k in columns) or len(set(columns)) != len(columns):
            raise TushareError('format', 'Tushare 返回的数据字段无效')
        if len(items) > 10_000 or any(not isinstance(row, list) or len(row) != len(columns) for row in items):
            raise TushareError('format', 'Tushare 返回的数据行无效')
        rows = [dict(zip(columns, row)) for row in items]
        if any(self._token in json.dumps(row, ensure_ascii=False) for row in rows):
            raise TushareError('format', 'Tushare 返回的数据包含不应展示的内容')
        if ttl:
            with _cache_lock:
                if len(_cache) > 512:
                    _cache.clear()
                _cache[key] = (time.monotonic() + ttl, copy.deepcopy(rows))
        return rows


def probe_tushare(token, client_factory=None):
    client = (client_factory or TushareClient)(token)
    end = datetime.now(CHINA).date()
    start = (end - timedelta(days=40)).strftime('%Y%m%d')
    end = end.strftime('%Y%m%d')
    probes = [
        ('daily', {'ts_code': '000001.SZ', 'start_date': start, 'end_date': end}, 'ts_code,trade_date,close'),
        ('daily_basic', {'ts_code': '000001.SZ', 'start_date': start, 'end_date': end}, 'ts_code,trade_date,total_mv'),
        ('index_member_all', {'ts_code': '000001.SZ', 'is_new': 'Y'}, 'ts_code,l1_name,l2_name,l3_name'),
        ('index_classify', {'level': 'L1', 'src': 'SW2021'}, 'index_code,industry_name'),
        ('fina_indicator', {'ts_code': '000001.SZ'}, 'ts_code,ann_date,end_date,roe'),
        ('trade_cal', {'exchange': 'SSE', 'start_date': start, 'end_date': end}, 'cal_date,is_open'),
    ]
    capabilities = {}
    authenticated = False
    for api_name, params, fields in probes:
        try:
            rows = client.query(api_name, params, fields, ttl=0)
            authenticated = True
            capabilities[api_name] = {'status': 'available' if rows else 'empty', 'count': len(rows),
                                      'message': '已取得样本数据' if rows else '接口返回空数据，尚不能确认数据覆盖',
                                      'checked_at': _now()}
        except TushareError as error:
            capabilities[api_name] = {'status': error.category, 'count': 0,
                                      'message': str(error), 'checked_at': _now()}
            if error.category == 'authentication':
                break
    available = sum(value['status'] == 'available' for value in capabilities.values())
    status = 'verified' if available == len(probes) else 'partial' if available else 'unverified' if authenticated else 'failed'
    return {'verification': status, 'capabilities': capabilities,
            'error': '' if status == 'verified' else '部分数据接口尚未取得有效数据，请查看各项权限状态'}


# Explicit industry labels, independent of company names. A narrow theme such as
# storage or memory chips is intentionally absent until business evidence exists.
INDUSTRY_LABELS = {
    'sector_insurance': {'保险', '保险Ⅱ', '保险Ⅲ'},
    'sector_semiconductor_equipment': {'半导体设备', '半导体材料'},
    'sector_semiconductor': {'半导体'},
    'sector_banking': {'银行'}, 'sector_securities': {'证券', '证券Ⅱ', '证券Ⅲ'},
    'sector_diversified_finance': {'多元金融'}, 'sector_nonbank': {'非银金融'},
    'sector_liquor': {'白酒', '白酒Ⅱ', '白酒Ⅲ'}, 'sector_food_beverage': {'食品饮料'},
    'sector_home_appliances': {'家用电器'}, 'sector_consumer_electronics': {'消费电子'},
    'sector_healthcare': {'医药生物'}, 'sector_medical': {'医疗器械', '医疗服务'},
    'sector_communication': {'通信'}, 'sector_pcb': {'印制电路板'},
    'sector_photovoltaic': {'光伏设备'}, 'sector_grid_equipment': {'电网设备'},
    'sector_power': {'电力'}, 'sector_utilities': {'公用事业'},
    'sector_coal': {'煤炭'}, 'sector_nonferrous': {'有色金属'}, 'sector_steel': {'钢铁'},
    'sector_chemicals': {'基础化工'}, 'sector_oil_gas': {'油气开采', '油服工程'},
    'sector_agriculture': {'农林牧渔'}, 'sector_transport': {'交通运输'},
    'sector_real_estate': {'房地产'}, 'sector_media': {'传媒'},
    'sector_auto_vehicle': {'乘用车', '商用车'}, 'sector_automotive': {'汽车'},
    'sector_construction_machinery': {'工程机械'}, 'sector_manufacturing': {'机械设备'},
    'sector_defense': {'国防军工'}, 'sector_environment': {'环保'},
    'sector_gold_equity': {'黄金', '黄金Ⅱ', '黄金Ⅲ'},
}


def board_ids_for_member(member, catalog):
    labels = {member.get(field) for field in ('l1_name', 'l2_name', 'l3_name')}
    return [row['id'] for row in catalog if labels.intersection(INDUSTRY_LABELS.get(row.get('id'), set()))]


def _source(api, status, count=0, as_of=None, error=None, suffix=''):
    row = {'id': 'tushare:' + api + (':' + suffix if suffix else ''), 'name': 'Tushare · ' + api,
           'url': DOC_URL + str(DOCS[api]), 'status': status, 'count': count,
           'as_of': as_of, 'fetched_at': _now(), 'scope': 'A股行业成分、代表股票及已披露财务；非基金数据'}
    if error:
        row['error'] = error
    return row


def gather_sector_company_evidence(catalog, config, as_of, client=None):
    result = {'status': 'not_configured', 'sources': [], 'sector_leaders': {}, 'warnings': [],
              'selection_method': '按申万行业成分确认归属，再按总市值和流动性选择最多8只交易代表；不等同于主营业务龙头认定',
              'request_count': 0}
    if not isinstance(config, dict) or not config.get('token'):
        result['warnings'].append('尚未配置 Tushare，行业成分与财务数据等待连接。')
        return result
    client = client or TushareClient(config['token'], request_budget=32)
    now = _stamp(as_of)
    today = now.strftime('%Y%m%d')
    deadline = time.monotonic() + 55

    def get(api, params=None, fields='', ttl=300, suffix=''):
        try:
            if time.monotonic() >= deadline:
                raise TushareError('budget', '本轮数据采集时间预算已用完，未覆盖部分留待下轮')
            rows = client.query(api, params, fields, ttl=ttl)
            result['sources'].append(_source(api, 'ok' if rows else 'partial', len(rows), suffix=suffix))
            return rows
        except TushareError as error:
            result['sources'].append(_source(api, 'error', error=str(error), suffix=suffix))
            result['warnings'].append(str(error))
            return []

    calendar_capability = (config.get('capabilities') or {}).get('trade_cal', {})
    full_year_calendar = isinstance(calendar_capability, dict) and calendar_capability.get('status') == 'available'
    calendar = get('trade_cal', {'exchange': 'SSE',
                                 'start_date': f'{now.year}0101' if full_year_calendar else (now - timedelta(days=25)).strftime('%Y%m%d'),
                                 'end_date': f'{now.year}1231' if full_year_calendar else today},
                   'exchange,cal_date,is_open', ttl=6 * 3600)
    if full_year_calendar and calendar:
        # A short date range cannot establish annual holiday coverage. The
        # calendar registry independently requires every day exactly once and
        # atomically rejects incomplete, malformed or mixed-exchange data.
        from research_trading_calendar import register_trade_calendar
        try:
            register_trade_calendar(calendar, now.year, DOC_URL + str(DOCS['trade_cal']), as_of)
            result['calendar_registered_year'] = now.year
        except ValueError:
            result['warnings'].append('年度交易日历返回不完整或格式无效，保留原已核验日历，不据此假定开市日。')
    # daily data is published after the close; morning and 14:30 runs use the
    # previous available close and explicitly label it as such.
    dates = [row.get('cal_date') for row in calendar if str(row.get('is_open')) == '1'
             and re.fullmatch(r'\d{8}', str(row.get('cal_date', '')))
             and row['cal_date'] <= today
             and (row['cal_date'] < today or now.hour >= 18)]
    if not dates:
        result['status'] = 'unavailable'
        result['warnings'].append('未取得可靠的最近交易日期，暂不请求或推测股票日线。')
        result['request_count'] = client.request_count
        return result
    day = max(dates)
    daily = get('daily', {'trade_date': day}, 'ts_code,trade_date,close,pct_chg,vol,amount', ttl=12 * 3600)
    basic = get('daily_basic', {'trade_date': day},
                'ts_code,trade_date,total_mv,circ_mv,turnover_rate,volume_ratio,pe_ttm,pb', ttl=12 * 3600)
    prices = {row.get('ts_code'): row for row in daily if re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', str(row.get('ts_code', '')))}
    sizes = {row.get('ts_code'): row for row in basic}
    classifications = get('index_classify', {'level': 'L1', 'src': 'SW2021'},
                          'index_code,industry_name', ttl=7 * 86400)
    # First run prioritises precise finance and semiconductor classifications.
    priority = {'非银金融': 0, '电子': 1, '电力设备': 2, '银行': 3, '医药生物': 4}
    classifications.sort(key=lambda row: (priority.get(row.get('industry_name'), 10), str(row.get('industry_name'))))
    members = []
    membership_ids = {}
    for classification in classifications:
        if client.request_count >= 24 or time.monotonic() >= deadline:
            result['warnings'].append('本轮行业成分采集达到请求预算，剩余行业下轮继续；已成功结果使用缓存。')
            break
        code = classification.get('index_code')
        if not re.fullmatch(r'\d{6}\.SI', str(code)):
            continue
        rows = get('index_member_all', {'l1_code': code, 'is_new': 'Y'},
                   'l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new',
                   ttl=7 * 86400, suffix=code)
        for row in rows:
            entry, exit_date = str(row.get('in_date') or ''), str(row.get('out_date') or '')
            if (entry and entry > today) or (exit_date and exit_date <= today) or row.get('is_new') == 'N':
                continue
            if not re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', str(row.get('ts_code', ''))):
                continue
            members.append(row)
            membership_ids[row['ts_code']] = 'tushare:index_member_all:' + code
        if len(rows) >= 2000:
            result['warnings'].append('单个行业成分达到接口单次上限，覆盖可能不完整。')
    grouped = {}
    for member in members:
        code = member['ts_code']
        if code not in prices or _number(sizes.get(code, {}).get('total_mv')) is None:
            continue
        # Risk labels only exclude samples; display names never establish theme membership.
        if 'ST' in str(member.get('name') or '').upper() or '退' in str(member.get('name') or ''):
            continue
        for board_id in board_ids_for_member(member, catalog):
            grouped.setdefault(board_id, {})[code] = member
    finance_cache = {}
    for board_id, mapped in grouped.items():
        ordered = sorted(mapped, key=lambda code: (-(_number(sizes[code].get('total_mv')) or 0),
                                                   -(_number(prices[code].get('amount')) or 0), code))[:MAX_SAMPLES]
        leaders = []
        for code in ordered:
            member, price, size = mapped[code], prices[code], sizes[code]
            if code not in finance_cache and client.request_count < 32 and time.monotonic() < deadline:
                rows = get('fina_indicator', {'ts_code': code},
                           'ts_code,ann_date,end_date,roe,eps,netprofit_yoy,tr_yoy,grossprofit_margin',
                           ttl=12 * 3600, suffix=code)
                # Date-only disclosures cannot prove publication before 09:10 or
                # 14:30 today. Use prior-day disclosures conservatively.
                usable = [r for r in rows if re.fullmatch(r'\d{8}', str(r.get('ann_date', '')))
                          and r['ann_date'] < today and str(r.get('end_date') or '') <= today]
                usable.sort(key=lambda row: (row.get('end_date') or '', row['ann_date']), reverse=True)
                finance_cache[code] = usable[0] if usable else None
            source_ids = [membership_ids[code], 'tushare:daily', 'tushare:daily_basic']
            financials = finance_cache.get(code)
            if financials:
                source_ids.append('tushare:fina_indicator:' + code)
            leaders.append({'ts_code': code, 'name': member.get('name') or code,
                            'industry': member.get('l3_name') or member.get('l2_name') or member.get('l1_name'),
                            'role': '行业交易代表样本（主营龙头身份待核对）',
                            'leader_verified': False,
                            'selection_basis': '行业成分归属；按总市值、成交额依次排序',
                            'quote': {**{key: price.get(key) for key in ('trade_date', 'close', 'pct_chg', 'vol', 'amount')},
                                      'data_kind': 'daily_close', 'is_intraday': False,
                                      'units': {'vol': '手', 'amount': '千元'}},
                            'market_metrics': {key: size.get(key) for key in ('total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio', 'pe_ttm', 'pb')},
                            'financials': copy.deepcopy(financials),
                            'financials_note': '仅使用采集日前已披露报告；披露日未提供时刻，当日报告不进入本轮',
                            'membership_evidence': {key: member.get(key) for key in ('l1_name', 'l2_name', 'l3_name', 'in_date', 'out_date')},
                            'as_of': datetime.strptime(day, '%Y%m%d').replace(hour=15, tzinfo=CHINA).isoformat(),
                            'source_ids': source_ids})
        result['sector_leaders'][board_id] = leaders
    result['status'] = 'partial' if result['sector_leaders'] else 'unavailable'
    result['request_count'] = client.request_count
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    result['warnings'].append('股票行情为最近已取得的收盘日线，不能代表14:30实时表现；行业代表样本不等同于已核验业务龙头。')
    return result


def collect_company_announcements(leaders, config=None, as_of=None):
    """Keep public disclosure collection separate from restricted news APIs."""
    return {'status': 'not_connected', 'announcements': [], 'sources': [],
            'warnings': ['公司公告使用独立公开披露采集器；未将新闻摘要或财务日期当作公告全文。']}
