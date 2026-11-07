"""Subscriber scarcity observations derived solely from dated source-bound AI output."""
import copy
import json
import math
from datetime import datetime, timedelta

from research_data import CHINA
from research_news_verification import (clean, excerpt_in, signature, decode_verification,
                                        revalidate_verification)

VERSION = 'scarcity_news_20261101_v2'
METHOD = '最近7日已采集公告和官方新闻 → 事实与观点辨析 → 相反证据核对 → 具体环节分项评分。'
NOTE = '只按本批原文证据判断具体环节，不把涨价、热度或需求增长等同于稀缺；未标注表示证据不足。稀缺不代表低估或上涨。'
ELIGIBLE = ('admin', 'active', 'exhausted')
DIMENSIONS = (('concentration','供给集中度'), ('expansion','扩产难度'),
              ('substitution','替代难度'), ('technology','技术壁垒'))
CATEGORIES = {'resource':'资源供给', 'capacity':'产能约束', 'technology':'技术壁垒'}
DIRECTIONS = {'tightening':'约束增强', 'easing':'约束缓解', 'mixed':'影响待辨'}


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)
    except (ValueError, TypeError):
        return None


def _response(response):
    choice = response['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('新闻稀缺性评估未完整返回')
    value = json.loads(choice['message']['content'])
    if not isinstance(value, dict) or not isinstance(value.get('events'), list):
        raise ValueError('新闻稀缺性评估格式无效')
    return value


def decode_scarcity(response, candidates, catalog, leaders=()):
    """Optional extension of the existing single event request; no provider I/O."""
    raw = {r['id']:r for r in candidates}
    boards = {r['id']:r for r in catalog}
    memberships = {}
    for company in leaders:
        code = str(company.get('ts_code') or '').split('.')[0]
        memberships.setdefault(code,set()).update(m.get('sector_id') for m in company.get('sector_memberships',[]))
    claims, assessed, seen = [], set(), set()
    for row in _response(response)['events']:
        if not isinstance(row,dict) or row.get('id') not in raw or row['id'] in seen:
            continue
        source = raw[row['id']]
        seen.add(row['id'])
        verification = decode_verification(row.get('verification'), source, candidates)
        proposed = row.get('scarcity_assessments')
        if not isinstance(proposed,list) or verification['status'] == 'insufficient':
            continue
        assessed.add(source['id'])
        for item in proposed[:1]:
            if len(claims)>=4:
                break
            if not isinstance(item,dict):
                continue
            identity, category, direction = item.get('sector_id'), item.get('category'), item.get('direction')
            scope, reason, boundary = clean(item.get('scope'),250), clean(item.get('reason')), clean(item.get('boundary'),600)
            fact = excerpt_in(item.get('fact_excerpt'),source)
            if (identity not in boards or category not in CATEGORIES or direction not in DIRECTIONS
                    or len(scope)<4 or len(reason)<15 or len(boundary)<12 or not fact):
                continue
            mapped = set(source.get('sector_ids') or [])
            codes = source.get('stock_codes') or []
            for code in codes:
                mapped.update(memberships.get(str(code).split('.')[0],set()))
            # Company disclosures require an input business relationship; model memory is not a mapping.
            if codes and identity not in mapped:
                continue
            scope_level = 'company' if codes or source.get('event_type') == 'company_announcement' else 'industry'
            company_name=clean(source.get('company_name'),100)
            if scope_level=='company' and company_name and company_name not in scope:
                scope=company_name+' · '+scope
            dimensions = []
            proposed_dims = item.get('dimensions') if isinstance(item.get('dimensions'),dict) else {}
            for key, title in DIMENSIONS:
                d = proposed_dims.get(key)
                if not isinstance(d,dict):
                    continue
                level, why = d.get('level'), clean(d.get('reason'),600)
                quote = excerpt_in(d.get('fact_excerpt'),source)
                if type(level) is int and 0<=level<=5 and len(why)>=12 and quote:
                    dimensions.append({'id':key,'title':title,'level':level,'points':level*5,
                                       'reason':why,'fact_excerpt':quote})
            claims.append({'event_id':source['id'],'sector_id':identity,'category':category,
                'direction':direction,'scope':scope,'scope_level':scope_level,'reason':reason,
                'boundary':boundary,'fact_excerpt':fact,'dimensions':dimensions,'verification':verification,
                'source':{k:source.get(k) for k in ('id','title','url','published_at','source_name','company_name','source_id')},
                'signature':signature(source)})
    return {'version':VERSION,'assessments':claims,'assessed_event_ids':sorted(assessed),
            'status':'completed' if len(assessed)==len(candidates) and candidates else 'partial' if assessed else 'pending'}


def _current_claims(report, now=None):
    from research_event_ai import _eligible_event_candidates
    now = now or _time(report.get('as_of')) or datetime.now(CHINA)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CHINA)
    candidates = _eligible_event_candidates({**report,'as_of':now.isoformat()})
    sources = {r['id']:r for r in candidates}
    meta = (report.get('event_analysis') or {}).get('scarcity_analysis') or {}
    claims = []
    generated=_time((report.get('event_analysis') or {}).get('generated_at'))
    if (meta.get('version') != VERSION or report.get('report_stale') is True or not generated
            or not timedelta(0)<=now-generated<=timedelta(days=7)):
        return [], candidates, {}
    for stored in meta.get('assessments',[]):
        if not isinstance(stored,dict):
            continue
        source = sources.get(stored.get('event_id'))
        if not source or signature(source) != stored.get('signature'):
            continue
        claim = copy.deepcopy(stored)
        claim['verification'] = revalidate_verification(claim.get('verification'),source,candidates)
        claims.append(claim)
    return claims, candidates, meta


