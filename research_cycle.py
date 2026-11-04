"""Subscriber long-wave research workspace; local evidence projection, no AI I/O.

Kondratieff is an organising hypothesis, not an estimated market clock. Current
PMI/funding observations describe a short-term environment only. No extrapolated
long-wave dates, invented macro series, paid narratives or new research scores.
"""
import math
from datetime import datetime
from urllib.parse import urlsplit

from research_data import CHINA
from research_trading_calendar import last_closed_trading_day
from research_scarcity import profile_for, profiles_for, attention_for, summary_for, NOTE as SCARCITY_NOTE
from research_numbers import strict_finite_number as finite

VERSION = 'long_wave_workspace_v1'
ELIGIBLE = ('admin', 'active', 'exhausted')
THEMES = (
    ('digital', '数字生产力', '01', 'AI、算力与半导体',
     ['sector_ai', 'sector_semiconductor', 'sector_memory_chip', 'sector_cpo'],
     '把技术投入转化为收入、利润与现金流，才有持续研究价值。',
     ['核验公司订单、交付与收入确认', '连续财报验证利润增长及现金回收'],
     ['资本开支先行，收入兑现可能滞后', '高估值、利率上行与技术替代风险']),
    ('energy', '能源与电网', '02', '电网、储能与电力',
     ['sector_grid_equipment', 'sector_energy_storage', 'sector_power'],
     '围绕能源系统投资，追踪订单质量、项目回报与供需变化。',
     ['核验实际招标、中标与项目交付', '核验利用率、毛利与经营现金流'],
     ['产能过剩和价格竞争', '项目延期、政策及回款风险']),
    ('manufacturing', '制造效率升级', '03', '机器人与先进制造',
     ['sector_robotics', 'sector_advanced_manufacturing', 'sector_semiconductor_equipment', 'sector_construction_machinery'],
     '关注设备更新与自动化如何改善客户效率和企业盈利。',
     ['区分试点订单和规模化收入', '跟踪订单持续性、毛利与应收账款'],
     ['主题热度快于商业兑现', '需求周期、出口与供应链约束']),
    ('resources', '资源供给约束', '04', '有色、稀土与化工',
     ['sector_nonferrous', 'sector_rare_earth_magnet', 'sector_chemicals'],
     '同时观察需求、库存和新增供给，不把涨价直接等同长期繁荣。',
     ['核验产品价格、库存与产能投放', '核验销量、单位成本与盈利弹性'],
     ['需求转弱或供给释放', '商品价格回落、汇率与杠杆风险']),
    ('health', '医疗与人口需求', '05', '创新药、医疗与养老',
     ['sector_innovative_drug', 'sector_medical', 'sector_eldercare'],
     '从长期需求出发，用产品进展和可持续支付能力验证商业价值。',
     ['核验临床、审批和商业化进度', '核验支付政策、收入质量与现金储备'],
     ['研发失败与审批不确定性', '支付约束、竞争和融资稀释']),
    ('resilience', '现金流与韧性', '06', '红利、现金流与公用事业',
     ['dividend', 'style_cashflow', 'sector_utilities'],
     '在研究机会的同时，检查分红和现金流能否持续。',
     ['核验经营现金流与分红覆盖', '核验负债、资本开支和收益来源'],
     ['分红下降与估值过高', '利率变化及行业盈利下行']),
)
SCENARIOS = (
    ('repair', '需求扩张 · 资金趋宽', '新订单 PMI ≥50，20日隔夜 Shibor 下降至少5基点',
     '交叉核验创新与制造主题的订单兑现，避免只依赖流动性。'),
    ('friction', '需求扩张 · 资金趋紧', '新订单 PMI ≥50，20日隔夜 Shibor 上升至少5基点',
     '检查盈利能否覆盖资金成本和估值压力，优先核验现金流质量。'),
    ('transition', '需求偏弱 · 资金趋宽', '新订单 PMI <50，20日隔夜 Shibor 下降至少5基点',
     '观察宽资金能否传导至订单和利润，保留耐心，等待公司证据配合。'),
    ('pressure', '需求偏弱 · 资金趋紧', '新订单 PMI <50，20日隔夜 Shibor 上升至少5基点',
     '降低研究优先级中的叙事权重，先检查现金流、杠杆与回撤风险。'),
)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed.astimezone(CHINA)
    except (ValueError, TypeError):
        return None


def fresh(value, now, days):
    date = timestamp(value)
    return date is not None and 0 <= (now - date).total_seconds() <= days * 86400


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        return value if url.scheme == 'https' and url.hostname and not url.username and not url.password else None
    except ValueError:
        return None


