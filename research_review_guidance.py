"""Deterministic, subscription-scoped follow-up priorities for five-day reviews.

This is an explicit research policy, not a fitted return model or probability.
It leaves the existing research and historical review scores untouched.
"""
import math

from research_sector_ai import _research_action
from research_numbers import strict_finite_number as finite


GUIDANCE_VERSION = 'review_attention_v1'
GUIDANCE_METHOD = (
    '推荐关注指数=min(五日走势复盘分,所有适用的研究与风险上限)，满分100。'
    '完整研究档位的上限：重点跟踪100、中性64、谨慎49、规避29；'
    '研究未完成或仅为参考指标时上限49，不把基础/70折算成完整分。'
    '环境风险未评估或≥70时上限49，≥85时上限29；行情高风险上限49、特大风险上限29。'
    '五日最大回撤≥10%时上限29；五日收益为负或跑输参考样本时上限64。'
    '上限取最严格的一项，不重复相减。缺少完整五日评分或报告过期时不出指数。'
    '档位：≥65乐观看待、50至不足65中性、30至不足50谨慎、低于30规避。'
    '这些是公开的研究筛选规则，未经收益策略回测，不表示上涨概率或买卖价格。')


def review_action(score):
    if not finite(score) or not 0 <= score <= 100:
        return 'wait'
    return 'track' if score >= 65 else 'observe' if score >= 50 else 'cautious' if score >= 30 else 'avoid'


LABELS = {'track': '乐观看待', 'observe': '中性', 'cautious': '谨慎', 'avoid': '规避', 'wait': '待评估'}
HEADLINES = {'track': '纳入重点跟踪，参与前再核验', 'observe': '持续观察，等待改善得到确认',
             'cautious': '降低优先级，先看风险修复', 'avoid': '暂缓新增参与，优先复核风险',
             'wait': '先补齐证据，暂不形成参与判断'}
BEFORE = {
    'track': '可纳入重点观察清单。参与前核对最新公告、估值与实际标的流动性，再结合自己的风险承受能力制定计划。',
    'observe': '以观察为主，等待走势与公司证据共同改善；不要仅因一天上涨就升级参与计划。',
    'cautious': '暂不提高参与优先级，先确认走势止弱、相对表现修复，以及尚未评估的公司或事件证据。',
    'avoid': '暂缓新增参与计划。不要仅因跌幅较大就判断已经便宜，先等待止弱与风险条件改善。',
    'wait': '补齐本期样本日线、参考样本与研究依据；证据不足时不设入场价、不用零分代替未知。'}
HOLDING = {
    'track': '复核持有理由是否仍成立，继续跟踪公告和风险变化；指数上升不代表需要自动加仓。',
    'observe': '对照原先持有逻辑与风险预算，检查表现是否持续落后；不把中性观察当作自动加仓信号。',
    'cautious': '优先检查仓位是否超出原定风险预算，以及原先持有理由是否减弱；条件未修复前避免盲目摊薄成本。',
    'avoid': '优先复核原定风控和退出条件；若原有持有理由失效，应按自己的既定计划控制风险，不把短暂反弹当作趋势恢复。',
    'wait': '先核对实际持仓对应的公告和行情，继续执行原有风控计划，不能据缺失数据认定风险已经解除。'}
UPGRADE = {
    'track': '维持重点跟踪需指数持续≥65、完整公司研究仍满足重点跟踪条件，且没有更低的风险上限。',
    'observe': '只有指数≥65、完整公司研究达到重点跟踪条件，且行情与环境限制解除后，才升级为重点跟踪。',
    'cautious': '指数达到50，且研究证据、行情与环境风险均不再受49分及以下上限约束后，才转为中性观察。',
    'avoid': '指数回到30并解除29分上限后，才进入谨慎观察；指数达到50且相关限制解除后，再提高关注优先级。',
    'wait': '先取得最近连续26个交易日的公司样本与同日参考数据，并更新有效报告；评分完整后再按档位判断。'}


