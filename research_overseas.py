"""Dated HK/US representative-company research baskets.

This adapter uses fixed, disclosed representative samples, not a claim that
these are the largest three companies or that a basket represents the market.
Prices are completed local sessions only; no A-share calendar is reused.
"""
from __future__ import annotations

import copy
import gzip
import html
import json
import math
import os
import re
import threading
import time as clock_time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo

from research_data import CHINA, now_iso
from research_transport import fetch_bytes, decompress_gzip
from research_overseas_references import collect_overseas_references, reference_quote_fresh
from research_sample_policy import MAX_SAMPLES, CANDIDATE_LIMIT, financial_ready

HK_CALENDAR = 'https://www.hkex.com.hk/Services/Trading/Derivatives/Overview/Trading-Calendar-and-Holiday-Schedule?sc_lang=en'
US_CALENDAR = 'https://www.nyse.com/markets/hours-calendars'
VERSION = 'leader_equal_weight_v1'
MIN_HISTORY = 61
CACHE_PATH = Path(__file__).resolve().parent / 'data' / 'overseas-company-cache.json'
CACHE_LIMIT = 4_000_000
CACHE_ENTRY_LIMIT = 600_000
CACHE_MAX_ENTRIES = 128
_cache_lock = threading.RLock()
_cache = {}
try:
    if CACHE_PATH.stat().st_size <= CACHE_LIMIT:
        document = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        for key, row in document.get('datasets', {}).items():
            if (isinstance(row, dict) and isinstance(row.get('data'), str)
                and len(row['data'].encode('utf-8')) <= CACHE_ENTRY_LIMIT
                and isinstance(row.get('expires'), (float, int)) and row['expires'] > clock_time.time()):
                _cache[key] = row
except (OSError, ValueError, TypeError, AttributeError):
    pass
ZONES = {'HK': ZoneInfo('Asia/Hong_Kong'), 'US': ZoneInfo('America/New_York')}
# 2026 exchange holiday tables, independently checked 2026-10-31. Unknown
# years are closed to this adapter until their schedules have been checked.
CLOSURES = {
 'HK': set('2026-01-01 2026-02-17 2026-02-18 2026-02-19 2026-04-03 2026-04-06 2026-04-07 2026-05-01 2026-05-25 2026-06-19 2026-07-01 2026-10-01 2026-10-19 2026-12-25'.split()),
 'US': set('2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25'.split())}
HALF_DAYS = {'HK': set('2026-02-16 2026-12-24 2026-12-31'.split()),
             'US': set('2026-11-27 2026-12-24'.split())}

# Explicit editorial samples with issuer/SEC evidence, never inferred from a
# fund name or represented as complete official index constituents.
SAMPLES = {
 'overseas_hk_equity': [
   {'code':'00700.HK','name':'腾讯控股','official':'https://www.tencent.com/en-us/investors.html','tokens':['Tencent']},
   {'code':'09988.HK','name':'阿里巴巴','official':'https://www.alibabagroup.com/en-US/ir-home','tokens':['Alibaba'],'finance_cik':'0001577552'},
   {'code':'00005.HK','name':'汇丰控股','official':'https://www.hsbc.com/investors','tokens':['HSBC'],'finance_cik':'0001089113'}],
 'overseas_hk_innovative_drug': [
   {'code':'09926.HK','name':'康方生物','official':'https://www.akesobio.com/en/','tokens':['9926','biopharmaceutical']},
   {'code':'06160.HK','name':'百济神州 / BeOne','official':'https://www.beonemedicines.com/about/about-us/','tokens':['BeOne','oncology'],'finance_cik':'0001651308'}],
 'overseas_us_equity': [
   {'code':'AAPL.US','name':'苹果','cik':'0000320193'},
   {'code':'MSFT.US','name':'微软','cik':'0000789019'},
   {'code':'NVDA.US','name':'英伟达','cik':'0001045810'}],
 'overseas_healthcare': [
   {'code':'ABBV.US','name':'艾伯维 / AbbVie','cik':'0001551152',
    'business_url':'https://www.abbvie.com/who-we-are.html',
    'business_tokens':['AbbVie','creating medicines and solutions'],
    'business_description':'公司官网披露药物及治疗解决方案业务；为海外医药有限代表样本，并非整个海外医疗市场。'},
   {'code':'MRK.US','name':'默沙东 / Merck','cik':'0000310158',
    'business_url':'https://www.merck.com/company-overview/',
    'business_tokens':['Merck','biopharmaceutical','medicines','vaccines'],
    'business_description':'公司官网披露生物制药、药物及疫苗业务；不代表器械、医院或全部海外医药子行业。'}]}