def macro_signals(report, now):
    macro = (report.get('strategy') or {}).get('macro_evidence') or {}
    source = next((s for s in (report.get('snapshot') or {}).get('sources', [])
                   if s.get('id') == 'macro:nbs_pmi'), {})
    values = macro.get('values') or {}
    pmi_ok = (macro.get('status') == 'ok' and source.get('status') in ('ok', 'partial')
              and fresh(macro.get('published_at'), now, 62)
              and source.get('as_of') == macro.get('published_at')
              and safe_url(macro.get('url')) is not None
              and urlsplit(macro['url']).hostname == 'www.stats.gov.cn'
              and source.get('url') == macro.get('url')
              and all(finite(values.get(k)) and 0 <= values[k] <= 100
                      for k in ('manufacturing', 'new_orders', 'composite')))
    liquidity = report.get('market_liquidity') or {}
    closed = last_closed_trading_day(now.isoformat())
    funding_ok = (liquidity.get('status') == 'ok' and closed is not None
                  and fresh(liquidity.get('as_of'), now, 12)
                  and closed <= str(liquidity.get('as_of'))[:10] <= now.date().isoformat()
                  and finite(liquidity.get('annual_rate_pct')) and 0 <= liquidity['annual_rate_pct'] <= 100
                  and finite(liquidity.get('rate_change_20d_bp'))
                  and bool(liquidity.get('source_ids')))
    return [
        {'id':'demand', 'title':'景气与订单', 'status':'ready' if pmi_ok else 'missing',
         'value':values.get('new_orders') if pmi_ok else None, 'unit':'新订单 PMI',
         'detail':('制造业 %.1f · 综合产出 %.1f；50为荣枯分界。' % (values['manufacturing'], values['composite']))
                   if pmi_ok else '等待有效的官方PMI及发布时间核验。',
         'as_of':macro.get('published_at') if pmi_ok else None,
         'source_name':'国家统计局 · '+str(macro.get('title') or '月度PMI'),
         'url':safe_url(macro.get('url')) if pmi_ok else None,
         'scope':'月度景气观察，不能确定长期周期阶段。'},
        {'id':'funding', 'title':'短端资金', 'status':'ready' if funding_ok else 'missing',
         'value':liquidity.get('annual_rate_pct') if funding_ok else None, 'unit':'% · 隔夜 Shibor',
         'change_bp':liquidity.get('rate_change_20d_bp') if funding_ok else None,
         'detail':('近20个有效发布日变化 %+.1f 基点。' % liquidity['rate_change_20d_bp'])
                   if funding_ok else '等待近期有效的人民币隔夜资金利率。',
         'as_of':liquidity.get('as_of') if funding_ok else None,
         'source_name':'人民币隔夜 Shibor · 既有数据接口', 'url':'https://www.shibor.org/',
         'scope':'仅代表人民币短端资金价格，非完整流动性或全球实际利率。'},
        {'id':'inflation', 'title':'通胀与实际利率', 'status':'missing', 'value':None,
         'detail':'CPI、PPI与实际利率的长期序列尚未接入。'},
        {'id':'credit', 'title':'信用与债务', 'status':'missing', 'value':None,
         'detail':'社融、债务负担与信用脉冲的长期序列尚未接入。'},
        {'id':'productivity', 'title':'生产率与投资', 'status':'missing', 'value':None,
         'detail':'生产率、研发与资本开支的长期序列尚未接入。'},
    ]


def sector_evidence(sector, watched, now, report=None, scarcity_profiles=None):
    closed = last_closed_trading_day(now.isoformat())
    observed = (sector.get('quote') or {}).get('as_of') or sector.get('as_of')
    index = sector.get('custom_index') or {}
    valid = (sector.get('status') == 'ok' and sector.get('score_model') == 'company_research_v2'
             and index.get('ready') is True and closed is not None and fresh(observed, now, 12)
             and closed <= str(observed)[:10] <= now.date().isoformat())
    breakdown = sector.get('score_breakdown') or {}
    def point(key, low, high):
        v = (breakdown.get(key) or {}).get('points')
        return v if valid and finite(v) and low <= v <= high else None
    fund, trend, event = point('fundamentals', 0, 40), point('trend', 0, 30), point('catalysts', -30, 30)
    full = sector.get('research_score')
    complete = (valid and sector.get('score_status') == 'complete' and finite(full) and 0 <= full <= 100
                and all(v is not None for v in (fund, trend, event)))
    tier = (sector.get('research_tier') or {}).get('label') if complete else '待完成评估'
    confirmed = sector.get('confirmed_score')
    risk = sector.get('market_risk') or {}
    risk_score = risk.get('score') if valid and finite(risk.get('score')) and 0 <= risk['score'] <= 100 else None
    scarcity = (scarcity_profiles.get(sector['id']) if scarcity_profiles is not None else profile_for(sector['id'],now,report))
    scarcity = {**scarcity} if scarcity else None
    if scarcity:
        scarcity['attention'] = attention_for(sector, stale=not valid)
    return {'id':sector['id'], 'title':sector.get('title') or sector.get('label') or sector['id'],
            'watched':sector['id'] in watched, 'status':'ready' if valid else 'pending',
            'scarcity':scarcity,
            'as_of':observed if valid else None, 'score':full if complete else None,
            'known_score':confirmed if valid and finite(confirmed) and 0 <= confirmed <= 100 else None,
            'tier':tier, 'fundamentals':fund, 'trend':trend, 'catalysts':event,
            'risk_score':risk_score, 'risk_status':risk.get('status') if valid else None,
            'checks':[{'label':'基本面 ≥28/40', 'state':'unknown' if fund is None else 'met' if fund >= 28 else 'unmet'},
                      {'label':'走势 ≥18/30', 'state':'unknown' if trend is None else 'met' if trend >= 18 else 'unmet'},
                      {'label':'事件催化为正', 'state':'unknown' if event is None else 'met' if event > 0 else 'unmet'}]}