def strength_for(claim):
    """Four ordinal dimensions, never fill missing evidence or score opinions."""
    ver = claim.get('verification') or {}
    usable = ver.get('status') in ('cross_checked','single_source') and ver.get('claim_type')=='fact' and claim.get('direction')!='mixed'
    values = {v['id']:v for v in claim.get('dimensions',[]) if usable}
    dims=[]
    for key,title in DIMENSIONS:
        d=values.get(key)
        dims.append({'id':key,'title':title,'level':d['level'] if d else None,
            'points':d['points'] if d else None,'maximum':25,
            'reason':d['reason'] if d else '本批原文不足以对该项定级。',
            'fact_excerpt':d['fact_excerpt'] if d else '', 'source_indices':[0] if d else []})
    known=sum(d['points'] for d in dims if d['points'] is not None)
    count=sum(d['points'] is not None for d in dims)
    return {'score':known if count==4 else None,'confirmed_score':known if count else None,'maximum':100,
        'possible_range':[known,known+25*(4-count)] if count else [],'coverage':count,'coverage_total':4,
        'status':'complete' if count==4 else 'partial' if count else 'pending','dimensions':dims,
        'method':'AI按本批原文逐项判断0～5档×5分，每项最高25；0表示原文支持无明显约束，1弱、2有限、3中等、4高、5极高。没有直接依据、仅预测或有争议的项目不补分；不是官方指标、真实性概率或收益预测。'}


def attention_for(sector, *, stale=False):
    """Reuse the existing gated company research score; never add scarcity points."""
    from research_balanced_score import research_tier
    number = lambda v: type(v) in (int, float) and math.isfinite(v)
    active = not stale and sector.get('status') in ('ok', 'partial') and sector.get('score_model') == 'company_research_v2'
    breakdown = sector.get('score_breakdown') or {}
    point = lambda key: (breakdown.get(key) or {}).get('points')
    f,t,c = point('fundamentals'),point('trend'),point('catalysts')
    score = sector.get('research_score', sector.get('recommendation_index'))
    requirements = sector.get('requirements') or []
    data_ready = not requirements or all(any(r.get('id') == key and r.get('status') == 'ok' for r in requirements) for key in ('data','mapping','model'))
    complete = active and data_ready and sector.get('score_status') == 'complete' and number(score) and 0 <= score <= 100 and all(number(v) for v in (f,t,c))
    tier = research_tier(score if complete else None, f, t, c, bool(complete))
    known = sector.get('confirmed_score')
    return {'score':score if complete else None, 'known_score':known if active and number(known) else None,
            'known_maximum':sector.get('score_maximum',70), 'status':'complete' if complete else 'pending',
            'label':tier['label'] if complete else '待完成评估',
            'note':'关注值沿用公司研究分与原有档位门槛，稀缺标签不加分。完整证据不足时只列基础/阶段分。'}