# Additional candidates are optional until their own accounts and recent
# history pass verification; a failed new request cannot invalidate the core.
ADDITIONAL_SAMPLES = {
 'overseas_us_equity':[
   {'code':'AMZN.US','name':'亚马逊','cik':'0001018724'},
   {'code':'GOOG.US','name':'Alphabet','cik':'0001652044'},
   {'code':'META.US','name':'Meta Platforms','cik':'0001326801'},
   {'code':'BRK-B.US','name':'伯克希尔哈撒韦B','cik':'0001067983'},
   {'code':'JPM.US','name':'摩根大通','cik':'0000019617'}],
 'overseas_healthcare':[
   {'code':'LLY.US','name':'礼来 / Eli Lilly','cik':'0000059478','business_sec_sic':'2834'},
   {'code':'JNJ.US','name':'强生 / Johnson & Johnson','cik':'0000200406','business_sec_sic':'2834'},
   {'code':'PFE.US','name':'辉瑞 / Pfizer','cik':'0000078003','business_sec_sic':'2834'}],
 'overseas_hk_equity':[
   {'code':'09618.HK','name':'京东集团-SW','identity_cik':'0001549802','finance_cik':'0001549802',
    'sec_ticker':'JD','sec_name':'JD.com, Inc.','quote_name':'JD-SW'},
   {'code':'09999.HK','name':'网易','identity_cik':'0001110646','finance_cik':'0001110646',
    'sec_ticker':'NTES','sec_name':'NetEase, Inc.','quote_name':'NTES'},
   {'code':'09888.HK','name':'百度集团-W','identity_cik':'0001329099','finance_cik':'0001329099',
    'sec_ticker':'BIDU','sec_name':'Baidu, Inc.','quote_name':'BIDU-W'}]}

SAMPLES['overseas_hk_internet']=[
    dict(SAMPLES['overseas_hk_equity'][0],
        business_url='https://www.tencent.com/en-us/business.html',
        business_tokens=['Tencent','Weixin/WeChat','Tencent Games','Tencent Cloud'],
        business_description='腾讯官网明确列示微信、网络游戏与云服务；仅作为港股互联网及平台业务有限样本。'),
    dict(SAMPLES['overseas_hk_equity'][1],
        business_url='https://www.alibabagroup.com/en-US/about-alibaba',
        business_tokens=['Alibaba','Internet','commerce'],
        business_description='阿里官网明确列示互联网与商业平台、AI及云业务；不将全部收入视作纯互联网。'),
    dict(ADDITIONAL_SAMPLES['overseas_hk_equity'][1],
        business_url='https://www.neteasegames.com/',
        business_tokens=['online games division of NetEase, Inc.','NASDAQ: NTES and HKEX: 9999'],
        business_description='网易游戏官网列明其为NetEase线上游戏业务及美港上市代码；只代表港股线上娱乐样本。')]

# These issuers publish parallel CNY facts and USD convenience translations.
# Select the explicitly reported CNY series, never convert the two ourselves.
SEC_REPORTED_CURRENCY={1577552:'CNY',1549802:'CNY',1110646:'CNY',1329099:'CNY'}


def sample_specs(identity):
    return (SAMPLES.get(identity,[])+ADDITIONAL_SAMPLES.get(identity,[]))[:CANDIDATE_LIMIT]

SCOPE = '预先列明的代表公司样本，非全市场或全行业；不宣称全市场市值前三或主营业务市占率龙头认证。'
METHOD = ('独立代表公司样本指标：至多8家公司等权，当前样本固定回溯；共同首日=100，'
          '每天将样本收盘收益率取算术平均后连乘；港股采用供应商可取得的前复权序列，'
          '未返回复权序列时明确采用未复权价格序列（公司行为可能产生价格跳变），美股使用复权收盘。'
          '港股按香港交易日、美股按纽约交易日及夏令时核验，'
          '仅用当地已完成交易日，不将盘中数据当收盘。至少2只、全部样本共同覆盖最近61个当地交易日才评分。'
          '不代表官方指数或全市场表现，不是历史选样策略回测。综合趋势、已核验披露日的业绩、已评估重要事件；'
          '综合分还须满足有效数据、明确映射、专用模型三项条件，包括已核验披露日的公司财务证据；'
          '缺失财务证据时不提供综合分，未评估消息不计入事件调整。大盘约束采用全站A股市场风险，并非港美本地大盘风险。')


def _stamp(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed


def finite(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)


def is_session(market, day):
    day = date.fromisoformat(str(day)[:10]) if not isinstance(day,date) else day
    if market not in CLOSURES or day.year != 2026:
        return None
    return day.weekday() < 5 and day.isoformat() not in CLOSURES[market]


def session_close(market, day):
    day = date.fromisoformat(str(day)[:10]) if not isinstance(day,date) else day
    if not is_session(market, day):
        return None
    hour = (12 if market == 'HK' else 13) if day.isoformat() in HALF_DAYS[market] else 16
    # HK closing auction ends at 16:10; allow a short vendor publication delay
    # before consuming a full day's quote. This is deliberately conservative.
    minute = 15 if market == 'HK' and hour == 16 else 10
    return datetime.combine(day,time(hour,minute),ZONES[market])


def last_complete_session(market, as_of):
    if market not in ZONES:
        return None
    now = _stamp(as_of).astimezone(ZONES[market])
    day = now.date()
    for _ in range(370):
        opened = is_session(market,day)
        if opened is None:
            return None
        if opened and now >= session_close(market,day):
            return day.isoformat()
        day -= timedelta(days=1)
    return None


def recent_sessions(market, as_of, count=MIN_HISTORY):
    last = last_complete_session(market,as_of)
    if last is None:
        return []
    result=[]
    day=date.fromisoformat(last)
    for _ in range(370):
        opened=is_session(market,day)
        if opened is None:
            return []
        if opened:
            result.append(day.isoformat())
        if len(result)==count:
            return list(reversed(result))
        day-=timedelta(days=1)
    return []


def _fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; FundPilotLocalResearch/1.0; public research)',
        'Accept':'application/json,text/html,*/*'})
    body=fetch_bytes(request,timeout=15,max_bytes=16_000_000 if '/api/xbrl/companyfacts/' in url else 8_000_000)
    if body[:2]==b'\x1f\x8b':
        body=decompress_gzip(body)
    return body.decode('utf-8-sig',errors='replace')