def project_cycle(accounts, user_id, report, now=None, *, report_stale=False):
    sub = accounts.subscriptions.summary(user_id)
    result = {'version':VERSION, 'access':sub['status'] in ELIGIBLE,
              'subscription_status':sub['status'], 'credit_cost':0, 'included':True,
              'phase':'unverified', 'phase_label':'长期阶段尚待验证',
              'method':'以长期主题提出研究命题，以当前宏观和公司证据检验；不改变既有板块评分。',
              'note':'当前情景是月度景气与短端资金的交叉观察，不是康波阶段判定，也不是收益预测。'}
    if not result['access']:
        return {**result, 'status':'locked'}
    now = now or datetime.fromtimestamp(accounts.clock(), CHINA)
    report = report if isinstance(report, dict) else {}
    valid_report = not report_stale and fresh(report.get('as_of'), now, 3)
    evidence_report = report if valid_report else {}
    signals = macro_signals(evidence_report, now)
    scenario = 'unverified'
    if all(s['status'] == 'ready' for s in signals[:2]):
        demand, change = signals[0]['value'], signals[1]['change_bp']
        scenario = ('repair' if demand >= 50 else 'transition') if change <= -5 else (
            ('friction' if demand >= 50 else 'pressure') if change >= 5 else 'mixed')
    watched = set(accounts.watchlist(user_id))
    sectors = {s['id']:s for s in evidence_report.get('sector_analysis', []) if isinstance(s, dict) and isinstance(s.get('id'), str)}
    scarcity_profiles=profiles_for(evidence_report,now)
    themes = []
    for identity, title, serial, subtitle, ids, thesis, checks, risks in THEMES:
        items = [sector_evidence(sectors[i], watched, now, evidence_report, scarcity_profiles) for i in ids if i in sectors]
        themes.append({'id':identity, 'title':title, 'serial':serial, 'subtitle':subtitle,
                       'thesis':thesis, 'next_checks':checks, 'risks':risks, 'sectors':items,
                       'watch_count':sum(s['watched'] for s in items),
                       'evidence_count':sum(s['status']=='ready' for s in items)})
    return {**result, 'status':'ready' if valid_report else 'awaiting_report',
            'as_of':report.get('as_of') if valid_report else None,
            'signals':signals, 'coverage':sum(s['status']=='ready' for s in signals),
            'coverage_total':len(signals), 'current_scenario':scenario,
            'scenarios':[{'id':i, 'title':t, 'condition':c, 'implication':x, 'active':i==scenario} for i,t,c,x in SCENARIOS],
            'themes':themes, 'scarcity_note':SCARCITY_NOTE, 'scarcity_summary':summary_for(evidence_report,now),
            'scarcity_sectors':[{'id':s['id'], 'title':s.get('title') or s.get('label') or s['id'],
                                'scarcity':{**p, 'attention':attention_for(s, stale=sector_evidence(s,watched,now)['status']!='ready')}, 'watched':s['id'] in watched}
                               for s in sectors.values() if (p := scarcity_profiles.get(s['id']))],
            'references':[
                {'title':'Kondratieff · The Long Waves in Economic Life（1935）',
                 'url':'https://doi.org/10.2307/1928486', 'scope':'长波研究的原始文献线索；并非当前市场阶段的证据。'},
                {'title':'当前数据口径', 'scope':'PMI和Shibor来源与日期见上方；主题对应关系和情景阈值为本站研究设计，未经策略回测。'}]}
