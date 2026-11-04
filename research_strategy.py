"""Seven-calendar-day research overlay; deterministic rules, never trade execution.

The pressure score is a limited public-index sample heuristic, not VIX, a survey,
or a forecast. Rolling holding evidence is descriptive and includes only fully
realized historical windows. All returns are percentages before unknown costs.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone
from research_trading_calendar import a_share_quote_fresh
from research_numbers import parse_number as _number, clamp as _clamp

CHINA = timezone(timedelta(hours=8))
SCHEMA_VERSION = 1
MIN_HOLDING_DAYS = 7
MIN_ROLLING_WINDOWS = 30
MIN_MARKET_INDICES = 3


def _timestamp(value):
    if not isinstance(value, str) or len(value) <= 10:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp).astimezone(CHINA)
    except ValueError:
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _headline_pressure(news, now):
    positive = ('增长', '增持', '回购', '净流入', '降准', '利好', '上调')
    negative = ('下滑', '减持', '亏损', '违约', '净流出', '下调', '利空', '大跌', '暴跌')
    scores, unknown, stale, excluded_category = [], 0, 0, 0
    categorized = any(item.get('category') for item in news)
    market_categories = {'财经新闻', '市场新闻', '联网检索'}
    for item in news:
        if categorized and item.get('category') not in market_categories:
            excluded_category += 1
            continue
        stamp = _date(item.get('published_at'))
        if stamp is None:
            unknown += 1
            continue
        if not 0 <= (now.date() - stamp).days <= 3:
            stale += 1
            continue
        text = str(item.get('title', '')) + ' ' + str(item.get('summary', ''))
        pos = sum(word in text for word in positive)
        neg = sum(word in text for word in negative)
        scores.append(1 if neg > pos else (-1 if pos > neg else 0))
    negative_share = sum(value > 0 for value in scores) / len(scores) if scores else None
    points = negative_share * 5 if negative_share is not None else 0
    return {'name': '近三天标题负面词样本', 'raw': round(negative_share * 100, 2) if negative_share is not None else None,
            'unit': '%', 'points': round(points, 2), 'max_points': 5,
            'sample_count': len(scores), 'unknown_date_count': unknown, 'stale_count': stale,
            'excluded_category_count': excluded_category,
            'status': 'available' if scores else 'unavailable',
            'explanation': '负面词占优标题比例×5，仅作弱辅助；有类别时只取财经新闻/市场新闻/联网检索，排除基金公告以避免基金选择改变情绪分母。不能理解否定语义或反映真实投资者情绪；缺失不伪装成中性新闻。'}


def _pressure(snapshot):
    now = _timestamp(snapshot.get('as_of'))
    values, timestamps, excluded, valid_quotes = [], [], [], []
    unique = set()
    for index, quote in enumerate(snapshot.get('market', [])):
        code = str(quote.get('code') or quote.get('name') or index)
        if code in unique:
            continue
        unique.add(code)
        change = _number(quote.get('change_pct'))
        stamp = _timestamp(quote.get('as_of'))
        if now is None or change is None or stamp is None or not a_share_quote_fresh(quote.get('as_of'), snapshot.get('as_of')):
            excluded.append({'code': code, 'reason': '涨跌幅/明确行情时点缺失、未来时点或已过期'})
            continue
        values.append(change)
        timestamps.append(stamp)
        valid_quotes.append({'code': code, 'name': quote.get('name', code), 'change_pct': change})
    coverage = {'fresh_indices': len(values), 'total_indices': len(unique), 'minimum_indices': MIN_MARKET_INDICES,
                'excluded': excluded, 'required_fresh_share': 0.5,
                'freshness_limit_hours': None, 'freshness_rule': '已核验A股交易日历：休市及盘前使用最近收盘，盘中要求当日近期行情'}
    valid = now is not None and len(values) >= MIN_MARKET_INDICES and len(values) >= len(unique) * .5
    news = _headline_pressure(snapshot.get('news', []), now) if now else {'name': '近三天标题负面词样本', 'raw': None, 'points': 0, 'max_points': 5, 'sample_count': 0, 'status': 'unavailable', 'explanation': '缺少采集时点，无法核验新闻时效。'}
    components = []
    if values:
        mean = statistics.mean(values)
        falling = sum(value < 0 for value in values) / len(values)
        severe = sum(value <= -2 for value in values) / len(values)
        components = [
            {'name': '指数样本平均跌幅', 'raw': round(mean, 3), 'unit': '%', 'points': round(_clamp(-mean / 4, 0, 1) * 45, 2), 'max_points': 45, 'explanation': '平均跌幅每 4 个百分点对应 45 分，上涨不计下跌压力。'},
            {'name': '下跌指数占比', 'raw': round(falling * 100, 2), 'unit': '%', 'points': round(falling * 35, 2), 'max_points': 35, 'explanation': '仅覆盖此处指数样本，成分可能重叠，不是全市场涨跌家数。'},
            {'name': '跌幅至少 2% 的指数占比', 'raw': round(severe * 100, 2), 'unit': '%', 'points': round(severe * 15, 2), 'max_points': 15, 'explanation': '观察样本内部的同步大幅下跌，不能替代期权隐含波动率。'},
        ]
    components.append(news)
    score = round(_clamp(sum(component['points'] for component in components), 0, 100)) if valid else None
    worst = min(valid_quotes, key=lambda item: item['change_pct']) if valid_quotes else None
    override = valid and statistics.mean(values) <= -2 and sum(value < 0 for value in values) / len(values) >= .75 and min(values) <= -4
    override_reason = ('触发同步大跌保护：样本平均跌幅至少2%、至少75%样本下跌且最差指数跌幅至少4%；即使压力分未达70，也暂停新增并进入防御。' if override else '')
    label = '数据不足' if score is None else ('高压力' if score >= 70 or override else ('压力上升' if score >= 40 else '样本压力较低'))
    summary = (f'{len(values)} 个新鲜指数平均 {statistics.mean(values):+.2f}%，其中 {sum(value < 0 for value in values)} 个下跌；'
               f'最弱为 {worst["name"]} {worst["change_pct"]:+.2f}%。压力代理分 {score}/100。'
               if valid else
               f'只有 {len(values)} / {len(unique)} 个指数具有有效时点；至少需 3 个且覆盖已收到样本的一半，暂停新增风险候选。')
    if news.get('status') == 'unavailable':
        summary += '新闻情绪分项不可用，未虚构新闻结论。'
    return {'score': score, 'label': label, 'summary': summary, 'components': components,
            'coverage': coverage, 'as_of': snapshot.get('as_of'),
            'calculated_at': snapshot.get('as_of'),
            'quote_as_of': max(timestamps).isoformat() if timestamps else None,
            'latest_market_as_of': max(timestamps).isoformat() if timestamps else None,
            'market_condition': {'mean_change_pct': round(statistics.mean(values), 3) if values else None, 'declining_count': sum(value < 0 for value in values), 'worst_index': worst},
            'stress_override': {'active': bool(override), 'reason': override_reason, 'rule': '平均涨跌幅≤-2%、下跌比例≥75%、最差指数涨跌幅≤-4%，三项同时满足'},
            'method': '0–100 分样本压力代理：平均跌幅最多45分、下跌指数占比最多35分、跌超2%占比最多15分、标题负面词比例最多5分。不是VIX、真实恐慌指数或收益预测，未经策略回测。按已核验A股交易日历核验最近收盘或当日近期行情；日历缺失时保持未知。'}


def _regime(panic, previous):
    score = panic['score']
    if score is None:
        return {'mode': 'unknown', 'label': '数据不足，暂停新增', 'reason': panic['summary'], 'hysteresis_applied': False}
    stress_override = panic.get('stress_override', {}).get('active', False)
    baseline = 'defensive' if score >= 70 or stress_override else ('cautious' if score >= 40 else 'risk_on')
    current_time = _timestamp(panic['as_of'])
    prior_time = _timestamp(previous.get('panic', {}).get('as_of')) if isinstance(previous, dict) else None
    prior_mode = previous.get('regime', {}).get('mode') if isinstance(previous, dict) else None
    prior_quote = previous.get('panic', {}).get('latest_market_as_of') if isinstance(previous, dict) else None
    same_valid_close = bool(prior_quote and prior_quote == panic.get('latest_market_as_of')
                            and a_share_quote_fresh(prior_quote, panic.get('as_of')))
    prior_valid = (isinstance(previous, dict) and previous.get('schema_version') == SCHEMA_VERSION
                   and _number(previous.get('panic', {}).get('score')) is not None
                   and 0 <= _number(previous['panic']['score']) <= 100
                   and prior_mode in ('risk_on', 'cautious', 'defensive')
                   and prior_time is not None and current_time is not None
                    and 0 <= (current_time - prior_time).total_seconds()
                    and ((current_time - prior_time).total_seconds() <= 72 * 3600 or same_valid_close))
    mode, held, extra = baseline, False, ''
    if prior_valid:
        old_quote = _timestamp(previous['panic'].get('latest_market_as_of'))
        new_quote = _timestamp(panic.get('latest_market_as_of'))
        new_observation = old_quote is not None and new_quote is not None and new_quote > old_quote
        if prior_mode == 'defensive' and score < 70 and not stress_override:
            if score >= 55 or not new_observation:
                mode, held = 'defensive', True
                extra = '防御状态需压力降至55以下且出现新的行情时点才退回谨慎；重复刷新同一行情不视作恢复。'
            else:
                mode, held = 'cautious', True
                extra = '压力已低于55且出现新行情，先由防御退回谨慎，不直接恢复新增风险仓位。'
        elif prior_mode == 'cautious' and score < 40:
            if score >= 30 or not new_observation:
                mode, held = 'cautious', True
                extra = '谨慎状态需压力降至30以下并出现新的行情时点才恢复候选筛选。'
    labels = {'risk_on': '允许筛选，条件核验后研究', 'cautious': '谨慎观察，暂停新增风险候选', 'defensive': '防御优先，暂停新增风险候选'}
    reason = f'样本压力 {score}/100；70及以上进入防御，40–69通常进入谨慎。' + panic.get('stress_override', {}).get('reason', '') + extra
    return {'mode': mode, 'label': labels[mode], 'reason': reason, 'hysteresis_applied': held}


def rolling_holding_evidence(fund, as_of, minimum_days=MIN_HOLDING_DAYS):
    """Describe completed >=7-calendar-day holding windows, never future rows."""
    end_date = _date(as_of)
    records, excluded_future = {}, 0
    for row in fund.get('history', []):
        day = _date(row.get('date'))
        if day is None or end_date is None:
            continue
        if day > end_date:
            excluded_future += 1
            continue
        records[day] = _number(row.get('return_pct'))
    days = sorted(records)[-505:]
    windows = []
    skipped = 0
    for start_index, start_day in enumerate(days):
        target = start_day + timedelta(days=minimum_days)
        total = 1.0
        previous_day = start_day
        for current in days[start_index + 1:]:
            change = records[current]
            if (current - previous_day).days > 14 or change is None or not -100 < change <= 100:
                skipped += 1
                break
            total *= 1 + change / 100
            previous_day = current
            if current >= target:
                if (current - target).days > 7:
                    skipped += 1
                    break
                windows.append({'start': start_day.isoformat(), 'end': current.isoformat(), 'days': (current - start_day).days, 'return_pct': (total - 1) * 100})
                break
    values = [window['return_pct'] for window in windows]
    enough = len(values) >= MIN_ROLLING_WINDOWS
    return {
        'status': 'sufficient' if enough else 'insufficient', 'minimum_calendar_days': minimum_days,
        'sample_count': len(values), 'minimum_windows': MIN_ROLLING_WINDOWS,
        'median_return_pct': round(statistics.median(values), 3) if values else None,
        'worst_return_pct': round(min(values), 3) if values else None,
        'negative_frequency_pct': round(sum(value < 0 for value in values) / len(values) * 100, 2) if values else None,
        'first_window_start': windows[0]['start'] if windows else None,
        'last_window_end': windows[-1]['end'] if windows else None,
        'actual_days_range': [min(window['days'] for window in windows), max(window['days'] for window in windows)] if windows else None,
        'excluded_future_rows': excluded_future, 'skipped_incomplete_or_invalid': skipped,
        'costs_included': False, 'overlapping_windows': True,
        'method': '每个历史起点取满7个自然日后首次公布净值的日期，使用来源日收益复利，窗口终点必须不晚于采集日；无完整收益率则跳过。窗口重叠且非独立样本，只是历史持有描述，不是按历史信号交易回测，也不是未来胜率。未含申赎费用、确认延迟或交易摩擦，满7天不代表盈利或免赎回费。',
    }


def _catalog(universe, snapshot):
    extra = universe if isinstance(universe, list) else (universe.get('funds', universe.get('items', [])) if isinstance(universe, dict) else [])
    return [row for row in list(snapshot.get('funds', [])) + list(extra) if isinstance(row, dict)]


def _overseas_supported(fund, snapshot):
    kind = str(fund.get('fund_type', '')).upper()
    holdings = fund.get('holdings') or {}
    overseas = ('QDII' in kind or '海外' in kind or any(
        row.get('instrument_type') == 'stock' and
        (len(str(row.get('code', ''))) == 5 or str(row.get('code', ''))[:1].isalpha())
        for row in holdings.get('rows', []) if isinstance(row, dict)))
    if not overseas:
        return True, None
    code = str(fund.get('code', ''))
    now = _timestamp(snapshot.get('as_of'))
    def matched(rows):
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamp = _timestamp(row.get('as_of'))
            matches = row.get('fund_code') == code or code in row.get('fund_codes', [])
            source = row.get('source_url', '')
            numeric_evidence = any(_number(row.get(key)) is not None for key in ('change_pct', 'last', 'rate', 'value'))
            if (matches and now and stamp and 0 <= (now - stamp).total_seconds() <= 72 * 3600
                    and numeric_evidence and isinstance(source, str) and source.startswith(('https://', 'http://'))):
                return True
        return False
    complete = matched(snapshot.get('overseas_market', [])) and matched(snapshot.get('fx', []))
    return complete, ('已匹配该基金的海外市场和汇率时点；国内指数压力仅作为额外环境约束。' if complete else
                      '缺少匹配该基金且新鲜的海外市场/汇率证据，自动暂缓；A股指数压力不能替代海外基金风险。')


def _defensive_options(universe, snapshot, regime):
    catalog = _catalog(universe, snapshot)
    money, sovereign, bank_equity = [], [], []
    seen = set()
    today = _date(snapshot.get('as_of'))
    for fund in catalog:
        code = str(fund.get('code', ''))
        if code and code in seen:
            continue
        seen.add(code)
        status = str(fund.get('purchase_status', fund.get('status', ''))).lower()
        nav_date = _date(fund.get('nav_date'))
        lock_until = _date(fund.get('lock_until'))
        blocked = (fund.get('is_locked') is True or fund.get('purchase_available') is False
                   or fund.get('alipay_available') is False or fund.get('quality') in ('stale', 'insufficient')
                   or any(word in status for word in ('locked', 'closed', 'unavailable', '暂停', '封闭', '不可购买'))
                   or (today is not None and nav_date is not None and not 0 <= (today - nav_date).days <= 7)
                   or (today is not None and lock_until is not None and lock_until > today))
        if blocked:
            continue
        name = str(fund.get('name', ''))
        kind = str(fund.get('fund_type', fund.get('asset_class', '')))
        record = {'code': code, 'name': name, 'verification_status': 'classification_inferred', 'platform_eligibility': 'unknown'}
        if ('货币' in kind or kind == 'money') and len(money) < 5:
            money.append(record)
        if fund.get('verified_short_sovereign_exposure') is True and len(sovereign) < 5:
            sovereign.append(record)
        from research_holdings import verify_board
        if verify_board(fund, 'sector_banking', as_of=snapshot.get('as_of'))['status'] == 'matched' and len(bank_equity) < 5:
            bank_equity.append(record)
    common = {'verification_status': 'source_unavailable', 'can_trade': False, 'execution_eligible': False,
              'platform_eligibility': 'unknown', 'selection_scope': '通用研究类别，未基于个人完整资产配置',
              'verification_blockers': ['具体产品性质、条款、费用和平台可买状态尚未接入可靠自动核验源'],
              'priority': '优先核验' if regime in ('defensive', 'unknown') else '备选研究'}
    return [
        {**common, 'category': 'bank_deposit', 'label': '银行存款（核对产品性质）', 'examples': [],
         'reason': '可作为资金等待期的通用研究方向；具体银行资质、存款性质、期限和提前支取条款的可靠数据源尚未接入。',
         'limitations': ['银行理财产品不等于银行存款，不能视为保本存款。', '未接入具体存款产品或利率；没有推荐特定银行、承诺收益或核验保险覆盖。'],
         'operation': '自动核验流程尚未确认具体存款产品，保持类别研究状态；不因本页压力分办理存款或转账。'},
        {**common, 'category': 'money_market', 'label': '货币市场基金', 'examples': money,
         'reason': '作为现金管理研究方向；需核对流动性、信用风险及赎回限额。',
         'limitations': ['货币基金不保证本金或收益；历史七日年化不是承诺回报。', '未核验支付宝可购买资格、快速赎回额度、到账时间和具体费用。'],
         'operation': '产品资料、申赎条件和费用的核验源缺失，继续扫描已接入的数据；不承诺后续自动补齐，不形成可执行交易方案。'},
        {**common, 'category': 'short_government_debt', 'label': '短久期国债或相应基金（须核验）', 'examples': sovereign,
         'supported_by_current_catalog': bool(sovereign),
         'reason': '仅在有明确短久期国债暴露证据时作为防御研究方向；普通短债基金可能承担信用风险。',
         'limitations': ['国债基金净值仍可能波动，不等于存款或保本产品。', '当前目录有匹配名称仍需核验持仓和久期；没有匹配项时只保留类别，不虚构具体产品。'],
         'operation': '最新持仓、久期、费用和赎回规则的核验源尚未齐备，保持阻断；不承诺未来补齐，不把所有债券基金当作低风险国债。'},
        {**common, 'category': 'excluded_bank_equity', 'label': '银行股票/指数基金：不作为低风险替代', 'examples': bank_equity,
         'priority': '明确排除', 'reason': '银行股票基金仍承担权益价格和行业集中风险，不能因名称含“银行”归入存款或现金管理。',
         'limitations': ['防御状态不自动轮换到银行股票基金。'], 'operation': '如持有此类基金，继续按权益风险预算评估。'},
    ]


def _holding_plan(item, evidence):
    return {
        'minimum_calendar_days': MIN_HOLDING_DAYS,
        'new_position': '当前仅进入公开数据研究清单；费率和可购买资格的核验源尚未接入，执行状态为阻断，后续扫描不代表会自动补齐。',
        'existing_position': '若已持有，先核对实际仓位与确认日期；不重复新建仓位，也不因满7天自动赎回。',
        'intended_holding': '计划持有至少7个自然日，并在每次新净值披露后复核；这是研究期限，不是基金合同的最短持有期。风险条件触发可提前复核调整，能否赎回及费用按产品规则。',
        'steps': ['系统继续扫描已接入的基金类型、净值和公告；费用、确认规则与平台可买状态的核验源缺失，保持阻断，不要求手工粘贴研究资料或承诺未来补齐。',
                  '若决定建仓，结合现有持仓与现金需求自行确定计划金额；遵守策略仓位上限，所有基金与现金合计不超过总资产100%。',
                  '条件仍满足且产品规则允许时，可把计划金额分三批，每批不超过计划金额的1/3；下一批需新的独立净值更新确认，不能自动定时买入。',
                  '记录实际确认日期、费用与预定复核日；至少7天是意向持有期，不是盈利目标或免赎回费门槛。'],
        'risk_exit': ['样本压力达到70或进入防御状态时暂停剩余新增批次，已持有部分结合实际风险预算与费用复核，不自动清仓。',
                      item.get('invalidation', '净值趋势或风险阈值改变时重新评估。'),
                      '重大基金公告、数据过期或流动性限制出现时暂停执行；产品封闭期或最短持有期可能限制退出。'],
        'review_schedule': '每个交易日净值披露后及重大公告出现时复核；不得把自然日更新当作新增交易日数据。',
        'evidence': evidence,
        'fee_status': 'source_unavailable', 'platform_eligibility': 'source_unavailable',
        'verified_buyable': False, 'execution_eligible': False,
        'verification_blockers': ['最新申赎费率和份额确认起算未自动核验', '基金最短持有/封闭期及赎回限制未自动核验', '支付宝可购买资格未自动核验'],
    }


def build_strategy(snapshot, quant, universe=None, previous=None):
    """Overlay market regime, conditional research shortlist and defense categories."""
    panic = _pressure(snapshot)
    regime = _regime(panic, previous)
    summary_action = {
        'risk_on': '可继续筛选，但产品条件与风险仍需核验。',
        'cautious': '保持谨慎，暂停新增权益风险候选。',
        'defensive': '保持防御研究，暂停新增权益风险候选。',
        'unknown': '数据未满足时效与覆盖门槛，暂停新增风险候选。',
    }
    panic['summary'] += summary_action[regime['mode']]
    if regime.get('hysteresis_applied'):
        panic['summary'] += '当前模式包含恢复滞回保护，不能仅凭本次较低压力分恢复新增。'
    funds = {str(fund.get('code')): fund for fund in snapshot.get('funds', [])}
    candidates, excluded, holding_evidence = [], [], {}
    for item in quant:
        code = str(item.get('code', ''))
        fund = funds.get(code)
        category = item.get('asset_class')
        if category not in ('equity_mixed', 'equity', 'mixed'):
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': '不在本策略的中高风险权益/混合研究范围内；其他类别单独评估。'})
            continue
        if item.get('quality') != 'ok':
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': '未通过现有净值质量、趋势、推荐指数或风险条件。'})
            continue
        evidence = rolling_holding_evidence(fund or {}, snapshot.get('as_of'))
        drawdown_limit = _number(item.get('thresholds', {}).get('drawdown_limit'))
        drawdown_limit = drawdown_limit if drawdown_limit is not None and 0 < drawdown_limit <= 100 else 8.0
        fit_checks = [
            {'name': '完整历史窗口', 'passed': evidence['sample_count'] >= MIN_ROLLING_WINDOWS, 'value': evidence['sample_count'], 'threshold': MIN_ROLLING_WINDOWS},
            {'name': '历史窗口中位收益为正', 'passed': evidence['median_return_pct'] is not None and evidence['median_return_pct'] > 0, 'value': evidence['median_return_pct'], 'threshold': 0},
            {'name': '历史负收益频率不超过55%', 'passed': evidence['negative_frequency_pct'] is not None and evidence['negative_frequency_pct'] <= 55, 'value': evidence['negative_frequency_pct'], 'threshold': 55},
            {'name': '历史最差窗口不超回撤预算', 'passed': evidence['worst_return_pct'] is not None and evidence['worst_return_pct'] >= -drawdown_limit, 'value': evidence['worst_return_pct'], 'threshold': -drawdown_limit},
        ]
        evidence['suitability'] = {'eligible': all(check['passed'] for check in fit_checks), 'checks': fit_checks,
                                   'method': '固定历史筛选：≥30个完整窗口、中位收益>0、负收益频率≤55%、最差窗口收益不低于当前量化回撤阈值的负值。属于未经策略回测的启发式筛选，不预测未来收益，历史样本可能失效。'}
        holding_evidence[code] = evidence
        if item.get('action') != '分批配置候选' or _number(item.get('score')) is None:
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': '净值样本有效，已计算至少7天历史持有统计；但未通过现有趋势、推荐指数或风险条件，不进入新增候选。'})
            continue
        overseas_supported, overseas_note = _overseas_supported(fund or {}, snapshot)
        if not overseas_supported:
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': overseas_note,
                             'verification_status': 'source_unavailable', 'execution_eligible': False})
            continue
        # Sector names cannot stand in for the fund's disclosed positions.
        # Import lazily because selection also uses the strategy's output.
        from research_selection import _classify
        from research_categories import board_for
        from research_holdings import verify_board
        board = board_for(fund or {}, _classify(fund or {}, item)[0], as_of=snapshot.get('as_of'))
        board_match = verify_board(fund or {}, board['id'], as_of=snapshot.get('as_of'))
        if board.get('requires_holdings_match') and board_match.get('status') != 'matched':
            excluded.append({'code': code, 'name': item.get('name', code),
                             'reason': '板块持仓核验未通过：' + board_match.get('reason', '缺少可靠披露证据'),
                             'board_match': board_match, 'execution_eligible': False})
            continue
        if evidence['status'] != 'sufficient':
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': f'只有 {evidence["sample_count"]} 个完整的至少7天历史窗口，少于30个；暂不形成新增候选。'})
            continue
        if not evidence['suitability']['eligible']:
            failed = [check['name'] for check in fit_checks if not check['passed']]
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': '至少7天历史持有筛选未通过：' + '、'.join(failed) + '；保留观察，不把量化高分当作持有期适配证明。', 'holding_checks': fit_checks})
            continue
        if regime['mode'] != 'risk_on':
            excluded.append({'code': code, 'name': item.get('name', code), 'reason': f'当前为“{regime["label"]}”，市场状态阻断新增风险候选。'})
            continue
        candidates.append({
            'code': code, 'name': item.get('name', code), 'score': item['score'],
            'action': '条件性研究候选，待产品核验',
            'reason': f'通过现有量化规则且样本压力低于新增门槛。历史至少7天窗口 {evidence["sample_count"]} 个，中位收益 {evidence["median_return_pct"]:+.3f}%，最差 {evidence["worst_return_pct"]:+.3f}%，负收益频率 {evidence["negative_frequency_pct"]:.2f}%；未扣费用，不能据此保证未来持有7天盈利。',
            'holding_plan': _holding_plan(item, evidence), 'verification_status': 'public_research_only',
            'risk_classification': '中高风险研究范围：根据基金类型推断，非官方风险评级',
            'fund_type': (fund or {}).get('fund_type'), 'overseas_evidence_note': overseas_note,
            'board_match': board_match,
            'verified_buyable': False, 'can_trade': False, 'execution_eligible': False,
            'platform_eligibility': 'source_unavailable',
            'verification_blockers': ['费用、确认起算和持有约束尚未自动核验', '支付宝平台可购买资格尚未自动核验'],
            'evidence_ids': item.get('evidence_ids', ['nav:' + code]),
        })
    candidates.sort(key=lambda item: (-item['score'], item['code']))
    return {
        'schema_version': SCHEMA_VERSION, 'as_of': snapshot.get('as_of'), 'panic': panic, 'regime': regime,
        'horizon': {'minimum_days': MIN_HOLDING_DAYS, 'label': '至少7个自然日的研究持有计划',
                    'notice': '不是产品最短持有期限或免赎回费门槛；实际份额确认、费用和可赎回时间按最新产品规则。风险触发时可提前复核，不保证7天收益。'},
        'candidates': candidates, 'excluded_candidates': excluded, 'holding_evidence': holding_evidence,
        'defensive_options': _defensive_options(universe, snapshot, regime['mode']),
        'execution': {'automatic_trading': False, 'verified_platform_orders': False,
                      'note': '输出公开数据研究清单和条件性操作步骤；产品购买资格、费用和持有约束的可靠核验源缺失，处于阻断状态；继续扫描已接入源，不承诺未来补齐，也不要求手工提供市场分析；不会自动交易。'},
    }
