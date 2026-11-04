"""Explainable research rules computed from dated public data, with no trade execution.

These fixed weights are heuristics, not a fitted model or a backtested strategy.
All reported return / volatility / drawdown / moving-average gaps are percentages.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone

CHINA = timezone(timedelta(hours=8))
RISK_LIMITS = {
    '稳健增强': {'volatility': 15.0, 'drawdown': 8.0},
    '均衡配置': {'volatility': 22.0, 'drawdown': 12.0},
    '积极成长': {'volatility': 30.0, 'drawdown': 18.0},
}
CATEGORY_RULES = {
    'short_bond': {'label': '短债', 'scales': (30.0, 12.0), 'limits': ((0.8, 0.5), (1.2, 0.8), (1.5, 1.0)), 'use_rsi': False},
    'bond': {'label': '债券', 'scales': (8.0, 3.0), 'limits': ((3.0, 2.0), (5.0, 3.0), (6.0, 4.0)), 'use_rsi': False},
    'money': {'label': '货币', 'scales': (50.0, 20.0), 'limits': ((0.15, 0.1), (0.25, 0.2), (0.35, 0.3)), 'use_rsi': False},
    'gold': {'label': '黄金', 'scales': (1.3, 0.55), 'use_rsi': True},
    'equity_mixed': {'label': '权益/混合参考', 'scales': (1.3, 0.55), 'use_rsi': True},
}
METRIC_KEYS = ('return_20d', 'return_60d', 'volatility_annual', 'max_drawdown',
               'rsi14', 'ma20_gap', 'ma60_gap')


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _date(value):
    if isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _today(snapshot):
    return _date(snapshot.get('as_of')) or datetime.now(CHINA).date()


def _clamp(value, low, high):
    return max(low, min(high, value))


def _category(fund, risk):
    declared = str(fund.get('fund_type') or fund.get('asset_class') or fund.get('category') or '')
    text = declared
    if any(term in text for term in ('黄金', 'gold', 'Gold')):
        key = 'gold'
    elif any(term in text for term in ('货币', 'money_market')):
        key = 'money'
    elif any(term in text for term in ('混合', '可转债', '二级债', 'convertible', 'mixed')):
        key = 'equity_mixed'
    elif any(term in text for term in ('短债', '超短债', '短期纯债', 'short_bond')):
        key = 'short_bond'
    elif '固收' in declared or any(term in text for term in ('债券', '纯债', 'bond')):
        key = 'bond'
    else:
        key = 'equity_mixed'
    rule = CATEGORY_RULES[key]
    limits = RISK_LIMITS.get(risk, RISK_LIMITS['稳健增强']).copy()
    if 'limits' in rule:
        risk_index = list(RISK_LIMITS).index(risk) if risk in RISK_LIMITS else 0
        limits = dict(zip(('volatility', 'drawdown'), rule['limits'][risk_index]))
    basis = f'仅依据数据源类型“{declared}”；基金名称不参与' if declared else '来源类型缺失，采用权益参考风险尺度；不推断基金板块或低风险类型'
    return key, rule, limits, basis


def _rsi(values, period=14):
    """Wilder smoothed RSI on the dividend-adjusted wealth index."""
    if len(values) <= period:
        return None
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gain = sum(max(change, 0) for change in changes[:period]) / period
    loss = sum(max(-change, 0) for change in changes[:period]) / period
    for change in changes[period:]:
        gain = (gain * (period - 1) + max(change, 0)) / period
        loss = (loss * (period - 1) + max(-change, 0)) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _drawdown(values):
    high = values[0]
    worst = 0.0
    for value in values:
        high = max(high, value)
        worst = min(worst, value / high - 1.0)
    return worst * 100.0


def _series(fund, today):
    records = {}
    notes = []
    invalid = False
    for row in fund.get('history', []):
        if not isinstance(row, dict):
            continue
        point_date = _date(row.get('date'))
        nav = _number(row.get('nav'))
        if point_date is None or nav is None or nav <= 0:
            continue
        if point_date > today:
            invalid = True
            continue
        records[point_date] = (nav, _number(row.get('return_pct')))
    dates = sorted(records)[-254:]
    if len(dates) < 2:
        return [], [], dates, notes, invalid
    returns = []
    wealth = [100.0]
    fallback = 0
    for previous_date, point_date in zip(dates, dates[1:]):
        previous_nav = records[previous_date][0]
        nav, daily_return = records[point_date]
        if daily_return is None:
            daily_return = (nav / previous_nav - 1.0) * 100.0
            fallback += 1
        if daily_return <= -100 or daily_return > 100:
            invalid = True
            notes.append('日收益率异常，已阻断配置判断；请核对分红、拆分或数据源。')
            return [], [], dates, notes, invalid
        if (point_date - previous_date).days > 14:
            invalid = True
            notes.append('净值序列存在超过 14 天的断档，不能视作连续交易日样本。')
        returns.append(daily_return / 100.0)
        wealth.append(wealth[-1] * (1.0 + returns[-1]))
    if fallback:
        notes.append(f'{fallback} 个区间缺少来源日收益率，使用单位净值变化替代；分红/拆分可能扭曲指标，不能据此形成配置候选。')
    if invalid:
        notes.append('存在未来日期、异常收益或长时间断档，请先核验原始净值序列。')
    return returns, wealth, dates, notes, invalid or fallback > 0


def build_quant(snapshot, prefs):
    """Produce one evidence-backed quantitative assessment for each fund."""
    today = _today(snapshot)
    risk = prefs.get('risk', '稳健增强')
    minimum = _number(prefs.get('min'))
    minimum = 72.0 if minimum is None else _clamp(minimum, 0, 100)
    results = []
    for fund in snapshot.get('funds', []):
        code = str(fund.get('code', ''))
        category, rule, limits, category_basis = _category(fund, risk)
        fixed_income = category in ('short_bond', 'bond', 'money')
        metrics = {key: None for key in METRIC_KEYS}
        metrics['observations'] = 0
        returns, wealth, dates, notes, invalid = _series(fund, today)
        nav_date = dates[-1] if dates else _date(fund.get('nav_date'))
        advertised_date = _date(fund.get('nav_date'))
        if advertised_date and advertised_date > today:
            invalid = True
            notes.append('数据源最新净值日期在未来，已阻断配置判断。')
        if advertised_date and nav_date and advertised_date != nav_date:
            notes.append(f'头部净值日期与历史序列末日不同；指标采用历史末日 {nav_date.isoformat()}。')
        age_days = (today - nav_date).days if nav_date else None
        metrics['observations'] = len(returns)
        quality = 'ok'
        if invalid or len(returns) < 60 or nav_date is None or (age_days is not None and age_days < 0):
            quality = 'insufficient'
        elif age_days > 7:
            quality = 'stale'
        item = {
            'code': code, 'name': fund.get('name') or code,
            'score': None, 'action': '数据不足', 'metrics': metrics,
            'reasons': notes.copy(), 'invalidation': '至少需要 60 个连续有效日收益及未过期的净值数据。',
            'quality': quality, 'nav_date': nav_date.isoformat() if nav_date else None,
            'age_days': age_days, 'source_url': fund.get('source_url', ''),
            'evidence_ids': ['nav:' + code],
            'method': '固定启发式评分，未经收益回测；仅用于同类基金研究排序，不是收益概率。',
            'asset_class': category, 'asset_class_label': rule['label'], 'category_basis': category_basis,
            'configuration_scope': 'trend_observation_only' if fixed_income else 'conditional_candidate',
            'thresholds': {'minimum_score': minimum, 'annual_volatility_limit': limits['volatility'], 'drawdown_limit': limits['drawdown'], 'uses_rsi_gate': rule['use_rsi']},
        }
        item['reasons'].append(f'适用类别：{rule["label"]}；{category_basis}。采用该类固定研究尺度，分数不能直接与其他类别比较。')
        if fixed_income:
            item['reasons'].append('固收类不按权益 RSI 高位判定过热。当前缺少可核验的信用评级分布、久期、杠杆与流动性资料，历史研究分仅评价历史收益稳定性和趋势，不形成配置候选。')
        elif category == 'gold':
            item['reasons'].append('黄金分数只评价黄金总收益曲线的趋势与风险；不代表黄金相对股票/债券更值得买，还需复核汇率、溢价/折价、跟踪误差及海外交易时点。')
        if len(returns) >= 20:
            metrics['return_20d'] = round((wealth[-1] / wealth[-21] - 1) * 100, 2)
            metrics['ma20_gap'] = round((wealth[-1] / statistics.mean(wealth[-20:]) - 1) * 100, 2)
        if len(returns) >= 14:
            metrics['rsi14'] = round(_rsi(wealth), 2)
        if returns:
            metrics['max_drawdown'] = round(_drawdown(wealth[-121:]), 2)
            metrics['drawdown_observations'] = min(120, len(returns))
        if len(returns) >= 60:
            metrics['return_60d'] = round((wealth[-1] / wealth[-61] - 1) * 100, 2)
            metrics['ma60_gap'] = round((wealth[-1] / statistics.mean(wealth[-60:]) - 1) * 100, 2)
            metrics['volatility_annual'] = round(statistics.stdev(returns[-60:]) * math.sqrt(252) * 100, 2)
        if quality != 'ok':
            if quality == 'stale':
                item['reasons'].append(f'历史净值截至 {item["nav_date"]}，距采集日 {age_days} 天，超过 7 天有效期。保留历史指标但不输出配置建议。')
            elif len(returns) < 60:
                item['reasons'].append(f'仅有 {len(returns)} 个有效日收益，少于所需的 60 个；无法形成可靠的趋势比较。')
            if not item['reasons']:
                item['reasons'].append('缺少可核验的净值日期或收益序列。')
            results.append(item)
            continue
        r20, r60 = metrics['return_20d'], metrics['return_60d']
        gap20, gap60 = metrics['ma20_gap'], metrics['ma60_gap']
        vol, drawdown, rsi = metrics['volatility_annual'], metrics['max_drawdown'], metrics['rsi14']
        components = {
            'base': 50.0,
            'momentum_20d': _clamp(r20 * rule['scales'][0], -15, 15),
            'momentum_60d': _clamp(r60 * rule['scales'][1], -15, 15),
            'trend_20d': 6 if gap20 > 0 else (-6 if gap20 < 0 else 0),
            'trend_60d': 9 if gap60 > 0 else (-9 if gap60 < 0 else 0),
            'volatility_penalty': -min(20, max(0, vol - limits['volatility']) / limits['volatility'] * 10),
            'drawdown_penalty': -min(20, abs(drawdown) / limits['drawdown'] * 10),
            'rsi_penalty': (-8 if rsi > 80 else (-4 if rsi > 70 or rsi < 30 else 0)) if rule['use_rsi'] else 0,
        }
        item['score'] = round(_clamp(sum(components.values()), 0, 100))
        item['score_components'] = {key: round(value, 2) for key, value in components.items()}
        item['reasons'] += [
            f'近 20 / 60 个净值发布日总收益为 {r20:+.2f}% / {r60:+.2f}%；总收益曲线相对 20 / 60 日均线偏离 {gap20:+.2f}% / {gap60:+.2f}%。',
            f'近 60 日年化波动 {vol:.2f}%；最近 {metrics["drawdown_observations"]} 个样本日最大回撤 {drawdown:.2f}%；RSI14 为 {rsi:.1f}。',
            f'{rule["label"]} / {risk}固定规则阈值：年化波动 {limits["volatility"]:g}%、窗口回撤 {limits["drawdown"]:g}%；这些阈值未根据你的完整资产与投资期限校准。',
            f'动量分使用 20 日收益×{rule["scales"][0]:g} 与 60 日收益×{rule["scales"][1]:g}，各截断为 ±15 分；类别尺度是未经回测的启发式设定。',
        ]
        bearish = r60 < 0 and gap20 < 0 and gap60 < 0
        reduce_threshold = min(5, limits['drawdown'])
        if bearish and drawdown < -reduce_threshold:
            item['action'] = '考虑减仓（如持有）'
            item['reasons'].append(f'中期收益和两条均线方向均转弱且回撤超过 {reduce_threshold:g}%；如已持有，先复核仓位、持有期限与赎回费，再考虑降低暴露。')
        elif vol > limits['volatility'] or abs(drawdown) > limits['drawdown']:
            item['action'] = '暂缓新增'
            item['reasons'].append('波动或回撤已超出当前规则阈值，新增配置暂缓。')
        elif r20 < 0 and r60 < 0:
            item['action'] = '暂缓新增'
            item['reasons'].append('短期与中期收益同时为负，等待趋势恢复。')
        elif fixed_income:
            item['action'] = '继续观察'
            item['reasons'].append('当前净值趋势未触发风险阈值，但信用、久期和流动性核验不足；高研究分不升级为买入或配置候选。')
        elif item['score'] >= minimum and r20 > 0 and r60 > 0 and gap20 > 0 and gap60 > 0 and (not rule['use_rsi'] or rsi < 80):
            item['action'] = '分批配置候选'
            item['reasons'].append('趋势、动量和风险阈值同时满足规则；只有补齐费用、公告与持有期限核验后，才可考虑分批配置。')
        else:
            item['action'] = '继续观察'
            item['reasons'].append('当前未同时满足最低研究分、趋势一致性与不过热条件，继续观察。')
        if item['action'] == '分批配置候选':
            item['invalidation'] = (f'下一次更新若 20 日总收益≤0、总收益曲线跌回其 60 日均线以下、年化波动>{limits["volatility"]:g}%、'
                                    f'窗口回撤超过 {limits["drawdown"]:g}%，或出现重大公告/净值数据超过 7 天未更新，候选条件失效并暂停剩余批次。')
        elif fixed_income and item['action'] == '继续观察':
            item['invalidation'] = (f'信用、久期、杠杆和流动性信息经核验且风险符合自身期限后，重新评估观察结论；若年化波动超过 {limits["volatility"]:g}% '
                                    f'或回撤绝对值超过 {limits["drawdown"]:g}%，转入风险复核。RSI 高位本身不使固收观察结论失效。')
        else:
            item['invalidation'] = (f'当前{item["action"]}判断在后续净值更新中，若 20 / 60 日总收益恢复为正、总收益曲线重新站上其 20 / 60 日均线、'
                                    f'年化波动回落至 {limits["volatility"]:g}%以内且回撤绝对值回到 {limits["drawdown"]:g}%以内，应重新评估，不能沿用原风险判断；'
                                    '重大公告或数据过期也会要求重新核验。')
        results.append(item)
    return results


def build_sentiment(snapshot):
    """A limited index sample and headline lexicon, never a market-wide survey."""
    today = _today(snapshot)
    valid = []
    for market in snapshot.get('market', []):
        change = _number(market.get('change_pct'))
        point_date = _date(market.get('as_of'))
        if change is not None and point_date and 0 <= (today - point_date).days <= 3:
            valid.append(change)
    positive = ('增长', '增持', '回购', '提升', '创新高', '净流入', '降准', '利好', '上调')
    negative = ('下滑', '减持', '亏损', '风险', '处罚', '违约', '净流出', '下调', '利空')
    headlines = []
    unknown_date = 0
    for news in snapshot.get('news', []):
        published = _date(news.get('published_at'))
        if published is None:
            unknown_date += 1
            continue
        if not 0 <= (today - published).days <= 3:
            continue
        text = str(news.get('title', '')) + ' ' + str(news.get('summary', ''))
        pos = sum(word in text for word in positive)
        neg = sum(word in text for word in negative)
        headlines.append(1 if pos > neg else (-1 if neg > pos else 0))
    mean_change = statistics.mean(valid) if valid else None
    breadth = sum(value > 0 for value in valid) / len(valid) if valid else None
    score = round(_clamp(50 + mean_change * 12 + (breadth - 0.5) * 40, 0, 100)) if valid else None
    label = '样本不足' if score is None else ('样本偏强' if score >= 60 else ('样本偏弱' if score <= 40 else '样本中性'))
    headline_score = round((statistics.mean(headlines) + 1) * 50) if headlines else None
    basis = f'{len(valid)} 个有时间戳的指数样本；{len(headlines)} 条近 3 天新闻/公告；{unknown_date} 条发布时间不明内容未纳入情绪计算。'
    return {
        'score': score, 'label': label, 'basis': basis,
        'coverage': {'indices': len(valid), 'recent_headlines': len(headlines), 'unknown_date_headlines': unknown_date},
        'index_mean_change_pct': round(mean_change, 2) if mean_change is not None else None,
        'index_positive_ratio_pct': round(breadth * 100, 2) if breadth is not None else None,
        'headline_score': headline_score,
        'method': '指数代理分=50+样本平均涨跌幅×12+(上涨指数比例−0.5)×40，截断为0–100。新闻词典分另列，不参与基金评分。指数存在成分重叠，不是全市场上涨家数；新闻词典不能理解否定与复杂语境，不代表真实投资者情绪。',
    }


def _operation_plan(item, position):
    """Translate an explicit research state into conditional, auditable steps."""
    cap = (f'单只基金不超过组合总资产的 {position:g}%；这是上限，不是建议满配。'
           '所有基金与现金合计不得超过总资产 100%，还需预留日常现金并核对其他持仓。')
    fees = ['核对基金最新申购费、赎回费及各持有期限对应的费率，不假定免费或固定费率。',
            '核对限购/暂停申赎、交易截止时间、确认和到账规则；短期调仓须先评估赎回成本。']
    schedule = '每个交易日净值披露后复核一次；出现重大基金公告时立即复核。未取得新净值时不把旧数据当作新信号。'
    plan = {'new_position': '', 'existing_position': '', 'entry_conditions': [], 'steps': [],
            'position_limit': cap, 'review_schedule': schedule,
            'exit_conditions': [], 'fee_checks': fees}
    if item['quality'] != 'ok':
        plan.update({
            'new_position': '等待数据恢复，当前不形成新增配置操作。',
            'existing_position': '核对持仓与最新公告，保留原计划供复核；不因缺失或过期数据直接卖出。',
            'entry_conditions': ['先取得至少 60 个有效日收益，确认净值日期不超过 7 天且没有未来日期、明显断档或复权疑点。', '重新运行研究，质量门槛通过后再评估操作。'],
            'steps': ['检查当前失败或过期的数据来源。', '等待最新净值/公告披露，刷新数据后重新计算历史研究分。'],
            'exit_conditions': ['数据不足不能独立触发卖出；重大公告、流动性需求或已设风险预算发生变化时人工复核。'],
        })
        return plan
    limits = item['thresholds']
    common_exit = [
        '20 日总收益转为不高于 0，或总收益曲线跌回其 60 日均线以下时暂停后续批次并复核。',
        f'60 日年化波动超过 {limits["annual_volatility_limit"]:g}% 或窗口最大回撤绝对值超过 {limits["drawdown_limit"]:g}% 时重新评估风险预算。',
        '出现重大基金公告、数据过期或申赎异常时暂停后续操作；均线基于复利总收益曲线，不能直接当作单位净值买卖价格。',
    ]
    plan['exit_conditions'] = common_exit
    if item['action'] == '分批配置候选':
        plan.update({
            'new_position': '完成费用、公告和持有期限核验后，可将自行确定的计划金额分 3 批，每批不超过计划金额的 1/3；每一批执行前重新检查条件。',
            'existing_position': '先汇总现有仓位与同类基金重叠暴露；已有配置满足计划时无需加仓，仅对未达到计划且仍符合条件的部分评估分批新增。',
            'entry_conditions': [f'历史研究分不低于 {limits["minimum_score"]:g}，且数据质量仍为有效；最终推荐指数还需通过市场风险与板块持仓核验。', '20 / 60 日总收益均大于 0，总收益曲线同时位于其 20 / 60 日均线之上，RSI14 小于 80。', f'年化波动不超过 {limits["annual_volatility_limit"]:g}%，窗口回撤绝对值不超过 {limits["drawdown_limit"]:g}%。', '确认基金公告、费用、投资期限与自身风险承受能力，并留足现金。'],
            'steps': ['先确定计划金额，检查现有持仓与单只仓位上限；上限不是目标仓位。', '条件全部通过后才考虑第一批，金额不超过计划金额的 1/3。', '待下一次独立净值更新后重新运行研究；条件仍全部通过才考虑第二批，不机械加仓。', '后续独立净值更新再次通过条件后才考虑第三批；任何失效条件触发都暂停剩余批次。'],
        })
    elif item['action'] == '考虑减仓（如持有）':
        plan.update({
            'new_position': '暂缓建立新仓，等待中期趋势与风险指标恢复。',
            'existing_position': '若已经持有，先核验是否超过个人风险预算；考虑分批降低超标部分，具体金额取决于实际持仓、费用与资金期限。没有持仓则没有卖出操作。',
            'entry_conditions': ['中期趋势恢复、风险阈值重新满足且历史研究分达到设定门槛后，重新评估新增。'],
            'steps': ['确认实际持仓、买入日期和当前赎回费用。', '比较当前回撤与既定风险预算，明确需要降低的是超标风险部分。', '若决定调整，结合费率和流动性规则分批处理；不因单日波动机械清仓。', '下一次净值更新后重新检查中期趋势和风险指标。'],
        })
    elif item['action'] == '暂缓新增':
        plan.update({
            'new_position': '暂缓新增配置，等待趋势或风险指标改善。',
            'existing_position': '复核已有仓位与风险预算；暂缓新增不等于必须卖出，是否调整取决于实际持仓和费用。',
            'entry_conditions': ['波动、回撤和趋势重新满足规则，同时历史研究分达到门槛后再评估。'],
            'steps': ['保留观察清单，暂停新增批次。', '检查造成暂缓的具体指标及相关公告。', '下一次净值更新后重新计算，不用过期信号安排操作。'],
        })
    else:
        plan.update({
            'new_position': '保持观察，当前不形成新增配置操作。',
            'existing_position': '按原有计划复核风险预算，不把“继续观察”当作自动卖出指令。',
            'entry_conditions': [f'历史研究分达到 {limits["minimum_score"]:g} 且趋势、风险和不过热条件同时通过后再评估。'],
            'steps': ['查看未满足条件的指标和新闻公告。', '等待后续独立净值更新，检查信号是否改善且有持续性。', '条件未全部通过时保持观察，不按分数接近门槛提前下单。'],
        })
    if item['action'] in ('考虑减仓（如持有）', '暂缓新增'):
        plan['exit_conditions'] = [
            '当前风险信号已经触发，不能把同一负向条件重复视作新的卖出理由；下一次更新检查它是否持续或进一步恶化。',
            '若实际持仓风险超出事先设定的个人预算，再结合持有期限、赎回费与流动性评估调整幅度；没有持仓则无卖出操作。',
            item['invalidation'],
        ]
    if item.get('configuration_scope') == 'trend_observation_only':
        plan['entry_conditions'] = [
            '先核验基金分类与最新报告中的信用评级分布、久期、杠杆和流动性；货币类还需核对收益口径与份额净值机制。',
            f'类内历史研究分仅供研究排序；净值风险需满足年化波动不超过 {limits["annual_volatility_limit"]:g}%、回撤绝对值不超过 {limits["drawdown_limit"]:g}% 的当前启发式阈值。',
            '资料补齐后仍需结合资金期限、费用与持仓评估；当前版本不以固收趋势分自动产生分批配置候选，RSI 高位不作为过热门槛。',
        ]
        if item['action'] == '继续观察':
            plan['new_position'] = '等待信用、久期、杠杆和流动性核验；当前固收历史研究分只作类内趋势观察，不安排新增批次。'
            plan['steps'] = ['打开最新定期报告和公告，核对信用暴露、久期、杠杆与流动性。', '结合自己的资金使用时间和申赎费用判断期限是否匹配。', '持续跟踪净值风险，不因低波动单边上涨带来的高 RSI 判定过热或机械卖出。']
            plan['exit_conditions'] = [item['invalidation'], '若出现信用事件、赎回限制或流动性异常，结合实际持仓复核；单看平稳历史净值不能排除尾部风险。']
    return plan


def build_analysis(snapshot, quant, prefs):
    valid = [item for item in quant if item['quality'] == 'ok']
    candidates = [item for item in valid if item['action'] == '分批配置候选']
    guarded = [item for item in valid if item['action'] in ('暂缓新增', '考虑减仓（如持有）')]
    sentiment = snapshot.get('sentiment') or build_sentiment(snapshot)
    source_errors = [source.get('name', source.get('id', '数据源')) for source in snapshot.get('sources', []) if source.get('status') != 'ok']
    position = _number(prefs.get('pos'))
    position = _clamp(position if position is not None else 25, 1, 100)
    summary = (f'已自动研究 {len(quant)} 只基金，其中 {len(valid)} 只具备有效量化样本；'
               f'{len(candidates)} 只进入分批配置候选，{len(guarded)} 只触发风险观察。')
    if not valid:
        summary += '当前没有足够新鲜、完整的数据形成配置判断，先等待数据恢复。'
    else:
        summary += '以下是基于公开数据和固定规则的研究决策，尚未包含 AI 深度解读。'
    views = []
    for market in snapshot.get('market', [])[:8]:
        change = _number(market.get('change_pct'))
        if change is not None:
            views.append(f'{market.get("name", market.get("code", "指数"))} {change:+.2f}%（{market.get("as_of") or "时点不明"}）')
    market_view = '；'.join(views) if views else '市场行情源暂不可用，基金净值指标与市场新闻分别评估，不推断实时市场方向。'
    market_view += f'\n情绪代理：{sentiment["label"]}。{sentiment["basis"]}'
    risks = [
        '评分是公开固定权重的启发式研究排序，尚未做历史收益回测，也不是收益率或成功概率；不宜跨基金类别直接比较。',
        '基金净值通常在交易结束后披露，可能滞后于当前市场；成交价格、限购、申赎费用和持有期限需另行核对。',
        '没有完整的个人持仓、投资期限、现金需求与损失承受能力，不能据此给出完整资产配置比例。',
        '指数样本情绪与新闻关键词只提供辅助线索，不能替代全市场交易情绪或新闻事实核验。',
    ]
    if source_errors:
        risks.append('以下数据源不完整或失败：' + '、'.join(source_errors) + '；缺失数据没有用模拟值补齐。')
    risks.extend(str(warning) for warning in snapshot.get('warnings', [])[:8])
    funds = []
    for item in quant:
        funds.append({
            'code': item['code'], 'name': item['name'], 'score': item['score'],
            'recommendation_index': None,
            'score_explanation': (f'历史研究分为 {item.get("asset_class_label", "同类")} 的 0–100 分固定启发式研究排序，由类别尺度动量、总收益曲线均线、波动、回撤'
                                  + ('和 RSI' if item['thresholds'].get('uses_rsi_gate', True) else '合成，固收类 RSI 不参与扣分或过热门槛')
                                  + '规则计算；未经收益回测，不是收益概率，不与其他资产类别直接比较。推荐指数另由市场、风险及板块持仓核验结果约束，可能低于历史研究分或不生成。') if item['score'] is not None else '数据质量未通过门槛，历史研究分与推荐指数均不生成，不能用 0 分替代未知。',
            'asset_class': item.get('asset_class'), 'asset_class_label': item.get('asset_class_label'),
            'action': item['action'], 'reason': '\n'.join(item['reasons']),
            'invalidation': item['invalidation'],
            'allocation': f'单只仓位上限 {position:g}%，不是目标仓位；未提供完整持仓，暂不生成组合权重。' if item['quality'] == 'ok' else '数据未满足质量门槛，暂不提供仓位建议。',
            'evidence_ids': item['evidence_ids'],
            'operation_plan': _operation_plan(item, position),
        })
    return {
        'summary': summary, 'market_view': market_view, 'risks': list(dict.fromkeys(risks)),
        'funds': funds,
        'next_steps': [
            '优先复核候选基金的最新公告、持仓、费率、申赎限制和计划持有期限。',
            '观察下一次净值更新是否仍满足趋势、波动和回撤条件；数据或重大公告改变时重新运行研究。',
            '配置 DeepSeek 后，可以把已采集证据与量化指标交给 AI 解释；不得把缺失数据视为已验证事实。',
        ],
    }