SEC_TAGS = frozenset({'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
    'Revenue', 'SalesRevenueNet', 'RevenueAndOperatingIncome', 'NetIncomeLoss', 'ProfitLoss'})


def compact_sec_facts(payload):
    """Retain only fields consumed by the finance parser and audit identifiers.

    Full SEC companyfacts can exceed the entire domestic cache limit. Keeping
    these six facts, their units and original periods/filing dates preserves
    the calculation while bounding each persisted issuer document.
    """
    result = {k: payload[k] for k in ('cik', 'entityName') if k in payload}
    result['facts'] = {}
    for namespace in ('us-gaap', 'ifrs-full'):
        facts = payload.get('facts', {}).get(namespace, {})
        selected = {}
        for tag in SEC_TAGS.intersection(facts):
            units = {}
            for currency,rows in facts[tag].get('units', {}).items():
                if not re.fullmatch(r'[A-Z]{3}',currency):continue
                # Parsing deliberately keeps a dated audit trail; rows are
                # not reduced to a precomputed score or assumed release day.
                units[currency] = [{k: row[k] for k in
                    ('start','end','val','filed','accn','form','fy','fp','frame') if k in row}
                    for row in rows if isinstance(row, dict)]
            selected[tag] = {'units': units}
        if selected:
            result['facts'][namespace] = selected
    return result


def _compact_response(url, value):
    if '/api/xbrl/companyfacts/' in url:
        return json.dumps(compact_sec_facts(json.loads(value)), separators=(',', ':'), ensure_ascii=False)
    if '/submissions/CIK' in url:
        payload = json.loads(value)
        return json.dumps({k: payload[k] for k in ('cik','name','tickers','exchanges','sic','sicDescription') if k in payload},
            separators=(',', ':'), ensure_ascii=False)
    return value


def _cache_get(key):
    with _cache_lock:
        row = _cache.get(key)
        return row['data'] if row and row.get('expires',0)>clock_time.time() else None


def _cache_put(key, value, ttl, fetched_at=None, expires=None):
    if not isinstance(value,str) or len(value.encode('utf-8')) > CACHE_ENTRY_LIMIT:
        raise ValueError('海外缓存单项超过有界大小限制')
    with _cache_lock:
        _cache[key] = {'data': value, 'expires': expires or clock_time.time()+ttl,
            'fetched_at': fetched_at or now_iso()}


def _save_cache():
    with _cache_lock:
        rows = sorted(((k,r) for k,r in _cache.items() if r.get('expires',0)>clock_time.time()),
            key=lambda item:item[1].get('fetched_at',''),reverse=True)[:CACHE_MAX_ENTRIES]
        live = {}
        for key,row in rows:
            candidate = dict(live); candidate[key] = row
            if len(json.dumps({'datasets':candidate},ensure_ascii=False).encode('utf-8')) <= CACHE_LIMIT:
                live = candidate
        _cache.clear();_cache.update(live)
        try:
            CACHE_PATH.parent.mkdir(parents=True,exist_ok=True)
            temp=CACHE_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps({'datasets':live},ensure_ascii=False),encoding='utf-8')
            os.replace(temp,CACHE_PATH)
        except OSError:
            pass


def _cached(key, url, ttl=21600):
    result=_cache_get(key)
    if result is None:
        result=_compact_response(url,_fetch(url))
        _cache_put(key,result,ttl)
    return result


def migrate_legacy_cache(path=None):
    """Explicit, one-time migration; caller coordinates with other writers."""
    path=Path(path) if path else Path(__file__).resolve().parent/'data'/'public-company-cache.json'
    if not path.exists():return {'migrated':0,'removed':0}
    if path.stat().st_size>64_000_000:raise ValueError('旧共享缓存超过迁移读取上限')
    document=json.loads(path.read_text(encoding='utf-8'))
    rows=document.get('datasets',{})
    if not isinstance(rows,dict):raise ValueError('旧缓存格式不符')
    migrated=removed=0
    by_code={spec['code']:spec for identity in SAMPLES for spec in sample_specs(identity)}
    for key in list(rows):
        if not key.startswith('overseas:'):continue
        row=rows[key];new_key=key[len('overseas:'):];data=row.get('data') if isinstance(row,dict) else None
        removed+=1
        if isinstance(data,(str,dict,list)) and row.get('expires',0)>clock_time.time():
            if not isinstance(data,str):data=json.dumps(data,ensure_ascii=False,separators=(',',':'))
            if new_key.startswith('finance:'):
                spec=by_code.get(new_key[len('finance:'):])
                if spec:data=_compact_response(finance_url(spec),data)
            if new_key.startswith('official:'):
                spec=by_code.get(new_key[len('official:'):])
                if spec and spec.get('cik'):
                    data=_compact_response('https://data.sec.gov/submissions/CIK'+spec['cik']+'.json',data)
            if len(data.encode('utf-8'))<=CACHE_ENTRY_LIMIT:
                _cache_put(new_key,data,1,row.get('fetched_at'),row.get('expires'));migrated+=1
        del rows[key]
    _save_cache()
    temp=path.with_suffix('.overseas-migration.tmp')
    temp.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
    os.replace(temp,path)
    return {'migrated':migrated,'removed':removed,'public_bytes':path.stat().st_size,
            'overseas_bytes':CACHE_PATH.stat().st_size if CACHE_PATH.exists() else 0}