def review_guidance(item, sector, *, current=True, report_as_of=None):
    if item.get('review_kind') == 'rate':
        return _liquidity_guidance(item, current, report_as_of)
    caps = []
    action = _research_action(sector)
    action_cap = {'track': 100, 'observe': 64, 'cautious': 49, 'avoid': 29,
                  'wait': 49, 'reference': 49}.get(action, 49)
    action_reason = {'track': '完整公司研究满足重点跟踪门槛', 'observe': '完整公司研究仍为中性档位',
                     'cautious': '完整公司研究处于谨慎档位', 'avoid': '完整公司研究处于规避档位',
                     'wait': '公司完整研究尚未完成，基础/阶段分不折算',
                     'reference': '当前仅为参考指标，不能替代完整公司研究'}.get(action, '研究证据尚未齐全')
    caps.append({'id': 'research', 'maximum': action_cap, 'reason': action_reason})
    risk = (sector.get('market_risk') or {}).get('score')
    if (not finite(risk) or not 0 <= risk <= 100
            or (sector.get('market_risk') or {}).get('status') in ('partial','pending','missing','unavailable')):
        caps.append({'id': 'environment', 'maximum': 49, 'reason': '环境风险尚未完成评估'})
        risk = None
    elif risk >= 85:
        caps.append({'id': 'environment', 'maximum': 29, 'reason': f'环境风险 {risk:g}/100，达到85分限制'})
    elif risk >= 70:
        caps.append({'id': 'environment', 'maximum': 49, 'reason': f'环境风险 {risk:g}/100，达到70分限制'})
    quote_risk = sector.get('risk')
    if isinstance(quote_risk, str) and '特大风险' in quote_risk:
        caps.append({'id': 'quote_risk', 'maximum': 29, 'reason': '样本行情被标记为特大风险'})
    elif isinstance(quote_risk, str) and '高风险' in quote_risk:
        caps.append({'id': 'quote_risk', 'maximum': 49, 'reason': '样本行情被标记为高风险'})
    elif not isinstance(quote_risk, str) or quote_risk not in ('低风险', '中风险'):
        caps.append({'id': 'quote_risk', 'maximum': 49, 'reason': '样本行情风险尚未完成评估'})
    dd, ret, excess = (item.get(k) for k in ('drawdown_pct', 'return_pct', 'excess_pct'))
    if finite(dd) and dd >= 10:
        caps.append({'id': 'drawdown', 'maximum': 29, 'reason': f'五日最大回撤 {dd:g}%，达到10%限制'})
    if finite(ret) and ret < 0:
        caps.append({'id': 'return', 'maximum': 64, 'reason': '五日样本收益仍为负值'})
    if finite(excess) and excess < 0:
        caps.append({'id': 'relative', 'maximum': 64, 'reason': '五日表现仍落后于参考公司样本'})
    required = (dd,ret) if item.get('review_kind')=='reference' else (dd,ret,excess)
    ready = (current and item.get('status') == 'completed' and finite(item.get('score'))
             and 0 <= item['score'] <= 100 and all(finite(v) for v in required))
    cap = min(row['maximum'] for row in caps)
    index = round(min(item['score'], cap), 2) if ready else None
    tier = review_action(index)
    basis = []
    if finite(ret):
        basis.append(f'五日样本涨跌 {ret:+g}%')
    if finite(excess):
        basis.append(f'相对参考样本 {excess:+g} 个百分点')
    if finite(dd):
        basis.append(f'五日最大回撤 {dd:g}%')
    if not current:
        reason = '报告已过期或日期尚未核验，历史走势可回看，当前推荐关注指数暂停提供。'
    elif not ready:
        reason = item.get('reason') or '五日复盘或参考证据尚未完整，暂不形成推荐关注指数。'
    else:
        reason = '以五日复盘分为基础，受当前研究证据与风险上限约束；不是收益预测。'
    checks = [
        {'id': 'trend', 'label': '走势修复', 'condition': '五日走势复盘分≥50',
         'value': f"{item['score']:g}/100" if finite(item.get('score')) else '待补数据',
         'met': item['score'] >= 50 if finite(item.get('score')) else None},
        {'id': 'relative', 'label': '相对表现', 'condition': '五日相对参考样本收益≥0个百分点',
         'value': f'{excess:+g} 个百分点' if finite(excess) else '本价格观察模型不设相对项' if item.get('review_kind')=='reference' else '待补数据',
         'met': excess >= 0 if finite(excess) else None},
        {'id': 'research', 'label': '公司证据', 'condition': '完整公司研究达到重点跟踪条件',
         'value': action_reason, 'met': action == 'track' if action not in ('wait', 'reference') else None},
        {'id': 'environment', 'label': '环境风险', 'condition': '环境风险<70，且行情不为高风险或特大风险',
         'value': (f'{risk:g}/100' if risk is not None else '待评估') + ' · ' + (quote_risk or '行情风险待评估'),
         'met': (risk < 70 and quote_risk in ('低风险', '中风险')) if risk is not None and quote_risk in ('低风险', '中风险', '高风险', '特大风险') else None}]
    return {'version': GUIDANCE_VERSION, 'status': 'ready' if ready else 'pending',
            'recommendation_index': index, 'maximum': 100, 'action': tier, 'label': LABELS[tier],
            'headline': HEADLINES[tier], 'reason': reason, 'basis': basis, 'caps': caps,
            'effective_cap': cap if ready else None, 'current_research_action': action,
            'before_participation': BEFORE[tier], 'if_holding': HOLDING[tier],
            'upgrade_condition': UPGRADE[tier],
            'risk_condition': '后续样本再走弱、回撤扩大或公告否定原有逻辑时，重新复核参与计划。环境风险≥70或行情高风险时上限49；环境风险≥85、行情特大风险或五日回撤≥10%时上限29。',
            'checks': checks, 'period_end': item.get('period_end'), 'research_as_of': report_as_of,
            'source_ids': list(dict.fromkeys(item.get('source_ids', []) + (sector.get('market_risk') or {}).get('source_ids', []))),
            'note': '仅为条件式研究参考。公司样本或参考指数不是可直接交易的产品；未使用你的持仓、成本或风险偏好，因此不提供个性化仓位和买卖价。'
                    + (' 本页环境风险为中国环境参考，并非当地市场、汇率或外币资金风险。' if sector.get('group')=='overseas' else '')}


