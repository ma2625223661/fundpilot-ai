"""Small, honest fund boards selected only from the already researched snapshot.

This module does no I/O, changes no input, and never changes an observation into
a buy instruction. Numeric comparisons stay inside one declared asset class.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime
from research_categories import BOARDS, boards_for
from research_holdings import verify_board


DEFENSIVE = {'short_bond', 'bond', 'money', 'overseas_bond'}
BLOCKED_ACTIONS = ('暂缓', '暂停', '减仓', '回避', '数据不足', '不可', '阻断', '防御', '风险')
MAX_RESEARCH_PER_BOARD = 3
MAX_DISPLAY_PER_BOARD = 3


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _brief(value, maximum=100):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= maximum else text[:maximum - 1].rstrip('，；、 ') + '…'


def _classify(fund, quant):
    """Asset buckets use explicit source types, never the fund title."""
    kind = str(fund.get('fund_type') or quant.get('fund_type') or '')
    basis = '仅按数据源明确资产类型分类，基金名称不参与'
    if '货币' in kind:
        return 'money', basis
    if '黄金' in kind:
        return 'gold', basis
    if '商品' in kind:
        return 'commodities', basis
    if 'QDII' in kind.upper():
        return ('overseas_bond' if '债' in kind else 'overseas_mixed' if '混合' in kind else 'overseas_equity'), basis
    if '债' in kind or '固收' in kind:
        for pattern, asset in ((r'可转债|转债', 'convertible_bond'),
                               (r'二级债|混合二级|二级混合|增强债|混合一级', 'secondary_bond'),
                               (r'短债|超短|中短|短期纯债', 'short_bond')):
            if re.search(pattern, kind):
                return asset, basis
        return 'bond', basis
    if '股票' in kind:
        return ('equity_index' if '指数' in kind else 'equity_active'), basis
    if '混合' in kind:
        return 'equity_active', basis
    return 'unclassified', '数据源资产类型缺失；不按基金名称猜测，持仓仍可独立核验行业主题'


def _family(fund):
    """Strip share-class markers at the end or before a known currency suffix."""
    explicit = fund.get('share_family') or fund.get('family_id')
    if explicit:
        return 'id:' + str(explicit)
    name = re.sub(r'\s+', '', str(fund.get('name') or fund.get('code') or ''))
    name = name.translate(str.maketrans({'（': '(', '）': ')'}))
    currency = r'(?:人民币|美元|港币|港元|欧元|日元|英镑|CNY|CNH|RMB|USD|HKD|EUR|JPY|GBP)(?:现汇|现钞|对冲)?'
    suffix = rf'(?=$|\({currency}\)$)'
    name = re.sub(r'\(([A-Z])(?:类|份额)?\)' + suffix, r'\1', name, flags=re.I)
    name = re.sub(r'(?<=[\u4e00-\u9fff)])[A-Z](?:类|份额)?' + suffix, '', name, flags=re.I)
    return name.casefold()


def _fresh(fund, quant, snapshot_date):
    if quant.get('quality') != 'ok' or snapshot_date is None:
        return False
    nav_date = _date(quant.get('nav_date') or fund.get('nav_date'))
    if nav_date is None or not 0 <= (snapshot_date - nav_date).days <= 7:
        return False
    # If the source advertises a conflicting future date, don't let an older q date hide it.
    source_date = _date(fund.get('nav_date'))
    if source_date and (source_date > snapshot_date or (snapshot_date - source_date).days > 7):
        return False
    return True


def _strategy_mode(strategy, snapshot):
    if not isinstance(strategy, dict):
        return 'unknown', set(), {}
    mode = strategy.get('regime', {}).get('mode', 'unknown')
    strategy_time = _timestamp(strategy.get('as_of') or strategy.get('panic', {}).get('as_of'))
    snapshot_time = _timestamp(snapshot.get('as_of'))
    try:
        same_report = strategy_time is not None and snapshot_time is not None and abs((snapshot_time - strategy_time).total_seconds()) <= 300
    except TypeError:
        same_report = False
    if not same_report or strategy.get('stale') or strategy.get('is_stale') or mode not in ('risk_on', 'cautious', 'defensive'):
        mode = 'unknown'
    candidates = {str(row.get('code')): row for row in strategy.get('candidates', []) if isinstance(row, dict)}
    return mode, set(candidates) if mode == 'risk_on' else set(), candidates


def _risk_flags(quant):
    metrics, thresholds = quant.get('metrics', {}), quant.get('thresholds', {})
    vol, vol_limit = _number(metrics.get('volatility_annual')), _number(thresholds.get('annual_volatility_limit'))
    drawdown, drawdown_limit = _number(metrics.get('max_drawdown')), _number(thresholds.get('drawdown_limit'))
    flags = []
    if vol is not None and vol_limit is not None and vol > vol_limit:
        flags.append(f'波动 {vol:g}% 高于上限 {vol_limit:g}%')
    if drawdown is not None and drawdown_limit is not None and abs(drawdown) > drawdown_limit:
        flags.append(f'回撤 {abs(drawdown):g}% 超过上限 {drawdown_limit:g}%')
    complete = all(value is not None for value in (vol, vol_limit, drawdown, drawdown_limit))
    return flags, complete


def _safe_action(source_action, quant_action, role, mode, flags):
    action = str(source_action or quant_action or '继续观察')
    if any(word in str(quant_action) for word in BLOCKED_ACTIONS) and not any(word in action for word in BLOCKED_ACTIONS):
        action = quant_action
    if flags and not any(word in action for word in BLOCKED_ACTIONS):
        action = '暂缓新增'
    if role != 'candidate' and any(word in action for word in ('配置候选', '研究候选', '买入', '建仓', '加仓')):
        action = '暂缓新增' if mode in ('cautious', 'defensive') else '继续观察'
    return action


def _headline(action, role, section, flags):
    if role == 'candidate':
        return '研究候选 · 执行条件未核验'
    if flags:
        return '暂缓新增 · 风险超限'
    if '减仓' in action:
        return '已有持仓需复核 · 不作新增推荐'
    if any(word in action for word in ('暂停', '暂缓', '防御')):
        return '暂缓新增 · 保留观察'
    if section in DEFENSIVE:
        return '防守观察 · 产品资料待核验'
    return '观察优选 · 暂无新增信号'


def recommendation_index(score, role, action, mode, flags, risk_complete=True):
    """Risk-capped attention index; keep the measured historical score intact."""
    if score is None or not risk_complete or mode not in ('risk_on', 'cautious', 'defensive'):
        return None
    level = 0 if score < 40 else 1 if score < 60 else 2 if score < 72 else 3 if score < 85 else 4
    if role != 'candidate':
        level = min(level, 2)
    if flags or re.search(r'暂缓|暂停|阻断|防御|风险超限', action):
        level = min(level, 1)
    if re.search(r'减仓|卖出|退出', action) or mode == 'defensive':
        level = 0
    elif mode == 'cautious':
        level = min(level, 2)
    return min(math.floor(score + .5), (39, 59, 71, 84, 100)[level])


def _blocked_plan(plan, action, reason):
    """Keep details when already blocked; override an unsafe active plan on a board."""
    result = copy.deepcopy(plan) if isinstance(plan, dict) else {}
    result['new_position'] = '当前保持观察，暂不安排新增批次。' + reason
    if '减仓' in action:
        result['existing_position'] = '如已持有，结合实际仓位、风险预算与费用复核；没有持仓则没有卖出操作。'
    else:
        result['existing_position'] = '如已持有，按原风险预算复核，当前不安排新增；观察状态不等于自动卖出。'
    result['steps'] = ['系统继续更新已接入的净值、行情与公告。', reason, '本板块只展示研究观察，未确认可执行购买，不自动下单。']
    result['entry_conditions'] = ['市场状态、基金趋势和风险条件重新通过，且产品执行信息可靠核验后再评估。']
    return result


def build_sections(snapshot, quant, analysis, strategy=None, limit=MAX_DISPLAY_PER_BOARD,
                   references=None, reference_catalog=None):
    """Return up to three distinct fund families per board; sources stay intact.

    A fund listed by the user's Yangjibao board reference is allowed to enter
    that requested board before its own quantitative/holdings study finishes.
    The card remains an observation with an unknown recommendation index until
    independent evidence is available; the reference never fabricates a
    holdings ratio.
    """
    try:
        limit = max(0, min(MAX_DISPLAY_PER_BOARD, int(limit)))
    except (ValueError, TypeError, OverflowError):
        limit = MAX_DISPLAY_PER_BOARD
    if limit == 0:
        return []
    snapshot_date = _date(snapshot.get('as_of'))
    source_funds = {str(row.get('code')): row for row in snapshot.get('funds', []) if isinstance(row, dict)}
    analysis_funds = analysis.get('funds', []) if isinstance(analysis, dict) else []
    analyzed = {str(row.get('code')): row for row in analysis_funds if isinstance(row, dict)}
    mode, candidate_codes, strategy_candidates = _strategy_mode(strategy, snapshot)
    reference_catalog = {str(row.get('code')): row for row in (reference_catalog or [])
                         if isinstance(row, dict) and row.get('code')}
    # Persisted reports retain the enriched candidate reference (including its
    # display name), even when the broad universe is refreshed or unavailable.
    for reference in references or []:
        if isinstance(reference, dict) and reference.get('name') and reference.get('code'):
            reference_catalog.setdefault(str(reference['code']), reference)
    reference_by_code = {}
    for reference in references or []:
        if not isinstance(reference, dict):
            continue
        code, requested = str(reference.get('code') or ''), reference.get('requested_board_id')
        if not re.fullmatch(r'\d{6}', code) or requested not in BOARDS:
            continue
        reference_by_code.setdefault(code, []).append(reference)
    groups = {}
    for item in quant:
        if not isinstance(item, dict):
            continue
        code = str(item.get('code', ''))
        fund = source_funds.get(code)
        if not fund or not _fresh(fund, item, snapshot_date):
            continue
        asset_id, basis = _classify(fund, item)
        code_references = reference_by_code.get(code, [])
        boards = list(boards_for(fund, asset_id, as_of=snapshot.get('as_of')))
        for reference in code_references:
            requested = reference.get('requested_board_id')
            if not reference.get('direct_selection', True) or requested not in BOARDS:
                continue
            if not any(board.get('id') == requested for board in boards):
                boards.append(BOARDS[requested])
        for board in boards:
            section_id = board['id']
            board_match = verify_board(fund, section_id, as_of=snapshot.get('as_of'))
            reference_for_board = next((reference for reference in code_references
                                        if reference.get('requested_board_id') == section_id
                                        and reference.get('direct_selection', True)), None)
            # A direct user reference establishes display membership only. It
            # does not establish holdings evidence or a recommendation score.
            if (board.get('requires_holdings_match') and board_match.get('status') != 'matched'
                    and reference_for_board is None):
                continue
            original = analyzed.get(code, {})
            flags, risk_complete = _risk_flags(item)
            score = _number(item.get('score'))
            if score is not None and not 0 <= score <= 100:
                score = None
            source_action = original.get('action') or item.get('action', '继续观察')
            source_blocked = any(word in str(source_action) for word in BLOCKED_ACTIONS)
            candidate = (code in candidate_codes and item.get('action') == '分批配置候选' and not source_blocked
                         and not flags and risk_complete and score is not None and asset_id not in DEFENSIVE | {'unclassified'}
                         and (not board.get('requires_holdings_match') or board_match.get('status') == 'matched'))
            role = 'candidate' if candidate else 'observation'
            action = _safe_action(source_action, item.get('action'), role, mode, flags)
            credit_unknown = asset_id in DEFENSIVE | {'secondary_bond', 'convertible_bond'}
            if flags:
                blocker = flags[0] + '，当前不安排新增。'
            elif mode == 'unknown' and asset_id not in DEFENSIVE:
                blocker = '市场状态缺失或过期，暂不生成新增风险候选。'
            elif mode in ('cautious', 'defensive') and asset_id not in DEFENSIVE:
                blocker = '当前市场处于谨慎或防御模式，暂停新增风险仓位。'
            elif not risk_complete:
                blocker = '风险指标或阈值缺失，不能确认是否满足风险条件。'
            elif credit_unknown:
                blocker = '信用/久期、费用及支付宝可购资格未核验。'
            elif asset_id.startswith('overseas') or section_id.startswith('overseas'):
                blocker = '海外行情、汇率及产品执行信息须有匹配证据；未核验时仅观察。'
            else:
                blocker = '申赎费用、持有约束及支付宝可购资格未核验。'
            metrics = copy.deepcopy(item.get('metrics', {}))
            r20, r60 = _number(metrics.get('return_20d')), _number(metrics.get('return_60d'))
            if flags and score is not None:
                reason = f'{score:g} 分仅用于历史特征排序，不能覆盖风险超限；本次保留观察。'
            elif r20 is not None and r60 is not None:
                reason = f'近20/60日总收益 {r20:+g}% / {r60:+g}%；' + ('已通过当前候选筛选，仍属研究清单。' if candidate else '只在同类深研样本中观察，不代表可买入。')
            else:
                reason = '来自当前已深研样本的同类观察，历史分数不代表未来收益。'
            enriched = copy.deepcopy(original)
            enriched.update({
                'code': code, 'name': str(fund.get('name') or item.get('name') or code),
                'reference_candidate': copy.deepcopy(reference_for_board or fund.get('reference_candidate')),
                'direct_selection': bool(reference_for_board),
                'score': score, 'recommendation_index': (None if board.get('requires_holdings_match') and board_match.get('status') != 'matched'
                                                       else recommendation_index(score, role, action, mode, flags, risk_complete)),
                'recommendation_method': '推荐指数取原始历史研究分与风险状态档位上限的较小值；非候选最高71，暂缓或风险超限最高59，防御或退出最高39；不是收益或成功概率。',
                'action': action, 'role': role,
                'brief': {'headline': _brief(_headline(action, role, asset_id, flags)), 'reason': _brief(reason),
                          'risk': _brief(blocker), 'score_label': f'{score:g}/100 · 历史研究分' if score is not None else '研究分待核验'},
                'metrics': metrics, 'asset_class': item.get('asset_class'), 'board_category': section_id,
                'fund_type': fund.get('fund_type'), 'classification_basis': board.get('classification_basis', board.get('description', '')) + '；' + basis,
                'board_match': copy.deepcopy(board_match),
                'board_comparison': copy.deepcopy(board.get('board_comparison', [])),
                'asset_category': asset_id, 'board_label': board['label'], 'board_group': board['group'],
                'nav_date': item.get('nav_date') or fund.get('nav_date'),
                'quality': item.get('quality'), 'research_origin': fund.get('research_origin', 'current'),
                'evidence_collected_at': fund.get('evidence_collected_at') or fund.get('fetched_at') or snapshot.get('as_of'), 'risk_flags': flags, 'risk_check_complete': risk_complete,
                'execution_eligible': False, 'verified_buyable': False,
                'selection_scope': '当前深研样本内同类比较，非全市场最优；支付宝在售未核验',
                'source_action': source_action, 'quant_action': item.get('action'),
                'source_url': fund.get('source_url', item.get('source_url', '')),
            })
            enriched.setdefault('reason', '\n'.join(item.get('reasons', [])))
            enriched.setdefault('invalidation', item.get('invalidation', '资料或风险条件改变后重新评估。'))
            enriched.setdefault('operation_plan', {})
            if board_match.get('status') == 'matched':
                enriched['classification_basis'] += '；' + str(board_match.get('reason', '已按披露持仓核验板块匹配'))
            if candidate:
                if 'holding_plan' in strategy_candidates.get(code, {}):
                    enriched['holding_plan'] = copy.deepcopy(strategy_candidates[code]['holding_plan'])
            else:
                enriched['operation_plan'] = _blocked_plan(enriched['operation_plan'], action, blocker)
            risk_bucket = 0 if not flags and risk_complete and not any(word in action for word in BLOCKED_ACTIONS) else (1 if not flags and risk_complete else 2)
            vol = _number(metrics.get('volatility_annual'))
            drawdown = _number(metrics.get('max_drawdown'))
            match_ratio = _number(board_match.get('matched_disclosed_pct'))
            reference = reference_for_board or fund.get('reference_candidate') or {}
            reference_member = (reference.get('requested_board_id') == section_id
                                and reference.get('direct_selection', True)
                                and (reference.get('source_kind') in ('user_reference', 'yangjibao', 'web_discovery')
                                     or reference.get('forced_selection')))
            reference_priority = (2 if reference.get('forced_selection') or reference.get('source_kind') == 'web_discovery'
                                  else 1) if reference_member else 0
            reference_order = _number(reference.get('display_order'))
            sort_key = (-reference_priority, -(match_ratio if match_ratio is not None else -1),
                        reference_order if reference_order is not None else math.inf,
                        0 if candidate else 1, risk_bucket, -(score if score is not None else -1),
                        vol if vol is not None else math.inf, abs(drawdown) if drawdown is not None else math.inf, code)
            groups.setdefault(section_id, []).append((sort_key, _family(fund), enriched))

    # Include every directly referenced screenshot member even when the current
    # 96-fund deep-research budget did not reach it. These are honest pending
    # cards: no score, holdings ratio or action is invented.
    for code, code_references in reference_by_code.items():
        for reference in code_references:
            if not reference.get('direct_selection', True):
                continue
            section_id = reference.get('requested_board_id')
            if section_id not in BOARDS:
                continue
            catalog = reference_catalog.get(code) or source_funds.get(code) or {}
            forced_discovery = bool(reference.get('forced_selection') or reference.get('source_kind') == 'web_discovery')
            if code not in reference_catalog and code not in source_funds:
                # Public-search candidates are explicitly requested to appear
                # even when the current universe did not include their row.
                # Only the published identity is carried forward; every
                # quantitative, holdings and trade field remains unknown.
                catalog = {'code': code,
                           'name': reference.get('name') if reference.get('name') and reference.get('name') != code else '*****',
                           'fund_type': reference.get('fund_type'),
                           'source_url': reference.get('source_url')}
            if any(existing[2].get('code') == code for existing in groups.get(section_id, [])):
                continue
            board = BOARDS[section_id]
            match = verify_board(catalog, section_id, as_of=snapshot.get('as_of'))
            asset_id, basis = _classify(catalog, {})
            source_label = '互联网搜索候选' if forced_discovery else '截图指定板块'
            pending_plan = {
                'new_position': f'{source_label}已直接选入，等待净值、风险与持仓研究完成后再评估；当前不生成买入指令。',
                'existing_position': '如已持有，按实际仓位和风险预算复核；本卡不自动调整仓位。',
                'entry_conditions': ['完成本基金净值与风险指标研究。', '取得报告期披露股票持仓并计算本板块匹配比例。', '市场状态和产品交易条件通过核验。'],
                'steps': [f'系统优先采集该{source_label}的净值、风险、公告和持仓。', '显示真实匹配比例后，按比例与同板块基金重新排序。', '研究完成前保持观察，不自动下单。'],
                'review_schedule': '下一轮自动研究完成后更新；数据缺失时继续标记待核验。',
                'fee_checks': ['支付宝可购、限购、确认起算、最短持有和申赎费率尚未核验。']
            }
            if forced_discovery:
                pending_plan['steps'][0] = '系统会在后续自动研究轮次核对公开产品页、净值、风险和披露持仓。'
            enriched = {
                'code': code,
                'name': str(catalog.get('name') or reference.get('name') or code),
                'reference_candidate': copy.deepcopy(reference),
                'direct_selection': True,
                'score': None,
                'recommendation_index': None,
                'recommendation_method': f'{source_label}直接收录；推荐指数待本轮独立量化研究完成后计算。',
                'action': (f'{source_label} · 强制纳入 · 待核验' if forced_discovery else '截图指定板块 · 待深研'),
                'role': 'observation',
                'brief': {'headline': (f'{source_label} · 强制纳入 · 等待自动深研' if forced_discovery else '截图指定板块 · 等待自动深研'),
                          'reason': f'按{source_label}结果直接选入该板块；本轮尚未完成该基金的净值、风险和持仓研究。',
                          'risk': '推荐指数、持仓匹配比例和支付宝可买资格待核验。',
                          'score_label': '推荐指数待评估'},
                'metrics': {}, 'asset_class': catalog.get('fund_type'), 'board_category': section_id,
                'fund_type': catalog.get('fund_type'),
                'classification_basis': board.get('description', '') + f'；{source_label}直接选入，实际持仓匹配比例独立核验；' + basis,
                'board_match': copy.deepcopy(match), 'board_comparison': [],
                'asset_category': asset_id, 'board_label': board['label'], 'board_group': board['group'],
                'nav_date': catalog.get('nav_date'), 'research_origin': 'web_discovery_forced_pending' if forced_discovery else 'yangjibao_reference_pending',
                'evidence_collected_at': catalog.get('fetched_at') or snapshot.get('as_of'),
                'risk_flags': [],
                'execution_eligible': False, 'verified_buyable': False, 'alipay_available': 'unverified',
                'selection_scope': f'{source_label}直接选入；等待独立研究，不代表推荐或可交易资格。',
                'source_action': (f'{source_label} · 强制纳入 · 待核验' if forced_discovery else '截图指定板块 · 待深研'), 'quant_action': None,
                'source_url': catalog.get('source_url', f'https://fund.eastmoney.com/{code}.html'),
                'operation_plan': pending_plan,
                'reason': f'{source_label}归属已收录，量化与持仓证据尚未完成。',
                'invalidation': '持仓、净值、风险或产品信息核验后更新；来源分类不等于实际持仓证明。'
            }
            reference_order = _number(reference.get('display_order'))
            groups.setdefault(section_id, []).append(((-2 if forced_discovery else -1, -1,
                reference_order if reference_order is not None else math.inf, 1, 2, math.inf, math.inf, math.inf, code),
                _family(catalog or enriched), enriched))
    sections = []
    for section_id, board in BOARDS.items():
        if section_id not in groups:
            continue
        ranked = sorted(groups[section_id], key=lambda row: row[0])
        distinct = []
        local_families = set()
        for _, family, fund in ranked:
            if family in local_families:
                continue
            local_families.add(family)
            distinct.append(fund)
        picked = distinct[:limit]
        if not picked:
            continue
        for index, fund in enumerate(picked, 1):
            fund['rank'] = index
            fund['selection_reason'] = (('按互联网搜索候选强制收录本板块基金，持仓匹配比例独立核验。'
                                         if (fund.get('reference_candidate') or {}).get('source_kind') == 'web_discovery'
                                         else '按养基宝板块分类优先收录本板块基金，持仓匹配比例独立核验。')
                                        if fund.get('reference_candidate') else
                                        '优先已披露股票与本板块匹配比例更高的基金；同比例再比较策略资格、风险、历史分数与波动回撤。') + '风险与操作状态单独核验，不因板块归属而提升为买入。'
        status = 'candidate' if any(fund['role'] == 'candidate' for fund in picked) else 'observation'
        has_reference = any(f.get('reference_candidate') for f in picked)
        sections.append({'id': section_id, 'label': board['label'], 'group': board['group'], 'display_title': '研究候选' if status == 'candidate' else '观察优选',
                         'requires_holdings_match': board.get('requires_holdings_match', False),
                         'description': ('按养基宝软件的板块分类收录，展示各基金真实的板块持仓匹配比例。' if has_reference else board['description']), 'status': status,
                         'selection_method': ('按养基宝板块分类收录的基金优先保留在指定板块，最多展示3只；实际持仓比例、推荐指数与风险状态分别计算，不以其他板块匹配更高为由移走。未核验支付宝在售。' if has_reference else '基金名称只用于展示。每只基金仅归入已披露持仓匹配比例最高的一个板块，同比例优先更细分方向；各板块再按实际匹配比例由高到低选取最多3只，资料不全时使用已确认下限。大部分符合（>50%）即可，不要求超过75%；同比例再比较策略资格、风险、研究分与波动回撤。未核验支付宝在售。'),
                         'eligible_count': len(distinct), 'eligible_share_count': len(ranked), 'funds': picked})
    return sections