def history_url(code):
    if code.endswith('.HK'):
        return 'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk'+code[:5]+',day,,,121,qfq'
    if re.fullmatch(r'[A-Z][A-Z.\-]{0,9}\.US',code):
        return 'https://query1.finance.yahoo.com/v8/finance/chart/'+quote(code[:-3])+ '?interval=1d&range=6mo'
    raise ValueError('海外证券代码不合法')


def parse_history(payload,code,as_of):
    market='HK' if code.endswith('.HK') else 'US'
    cutoff=last_complete_session(market,as_of)
    if cutoff is None:
        raise ValueError('当地交易日历未经核验')
    points={}
    if market=='HK':
        series=payload.get('data',{}).get('hk'+code[:5],{})
        raw=series.get('qfqday') or series.get('day') or []
        adjustment='forward_adjusted' if series.get('qfqday') else 'unadjusted'
        unadjusted={r[0]:r[2] for r in series.get('day',[]) if isinstance(r,list) and len(r)>=3}
        # No raw close may be returned alongside a forward-adjusted series.
        # Preserve that absence; do not label an adjusted price as actual close.
        rows=[(r[0],r[2],r[2] if adjustment=='unadjusted' else unadjusted.get(r[0]))
              for r in raw if isinstance(r,list) and len(r)>=3]
    else:
        adjustment='adjusted'
        result=(payload.get('chart',{}).get('result') or [None])[0]
        if not isinstance(result,dict) or result.get('meta',{}).get('symbol')!=code[:-3]:
            raise ValueError('美股日线证券身份不符')
        meta=result['meta']
        if meta.get('currency')!='USD' or meta.get('exchangeTimezoneName')!='America/New_York':
            raise ValueError('美股日线币种或交易时区不符')
        indicators=result.get('indicators',{})
        adj=(indicators.get('adjclose') or [{}])[0].get('adjclose') or []
        closes=(indicators.get('quote') or [{}])[0].get('close') or []
        rows=[(datetime.fromtimestamp(ts,ZONES['US']).date().isoformat(),adj[i] if i<len(adj) else None,
                closes[i] if i<len(closes) else None) for i,ts in enumerate(result.get('timestamp',[]))]
    for day,value,unadjusted in rows:
        try:
            day=date.fromisoformat(day).isoformat()
            value=float(value);unadjusted=float(unadjusted) if unadjusted is not None else None
        except (ValueError,TypeError):
            continue
        if day<=cutoff and is_session(market,day) and finite(value) and value>0 and (unadjusted is None or finite(unadjusted) and unadjusted>0):
            points[day]={'date':day,'close':value,'unadjusted_close':unadjusted,'adjustment':adjustment}
    return [points[d] for d in sorted(points)][-121:]


def parse_sec_financials(payload,as_of):
    """Use filed financial facts and same-duration prior-year comparatives."""
    now=_stamp(as_of).astimezone(ZONES['US']).date()
    facts=payload.get('facts',{}).get('us-gaap') or payload.get('facts',{}).get('ifrs-full',{})
    revenue_tags=['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','Revenue','SalesRevenueNet','RevenueAndOperatingIncome']
    profit_tags=['NetIncomeLoss','ProfitLoss']
    def entries(tags,currency):
        out=[]
        for tag in tags:
            for row in facts.get(tag,{}).get('units',{}).get(currency,[]):
                try:
                    end=date.fromisoformat(row['end']);start=date.fromisoformat(row['start']);filed=date.fromisoformat(row['filed'])
                    if end<=filed<now and 0<=(now-end).days<=1100 and finite(row.get('val')) and 60<=(end-start).days<=380:
                        out.append(row)
                except (KeyError,ValueError,TypeError):
                    continue
        return out
    currencies={currency for tag in revenue_tags+profit_tags for currency in facts.get(tag,{}).get('units',{})
        if re.fullmatch(r'[A-Z]{3}',currency)}
    choices=[]
    preferred=SEC_REPORTED_CURRENCY.get(payload.get('cik'))
    for currency in currencies:
        if preferred and currency!=preferred:continue
        rev=entries(revenue_tags,currency);profit=entries(profit_tags,currency)
        if rev or profit:
            latest_end=max(r['end'] for r in rev+profit)
            choices.append((latest_end,sum(bool(rows) for rows in (rev,profit)),currency,rev,profit))
    if not choices:return {}
    best=max((r[0],r[1]) for r in choices)
    selected=[r for r in choices if (r[0],r[1])==best]
    # No silent conversion between two reported currencies for the same period.
    if len(selected)!=1:return {}
    _,_,currency,rev,profit=selected[0]
    if not rev and not profit:
        return {}
    latest=max(rev+profit,key=lambda r:(r['end'],r['filed'],r.get('start','')))
    if (now-date.fromisoformat(latest['end'])).days>550:
        return {}
    end=latest['end'];start=latest['start']
    def select(rows):
        same=[r for r in rows if r['end']==end and r['start']==start]
        return max(same,key=lambda r:r['filed']) if same else None
    r,p=select(rev),select(profit)
    def yoy(current,rows):
        if not current:return None
        duration=(date.fromisoformat(current['end'])-date.fromisoformat(current['start'])).days
        prev=[v for v in rows if 350<=(date.fromisoformat(current['end'])-date.fromisoformat(v['end'])).days<=378
              and abs((date.fromisoformat(v['end'])-date.fromisoformat(v['start'])).days-duration)<=10 and v['filed']<=current['filed']]
        prior=max(prev,key=lambda v:v['filed']) if prev else None
        return (current['val']/abs(prior['val'])-prior['val']/abs(prior['val']))*100 if prior and prior['val'] else None
    return {'ann_date':max(v['filed'] for v in (r,p) if v),'end_date':end,
        'tr_yoy':yoy(r,rev),'netprofit_yoy':yoy(p,profit),'revenue':r['val'] if r else None,
        'net_profit':p['val'] if p else None,'currency':currency,'source_note':'美国SEC XBRL；按列明币种、同区间同比，未混用单季与累计期；可能晚于本地市场最新报告'}


