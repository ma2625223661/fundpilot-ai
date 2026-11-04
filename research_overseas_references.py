"""Foreign index histories with explicit identity, native session and scope.

These are index price observations. They deliberately do not manufacture
company accounts, dividend yields, currency hedges or a global investable return.
"""
from __future__ import annotations
import json, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time
from urllib.parse import quote
from zoneinfo import ZoneInfo

from research_data import now_iso
from research_numbers import finite_number as finite

REFERENCES = {
 'overseas_sp500': {'symbol':'^GSPC','name':'标普500指数','tokens':['S&P','500'],'currency':'USD','zone':'America/New_York','market':'US',
    'official':'https://www.spglobal.com/spdji/en/indices/equity/sp-500/', 'scope':'美国大型股参考指数，不代表全部美股；不含公司财务及未评估事件。'},
 'overseas_nasdaq': {'symbol':'^IXIC','name':'纳斯达克综合指数','tokens':['NASDAQ','Composite'],'currency':'USD','zone':'America/New_York','market':'US',
    'official':'https://indexes.nasdaq.com/Index/Overview/COMP','scope':'纳斯达克综合价格指数，不等同纳斯达克100；不含公司财务及未评估事件。'},
 'overseas_hang_seng': {'symbol':'^HSI','name':'恒生指数','tokens':['Hang Seng'],'currency':'HKD','zone':'Asia/Hong_Kong','market':'HK',
    'official':'https://www.hsi.com.hk/eng/indexes/all-indexes/hsi','scope':'香港恒生价格指数，不代表所有港股；不含公司财务及未评估事件。'},
 'overseas_hang_seng_technology': {'symbol':'HSTECH.HK','name':'恒生科技指数','tokens':['Hang Seng','TECH'],'currency':'HKD','zone':'Asia/Hong_Kong','market':'HK',
    'official':'https://www.hsi.com.hk/eng/indexes/all-indexes/hstech','scope':'恒生科技价格指数，包含硬件等科技行业，不当作纯互联网指数；不含公司财务及未评估事件。'},
 'overseas_jp_equity': {'symbol':'^N225','name':'日经225指数','tokens':['Nikkei','225'],'currency':'JPY','zone':'Asia/Tokyo','market':'JP',
    'official':'https://indexes.nikkei.co.jp/en/nkave','scope':'日经225日本股票价格参考；不代表全部日本上市公司，不含公司财务及未评估事件。'},
 'overseas_eu_equity': {'symbol':'^STOXX50E','name':'欧元区EURO STOXX 50指数','tokens':['EURO','STOXX','50'],'currency':'EUR','zone':'Europe/Zurich','market':'EU',
    'official':'https://stoxx.com/index/sx5e/','scope':'欧元区大型股参考，只覆盖欧元区，未覆盖英国、瑞士及全部欧洲股票；不含公司财务及未评估事件。'},
 'overseas_in_equity': {'symbol':'^NSEI','name':'印度NIFTY 50指数','tokens':['NIFTY','50'],'currency':'INR','zone':'Asia/Kolkata','market':'IN',
    'official':'https://www.niftyindices.com/indices/equity/broad-based-indices/NIFTY-50','scope':'印度NIFTY 50股票价格参考，不代表全部印度上市公司；不含公司财务及未评估事件。'},
 'overseas_vn_equity': {'symbol':'^VNINDEX.VN','name':'越南VNINDEX指数','tokens':['VNINDEX'],'currency':'VND','zone':'Asia/Bangkok','market':'VN',
    'official':'https://www.hsx.vn/','scope':'越南胡志明交易所VNINDEX股票价格参考，不代表河内交易所或全部越南市场；不含公司财务及未评估事件。'},
 'reference_tw_equity': {'symbol':'^TWII','name':'台湾加权股票指数','tokens':['TSEC','CAPITALIZATION','WEIGHTED'],'currency':'TWD','zone':'Asia/Taipei','market':'TW',
    'official':'https://www.twse.com.tw/en/indices/taiex/mi-5mins-hist.html','scope':'台湾加权股票价格指数，仅作为有限地区组合的市场观察。'},
 'reference_br_equity': {'symbol':'^BVSP','name':'巴西IBOVESPA指数','tokens':['IBOVESPA'],'currency':'BRL','zone':'America/Sao_Paulo','market':'BR',
    'official':'https://www.b3.com.br/en_us/market-data-and-indices/indices/broad-indices/ibovespa.htm','scope':'巴西IBOVESPA股票价格指数，仅作为有限地区组合的市场观察。'},
 'reference_au_equity': {'symbol':'^AXJO','name':'澳大利亚S&P/ASX200指数','tokens':['S&P/ASX','200'],'currency':'AUD','zone':'Australia/Sydney','market':'AU',
    'official':'https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200/','scope':'澳大利亚S&P/ASX200股票价格指数，仅作为有限地区组合的市场观察。'},
}