def _liquidity_guidance(item, current, report_as_of):
    metrics = item.get('rate_metrics') or {}
    ready = bool(current and item.get('status')=='completed' and finite(item.get('score')))
    return {'version':GUIDANCE_VERSION,'status':'ready' if ready else 'pending',
        'name':'流动性观察指数','recommendation_index':item.get('score') if ready else None,'maximum':100,
        'action':'observe' if ready else 'wait','label':item.get('score_label','待评估') if ready else '待评估',
        'headline':'观察隔夜资金松紧，区分利率与投资回报' if ready else '等待同期限利率证据',
        'reason':'使用隔夜Shibor专用模型。高分只表示资金相对趋宽或平稳，不能解释为货币产品收益、安全或买入建议。',
        'effective_cap':None,'caps':[],'basis':[],
        'before_participation':'先核对具体产品期限、流动性和信用条件；本指数只提供银行间资金环境参考，不能替代产品研究。',
        'if_holding':'按实际产品的赎回条件和资金用途安排流动性；隔夜Shibor上升或下降均不等于你的产品盈亏。',
        'upgrade_condition':'持续核对同一期限的官方发布值及5、20日基点变化，结合政策与信用证据判断资金松紧。',
        'risk_condition':'当日利率跳升、20日波动扩大或信用风险变化时重新核验；不能凭隔夜利率推断保本或长期收益。',
        'checks':[{'id':'rate','label':'同期限利率','condition':'人民币隔夜Shibor，年化利率%口径',
            'value':str(metrics.get('annual_rate_pct','待补数据'))+'%','met':True if ready else None}],
        'period_end':item.get('period_end'),'research_as_of':report_as_of,'source_ids':item.get('source_ids',[]),
        'note':'利率基点变化不是价格涨跌；未调用AI，也未形成个性化投资建议。'}