def finance_url(spec):
    if spec.get('finance_cik') or spec.get('cik'):
        return 'https://data.sec.gov/api/xbrl/companyfacts/CIK'+(spec.get('finance_cik') or spec['cik'])+'.json'
    return 'https://datacenter.eastmoney.com/securities/api/data/v1/get?'+urlencode({
        'reportName':'RPT_HKF10_FN_MAININDICATOR','columns':'ALL','filter':'(SECUCODE="'+spec['code']+'")',
        'pageSize':12,'pageNumber':1,'sortColumns':'REPORT_DATE','sortTypes':-1})


def parse_hk_financials(payload,code,as_of):
    now=_stamp(as_of).date()
    rows=[]
    for r in (payload.get('result') or {}).get('data',[]):
        try:
            end=date.fromisoformat(str(r.get('REPORT_DATE',''))[:10])
        except ValueError:
            continue
        if r.get('SECUCODE')==code and end<now and 0<=(now-end).days<=550:
            rows.append((end,r))
    if not rows:return {}
    end,row=max(rows,key=lambda r:r[0])
    # The HK source provides report periods but no publication day. Never
    # manufacture an announcement date or include it in financial adjustments.
    return {'ann_date':None,'end_date':end.isoformat(),'tr_yoy':row.get('OPERATE_INCOME_YOY'),
        'netprofit_yoy':row.get('HOLDER_PROFIT_YOY'),'roe':row.get('ROE_AVG'),'eps':row.get('BASIC_EPS'),
        'grossprofit_margin':row.get('GROSS_PROFIT_RATIO'),'currency':None,
        'currency_note':'财务报表币种尚未核验；不沿用证券交易币种',
        'publication_status':'unknown','source_note':'公开财务表未提供披露日期；只供报告期参考，不纳入业绩评分'}


def hk_income_url(code,end_date):
    return 'https://datacenter.eastmoney.com/securities/api/data/v1/get?'+urlencode({
        'reportName':'RPT_HKF10_FN_INCOME','columns':'ALL',
        'filter':'(SECUCODE="'+code+'")' + "(REPORT_DATE='"+end_date+"')",
        'pageSize':100,'pageNumber':1,'sortColumns':'REPORT_DATE','sortTypes':-1})


def parse_hk_financial_currency(payload,code,end_date):
    """Validate statement currency independently of the HK quote currency."""
    currencies=set()
    aliases={'CNY':'CNY','人民币':'CNY','人民幣':'CNY','RMB':'CNY',
        'HKD':'HKD','港币':'HKD','港幣':'HKD','港元':'HKD',
        'USD':'USD','美元':'USD'}
    for row in (payload.get('result') or {}).get('data',[]):
        if row.get('SECUCODE')!=code or str(row.get('REPORT_DATE',''))[:10]!=end_date:
            continue
        values={aliases.get(str(row.get(k,''))) for k in ('CURRENCY_CODE','CURRENCY')}
        values.discard(None)
        currencies.update(values)
    return next(iter(currencies)) if len(currencies)==1 else None


def match_akeso_publication(payload,end_date,as_of):
    """Match the report period in the issuer-linked announcement feed title."""
    end=date.fromisoformat(end_date)
    now=_stamp(as_of).date()
    period=end.strftime('%B %d, %Y').upper().replace(' 0',' ')
    matching=[]
    for row in payload.get('News',[]):
        title=re.sub(r'\s+',' ',str(row.get('title',''))).upper()
        if ('RESULTS ANNOUNCEMENT' not in title or period not in title or not row.get('hasAttachments')):
            continue
        try:
            published=datetime.strptime(row['formatedDate'],'%d %B %Y').date()
        except (ValueError,TypeError,KeyError):
            continue
        if end<=published<now:
            matching.append((published,row))
    if not matching:
        return None
    published,row=min(matching,key=lambda r:r[0])
    return {'ann_date':published.isoformat(),'title':row['title'],
        'url':'https://asia.tools.euroland.com/tools/Pressreleases/GetPressRelease/?'+urlencode(
            {'ID':row['ID'],'lang':'en-GB','companycode':'ky-9926'})}


def match_tencent_publication(document,end_date,as_of):
    """Read the visible news-entry date, never the page's modification time."""
    end=date.fromisoformat(end_date);now=_stamp(as_of).date()
    quarter={3:'First',6:'Second',9:'Third',12:'Fourth'}.get(end.month)
    if not quarter:return None
    title='Tencent Announces '+str(end.year)+' '+quarter+' Quarter Results'
    for article in re.findall(r'<article\b[^>]*>(.*?)</article>',document,re.S|re.I):
        clean=html.unescape(re.sub('<[^>]+>',' ',article))
        if title not in clean:continue
        match=re.search(r"class=['\"]entry-meta['\"][^>]*>([^<]+)",article)
        link=re.search(r"href=['\"](https://www\.tencent\.com/[^'\"]+\.pdf)['\"]",article)
        if not match or not link:continue
        try:published=datetime.strptime(match.group(1).strip(),'%B %d, %Y').date()
        except ValueError:continue
        if end<=published<now:
            return {'ann_date':published.isoformat(),'title':title,'url':link.group(1)}
    return None