COMPOSITES = {
 'overseas_global_equity': {'name':'全球·五地市场样本指标','members':['overseas_sp500','overseas_eu_equity','overseas_jp_equity','overseas_in_equity','reference_au_equity'],
    'scope':'美国大型股、欧元区大型股、日本、印度、澳大利亚五地指数的有限市场样本；不是官方全球指数，不覆盖全部国家。各本币价格收益等权，不含汇率、股息、公司财务或未评估事件。'},
 'overseas_asia_pacific': {'name':'亚太·五地市场样本指标','members':['overseas_jp_equity','overseas_in_equity','reference_tw_equity','reference_au_equity','overseas_hang_seng'],
    'scope':'日本、印度、台湾、澳大利亚及香港五地股票指数的有限亚太市场样本；不覆盖全部亚太国家或全部股票。各本币价格收益等权，不含汇率、股息、公司财务或未评估事件。'},
 'overseas_em_equity': {'name':'新兴市场·三地市场样本指标','members':['overseas_in_equity','reference_tw_equity','reference_br_equity'],
    'scope':'印度、台湾及巴西三地股票指数的有限新兴市场样本；不是MSCI新兴市场指数，不代表全部新兴国家。各本币价格收益等权，不含汇率、股息、公司财务或未评估事件。'},
}

def reference_quote_fresh(quote,as_of):
 """Require an evidenced complete local session; never reuse A-share dates."""
 if quote.get('score_scope')!='reference_trend' or not quote.get('reference_session_completed'):
  return False
 members=quote.get('reference_members')
 if members:
  try:
   common=datetime.fromisoformat(str(quote['as_of'])[:10]).date()
   earliest=min(datetime.fromisoformat(str(m['as_of'])[:10]).date() for m in members)
   return bool(all(reference_quote_fresh(member,as_of) for member in members)
               and str(common)==quote.get('reference_common_end') and 0<=(earliest-common).days<=7)
  except (ValueError,KeyError,TypeError):return False
 try:
  zone=ZoneInfo(quote['reference_timezone'])
  now=datetime.fromisoformat(as_of.replace('Z','+00:00')).astimezone(zone)
  observed=datetime.fromisoformat(quote['reference_observed_at'].replace('Z','+00:00')).astimezone(zone)
  day=datetime.fromisoformat(str(quote['as_of'])[:10]).date()
  expected=datetime.fromisoformat(quote['reference_latest_completed_date']).date()
  close=datetime.fromisoformat(quote['reference_session_end'].replace('Z','+00:00')).astimezone(zone)
  if observed>now+timedelta(minutes=5) or (now-observed)>timedelta(hours=36) or day!=expected:
   return False
  if quote.get('market') in ('US','HK'):
   from research_overseas import last_complete_session
   return str(day)==last_complete_session(quote['market'],as_of)
  # Native holidays beyond the collected session have not been established.
  # Invalidate once another weekday's closing boundary has passed.
  next_day=day+timedelta(days=1)
  while next_day.weekday()>=5:next_day+=timedelta(days=1)
  next_close=datetime.combine(next_day,close.timetz().replace(tzinfo=None),zone)+timedelta(minutes=15)
  return day<=now.date() and now<next_close and (now.date()-day).days<=4
 except (ValueError,KeyError,TypeError):
  return False


def history_url(symbol):
 if symbol in {'^HSI','HSTECH.HK'}:
  code='HSI' if symbol=='^HSI' else 'HSTECH'
  return 'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk'+code+',day,,,121,qfq'
 return 'https://query1.finance.yahoo.com/v8/finance/chart/'+quote(symbol,safe='')+'?interval=1d&range=1y'

