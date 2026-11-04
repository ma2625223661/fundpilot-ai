"""Date-checked NBS monthly PMI evidence; no inferred GDP or policy rates."""
import html
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from research_data import CHINA, fetch_text, now_iso
from research_evidence_cache import load_record,save_record

LIST_URL='https://www.stats.gov.cn/sj/zxfb/'
CACHE_PATH=Path(__file__).resolve().parent/'data'/'macro-pmi-cache.json'


def cached_pmi(as_of):
    record=load_record(CACHE_PATH,'nbs_pmi')
    if not isinstance(record,dict):return None
    try:
        # Reparse the original official evidence, retaining its publication
        # date, rather than trusting a stored calculated score.
        result=parse_pmi(record['document'],record['url'],as_of)
        fetched=datetime.fromisoformat(record['fetched_at'].replace('Z','+00:00'))
        fetched=fetched.replace(tzinfo=CHINA) if fetched.tzinfo is None else fetched
        now=datetime.fromisoformat(as_of.replace('Z','+00:00'));now=now.replace(tzinfo=CHINA) if now.tzinfo is None else now
        if fetched>now:return None
        result['observed_at']=record['fetched_at']
        result['cache_used']=True
        return result,record['fetched_at']
    except (KeyError,TypeError,ValueError):return None


def collect_cached_macro_risk(as_of):
    return collect_macro_risk(as_of,use_cache=True)


def parse_pmi(document, url, as_of):
    if urlparse(url).hostname!='www.stats.gov.cn':raise ValueError('宏观证据必须来自国家统计局')
    title=re.search(r'<meta\s+name="ArticleTitle"\s+content="([^"]+)"',document)
    date=re.search(r'<meta\s+name="PubDate"\s+content="([^"]+)"',document)
    if not title or not date or not re.fullmatch(r'\d{4}年\d{1,2}月中国采购经理指数运行情况',title[1]):raise ValueError('PMI公告身份缺失')
    published=datetime.strptime(date[1],'%Y/%m/%d %H:%M').replace(tzinfo=CHINA)
    now=datetime.fromisoformat(as_of.replace('Z','+00:00'));now=now.replace(tzinfo=CHINA) if now.tzinfo is None else now
    period=re.fullmatch(r'(\d{4})年(\d{1,2})月中国采购经理指数运行情况',title[1])
    year,month=map(int,period.groups())
    if not 1<=month<=12 or (year,month)>(published.year,published.month):raise ValueError('PMI统计期尚未结束或身份异常')
    if (published.year*12+published.month)-(year*12+month)>2:raise ValueError('PMI统计期过旧')
    if not 0 <= (now-published).total_seconds() <= 62*86400:raise ValueError('PMI公告尚未发布或已过期')
    visible=re.sub(r'<(script|style)\b[^>]*>.*?</\1>',' ',document,flags=re.S|re.I)
    visible=re.sub(r'\s+','',html.unescape(re.sub('<[^>]+>',' ',visible)))
    patterns={'manufacturing':r'制造业采购经理指数[（(]PMI[）)]为([\d.]+)%',
              'new_orders':r'新订单指数为([\d.]+)%','composite':r'综合PMI产出指数为([\d.]+)%'}
    values={}
    for key,pattern in patterns.items():
        match=re.search(pattern,visible)
        if not match or not 0 <= float(match[1]) <= 100:raise ValueError('PMI真实数值缺失')
        values[key]=float(match[1])
    score=sum(max(0,min(100,50-(values[k]-50)*10))*w for k,w in [('manufacturing',.4),('new_orders',.35),('composite',.25)])
    return {'status':'ok','title':title[1],'published_at':published.isoformat(),'observed_at':now_iso(),
            'values':values,'risk_score':round(score,2),'url':url,
            'method':'制造业PMI40%、新订单35%、综合产出25%；各分项风险=clip(50−(PMI−50)×10,0,100)。'
                     '月度景气风险代理，未经回测；不能代替GDP、通胀、政策利率或全部宏观环境。'}


def collect_macro_risk(as_of,*,use_cache=False):
    source={'id':'macro:nbs_pmi','name':'国家统计局 · 月度PMI','url':LIST_URL,'status':'error',
            'count':0,'as_of':None,'fetched_at':now_iso()}
    cached=cached_pmi(as_of) if use_cache else None
    if cached:
        result,fetched=cached
        now=datetime.fromisoformat(as_of.replace('Z','+00:00'));now=now.replace(tzinfo=CHINA) if now.tzinfo is None else now
        fetched_time=datetime.fromisoformat(fetched.replace('Z','+00:00'))
        fetched_time=fetched_time.replace(tzinfo=CHINA) if fetched_time.tzinfo is None else fetched_time
        if 0<=(now-fetched_time).total_seconds()<3600:
            source.update(status='ok',url=result['url'],count=3,as_of=result['published_at'],
                          fetched_at=fetched,cache_used=True,note='使用一小时内已核验的官方PMI公告缓存；保留原发布时间。')
            return result,source
    try:
        text=fetch_text(LIST_URL);candidates=[]
        for link,title in re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>',text,re.S|re.I):
            title=re.sub('<[^>]+>','',title).strip()
            if re.fullmatch(r'\d{4}年\d{1,2}月中国采购经理指数运行情况',title):
                url=urljoin(LIST_URL,link)
                if urlparse(url).hostname=='www.stats.gov.cn':candidates.append(url)
        if not candidates:raise ValueError('未找到官方PMI公告')
        # Try at most two releases. A newer release can be future-dated for
        # an as-of report; never use it in place of the previous public one.
        result=None
        for url in sorted(set(candidates),reverse=True)[:2]:
            try:
                document=fetch_text(url)
                result=parse_pmi(document,url,as_of)
                break
            except ValueError:
                continue
        if result is None:raise ValueError('未取得截至报告时点有效的官方PMI公告')
        source.update(status='ok',url=url,count=3,as_of=result['published_at'])
        if use_cache:save_record(CACHE_PATH,'nbs_pmi',{'document':document,'url':url,'fetched_at':source['fetched_at']})
        return result,source
    except Exception as error:
        source['error']=type(error).__name__+'：'+str(error)[:180]
        if cached:
            result,fetched=cached
            source.update(status='partial',url=result['url'],count=3,as_of=result['published_at'],fetched_at=fetched,
                          cache_used=True,note='最新请求失败，使用发布时间仍有效的已核验官方公告。')
            result['latest_request_error']=source['error']
            return result,source
        return {'status':'unavailable','risk_score':None,'error':source['error']},source