def _akeso_publication(end_date,as_of):
    key='akeso:announcements:'+str(_stamp(as_of).year)
    cached=_cache_get(key)
    payload=json.loads(cached) if cached is not None else None
    if payload is None:
        params={'strDateFrom':'01/01/'+str(_stamp(as_of).year),'strDateTo':_stamp(as_of).strftime('%d/%m/%Y'),
            'companyCode':'ky-9926','lang':'en-GB','orderBy':0,'pageIndex':0,'pageJummp':200,'typeFilter':'',
            'hasTypeFilter':'false','searchPhrase':'','onlyInsiderInfo':'false','alwaysIncludeInsiders':'false',
            'strYears':str(_stamp(as_of).year)}
        req=urllib.request.Request('https://asia.tools.euroland.com/tools/Pressreleases/Main/GetNews/',
            data=urlencode(params).encode(),headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/x-www-form-urlencoded'})
        body=fetch_bytes(req,timeout=10,max_bytes=2_000_000)
        payload=json.loads(body)
        _cache_put(key,json.dumps(payload,ensure_ascii=False,separators=(',',':')),86400)
    return match_akeso_publication(payload,end_date,as_of)


def _source(identity,name,url,as_of,status='ok',count=1,error=''):
    return {'id':identity,'name':name,'url':url,'as_of':as_of,'status':status,
        'fetched_at':now_iso(),'count':count,'error':error}


def _collect(spec,as_of):
    code=spec['code'];market='HK' if code.endswith('.HK') else 'US'
    cutoff=last_complete_session(market,as_of)
    sources=[]
    official=spec.get('official') or 'https://data.sec.gov/submissions/CIK'+(spec.get('identity_cik') or spec['cik'])+'.json'
    evidence=_cached('official:'+code,official)
    issuer=None
    if spec.get('cik'):
        issuer=json.loads(evidence)
        if code[:-3] not in issuer.get('tickers',[]) or not set(issuer.get('exchanges',[])).intersection({'Nasdaq','NYSE'}):
            raise ValueError('SEC证券上市身份不符')
    elif spec.get('identity_cik'):
        issuer=json.loads(evidence)
        if (int(issuer.get('cik',0))!=int(spec['identity_cik']) or issuer.get('name')!=spec['sec_name']
            or spec['sec_ticker'] not in issuer.get('tickers',[])):
            raise ValueError('SEC发行人名称、代码及身份不符')
    elif not all(token.lower() in evidence.lower() for token in spec.get('tokens',[])):
        raise ValueError('公司官网业务证据内容不符')
    source_id='overseas:membership:'+code
    sources.append(_source(source_id,'公司官网/SEC · 代表样本归属 '+spec['name'],official,None))
    business_id=None
    business_url=spec.get('business_url');business_description=spec.get('business_description')
    if spec.get('business_sec_sic'):
        if (not issuer or str(issuer.get('sic'))!=spec['business_sec_sic']
            or issuer.get('sicDescription')!='Pharmaceutical Preparations'):
            raise ValueError('SEC药品制剂行业归属未核验')
        business_id='overseas:business:'+code;business_url=official
        business_description='SEC披露SIC 2834 Pharmaceutical Preparations（药品制剂）；仅核验海外医药大类，不将其视为纯创新药或全部业务收入构成。'
        sources.append(_source(business_id,'SEC · 药品制剂行业归属 '+spec['name'],official,None))
    if spec.get('business_url'):
        document=html.unescape(_cached('business:'+code,spec['business_url'],86400))
        document=re.sub(r'<(script|style)\b[^>]*>.*?</\1>',' ',document,flags=re.S|re.I)
        visible=re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',document))
        if not all(token.lower() in visible.lower() for token in spec.get('business_tokens',[])):
            raise ValueError('公司官网医药业务证据内容不符')
        business_id='overseas:business:'+code
        sources.append(_source(business_id,'公司官网 · 业务归属 '+spec['name'],spec['business_url'],None))
    url=history_url(code)
    history_payload=json.loads(_cached('history:'+code+':'+str(cutoff),url))
    if spec.get('quote_name'):
        quote_identity=((history_payload.get('data') or {}).get('hk'+code[:5]) or {}).get('qt',{}).get('hk'+code[:5],[])
        if (len(quote_identity)<76 or quote_identity[2]!=code[:5] or quote_identity[46]!=spec['quote_name']
            or quote_identity[75]!='HKD' or quote_identity[1]!=spec['name']):
            raise ValueError('港股报价证券代码、名称与交易币种未核验一致')
    histories=parse_history(history_payload,code,as_of)
    if len(histories)<2 or histories[-1]['date']!=cutoff:
        raise ValueError('海外样本日线未覆盖最近已完成交易日')
    last,prev=histories[-1],histories[-2]
    source_history='leader_history:'+code
    adjustment=histories[-1].get('adjustment')
    sources.append(_source(source_history,(('腾讯财经 · 港股前复权日线 ' if adjustment=='forward_adjusted' else '腾讯财经 · 港股未复权价格日线 ')
        if market=='HK' else 'Yahoo Finance · 美股复权日线 ')+code,url,cutoff,count=len(histories)))
    financial={};furl=finance_url(spec);fid='overseas:finance:'+code
    try:
        payload=json.loads(_cached('finance:'+code,furl,86400))
        sec_finance=bool(spec.get('finance_cik') or spec.get('cik'))
        if sec_finance and payload.get('cik')!=int(spec.get('finance_cik') or spec['cik']):
            raise ValueError('SEC财务发行人身份不符')
        financial=parse_sec_financials(payload,as_of) if sec_finance else parse_hk_financials(payload,code,as_of)
        if not sec_finance and financial.get('end_date'):
            currency_url=hk_income_url(code,financial['end_date'])
            currency_id='overseas:finance_currency:'+code
            try:
                income=json.loads(_cached('finance_currency:'+code+':'+financial['end_date'],currency_url,86400))
                currency=parse_hk_financial_currency(income,code,financial['end_date'])
                financial['currency']=currency
                financial['currency_note']=('已按同证券、同报告期利润表核验财务币种 '+currency if currency else
                    '同证券、同报告期利润表币种缺失或冲突；不以交易币种代替')
                sources.append(_source(currency_id,'东方财富 · 港股利润表财务币种 '+code,currency_url,
                    financial['end_date'],status='ok' if currency else 'partial',count=1 if currency else 0,
                    error='' if currency else '财务币种未取得唯一有效结果'))
            except Exception as error:
                sources.append(_source(currency_id,'东方财富 · 港股利润表财务币种 '+code,currency_url,
                    financial['end_date'],status='error',count=0,error=type(error).__name__+'：财务币种未核验'))
        if code=='09926.HK' and financial.get('end_date'):
            try:
                publication=_akeso_publication(financial['end_date'],as_of)
                if publication:
                    financial.update(ann_date=publication['ann_date'],publication_status='verified',
                        source_note='东方财富财务指标；公司官网所链接公告按报告期核验真实披露日期')
                    sources.append(_source('overseas:publication:'+code,'康方官网所链接 · 财报披露日期',
                        publication['url'],publication['ann_date']))
            except Exception:
                pass
        if code=='00700.HK' and financial.get('end_date'):
            try:
                news_url='https://www.tencent.com/investors/investor-news/'
                publication=match_tencent_publication(_cached('tencent:investor-news',news_url,86400),financial['end_date'],as_of)
                if publication:
                    financial.update(ann_date=publication['ann_date'],publication_status='verified',
                        source_note='东方财富财务指标；腾讯官网投资者新闻对应季度结果的可见发布日期核验')
                    sources.append(_source('overseas:publication:'+code,'腾讯官网 · 财报结果发布日期',
                        news_url,publication['ann_date']))
            except Exception:
                pass
        sources.append(_source(fid,('SEC · 已披露财务 ' if sec_finance else
            '东方财富 · 港股财务（官网披露日期已核验） ' if financial.get('ann_date') else
            '东方财富 · 港股财务（披露日未提供） ')+code,
            furl,financial.get('ann_date') or financial.get('end_date'),status='ok' if financial.get('ann_date') else 'partial',
            count=1 if financial else 0,error='' if financial.get('ann_date') else '披露日未取得，业绩数据不参与评分'))
    except Exception as error:
        sources.append(_source(fid,'海外财务 '+code,furl,None,status='error',count=0,error=type(error).__name__+'：财务未取得'))
    when=cutoff
    return {'ts_code':code,'name':spec['name'],'as_of':when,'market':market,'currency':'HKD' if market=='HK' else 'USD',
        'quote':{'trade_date':cutoff,'close':last['unadjusted_close'] or last['close'],
            'close_kind':'unadjusted_close' if last['unadjusted_close'] else 'forward_adjusted_close',
            'as_of_precision':'date','pct_chg':(last['close']/prev['close']-1)*100,
            'data_kind':'daily_close','is_intraday':False,'market':market,'currency':'HKD' if market=='HK' else 'USD'},
        'history':histories,'history_count':len(histories),'price_adjustment':adjustment,'financials':financial,'market_metrics':{},
        'membership_evidence':{'l1_name':'已核对证券身份与公司官网业务的指定代表样本（非官方指数成分名单）',
            'l2_name':spec['name'],'snapshot_date':_stamp(as_of).date().isoformat()},
        'selection_basis':'预先明确列出的代表公司，按证券身份及公司官网业务核对；不宣称全市场市值排名',
        'role':'代表公司样本；未认证主营业务市占率龙头','leader_verified':False,
        'business_evidence':{'url':business_url, 'description':business_description,
            'published_at':None,'observed_at':now_iso()} if business_id else None,
        'source_ids':[source_id,source_history,fid]+[s['id'] for s in sources
            if s['id'] in {'overseas:publication:'+code,'overseas:finance_currency:'+code,business_id}]},sources


def gather_overseas_company_evidence(catalog,as_of):
    ids={r['id'] for r in catalog}
    chosen={k:sample_specs(k) for k in SAMPLES if k in ids}
    result={'sector_leaders':{},'sources':[],'provider':'public_overseas','status':'partial'}
    specs={r['code']:r for rows in chosen.values() for r in rows}
    found={}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(_collect,spec,as_of):code for code,spec in specs.items()}
        for future in as_completed(futures):
            code=futures[future]
            try:
                row,sources=future.result();found[code]=row;result['sources'].extend(sources)
            except Exception as error:
                result['sources'].append(_source('overseas:sample:'+code,'海外代表公司 '+code,history_url(code),None,
                    status='error',count=0,error=type(error).__name__+'：'+str(error)[:160]))
    for identity,rows in chosen.items():
        result['sector_leaders'][identity]=[copy.deepcopy(found[r['code']]) for r in rows if r['code'] in found]
    result['status']='ok' if len(found)==len(specs) else 'partial'
    _save_cache()
    return result