def parse_index(payload,spec,as_of):
 result=(payload.get('chart',{}).get('result') or [None])[0]
 if not isinstance(result,dict):raise ValueError('指数来源没有返回有效结果')
 meta=result.get('meta') or {}
 visible=(str(meta.get('longName',''))+' '+str(meta.get('shortName',''))).casefold()
 # This exact EURO STOXX vendor feed sometimes omits currency. Do not invent
 # it: retain only index-point returns and expose the missing currency field.
 missing_euro_currency=(spec['symbol']=='^STOXX50E' and meta.get('currency') is None
                        and meta.get('exchangeName')=='ZRH')
 if (meta.get('symbol')!=spec['symbol'] or meta.get('instrumentType')!='INDEX'
     or (meta.get('currency')!=spec['currency'] and not missing_euro_currency) or meta.get('exchangeTimezoneName')!=spec['zone']
     or not all(token.casefold() in visible for token in spec['tokens'])):
  raise ValueError('指数代码、名称、类型、币种或当地时区不符')
 now=datetime.fromisoformat(str(as_of).replace('Z','+00:00'))
 if now.tzinfo is None:raise ValueError('研究时点缺少时区')
 zone=ZoneInfo(spec['zone']);local_now=now.astimezone(zone)
 regular=(meta.get('currentTradingPeriod') or {}).get('regular') or {}
 close=regular.get('end');rmt=meta.get('regularMarketTime')
 if not finite(rmt) or not finite(close):raise ValueError('来源缺少当地会话及行情时点')
 published=datetime.fromtimestamp(rmt,zone)
 if published>local_now+timedelta(minutes=5) or local_now-published>timedelta(days=7):
  raise ValueError('指数行情时点未来或超过7天；长假不推定仍有效')
 cutoff=published.date()
 close_time=datetime.fromtimestamp(close,zone)
 # A bar from an unfinished native session is never a completed daily bar.
 if local_now<close_time and cutoff==close_time.date():cutoff-=timedelta(days=1)
 timestamps=result.get('timestamp') or []
 indicators=result.get('indicators') or {}
 closes=((indicators.get('quote') or [{}])[0]).get('close') or []
 rows={}
 for stamp,value in zip(timestamps,closes):
  if not finite(stamp) or not finite(value) or value<=0:continue
  day=datetime.fromtimestamp(stamp,zone).date()
  if day<=cutoff and day.weekday()<5:rows[day.isoformat()]={'date':day.isoformat(),'close':float(value)}
 history=[rows[d] for d in sorted(rows)][-121:]
 if len(history)<61:raise ValueError('当地指数不足61个已完成日线点')
 if (local_now.date()-datetime.fromisoformat(history[-1]['date']).date()).days>7:
  raise ValueError('当地指数最近日线过期')
 if local_now>=close_time+timedelta(minutes=15) and history[-1]['date']!=str(close_time.date()):
  raise ValueError('来源会话已结束但缺少对应收盘日线')
 return history,meta

def _source(identity,spec,as_of,status='ok',count=0,error='',url=None,provider=None):
 provider=provider or ('腾讯财经' if spec['symbol'] in {'^HSI','HSTECH.HK'} else 'Yahoo Finance')
 return {'id':identity,'name':provider+' · '+spec['name'],'url':url or history_url(spec['symbol']),
  'official_url':spec['official'],'status':status,'count':count,'as_of':as_of,'as_of_precision':'date',
  'fetched_at':now_iso(),'scope':spec['scope'],'error':error}

