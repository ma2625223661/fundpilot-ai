"""Company research points and independent sensitivity-aware risk scores.

Editorial v2 weights are explicit research rules, not fitted return forecasts.
Only assessed catalysts can add/subtract points; missing evidence stays null.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from research_data import CHINA
from research_numbers import finite_number as finite

VERSION = 'company_research_v2'
METHOD = ('板块研究模型v2：基本面0–40、走势0–30，只有事件催化双向加减（−30至+30）；'
          '总分限0–100。基本面使用逐公司截尾后的营收增长、净利增长及实际盈利状态，'
          '先逐公司映射0–100再取中位数，覆盖权重为40%/35%/25%；缺项不补中性分。'
          '走势仅使用20日收益/60日收益/20日均线差，内部权重50%/25%/25%，'
          '映射分别为clip(50+收益×1.5)、clip(50+收益×0.75)、clip(50+均线差×2.5)。'
          '事件采用近7天已核验官方事件中最强利好与最强利空各一条，净影响×0.3；'
          '未评估事件为null，只展示基础已知分/70；部分事件已评估时展示阶段分/100，不冒充完整分。'
          '各分项先按0.01分四舍五入再相加，最终限0–100后分档：65/50/30为分界；乐观看待另须基本面至少28/40，'
          '且走势至少18/30或催化为正，全部评分证据核验完整。'
          '大盘、流动性和宏观风险另行评分，不截断板块研究分；未经收益回测。')
TECH = set('sector_cpo sector_pcb sector_mlcc sector_ai sector_ai_application sector_semiconductor '
           'sector_semiconductor_equipment sector_memory_chip sector_cloud_computing sector_domestic_computing '
           'sector_compute_leasing sector_communication sector_consumer_electronics sector_technology '
           'sector_robotics sector_fintech overseas_hk_internet overseas_hang_seng_technology index_star index_dual50 index_chinext'.split())
CYCLE = set('sector_oil_gas sector_coal sector_steel sector_chemicals sector_nonferrous sector_resources '
            'sector_real_estate sector_infrastructure sector_advanced_manufacturing sector_manufacturing '
            'sector_lithium_mining sector_construction_machinery sector_transport commodities sector_gold_equity gold'.split())


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=CHINA) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


def clip(value, lo=0, hi=100):
    return max(lo, min(hi, value))


def round_points(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))


def trend_points(metrics):
    fields = [('return_20d', .5, 1.5), ('return_60d', .25, .75), ('ma20_gap', .25, 2.5)]
    details = [{'field': key, 'value': metrics.get(key), 'weight': weight,
                'score': clip(50+metrics[key]*scale) if finite(metrics.get(key)) else None}
               for key, weight, scale in fields]
    if any(d['score'] is None for d in details):
        return {'points': None, 'maximum': 30, 'coverage_pct': 0, 'details': details}
    return {'points': round_points(sum(d['score']*d['weight'] for d in details)*.3),
            'maximum': 30, 'coverage_pct': 100, 'details': details}


def fundamental_points(leaders, as_of):
    from research_sample_policy import financial_ready
    reports = [r.get('financials') or {} for r in leaders if financial_ready(r, as_of)]
    n = len(leaders)
    channels = []
    for key, weight, scale in [('tr_yoy', .4, 1), ('netprofit_yoy', .35, .5), ('profitability', .25, None)]:
        values=[]
        for f in reports:
            if key == 'profitability':
                value = f.get('eps') if finite(f.get('eps')) else f.get('net_profit')
                if finite(value): values.append(100 if value > 0 else 0 if value < 0 else 50)
            elif finite(f.get(key)):
                values.append(clip(50+f[key]*scale))
        coverage = len(values)/n if n else 0
        lower = statistics.median(values+[0]*(n-len(values))) if n else 0
        upper = statistics.median(values+[100]*(n-len(values))) if n else 100
        channels.append({'field':key,'weight':weight,'count':len(values),'sample_count':n,
                         'coverage_pct':round(coverage*100,2),
                         'score':statistics.median(values) if values else None,
                         'possible_score_range':[lower, upper]})
    covered=sum(d['weight']*d['coverage_pct']/100 for d in channels)
    # Partial fundamentals earn only evidenced points; there is no redistribution
    # or guessed neutral result for missing fields/companies.
    points=sum((d['score'] or 0)*d['weight']*d['coverage_pct']/100*.4 for d in channels)
    return {'points':round_points(points) if covered else None,'maximum':40,
            'coverage_pct':round(covered*100,2),'details':channels,
            'possible_range':[round_points(sum(d['possible_score_range'][i]*d['weight']*.4 for d in channels)) for i in (0,1)],
            'scope':'公司整体营收增长、净利增长和盈利状态；估值、现金流、杠杆与主题分部收入尚未单独计分。'}


def catalyst_points(meta, identity, as_of):
    from research_event_ai import OFFICIAL_EVENT_SOURCES
    now=stamp(as_of); own=[];seen=set()
    if meta.get('status') in {'completed','partial'} and now:
        for row in meta.get('events',[]):
            date=stamp(row.get('published_at')); score=row.get('impact_score');direction=row.get('direction')
            key=(row.get('event_id') or row.get('id') or row.get('url') or row.get('title'),direction)
            if (row.get('evidence_usable') is not False and identity in row.get('sector_ids',[]) and date and 0 <= (now-date).total_seconds() <= 7*86400
                and finite(score) and 40 <= abs(score) <= 100
                and set(row.get('source_ids',[])).intersection(OFFICIAL_EVENT_SOURCES)
                and (direction=='positive' and score>0 or direction=='negative' and score<0) and key not in seen):
                seen.add(key);own.append(row)
    eligible=meta.get('eligible_count',0);assessed=meta.get('assessed_count',0)
    complete=(meta.get('status') in {'completed', 'no_evidence'} and meta.get('unassessed_count',0)==0 and meta.get('verification_incomplete_count',0)==0
              and (not finite(eligible) or eligible <= (assessed if finite(assessed) else 0)))
    pos=max((r['impact_score'] for r in own if r['direction']=='positive'),default=0)
    neg=min((r['impact_score'] for r in own if r['direction']=='negative'),default=0)
    known=round_points((pos+neg)*.3) if own or complete else None
    # With unassessed evidence, the unknown strongest positive/negative can
    # still move the net. These are mathematical bounds, not predictions.
    bounds = [known, known] if complete else [round_points((pos-100)*.3), round_points((100+neg)*.3)]
    return {'points':known if complete else None,'observed_adjustment':known,'maximum':30,
            'possible_range':bounds,
            'coverage_pct':100 if complete else 0, 'status': 'assessed' if complete and own else
            'no_material_events' if complete else 'partially_assessed' if own else 'unassessed',
            'positive_impact':pos if own else None,'negative_impact':neg if own else None,
            'source_ids':list(dict.fromkeys(s for r in own for s in r.get('source_ids',[]))),
            'note':'只取最强利好和最强利空，重复报道不叠加；评估范围限本批已采集官方证据。'}


def score_company(sector, meta, as_of):
    trend=trend_points(sector.get('metrics') or {})
    financial=fundamental_points(sector.get('leaders') or [],as_of)
    events=catalyst_points(meta,sector['id'],as_of)
    if trend['points'] is None or financial['points'] is None:
        return None
    base=trend['points']+financial['points']
    complete=events['points'] is not None and financial['coverage_pct']>=99.999
    adjustment=events['observed_adjustment']
    confirmed=round_points(clip(base+(adjustment if adjustment is not None else 0)))
    low=clip(trend['points']+financial['possible_range'][0]+events['possible_range'][0])
    high=clip(trend['points']+financial['possible_range'][1]+events['possible_range'][1])
    return {'score':confirmed, 'base_score':round_points(base), 'complete_score':confirmed if complete else None,
            'score_status':'complete' if complete else 'provisional',
            'score_maximum':100 if adjustment is not None else 70,
            'coverage_pct':round(.3*trend['coverage_pct']+.4*financial['coverage_pct']+.3*events['coverage_pct'],2),
            'possible_range':[round_points(low),round_points(high)],'breakdown':{'trend':trend,'fundamentals':financial,'catalysts':events}}


def research_tier(score, fundamentals, trend, catalyst, complete):
    """Only a complete company score can enter the four research tiers."""
    conditions={'total_at_least_65':finite(score) and score>=65,
                'fundamentals_at_least_28':finite(fundamentals) and fundamentals>=28,
                'trend_at_least_18_or_positive_catalyst':(finite(trend) and trend>=18) or (finite(catalyst) and catalyst>0),
                'evidence_complete':complete is True}
    if not finite(score) or not complete:
        return {'id':'pending','label':'待完成评估','reason':'评分证据未齐，不将阶段分套入完整档位。','conditions':conditions}
    if score>=65 and all(conditions.values()):
        identity,label,reason='optimistic','乐观看待','总分、基本面和配合条件均满足，纳入重点观察池。'
    elif score>=50:
        identity,label='neutral','中性'
        missing=[]
        if score>=65 and not conditions['fundamentals_at_least_28']:missing.append('基本面不足28/40')
        if score>=65 and not conditions['trend_at_least_18_or_positive_catalyst']:missing.append('走势不足18/30且催化非正')
        reason='；'.join(missing)+'，未进入乐观档。' if missing else '持续观察，等待证据改善。'
    elif score>=30:
        identity,label,reason='cautious','谨慎','降低关注优先级。'
    else:
        identity,label,reason='avoid','规避','当前证据不支持重点研究。'
    return {'id':identity,'label':label,'reason':reason,'conditions':conditions}


def apply_market_risks(report):
    from research_trading_calendar import a_share_quote_fresh
    strategy=report.setdefault('strategy',{});panic=strategy.get('panic') or {}
    market=panic.get('score') if finite(panic.get('score')) and 0<=panic['score']<=100 else None
    market_time=stamp(panic.get('quote_as_of') or panic.get('data_time'))
    now=stamp(report.get('as_of'))
    if not market_time or not now or not a_share_quote_fresh(market_time.isoformat(),now.isoformat()):market=None
    money=next((s for s in report.get('sector_analysis',[]) if s['id']=='money'),{})
    liquidity=100-money['recommendation_index'] if (money.get('status')=='ok' and money.get('score_scope')=='money_liquidity'
        and finite(money.get('recommendation_index')) and 0<=money['recommendation_index']<=100) else None
    money_time=stamp(money.get('as_of'))
    if not money_time or not now or not a_share_quote_fresh(money.get('as_of'),now.isoformat(),daily=True):liquidity=None
    macro_data=strategy.get('macro_evidence') or {};macro=macro_data.get('risk_score')
    macro_time=stamp(macro_data.get('published_at'))
    macro=macro if (finite(macro) and 0<=macro<=100 and macro_data.get('status')=='ok'
                   and macro_time and now and 0<=(now-macro_time).total_seconds()<=62*86400) else None
    strategy['risk_overview']={'market':market,'liquidity':liquidity,'macro':macro,
        'direction':'higher_is_riskier','liquidity_note':'人民币隔夜Shibor资金价格与变化代理，不等于政策利率或完整资金供给。',
        'source_ids':list(dict.fromkeys([r.get('source_id') for r in report.get('snapshot',{}).get('market',[]) if r.get('source_id')]
                     + ([money.get('quote',{}).get('source_id','sector_reference:money')] if liquidity is not None else [])+(['macro:nbs_pmi'] if macro is not None else [])))}
    for sector in report.get('sector_analysis',[]):
        identity=sector['id'];tech=identity in TECH;cycle=identity in CYCLE
        profile='科技敏感' if tech else '周期敏感' if cycle else '一般市场'
        weights={'market':.35,'liquidity':.5,'macro':.15} if tech else (
            {'market':.25,'liquidity':.15,'macro':.6} if cycle else {'market':.5,'liquidity':.3,'macro':.2})
        values={'market':market,'liquidity':liquidity,'macro':macro}
        coverage=sum(weights[k] for k,v in values.items() if v is not None)
        score=round(sum(values[k]*weights[k] for k in values if values[k] is not None)/coverage) if coverage else None
        sector['market_risk']={'score':score,'profile':profile,'weights':weights,'components':values,
            'coverage_pct':round(coverage*100),'status':'complete' if coverage>=.999999 else 'partial' if coverage else 'unavailable',
            'level':'高风险' if score is not None and score>=65 else '中风险' if score is not None and score>=40 else '低风险' if score is not None else '待核验',
            'source_ids':strategy['risk_overview']['source_ids'],
            'scope':'A股市场压力、人民币隔夜Shibor与中国PMI；海外方向仅作中国环境参考，非当地市场或外币利率风险。',
            'note':'风险越高分数越高；不扣减板块研究分。缺失分项不补中性值，部分风险仅按已取得权重归一。'}