def profile_for(sector_id, now=None, report=None, *, _claims=None):
    """Select the newest specific scope, never mix dimensions from different products."""
    claims = _current_claims(report or {},now)[0] if _claims is None else _claims
    own = [r for r in claims if r.get('sector_id')==sector_id]
    if not own:
        return None
    own.sort(key=lambda r:(_time(r['source']['published_at']),r['event_id']),reverse=True)
    # A newer easing/conflicting observation supersedes older bullish evidence.
    claim=own[0]
    ver=claim['verification'];strength=strength_for(claim)
    valid=ver['status'] in ('single_source','cross_checked') and ver['claim_type']=='fact'
    status=('easing' if valid and claim['direction']=='easing' else
            'reviewed' if valid and claim['direction']=='tightening' and any((d['level'] or 0)>=3 for d in strength['dimensions']) else 'needs_review')
    source=claim['source'];published=_time(source['published_at'])
    source_view={'title':source['title'],'url':source['url'],'published_at':source['published_at'],
                 'kind':source.get('source_name') or '公开披露','fact_excerpt':claim['fact_excerpt']}
    return {'version':VERSION,'status':status,'sector_id':sector_id,'category':claim['category'],
        'label':CATEGORIES[claim['category']],'scope':claim['scope'],'scope_level':claim['scope_level'],
        'basis':claim['reason'],'boundary':claim['boundary'],'direction':claim['direction'],
        'direction_label':DIRECTIONS[claim['direction']], 'verification':ver,
        'checks':['核对具体公司、产品及业务占比，避免把单家公司判断推广为全行业。',
                  '持续比对供给、订单、库存与扩产披露；关注相反证据。'],
        'invalidation':['新增产能、替代技术或需求变化使原约束不再成立。','来源更正、交叉证据冲突，或原文超过7日有效窗口。'],
        'sources':[source_view],'reviewed_at':(report.get('event_analysis') or {}).get('generated_at') or '',
        'review_due_at':(published+timedelta(days=7)).isoformat(), 'method':METHOD,'note':NOTE,
        'strength':strength,'credit_cost':0,'score_adjustment':0}


def profiles_for(report, now=None):
    claims,_,_=_current_claims(report,now)
    return {identity:profile_for(identity,now,report,_claims=claims)
            for identity in {r['sector_id'] for r in claims}}


def summary_for(report, now=None):
    claims,candidates,meta=_current_claims(report,now)
    analyzed=(report.get('event_analysis') or {})
    signatures=analyzed.get('candidate_signatures') or {}
    assessed=set(meta.get('assessed_event_ids') or []).intersection(r['id'] for r in candidates if signatures.get(r['id'])==signature(r))
    return {'version':VERSION,'status':'ready' if claims else 'no_supported_clues' if assessed else 'pending',
        'candidate_count':len(candidates),'assessed_count':len(assessed),'claim_count':len(claims),
        'selection_limit':12,'generated_at':analyzed.get('generated_at'),
        'note':'仅评估最近7日已采集且正文完整的公告与官方新闻，每批最多12条、4项稀缺线索；未标注不表示已排除，不代表全网覆盖。',
        'schedule':'A股交易日 09:20 / 14:50（北京时间）',
        'cost_note':'复用既有定时事件研究，新增核验内容会占用该请求的Token；不增加调用次数，查看与刷新不调用AI、不另扣研究点数。'}


def project_member_report(report, subscription_status, now=None, *, historical=False):
    """Enforce subscription access before serialization, including raw AI metadata."""
    if not isinstance(report,dict):
        return report
    allowed=subscription_status in ELIGIBLE
    out={k:v for k,v in report.items() if k not in ('scarcity_sectors','scarcity_note','scarcity_access','scarcity_summary','scarcity_analysis')}
    if isinstance(report.get('event_analysis'),dict):
        event={k:v for k,v in report['event_analysis'].items() if k not in ('scarcity_analysis','source_verifications')}
        event['events']=[{k:v for k,v in r.items() if allowed or k!='verification'} for r in event.get('events',[])]
        out['event_analysis']=event
    out['sector_analysis']=[]
    profiles=profiles_for(report,now) if allowed and not historical else {}
    if allowed:
        out['scarcity_access']={'allowed':True,'included':True,'credit_cost':0,'historical':historical}
        if not historical:
            out['scarcity_summary']=summary_for(report,now)
    for original in report.get('sector_analysis',[]):
        sector={k:v for k,v in original.items() if k!='scarcity'}
        if allowed and not historical:
            profile=copy.deepcopy(profiles.get(sector.get('id')))
            if profile:
                profile['attention']=attention_for(sector,stale=report.get('report_stale') is True)
                sector['scarcity']=profile
        out['sector_analysis'].append(sector)
    return out