def build_overseas_indicator(board,leaders,as_of):
    if board.get('id') not in SAMPLES or not leaders:
        return None
    specs=sample_specs(board['id']);allowed={r['code'] for r in specs}
    required_codes={r['code'] for r in SAMPLES[board['id']]}
    sample_markets={'US' if spec['code'].endswith('.US') else 'HK' for spec in specs}
    if len(sample_markets)!=1:
        return None
    market=next(iter(sample_markets))
    cutoff=last_complete_session(market,as_of)
    required=recent_sessions(market,as_of)
    valid=[];seen=set()
    for row in leaders[:CANDIDATE_LIMIT]:
        code=row.get('ts_code');q=row.get('quote') or {};member=row.get('membership_evidence') or {}
        try:
            day=date.fromisoformat(str(member.get('snapshot_date','')))
            age=(_stamp(as_of).date()-day).days
        except ValueError:
            continue
        if (code in seen or code not in allowed or q.get('market')!=market
            or q.get('trade_date')!=cutoff or row.get('as_of')!=cutoff or q.get('is_intraday') or not finite(q.get('close')) or q['close']<=0
            or not finite(q.get('pct_chg')) or not member.get('l1_name') or not row.get('source_ids') or not 0<=age<=45):
            continue
        if code not in required_codes:
            days={p.get('date') for p in row.get('history',[]) if finite(p.get('close')) and p['close']>0}
            if not financial_ready(row,as_of) or not set(required).issubset(days):continue
        seen.add(code);valid.append(row)
        if len(valid)>=MAX_SAMPLES:break
    if not valid or not cutoff:return None
    histories=[{p['date']:p['close'] for p in row.get('history',[]) if isinstance(p,dict)
        and isinstance(p.get('date'),str) and p['date']<=cutoff and is_session(market,p['date'])
        and finite(p.get('close')) and p['close']>0} for row in valid]
    days=sorted(set.intersection(*(set(r) for r in histories)))
    series=[];value=100.0
    for i,day in enumerate(days):
        ret=sum(h[day]/h[days[i-1]]-1 for h in histories)/len(histories) if i else 0
        value*=1+ret;series.append({'date':day,'close':value,'return_pct':ret*100 if i else None})
    # A finalized pool has already excluded incomplete candidates with an
    # explicit reason. Raw callers retain the original complete-core contract.
    finalized=bool(valid and all(r.get('sample_checks') and all(r['sample_checks'].values()) for r in valid))
    ready=(len(valid)>=2 and (finalized or required_codes.issubset(seen))
        and len(required)==MIN_HISTORY and set(required).issubset(days))
    last=series[-1]['close'] if series and days[-1]==cutoff else None
    change=series[-1]['return_pct'] if len(series)>=2 and days[-1]==cutoff else None
    meta={'id':'leader:'+board['id'],'version':VERSION,'name':board['title']+' · 代表公司样本指标',
        'market':market,'currency':'HKD' if market=='HK' else 'USD','scope':SCOPE,'method':METHOD,
        'weighting':'等权 · 每日收益率平均','base_value':100,'base_date':days[0] if days else None,
        'history_end':days[-1] if days else None,'history_count':len(series),'sample_count':len(valid),'minimum_samples':2,'maximum_samples':MAX_SAMPLES,
        'ready':ready,'is_intraday':False,'value':round(last,4) if last else None,'as_of':min(r['as_of'] for r in valid),
        'excluded':[{'code':spec['code'],'reason':'本轮未取得完整归属、已披露财务与近期日线；未纳入等权计算'}
            for spec in specs if spec['code'] not in seen],
        'calendar_source':HK_CALENDAR if market=='HK' else US_CALENDAR,
        'constituents':[{'code':r['ts_code'],'name':r['name'],'weight_pct':100/len(valid),'as_of':r['as_of'],
            'membership_date':r['membership_evidence']['snapshot_date'],'selection_basis':r['selection_basis'],
            'price_adjustment':r.get('price_adjustment'),
            'source_ids':r['source_ids']} for r in valid],
        'history':[{'date':p['date'],'value':round(p['close'],4)} for p in series]}
    price={'code':meta['id'],'name':meta['name'],'last':last,'change_pct':change,'as_of':meta['as_of'],
        'market':market,'currency':meta['currency'],'trade_date':cutoff,'source_id':meta['id'],'history_secid':meta['id'],
        'mapping_basis':'本站独立编制的海外代表公司等权样本，不是官方板块报价','scope_note':SCOPE,
        'data_frequency':'daily','as_of_precision':'date','asset_type':'equity','is_custom':True}
    source=_source(meta['id'],meta['name']+' · 本站计算',None,meta['as_of'],status='ok' if ready else 'partial',count=len(series),
        error='' if ready else '至少2只且全部样本需共同覆盖最近61个当地已完成交易日')
    source['scope']=SCOPE
    return {'meta':meta,'quote':price,'history':series,'source':source}