def parse_tencent_hk_index(payload,identity,as_of):
 """Verify the exact HK index identity beside its native completed daily bars."""
 from research_overseas import last_complete_session, is_session
 definitions={'overseas_hang_seng':('HSI','恒生指数','Hang Seng Index'),
              'overseas_hang_seng_technology':('HSTECH','恒生科技指数','Hang Seng TECH Index')}
 if identity not in definitions:raise ValueError('未配置对应香港指数身份')
 symbol,name,english=definitions[identity];key='hk'+symbol
 item=(payload.get('data') or {}).get(key) or {}
 qt=(item.get('qt') or {}).get(key) or []
 if (payload.get('code')!=0 or len(qt)<76 or qt[2]!=symbol or qt[63]!='ZS'
     or qt[75]!='HKD' or english!=qt[46] or qt[1]!=name):
  raise ValueError(name+'代码、类型、名称或币种未核验一致')
 cutoff=last_complete_session('HK',as_of)
 published=datetime.strptime(qt[30],'%Y/%m/%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
 now=datetime.fromisoformat(as_of.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Hong_Kong'))
 if not cutoff or published>now+timedelta(minutes=5) or str(published.date())<cutoff or (now-published).days>7:
  raise ValueError(name+'行情时点未覆盖最近香港完整交易日')
 rows={}
 for row in item.get('day') or []:
  if not isinstance(row,list) or len(row)<3:continue
  try:
   day=datetime.fromisoformat(row[0]).date().isoformat();value=float(row[2])
  except (ValueError,TypeError):continue
  if day<=cutoff and is_session('HK',day) and finite(value) and value>0:
   rows[day]={'date':day,'close':value}
 history=[rows[d] for d in sorted(rows)][-121:]
 if len(history)<61 or history[-1]['date']!=cutoff:raise ValueError(name+'完整日线不足61点或缺少最近交易日')
 # Intraday quotes establish identity only. Compare the displayed close to the
 # final daily bar only when both observations concern the completed session.
 if str(published.date())==cutoff:
  try:close=float(qt[3])
  except (TypeError,ValueError):raise ValueError(name+'收盘报价无效') from None
  if not finite(close) or abs(history[-1]['close']-close)>max(.01,close*1e-6):
   raise ValueError(name+'日线与同代码收盘报价不一致')
 return history


def parse_hstech(payload,as_of):
 return parse_tencent_hk_index(payload,'overseas_hang_seng_technology',as_of)


def parse_vnindex(payload,metadata,as_of):
 """Use the provider's exact HOSE symbol and local session, not an A-share day."""
 if (metadata.get('symbol')!='VNINDEX' or metadata.get('ticker')!='VNINDEX'
     or metadata.get('type')!='INDEX' or metadata.get('exchange-listed')!='HOSE'
     or metadata.get('timezone')!='Asia/Bangkok' or metadata.get('session')!='0900-1500'):
  raise ValueError('VNINDEX代码、指数类型、交易所或当地时区不符')
 if payload.get('s')!='ok':raise ValueError('VNINDEX日线来源没有有效结果')
 now=datetime.fromisoformat(as_of.replace('Z','+00:00')).astimezone(ZoneInfo(metadata['timezone']))
 cutoff=now.date() if now.timetz().replace(tzinfo=None)>=time(15,15) else now.date()-timedelta(days=1)
 rows={}
 for stamp,value in zip(payload.get('t') or [],payload.get('c') or []):
  if not finite(stamp) or not finite(value) or value<=0:continue
  day=datetime.fromtimestamp(stamp,ZoneInfo(metadata['timezone'])).date()
  if day<=cutoff and day.weekday()<5:rows[day.isoformat()]={'date':day.isoformat(),'close':float(value)}
 history=[rows[d] for d in sorted(rows)][-121:]
 if len(history)<61 or (now.date()-datetime.fromisoformat(history[-1]['date']).date()).days>7:
  raise ValueError('VNINDEX完整日线不足61点或超过7天；长假不推定有效')
 return history


def _collect(identity,as_of):
 from research_overseas import _cached
 spec=REFERENCES[identity];url=history_url(spec['symbol'])
 stamp=str(as_of)[:10]
 provider='Yahoo Finance';currency=spec['currency'];meta={}
 if identity in {'overseas_hang_seng','overseas_hang_seng_technology'}:
  from research_overseas import last_complete_session
  symbol='HSI' if identity=='overseas_hang_seng' else 'HSTECH'
  url=history_url(spec['symbol'])
  session=last_complete_session('HK',as_of)
  history=parse_tencent_hk_index(json.loads(_cached('reference:HKINDEX:v2:'+symbol+':'+str(session),url,3600)),identity,as_of)
  provider='腾讯财经'
  from research_overseas import session_close
  session_end=session_close('HK',history[-1]['date']).isoformat()
 elif identity=='overseas_vn_equity':
  metadata_url='https://dchart-api.vndirect.com.vn/dchart/symbols?symbol=VNINDEX'
  metadata=json.loads(_cached('reference:VNINDEX:identity',metadata_url,86400))
  now=datetime.fromisoformat(as_of.replace('Z','+00:00'))
  start=int((now-timedelta(days=400)).timestamp());end=int(now.timestamp())
  url=f'https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX&from={start}&to={end}'
  history=parse_vnindex(json.loads(_cached('reference:VNINDEX:'+stamp,url,3600)),metadata,as_of)
  provider='VNDIRECT';currency=None
  session_end=datetime.combine(datetime.fromisoformat(history[-1]['date']).date(),time(15),ZoneInfo(spec['zone'])).isoformat()
 else:
  payload=json.loads(_cached('reference:'+spec['symbol']+':'+stamp,url,3600))
  history,meta=parse_index(payload,spec,as_of)
  currency=meta.get('currency')
  session_end=datetime.fromtimestamp(meta['currentTradingPeriod']['regular']['end'],ZoneInfo(spec['zone'])).isoformat()
 source_id='overseas_reference:'+identity;history_id='reference:overseas:'+identity
 when=history[-1]['date'];last,prev=history[-1]['close'],history[-2]['close']
 q={'board_id':identity,'sector_id':identity,'code':spec['symbol'],'name':spec['name'],'full_name':spec['name'],
   'last':last,'change_pct':(last/prev-1)*100,'as_of':when,'as_of_precision':'date','data_frequency':'daily',
   'source_id':source_id,'source_url':url,'history_secid':history_id,'asset_type':'equity_index',
   'return_type':'price','market':spec['market'],'currency':currency,'unit':'index_points','score_scope':'reference_trend',
   'official_url':spec['official'],'scope_note':spec['scope'],
   'reference_timezone':spec['zone'],'reference_session_completed':True,
   'reference_observed_at':as_of,'reference_latest_completed_date':when,'reference_session_end':session_end,
   'mapping_basis':'明确代码、名称、指数类型、币种与当地时区均核验：'+spec['name']}
 if currency is None:
  q['scope_note']+=' 来源未提供报价币种，仅作指数点位变化，不做汇率或金额换算。'
  q['mapping_basis']='已核验代码、名称、指数类型与当地时区；报价币种未提供：'+spec['name']
 if not reference_quote_fresh(q,as_of):raise ValueError('当地完整收盘时点核验未通过')
 sources=[_source(source_id,spec,when,count=len(history),url=url,provider=provider),
          _source('sector_history:'+history_id,spec,when,count=len(history),url=url,provider=provider)]
 return q,sources,history_id,history

def collect_overseas_references(catalog,as_of):
 requested={r['id'] for r in catalog}
 composites={key:spec for key,spec in COMPOSITES.items() if key in requested}
 keys=(requested & REFERENCES.keys())|{key for spec in composites.values() for key in spec['members']}
 quotes=[];sources=[];histories={};found={}
 with ThreadPoolExecutor(max_workers=4) as pool:
  futures={pool.submit(_collect,key,as_of):key for key in keys}
  for future in as_completed(futures):
   key=futures[future]
   try:
    q,ss,hid,history=future.result();found[key]=(q,history);sources.extend(ss);histories[hid]=history
    if key in requested:quotes.append(q)
   except Exception as e:
    from research_transport import source_error
    sources.append(_source('overseas_reference:'+key,REFERENCES[key],None,'error',0,
        source_error(e,'海外指数日线未取得')))
 for identity,spec in composites.items():
  missing=[key for key in spec['members'] if key not in found]
  sid='overseas_reference:'+identity;hid='reference:overseas:'+identity
  if missing:
   sources.append({'id':sid,'name':spec['name'],'url':None,'status':'error','as_of':None,'count':0,
      'fetched_at':now_iso(),'scope':spec['scope'],'error':'指定市场日线未齐：'+','.join(missing)})
   continue
  windows=[{r['date']:r['close'] for r in found[key][1]} for key in spec['members']]
  days=sorted(set.intersection(*(set(h) for h in windows)))
  if len(days)<61:
   sources.append({'id':sid,'name':spec['name'],'url':None,'status':'partial','as_of':days[-1] if days else None,
     'count':len(days),'fetched_at':now_iso(),'scope':spec['scope'],'error':'指定各市场共同日线不足61点'})
   continue
  value=100.;series=[]
  for i,day in enumerate(days):
   if i:value*=sum(h[day]/h[days[i-1]] for h in windows)/len(windows)
   series.append({'date':day,'close':value})
  histories[hid]=series;last=series[-1]
  notes=spec['scope']+' 市场收盘时区不同，使用共同日期，不代表同一瞬时可交易价格。'
  if any(found[key][0].get('currency') is None for key in spec['members']):
   notes+=' 部分来源未提供报价币种，组合只汇总指数点位比例，不进行跨币种金额或汇率换算。'
  quotes.append({'board_id':identity,'sector_id':identity,'code':'markets:'+identity,'name':spec['name'],
    'last':last['close'],'change_pct':(last['close']/series[-2]['close']-1)*100,'as_of':last['date'],
    'as_of_precision':'date','data_frequency':'daily','source_id':sid,'history_secid':hid,'asset_type':'equity_index',
    'score_scope':'reference_trend','return_type':'local_currency_price_basket','scope_note':notes,
    'reference_session_completed':True,'reference_members':[found[key][0] for key in spec['members']],
    'reference_common_end':last['date'],
    'mapping_basis':'本站独立编制：'+','.join(REFERENCES[key]['name'] for key in spec['members'])+'；共同日期本币收益等权'})
  sources.extend([{'id':key,'name':spec['name']+' · 本站计算','url':None,'status':'ok','as_of':last['date'],
    'fetched_at':now_iso(),'count':len(series),'scope':notes,'error':''} for key in (sid,'sector_history:'+hid)])
 return quotes,sources,histories
