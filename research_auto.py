"""Server-owned automatic screening, research and periodic risk reassessment.

Optional AI credentials remain server-owned; the scanner never submits trades. A public fund universe is
not represented as a verified Alipay sale list. Every selected fund remains a
research candidate until platform and transaction terms are evidenced.
"""
import copy
import hashlib
import json
import re
import tempfile
import threading
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from research_data import CHINA, collect_research, now_iso
from research_quant import build_analysis, build_quant, build_sentiment
from research_market_sentiment import build_market_sentiment
from research_market_liquidity import build_market_liquidity
from research_selection import build_sections, MAX_DISPLAY_PER_BOARD
from research_categories import (BOARDS, SCHEMA_VERSION, build_board_coverage, enrich_board_diagnostics,
                                 register_dynamic_boards, board_catalog_scope, catalog_synchronized)
from research_strategy import build_strategy
from research_universe import collect_universe, pick_research_codes, pick_holdings_preflight_codes, cap_research_codes, plan_research_codes, MAX_RESEARCH_PER_BOARD
from research_auto_ai import enrich_auto_report
from research_holdings import collect_holdings, HOLDINGS_RULE_VERSION
from research_memory import update_holdings_index, update_check_ledger, attach_holdings_index, retain_research
from research_overview import build_market_overview
from research_schedule import (schedule_settings, schedule_signature, scheduled_time,
                               parse_schedule_time, schedule_allows_run, schedule_stop_time,
                               market_due_is_current, market_session_start)
from research_trading_calendar import calendar_status
from research_discovery import discover_public_candidates
from research_dynamic_boards import discover_dynamic_boards, merge_dynamic_board_registry
from research_candidates import (load_candidate_references, prepare_reference_candidates,
                                 build_reference_candidates, attach_reference_candidates)

AUTO_PREFS = {'risk': '积极成长', 'pos': 20, 'min': 72}
SCAN_INTERVAL = 30 * 60
RETRY_INTERVAL = 5 * 60
REPORT_VERSION = 1
MAX_REPORT_BYTES = 24_000_000
DEEP_LIMIT = 96
SOURCE_CONNECTIONS = [{
    'id': 'yangjibao', 'label': '养基宝', 'status': 'unavailable',
    'checked_at': '2026-10-30T13:50:38+08:00', 'http_status': 404,
    'reason': '官方板块请求使用登录标识与签名；本次匿名访问返回HTTP 404，尚未取得可接入数据。',
    'url': 'https://wx.yangjibao.com/app/market/hotplate',
}]


def _forced_discovery_references(discovery=None, previous_coverage=None):
    """Turn public-search hits into visible board members when verification stalls.

    These references are display membership only.  They deliberately carry no
    recommendation score, holdings ratio or purchase eligibility; the normal
    research pipeline can replace them with measured evidence later.
    """
    entries, seen = [], set()
    sources = []
    if isinstance(discovery, dict):
        sources.extend(discovery.get('boards', []))
    if isinstance(previous_coverage, list):
        sources.extend(previous_coverage)
    for board in sources:
        if not isinstance(board, dict):
            continue
        board_id = board.get('board_id') or board.get('id')
        if board_id not in BOARDS:
            continue
        search = board if board.get('candidates') is not None else board.get('web_search')
        if not isinstance(search, dict):
            continue
        for candidate in search.get('candidates', []):
            if not isinstance(candidate, dict):
                continue
            code = str(candidate.get('code') or '').strip()
            if not re.fullmatch(r'\d{6}', code):
                continue
            key = (code, board_id)
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                'code': code,
                'name': candidate.get('name') or code,
                'requested_board_id': board_id,
                'source_kind': 'web_discovery',
                'source_label': '互联网补充搜索',
                'direct_selection': True,
                'forced_selection': True,
                'discovery_status': candidate.get('status') or search.get('status'),
                'discovery_note': candidate.get('note') or candidate.get('screening_reason'),
                'fund_type': candidate.get('fund_type'),
                'source_url': candidate.get('source_url'),
                'search_url': candidate.get('search_url'),
                'searched_at': candidate.get('searched_at') or search.get('searched_at'),
            })
    return entries


def _merge_reference_rows(primary, extra):
    """Keep explicit user references first, then add forced web discoveries."""
    result, seen = [], {}
    for row in list(primary or []) + list(extra or []):
        if not isinstance(row, dict):
            continue
        code, board_id = str(row.get('code') or ''), row.get('requested_board_id')
        key = (code, board_id)
        if not re.fullmatch(r'\d{6}', code) or board_id not in BOARDS:
            continue
        if key in seen:
            existing = seen[key]
            if (not existing.get('name') or existing['name'] == code) and row.get('name'):
                existing['name'] = row['name']
            for field in ('fund_type', 'source_url', 'search_url'):
                if not existing.get(field) and row.get(field):
                    existing[field] = row[field]
            continue
        result.append(copy.deepcopy(row))
        seen[key] = result[-1]
    return result


def _mark_forced_discovery_searches(coverage):
    """Annotate persisted web-search rows so the UI explains the fallback."""
    for board in coverage if isinstance(coverage, list) else []:
        search = board.get('web_search') if isinstance(board, dict) else None
        if not isinstance(search, dict):
            continue
        for candidate in search.get('candidates', []):
            if isinstance(candidate, dict) and re.fullmatch(r'\d{6}', str(candidate.get('code') or '')):
                candidate['forced_selection'] = True
                candidate.setdefault('forced_selection_reason', '公开搜索候选已先纳入该板块展示，等待自动核验。')


def _search_unresolved_boards(universe, previous_coverage, refresh, progress):
    """Discover candidates publicly, without turning search text into evidence."""
    prior = previous_coverage if isinstance(previous_coverage, list) else []
    unresolved = [board for board in prior if isinstance(board, dict)
                  and board.get('status') in ('no_match', 'excluded', 'holdings_pending',
                                               'holdings_mismatch', 'insufficient')
                  and not board.get('displayed_count')]
    if not unresolved:
        return {'boards': [], 'sources': [], 'warnings': []}, []
    progress('正在为缺口板块检索公开基金网页', {'search_board_budget': 3})
    try:
        discovery = discover_public_candidates(unresolved, limit_boards=3, max_per_board=3, refresh=refresh)
    except Exception:
        # Public-page failures must not stop the existing data pipeline or
        # accidentally upgrade an unverified search result into a candidate.
        return {'boards': [], 'sources': [], 'warnings': ['公开网页后备检索未完成，本轮保留原研究范围。']}, []
    preferred = []
    rows = {row.get('code'): row for row in universe.get('funds', []) if isinstance(row, dict)}
    def identity_text(value):
        return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).casefold()
    for board in discovery.get('boards', []):
        for candidate in board.get('candidates', []):
            row = rows.get(candidate.get('code'))
            candidate['screened_at'] = universe.get('as_of') or now_iso()
            if row is None:
                candidate.update(status='not_in_current_ranking', screening_reason='本轮公开排行没有该代码的初筛记录，暂不能纳入策略；保留产品页供核验。')
            elif (not identity_text(candidate.get('name'))
                  or identity_text(candidate.get('name')) != identity_text(row.get('name'))
                  or (candidate.get('fund_type') and row.get('fund_type')
                      and identity_text(candidate['fund_type']) != identity_text(row['fund_type']))):
                candidate.update(status='identity_conflict', screening_reason='产品页与本轮基金目录的名称或类型不一致，等待来源身份复核；本轮不纳入深研。')
            elif not row.get('eligible'):
                reasons = [str(reason) for reason in row.get('exclusion_reasons', []) if reason]
                candidate.update(status='excluded', screening_reason='未通过本轮初筛：' + ('；'.join(reasons[:3]) or '当前类型或数据条件未通过'))
            else:
                candidate.update(status='screened', screening_reason='已与本轮公开排行交叉核验并通过初筛；仍须完成净值、风险和板块持仓核验。')
                preferred.append(candidate['code'])
    return discovery, list(dict.fromkeys(preferred))


def _attach_web_discovery(coverage, discovery, previous_coverage, selected_codes):
    previous = {row.get('id'): row.get('web_search') for row in previous_coverage
                if isinstance(row, dict) and isinstance(row.get('web_search'), dict)} if isinstance(previous_coverage, list) else {}
    current = {row.get('board_id'): row for row in discovery.get('boards', []) if isinstance(row, dict)}
    selected = set(selected_codes)
    for board in coverage:
        search = current.get(board['id'])
        if search is None and board['id'] in previous:
            search = {**copy.deepcopy(previous[board['id']]), 'from_previous_run': True,
                       'attempted_this_run': False}
            for item in search.get('candidates', []):
                item.setdefault('previous_screening_status', item.get('status'))
                item.setdefault('previous_screening_reason', item.get('screening_reason'))
                item.update(status='discovery_only', screening_reason='上次搜索发现，本轮未重新核验这条搜索记录；是否纳入深研以本轮实际研究记录为准。')
        if search is not None:
            board['web_search'] = copy.deepcopy(search)
            for item in board['web_search'].get('candidates', []):
                if isinstance(item, dict) and re.fullmatch(r'\d{6}', str(item.get('code') or '')):
                    item['forced_selection'] = True
                    item.setdefault('forced_selection_reason', '公开搜索候选已先纳入该板块展示，等待自动核验。')
                if item.get('status') == 'screened' and item.get('code') in selected:
                    item.update(status='research_selected', screening_reason='已纳入本轮深研，是否展示以本轮净值、风险及持仓核验结果为准。')


def _refresh_holdings_coverage(coverage, codes, snapshot, quant, sections):
    """Re-evaluate saved evidence under a new rule, retaining catalog counts."""
    from research_holdings import supported_board_ids
    supported = set(supported_board_ids())
    old = {board['id']: board for board in coverage if isinstance(board, dict) and board.get('id')}
    recalculated = build_board_coverage({}, codes, snapshot, quant, sections)
    evidence_keys = ('deep_count', 'valid_quant_count', 'matched_holdings_count',
                     'holdings_unknown_count', 'holdings_mismatch_count',
                     'displayed_count', 'candidate_count')
    for board in recalculated:
        previous = old.get(board['id'])
        if previous is None:
            continue
        measurements = {key: board[key] for key in evidence_keys}
        board.update(copy.deepcopy(previous))
        board.update(measurements)
        if board['displayed_count']:
            board['status'] = 'candidate' if board['candidate_count'] else 'observation'
            board['reason'] = '已按当前披露股票匹配比例规则复核，每板块最多展示三只。'
        elif board.get('requires_holdings_match') and board['id'] != 'holdings_unclassified' and board['id'] not in supported:
            board['status'] = 'source_unavailable'
        elif board.get('catalog_counts_known') is False:
            board['status'] = 'unknown'
        elif board['valid_quant_count'] and board.get('requires_holdings_match') and not board['matched_holdings_count']:
            board['status'] = 'holdings_pending' if board['holdings_unknown_count'] else 'holdings_mismatch'
        elif board.get('screened_count') == 0:
            board['status'] = 'no_match'
        elif board.get('eligible_count') == 0:
            board['status'] = 'excluded'
        elif not board['deep_count'] and board.get('eligible_count'):
            board['status'] = 'not_researched'
        else:
            board['status'] = 'insufficient'
        if not board['displayed_count']:
            board['reason'] = {
                'unknown': '旧报告未保存按持仓归类的板块初筛计数，等待新扫描。',
                'source_unavailable': '该方向所需专属证据源尚未接入，不能用名称或行业标签替代。',
                'holdings_pending': '净值研究已完成，披露持仓、报告期或主题证据尚不足；未核验匹配前不填入本板块。',
                'holdings_mismatch': '已取得的披露持仓未达到当前板块匹配要求；不以名称相似的基金补位。',
                'no_match': '本轮公开排行未识别到该方向；不等于全市场没有此类基金。',
                'excluded': '本轮匹配基金均未通过初筛；不使用受限或过期产品补位。',
                'not_researched': '本轮有初筛样本，深研预算未覆盖；尚未形成策略。',
                'insufficient': '已尝试深研，数据质量或新鲜度未满足展示条件；保留空缺。',
            }[board['status']]
    return enrich_board_diagnostics(recalculated, snapshot, quant, researched_codes=codes)


def apply_board_holdings_gate(snapshot, quant, analysis, strategy):
    """Recheck disclosed sector exposure, including restored older reports.

    This is a pure evidence check and never fetches data or calls the model.
    Original quantitative measurements remain available in the full report.
    """
    from research_categories import board_for, board_matches_for
    from research_selection import (_classify, _number, _risk_flags, _safe_action,
                                    recommendation_index, BLOCKED_ACTIONS, DEFENSIVE)
    from research_holdings import verify_board
    funds = {str(row.get('code')): row for row in snapshot.get('funds', [])}
    measured = {str(row.get('code')): row for row in quant}
    blocked = {}
    for row in analysis.get('funds', []):
        code = str(row.get('code'))
        fund = funds.get(code, {})
        board = board_for(fund, _classify(fund, measured.get(code, {}))[0], as_of=snapshot.get('as_of'))
        match = verify_board(fund, board['id'], as_of=snapshot.get('as_of'))
        row['board_match'] = match
        row['board_matches'] = [b.get('board_match') or verify_board(fund, b['id'], as_of=snapshot.get('as_of'))
                                for b in board_matches_for(fund, _classify(fund, measured.get(code, {}))[0], as_of=snapshot.get('as_of'))]
        row['selected_board_id'] = board['id']
        row['board_classification_method'] = board.get('classification_method')
        if board.get('requires_holdings_match') and match.get('status') != 'matched':
            blocked[code] = match
            if row.get('action') in ('分批配置候选', '7 天以上研究候选'):
                row['action'] = '继续观察'
                plan = row.setdefault('operation_plan', {})
                plan.update(new_position='板块持仓尚未核验通过，保持观察。',
                            existing_position='如已持有，按原风险预算复核；当前不安排新增。',
                            steps=['自动复核已披露持仓及行业证据。', '板块持仓匹配与风险条件均通过后再评估研究候选。'],
                            entry_conditions=['披露持仓与对应板块匹配，且市场及基金风险条件均通过。'])
    removed = [row for row in strategy.get('candidates', []) if str(row.get('code')) in blocked]
    if removed:
        strategy['candidates'] = [row for row in strategy.get('candidates', []) if str(row.get('code')) not in blocked]
        excluded = strategy.setdefault('excluded_candidates', [])
        for row in removed:
            match = blocked[str(row.get('code'))]
            excluded.append({'code': row.get('code'), 'name': row.get('name'), 'board_match': match,
                             'reason': '板块持仓核验未通过：' + match.get('reason', '缺少披露证据')})
        analysis['summary'] = strategy.get('regime', {}).get('label', '等待数据') + f' · {len(strategy["candidates"])} 只保留研究候选；板块持仓未核验的基金不进入对应主题推荐。'
    candidate_codes = {str(row.get('code')) for row in strategy.get('candidates', [])}
    mode = strategy.get('regime', {}).get('mode', 'unknown')
    for row in analysis.get('funds', []):
        code = str(row.get('code'))
        item = measured.get(code, {})
        flags, complete = _risk_flags(item)
        score = _number(item.get('score'))
        if score is not None and not 0 <= score <= 100:
            score = None
        asset = _classify(funds.get(code, {}), item)[0]
        source_action = str(row.get('action') or item.get('action', '继续观察'))
        candidate = (code in candidate_codes and item.get('action') == '分批配置候选'
                     and not any(word in source_action for word in BLOCKED_ACTIONS)
                     and not flags and complete and score is not None
                     and asset not in DEFENSIVE | {'unclassified'})
        role = 'candidate' if candidate else 'observation'
        action = _safe_action(source_action, item.get('action'), role, mode, flags)
        row['recommendation_index'] = (None if code in blocked or item.get('quality') != 'ok' else
                                       recommendation_index(score, role, action, mode, flags, complete))


def merge_snapshots(snapshots):
    result = {'as_of': now_iso(), 'funds': [], 'market': [], 'news': [],
              'sources': [], 'warnings': [], 'scope': '自动公开基金初筛与候选深研'}
    for key, identity, timestamp in [('funds', 'code', 'nav_date'), ('market', 'code', 'as_of'),
                                      ('news', 'url', 'published_at'), ('sources', 'id', 'fetched_at')]:
        seen = {}
        for snapshot in snapshots:
            for row in snapshot.get(key, []):
                row_id = row.get(identity)
                if row_id and (row_id not in seen or str(row.get(timestamp) or '') > str(seen[row_id].get(timestamp) or '')):
                    seen[row_id] = row
        result[key] = list(seen.values())
    result['warnings'] = list(dict.fromkeys(warning for snapshot in snapshots for warning in snapshot.get('warnings', [])))
    result['news'].sort(key=lambda row: row.get('published_at') or '', reverse=True)
    return result


def enforce_strategy(analysis, strategy):
    """Keep every detailed card consistent with the market/horizon decision."""
    result = copy.deepcopy(analysis)
    regime = strategy.get('regime', {})
    mode = regime.get('mode', 'unknown')
    selected = {row['code']: row for row in strategy.get('candidates', [])}
    exclusions = {row['code']: row for row in strategy.get('excluded_candidates', [])}
    for fund in result['funds']:
        plan = fund['operation_plan']
        fund['alipay_available'] = 'unverified'
        fund['execution_eligible'] = False
        plan['review_schedule'] = '服务运行时每 30 分钟自动复查；净值未更新时不把重复研究当作新信号。'
        plan['holding_horizon'] = '研究计划至少 7 个自然日；确认日起算、赎回到账与费用待数据核验，不保证第 7 天可无成本退出。'
        evidence = strategy.get('holding_evidence', {}).get(fund['code'])
        if evidence and evidence.get('sample_count'):
            fund['holding_evidence'] = evidence
            fund['reason'] += (f'\n历史至少 7 天持有区间：{evidence["sample_count"]} 个样本，'
                               f'中位收益 {evidence["median_return_pct"]:+.3f}%，最差 {evidence["worst_return_pct"]:+.3f}%，'
                               f'负收益频率 {evidence["negative_frequency_pct"]:.2f}%；未扣费用，历史频率不是未来概率。')
        if fund['code'] in exclusions:
            fund['reason'] += '\n自动策略筛选：' + exclusions[fund['code']]['reason']
        if fund['code'] in selected and mode in ('risk_on', 'cautious'):
            fund['action'] = '7 天以上研究候选'
            fund['reason'] += '\n' + str(selected[fund['code']].get('reason', ''))
            plan['new_position'] = '进入自动研究候选；支付宝可购与交易条款未验证，暂不生成可执行买入指令。'
            plan['steps'] = ['系统自动跟踪净值、市场压力与公告。', '计划研究持有至少 7 天，同时观察历史 7 天区间亏损与最差表现。',
                             '缺失的可购、费率或持有期信息继续标为待核验；数据补齐前保持研究状态。',
                             '行情转防御、数据失效或趋势破坏时，自动撤出新增研究候选。']
        elif fund['action'] in ('分批配置候选', '7 天以上研究候选'):
            fund['action'] = '防御期暂停新增' if mode == 'defensive' else '暂缓新增'
            plan['new_position'] = ('市场压力已触发防御，暂停新增中高风险仓位。' if mode == 'defensive' else
                                    '市场、持有期限或资料条件尚未全部通过，系统继续自动观察。')
            plan['existing_position'] = '如已持有，按实际仓位与风险预算复核；当前不安排补仓或新增批次。'
            plan['entry_conditions'] = ['系统重新核验市场模式、7 天区间风险和产品交易条件，全部通过后再评估研究资格。']
            plan['steps'] = ['继续自动获取更新数据。', '当前不安排新增批次。', '下一轮重新检查市场模式、7 天区间风险及基金交易条件。']
        else:
            plan['steps'] = ['系统持续更新净值、市场压力与公告摘要，并自动重新计算当前条件。',
                             '未达到新增条件时继续观察；缺失的交易条款保留未核验状态。',
                             '若已有持仓，报告仅提示风险变化；实际仓位与成本尚未接入，不推算个性化调整金额。']
        # Research outputs must not ask the user to supply facts that this mode
        # promises to collect automatically, or imply those facts were verified.
        plan['fee_checks'] = ['可购、限购、确认起算、最短持有和申赎费率未核验时，自动标记为待核验，不默认为零费用或可交易。',
                              '满 7 天不是统一免赎回费门槛，费用取决于份额和实际持有期限。']
    count = len(selected)
    result['summary'] = (f"{regime.get('label', '等待数据')} · " +
                         (f'{count} 只进入至少 7 天的中高风险研究候选。' if count else '本轮没有通过全部条件的中高风险研究候选。'))
    result['market_view'] = strategy.get('panic', {}).get('summary') or regime.get('reason', '')
    result['next_steps'] = ['系统按计划自动刷新公开基金初筛、净值和新闻公告。',
                            '行情明显恶化时自动切换防御方向；恢复后重新评估中高风险候选。',
                            '数据缺失时保持待核验并自动重试；不把未知状态当成低风险。']
    result['risks'] = list(dict.fromkeys([
        '支付宝完整在售清单尚未取得，公开基金研究候选不能视为已核验可购产品。',
        '至少 7 天是研究期限下限；中高风险基金可能在 7 天或更长时间内亏损。',
        '恐慌分为有限指数样本的市场压力代理，分数越高压力越大，不是实际投资者恐慌比例。',
    ] + result.get('risks', [])))
    return result


@catalog_synchronized
def _update_dynamic_catalog(funds, registry, as_of):
    from research_categories import BOARDS
    from research_holdings import BOARD_TAGS
    def normal(label):
        return re.sub(r'(?:行业|[ⅠⅡⅢⅣⅤ]+)$', '', str(label)).strip().casefold()
    # A broad parent's evidence set is not a dedicated board for each child.
    # Only an existing standalone label/alias (or a single-tag rule) suppresses
    # creating the missing, explicitly sourced industry destination.
    dedicated = {}
    for identity, tags in list(BOARD_TAGS.items()):
        board = BOARDS.get(identity, {})
        labels = {normal(label) for label in [board.get('label', ''), *board.get('aliases', [])]}
        dedicated[identity] = {tag for tag in tags if len(tags) == 1 or normal(tag) in labels}
    proposals = discover_dynamic_boards(funds, dedicated, as_of, registry=registry)
    return register_dynamic_boards(merge_dynamic_board_registry(registry, proposals, as_of), as_of)


def run_auto_research(progress=None, previous=None, refresh=False):
    update = progress or (lambda stage, details=None: None)
    update('正在扫描公开基金目录与区间收益', {'deep_done': 0, 'deep_total': 0})
    universe = copy.deepcopy(collect_universe(refresh=refresh))
    prior = previous if isinstance(previous, dict) else {}
    prior_index = prior.get('holdings_index') or update_holdings_index(
        [], prior.get('research_snapshot', {}).get('funds', []),
        prior.get('research_snapshot', {}).get('as_of') or now_iso())
    check_ledger = prior.get('holdings_check_ledger') or update_check_ledger({}, prior_index, universe.get('as_of') or now_iso())
    attach_holdings_index(universe, prior_index, check_ledger)
    dynamic_registry = register_dynamic_boards(prior.get('dynamic_board_registry', []), universe.get('as_of') or now_iso())
    dynamic_registry = _update_dynamic_catalog(universe.get('funds', []), dynamic_registry, universe.get('as_of') or now_iso())
    previous_coverage = previous.get('board_coverage') if isinstance(previous, dict) else None
    discovery, preferred_codes = _search_unresolved_boards(universe, previous_coverage, refresh, update)
    references = load_candidate_references()
    forced_discovery_references = _forced_discovery_references(discovery, previous_coverage)
    all_references = _merge_reference_rows(references, forced_discovery_references)
    reference_codes = prepare_reference_candidates(universe, references)
    forced_codes = [row['code'] for row in forced_discovery_references
                    if row.get('code') in {item.get('code') for item in universe.get('funds', [])
                                          if isinstance(item, dict) and item.get('eligible')}]
    preferred_codes = list(dict.fromkeys(reference_codes + forced_codes + preferred_codes))
    codes = pick_holdings_preflight_codes(universe, limit=DEEP_LIMIT, preferred_codes=preferred_codes)
    coverage = copy.deepcopy(universe.get('coverage', {}))
    coverage['total_count'] = coverage.get('catalog_count', 0)
    rows = {row['code']: row for row in universe.get('funds', [])}
    # Portfolio discovery is bounded separately from full research. A second
    # preflight batch can fill real portfolio gaps after reclassification.
    preflights, tried = [], []
    for attempt in range(2):
        if not codes:
            break
        current = collect_holdings({'as_of': universe.get('as_of') or now_iso(),
                                   'funds': [copy.deepcopy(rows[c]) for c in codes if c in rows],
                                   'sources': [], 'warnings': []},
                                  refresh=refresh, progress=update, preflight=True)
        preflights.append(current)
        tried.extend(codes)
        observed = [fund for result in preflights for fund in result.get('funds', [])]
        holdings_index = update_holdings_index(prior_index, observed, current['as_of'])
        check_ledger = update_check_ledger(check_ledger, current.get('funds', []), current['as_of'])
        attach_holdings_index(universe, holdings_index, check_ledger)
        dynamic_registry = _update_dynamic_catalog(current.get('funds', []), dynamic_registry, current['as_of'])
        rows = {row['code']: row for row in universe.get('funds', [])}
        remaining = {**universe, 'funds': [row for row in universe.get('funds', []) if row['code'] not in set(tried)]}
        codes = pick_holdings_preflight_codes(remaining, limit=DEEP_LIMIT, preferred_codes=preferred_codes)
    preliminary = merge_snapshots(preflights) if preflights else {'funds': [], 'sources': [], 'warnings': []}
    holdings_index = update_holdings_index(prior_index, preliminary.get('funds', []), universe.get('as_of') or now_iso())
    # Discovery must not displace already-proven higher-exposure portfolios.
    # Re-rank all known, eligible evidence together with this round's probes.
    pool_rows = [row for row in rows.values() if row.get('eligible') and (
        row['code'] in tried or (row.get('holdings') or {}).get('status') == 'ok'
        or row.get('universe_bucket') == 'defensive' or row.get('board_id') in {'gold', 'commodities'})]
    preferred_order = {code: index for index, code in enumerate(preferred_codes)}
    # User-provided board members keep their requested destination. Other
    # discovery hints only change probe order; fund families remain distinct.
    pool_rows.sort(key=lambda row: (row['code'] not in preferred_order,
                                   preferred_order.get(row['code'], len(preferred_order)),
                                   row['code'] not in tried, row['code']))
    codes = cap_research_codes([row['code'] for row in pool_rows], pool_rows,
                               as_of=universe.get('as_of') or now_iso())[:DEEP_LIMIT]
    holdings_rows = {**rows, **{f['code']: f for f in preliminary.get('funds', [])}}
    checked_count = sum(bool(row.get('holdings_checked_at')) for row in rows.values() if row.get('eligible'))
    coverage.update(holdings_preflight_count=len(tried), holdings_preflight_limit=DEEP_LIMIT * 2,
                    holdings_reclassified_excess_count=max(0, len(tried) - len(codes)), deep_requested_count=len(codes),
                    holdings_checked_total=checked_count,
                    holdings_unchecked_total=sum(bool(row.get('eligible')) for row in rows.values()) - checked_count,
                    reused_holdings_for_deep_count=sum(code not in tried for code in codes))
    coverage['dynamic_board_count'] = len(dynamic_registry)
    snapshots = []
    # Each collector has eight bounded workers; keeping batches sequential avoids
    # multiplying upstream traffic when the broad universe contains 20k funds.
    for start in range(0, len(codes), 8):
        batch = codes[start:start + 8]
        update(f'正在深研候选 {start + 1}–{start + len(batch)} / {len(codes)}',
               {'screened_count': coverage.get('screened_count', 0), 'deep_done': start, 'deep_total': len(codes)})
        snapshots.append(collect_research(batch, refresh=refresh, include_common=start == 0))
    if not snapshots:
        snapshots.append(collect_research(refresh=refresh, market_only=True))
    snapshot = merge_snapshots(snapshots)
    snapshot['sources'].extend(universe.get('sources', []))
    snapshot['sources'].extend(discovery.get('sources', []))
    snapshot['warnings'] = list(dict.fromkeys(snapshot['warnings'] + universe.get('warnings', [])
                                              + discovery.get('warnings', [])))
    for fund in snapshot['funds']:
        basic = rows.get(fund['code'], {})
        if basic.get('name'):
            fund['name'] = basic['name']
        for key in ('fund_type', 'universe_bucket', 'eligible', 'exclusion_reasons', 'alipay_available',
                    'purchase_status', 'provider_purchase_status', 'redemption_terms', 'screen_group',
                    'reference_candidate'):
            if key in basic:
                fund[key] = basic[key]
    obtained = {fund['code'] for fund in snapshot['funds']}
    for code in codes:
        if code not in obtained:
            snapshot['funds'].append({'code': code, 'name': rows[code]['name'], 'fund_type': rows[code].get('fund_type'),
                                      'nav': None, 'nav_date': None, 'history': [], 'alipay_available': 'unverified',
                                      'source_url': rows[code].get('source_url'), 'source_id': f'nav:{code}'})
    for fund in snapshot['funds']:
        disclosed = holdings_rows.get(fund['code'], {}).get('holdings')
        if disclosed is not None:
            fund['holdings'] = copy.deepcopy(disclosed)
    selected = set(codes)
    snapshot['sources'].extend(s for s in preliminary.get('sources', [])
                               if s.get('id', '').removeprefix('holdings:') in selected)
    present_sources = {s.get('id') for s in snapshot['sources']}
    for fund in snapshot['funds']:
        held = fund.get('holdings') or {}
        identity = held.get('source_id') or 'holdings:' + fund['code']
        if held.get('source_url') and identity not in present_sources:
            snapshot['sources'].append({'id': identity, 'name': '基金 ' + fund['code'] + ' 披露股票持仓',
                'url': held['source_url'], 'status': held.get('status', 'unknown'),
                'as_of': held.get('report_date'), 'fetched_at': held.get('fetched_at'),
                'count': len(held.get('rows', [])), 'scope': held.get('scope'),
                'reused': fund['code'] not in tried})
            present_sources.add(identity)
    snapshot['warnings'] = list(dict.fromkeys(snapshot['warnings'] + preliminary.get('warnings', [])))
    for fund in snapshot['funds']:
        nav_source = next((source for source in snapshot['sources'] if source.get('id') == 'nav:' + fund['code']), {})
        fund.update(research_origin='current', evidence_collected_at=nav_source.get('fetched_at') or snapshot.get('as_of'))
    retained_count = retain_research(snapshot, prior.get('research_snapshot', {}), universe, codes)
    coverage['retained_research_count'] = retained_count
    coverage['deep_count'] = len(codes)
    coverage['deep_data_count'] = len(obtained)
    update('正在计算恐慌分、持有区间风险和自动策略',
           {'screened_count': coverage.get('screened_count', 0), 'deep_done': len(codes), 'deep_total': len(codes)})
    snapshot['sentiment'] = build_sentiment(snapshot)
    quant = build_quant(snapshot, AUTO_PREFS)
    strategy = build_strategy(snapshot, quant, universe=universe, previous=previous)
    coverage['valid_quant_count'] = sum(q.get('quality') == 'ok' for q in quant)
    analysis = enforce_strategy(build_analysis(snapshot, quant, AUTO_PREFS), strategy)
    apply_board_holdings_gate(snapshot, quant, analysis, strategy)
    sections = build_sections(snapshot, quant, analysis, strategy,
                              references=all_references, reference_catalog=list(rows.values()))
    board_coverage = build_board_coverage(universe, codes, snapshot, quant, sections)
    _attach_web_discovery(board_coverage, discovery, previous_coverage, codes)
    candidate_references = build_reference_candidates(all_references, universe, snapshot, sections, codes)
    attach_reference_candidates(board_coverage, candidate_references)
    coverage.update(board_count=len(board_coverage), represented_board_count=sum(b['eligible_count'] > 0 for b in board_coverage),
                    researched_board_count=sum(b['deep_count'] > 0 for b in board_coverage),
                    displayed_board_count=len(sections), deep_limit=DEEP_LIMIT)
    return {'holdings_index': holdings_index, 'holdings_check_ledger': check_ledger,
            'dynamic_board_registry': dynamic_registry, 'candidate_references': candidate_references,
            'snapshot': snapshot, 'quant': quant, 'analysis': analysis, 'strategy': strategy, 'sections': sections,
            'market_overview': build_market_overview(universe, snapshot),
            'source_connections': copy.deepcopy(SOURCE_CONNECTIONS),
            'board_schema_version': SCHEMA_VERSION, 'board_coverage': board_coverage,
            'holdings_rule_version': HOLDINGS_RULE_VERSION,
            'universe': {'as_of': universe.get('as_of'), 'coverage': coverage,
                         'warnings': universe.get('warnings', []), 'selection_method': universe.get('selection_method'),
                         'selected_codes': codes,
                         'board_targets': plan_research_codes(codes, list(rows.values()), as_of=snapshot.get('as_of'))['board_targets'],
                         'source_scope': '公开基金初筛；支付宝完整在售范围未核验'},
            'prefs': dict(AUTO_PREFS), 'model': '自动全量初筛 + 候选量化研究', 'engine': 'automatic',
            'automatic': {'interval_seconds': SCAN_INTERVAL, 'minimum_holding_days': 7, 'paid_api_calls': False,
                          'per_board_deep_limit': MAX_RESEARCH_PER_BOARD, 'per_board_display_limit': MAX_DISPLAY_PER_BOARD,
                          'runs_while_server_online': True, 'trade_execution': False}}


def client_report_view(report):
    """Browser payload: drop per-company daily histories the page never reads.

    Each sample company carries ~120 adjusted closes, stored twice (sector cards
    and company evidence); together they were about half of the report. The page
    uses only quotes, financials and memberships, while server-side features such
    as the five-day review still read the full report. Shallow copies only: the
    cached report itself is never modified.
    """
    if not isinstance(report, dict):
        return report

    def strip(rows):
        return [{key: value for key, value in row.items() if key != 'history'} if isinstance(row, dict) else row
                for row in rows] if isinstance(rows, list) else rows
    view = dict(report)
    if isinstance(report.get('sector_analysis'), list):
        view['sector_analysis'] = [{**sector, 'leaders': strip(sector['leaders'])}
                                   if isinstance(sector, dict) and 'leaders' in sector else sector
                                   for sector in report['sector_analysis']]
    evidence = report.get('company_evidence')
    if isinstance(evidence, dict) and isinstance(evidence.get('sector_leaders'), dict):
        view['company_evidence'] = {**evidence, 'sector_leaders': {key: strip(rows)
                                    for key, rows in evidence['sector_leaders'].items()}}
    return view


class AutoResearchEngine:
    def __init__(self, state_path=None, interval=SCAN_INTERVAL, runner=None,
                 config_provider=None, ai_runner=None, research_scope='funds'):
        self.state_path = Path(state_path) if state_path else None
        self.interval = interval
        self.runner = runner or run_auto_research
        self.config_provider = config_provider or (lambda: {})
        self.ai_runner = ai_runner or enrich_auto_report
        self.research_scope = research_scope
        self._lock = threading.RLock()
        self._report_view_lock = threading.Lock()
        self._report_view_version = None
        self._report_view = None
        self._report_view_source = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._scheduler = None
        self._worker = None
        self._pending_scan = False
        self._last_public_attempt = None
        self._blocked_ai_revision = None
        self._ai_schedule_state = {}
        self._ai_runtime_directory = None
        self._ai_cost_guard = None
        self._ai_evidence_cache = None
        self._state = {'status': 'idle', 'stage': '等待自动研究启动', 'started_at': None,
                       'completed_at': None, 'next_run_at': None, 'progress': {}, 'report': None, 'error': None}
        self._restore()
        self._restore_schedule()
        if self.research_scope == 'sectors':
            from research_ai_cache import AIEvidenceCache
            from research_ai_cost import AICostGuard
            from research_ai_usage_import import bootstrap_usage
            if self.state_path:
                runtime_root = self.state_path.parent
            else:
                self._ai_runtime_directory = tempfile.TemporaryDirectory(prefix='fundpilot-ai-')
                runtime_root = Path(self._ai_runtime_directory.name)
            self._ai_cost_guard = AICostGuard(runtime_root / 'ai-cost.sqlite3')
            self._ai_evidence_cache = AIEvidenceCache(runtime_root / 'ai-evidence-cache.sqlite3')
            if self.state_path:
                bootstrap_usage(self._ai_cost_guard, self.state_path)

    def _restore_schedule(self):
        if not self.state_path:
            return
        path = self.state_path.with_suffix('.schedule.json')
        try:
            if not path.is_file() or path.stat().st_size > 8000:
                return
            saved = json.loads(path.read_text(encoding='utf-8'))
            if (isinstance(saved, dict) and isinstance(saved.get('signature'), list)
                    and (saved.get('next_run_at') is None or parse_schedule_time(saved['next_run_at']) is not None)):
                self._ai_schedule_state = saved
        except (ValueError, OSError, TypeError):
            pass

    def _persist_schedule(self):
        """Persist the paid-call gate independently of public scan success."""
        if not self.state_path:
            return
        path = self.state_path.with_suffix('.schedule.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._ai_schedule_state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def _restore(self):
        if not self.state_path or not self.state_path.is_file():
            return
        try:
            if self.state_path.stat().st_size > MAX_REPORT_BYTES:
                return
            saved = json.loads(self.state_path.read_text(encoding='utf-8'))
            if saved.get('version') != REPORT_VERSION or not isinstance(saved.get('report', {}).get('strategy'), dict):
                return
            if saved['report'].get('research_scope', 'funds') != self.research_scope:
                return
            self._state.update(report=saved['report'], completed_at=saved.get('completed_at'),
                               stage='已恢复上次报告，正在等待本轮自动更新', restored=True)
            if self.research_scope != 'sectors':
                register_dynamic_boards(saved['report'].get('dynamic_board_registry', []),
                                        saved['report'].get('snapshot', {}).get('as_of') or saved.get('completed_at'))
            old_ai = saved['report'].get('ai_research', {})
            if isinstance(saved.get('ai_schedule_state'), dict):
                self._ai_schedule_state = saved['ai_schedule_state']
            if old_ai.get('terminal_error'):
                self._blocked_ai_revision = old_ai.get('revision')
        except (ValueError, OSError, AttributeError):
            pass

    def _persist(self, report, completed):
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix('.tmp')
        if self.research_scope == 'sectors':
            payload = {'version': REPORT_VERSION, 'completed_at': completed, 'report': report,
                       'ai_schedule_state': self._ai_schedule_state}
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            if len(data) > MAX_REPORT_BYTES:
                raise OSError('板块报告超过本地保存字节预算')
            temp.write_bytes(data)
            temp.replace(self.state_path)
            return
        # Keep the reader and writer on the same byte budget. Full portfolios
        # can grow much faster than the lightweight discovery ledger; eviction
        # must not erase the fact that those funds have already been inspected.
        saved_report = dict(report)
        index = saved_report.pop('holdings_index', [])
        # These are pure derived views rebuilt by status(), not raw evidence.
        saved_report.pop('sections', None)
        if isinstance(report.get('analysis'), dict):
            saved_report['analysis'] = {**report['analysis'], 'funds': [
                {key: value for key, value in fund.items()
                 if key not in ('board_match', 'board_matches', 'board_comparison')}
                for fund in report['analysis'].get('funds', [])]}
        payload = {'version': REPORT_VERSION, 'completed_at': completed, 'report': saved_report,
                   'ai_schedule_state': self._ai_schedule_state}
        encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        base = encode(payload)
        # Index records are already ordered newest-first. Retain as many as
        # fit; the existing snapshot, catalogue and check ledger take priority.
        remaining = MAX_REPORT_BYTES - len(base) - 1024
        kept, used = [], 0
        for entry in index:
            size = len(encode(entry)) + 1
            if used + size > remaining:
                continue
            kept.append(entry)
            used += size
        saved_report['holdings_index'] = kept
        saved_report.setdefault('persistence', {})
        saved_report['persistence'] = {**saved_report['persistence'], 'holdings_index_saved': len(kept),
                                      'holdings_index_omitted': len(index) - len(kept)}
        data = encode(payload)
        if len(data) > MAX_REPORT_BYTES:
            # Never overwrite a usable previous report with a file restore()
            # would reject. The caller keeps the current report in memory.
            raise OSError('研究报告超过本地保存字节预算')
        temp.write_bytes(data)
        temp.replace(self.state_path)

    def start(self):
        with self._lock:
            if self._scheduler and self._scheduler.is_alive():
                return
            self._scheduler = threading.Thread(target=self._loop, name='fundpilot-auto-scheduler', daemon=True)
            self._scheduler.start()

    def _loop(self):
        if self.research_scope == 'sectors':
            return self._sector_loop()
        while not self._stop.is_set():
            config = self._configuration()
            setting = schedule_settings(config)
            if self.research_scope == 'sectors' and setting['mode'] == 'market_sessions':
                now = datetime.now(CHINA)
                slot = market_session_start(now)
                completed = None
                with self._lock:
                    try:
                        completed = datetime.fromisoformat(self._state.get('completed_at') or '')
                    except (TypeError, ValueError):
                        pass
                # Public collection may run during an unfinished bounded slot.
                # AI admission keeps its persisted due time; a newly started
                # service does not replay an already-missed fixed AI time.
                if slot is None or (completed is not None and completed >= slot):
                    due = scheduled_time(setting, now, after_run=True)
                    delay = max(1, (due - now).total_seconds()) if due else 3600
                    with self._lock:
                        self._state['next_run_at'] = (now + timedelta(seconds=delay)).isoformat(timespec='seconds')
                        self._wake.clear()
                    self._wake.wait(delay)
                    continue
            self.request_scan()
            with self._lock:
                worker = self._worker
            while worker and worker.is_alive() and not self._stop.wait(1):
                pass
            with self._lock:
                # A credential save during an active scan must not be consumed
                # by the ordinary post-scan wait/clear sequence.
                if self._pending_scan:
                    continue
                delay = RETRY_INTERVAL if self._state['status'] == 'error' else self.interval
                ai_due = self._ai_due(self._configuration())
                setting = schedule_settings(self._configuration())
                if setting['mode'] == 'market_sessions' and self._state['status'] != 'error':
                    collection_due = scheduled_time(setting, datetime.now(CHINA), after_run=True)
                    delay = max(1, (collection_due - datetime.now(CHINA)).total_seconds()) if collection_due else 3600
                if ai_due is not None:
                    delay = min(delay, max(1, (ai_due - datetime.now(CHINA)).total_seconds()))
                self._state['next_run_at'] = (datetime.now(CHINA) + timedelta(seconds=delay)).isoformat(timespec='seconds')
                self._wake.clear()
            self._wake.wait(delay)

    def _sector_loop(self):
        """One collector, two clocks: free quotes and durably reserved AI slots."""
        from research_live_schedule import next_quote_time, quote_due
        bootstrap = True
        while not self._stop.is_set():
            config = self._configuration()
            now = datetime.now(CHINA)
            ai_due = self._ai_due(config, now)
            setting = schedule_settings(config)
            paid_due = bool(ai_due and ai_due <= now and schedule_allows_run(setting, now))
            with self._lock:
                pending = self._pending_scan
                last_attempt = self._last_public_attempt
            free_due = quote_due(now, last_attempt)
            if bootstrap or pending or paid_due or free_due:
                # Only a scheduled run may admit paid work. Manual refresh,
                # startup and quote ticks explicitly deny every paid module.
                self.request_scan(public_only=not paid_due)
                bootstrap = False
                with self._lock:
                    worker = self._worker
                while worker and worker.is_alive() and not self._stop.wait(1):
                    pass
                continue
            public_due = next_quote_time(now, last_attempt)
            deadlines = [t for t in (public_due, ai_due) if t is not None]
            next_due = min(deadlines) if deadlines else now + timedelta(hours=1)
            delay = max(1, min(3600, (next_due-now).total_seconds()))
            with self._lock:
                if self._pending_scan:
                    continue
                self._state['next_run_at'] = next_due.isoformat(timespec='seconds')
                self._wake.clear()
            self._wake.wait(delay)

    def _configuration(self):
        try:
            value = self.config_provider()
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            # A credential store read failure must not fail public research or
            # expose decryption/storage diagnostics to the browser.
            return {}

    def _ai_due(self, config, now=None):
        """Synchronize a plan without performing research or reading HTTP data."""
        now = now or datetime.now(CHINA)
        signature = schedule_signature(config)
        with self._lock:
            # An already-running scan may hold an older configuration while a
            # user saves a future plan. It must never reset that new plan.
            if signature != schedule_signature(self._configuration()):
                return None
            if signature != self._ai_schedule_state.get('signature'):
                due = (scheduled_time(schedule_settings(config), now)
                       if config.get('enabled') and config.get('key') else None)
                self._ai_schedule_state = {'signature': signature,
                                           'next_run_at': due.isoformat(timespec='seconds') if due else None}
            if (not config.get('enabled') or not config.get('key')
                    or self._revision(config) == self._blocked_ai_revision and self._blocked_ai_revision is not None):
                return None
            due = parse_schedule_time(self._ai_schedule_state.get('next_run_at'))
            setting = schedule_settings(config)
            if due is not None and due <= now and (not schedule_allows_run(setting, now)
                    or setting['mode'] == 'market_sessions' and not market_due_is_current(due, now)):
                # A collection, shutdown or restart may span the exclusive stop
                # time. Expired slots never replay outside their daily window.
                due = scheduled_time(setting, now)
                self._ai_schedule_state['next_run_at'] = due.isoformat(timespec='seconds') if due else None
                self._persist_schedule()
            return due

    @staticmethod
    def _revision(config):
        return config.get('revision', config.get('generation'))

    def config_changed(self, schedule_only=False):
        """Refresh public research now; a schedule-only save waits for its next slot."""
        with self._lock:
            if self._stop.is_set():
                return False
            if schedule_only:
                config = self._configuration()
                setting = schedule_settings(config)
                now = datetime.now(CHINA)
                # A changed plan never creates an immediate paid request. For
                # an open repeating window also waits one full interval;
                # outside it, wait for the next daily opening instead.
                after_run = (setting['mode'] == 'interval' or
                             setting['mode'] == 'scheduled_interval' and setting.get('end_time') is not None)
                due = scheduled_time(setting, now, after_run=after_run) if config.get('enabled') and config.get('key') else None
                self._ai_schedule_state = {
                    'signature': schedule_signature(config),
                    'next_run_at': due.isoformat(timespec='seconds') if due else None,
                }
            else:
                # Credential/model/enable changes retain the existing behavior:
                # a newly enabled interval plan may run on the next scan.
                self._ai_schedule_state = {}
            self._persist_schedule()
            self._pending_scan = True
            self._state['next_run_at'] = now_iso()
            self._wake.set()
        self.start()
        return True

    def request_scan(self, refresh=False, public_only=False):
        with self._lock:
            if self._stop.is_set() or (self._worker and self._worker.is_alive()):
                return False
            self._state.update(status='running', stage='正在启动自动研究', started_at=now_iso(),
                               next_run_at=None, error=None, progress={})
            self._pending_scan = False
            self._last_public_attempt = datetime.now(CHINA)
            last_report = self._state.get('report') or {}
            previous = copy.deepcopy(last_report.get('strategy'))
            if self.research_scope == 'sectors':
                previous = previous if isinstance(previous, dict) else {}
                previous['_public_only'] = bool(public_only and not refresh)
                previous['_public_report'] = copy.deepcopy({k:last_report[k] for k in
                    ('as_of','company_evidence','company_evidence_as_of','_quote_histories','sector_analysis',
                     'snapshot','event_candidates','event_analysis','ai_research') if k in last_report})
                event = last_report.get('event_analysis', {})
                if isinstance(event, dict) and event.get('status') in ('completed', 'partial'):
                    previous['sector_context'] = {'event_analysis': copy.deepcopy(event)}
            if isinstance(previous, dict) and self.research_scope != 'sectors':
                # Coverage travels only with this next scan's context, leaving
                # the persisted strategy and its market history unchanged.
                previous['research_snapshot'] = copy.deepcopy(last_report.get('snapshot', {}))
                previous['holdings_index'] = copy.deepcopy(last_report.get('holdings_index', []))
                previous['holdings_check_ledger'] = copy.deepcopy(last_report.get('holdings_check_ledger', {}))
                previous['dynamic_board_registry'] = copy.deepcopy(last_report.get('dynamic_board_registry', []))
                previous['board_coverage'] = enrich_board_diagnostics(
                    last_report.get('board_coverage', []), last_report.get('snapshot', {}), last_report.get('quant', []))
            config = self._configuration()
            # Anchor a fixed start before collection so a scan spanning that
            # minute can still run AI after obtaining its fresh evidence.
            self._ai_due(config)
            self._worker = threading.Thread(target=self._run, args=(previous, refresh, config, public_only),
                                            name='fundpilot-auto-scan', daemon=True)
            self._worker.start()
            return True

    def _progress(self, stage, details=None):
        with self._lock:
            self._state.update(stage=stage, progress=details or {})

    def _run(self, previous, refresh, config, public_only=False):
        try:
            report = self.runner(progress=self._progress, previous=previous, refresh=refresh)
            if self.research_scope == 'sectors' and (report.get('research_scope') != 'sectors'
                                                     or not isinstance(report.get('sector_analysis'), list)):
                raise ValueError('板块研究器返回了不兼容的报告')
            revision = self._revision(config)
            def is_current():
                latest = self._configuration()
                return (not self._stop.is_set() and self._revision(latest) == revision
                        and bool(latest.get('enabled', True)) == bool(config.get('enabled', True)))
            baseline = report
            ai_config = config
            blocked = config.get('key') and revision is not None and revision == self._blocked_ai_revision
            current = is_current()
            due = self._ai_due(config) if current else None
            setting = schedule_settings(config)
            admitted_at = datetime.now(CHINA)
            stop_at = schedule_stop_time(setting, admitted_at)
            def can_start_request():
                now = datetime.now(CHINA)
                # Keep this batch tied to the window in which its evidence was
                # collected, even if a very slow upstream returns the next day.
                return (not public_only and is_current() and schedule_allows_run(setting, now)
                        and (stop_at is None or now < stop_at))
            scheduled = bool(config.get('enabled') and config.get('key') and current and not blocked
                             and (public_only or due is None or not schedule_allows_run(setting, admitted_at)
                                                       or due > admitted_at))
            if public_only or blocked or scheduled or not current:
                ai_config = {**config, 'enabled': False}
            elif config.get('enabled') and config.get('key'):
                # Reserve this slot durably before any paid call. A process
                # restart during an upstream request must not replay that slot.
                with self._lock:
                    if is_current():
                        reserved = scheduled_time(schedule_settings(config), datetime.now(CHINA), after_run=True)
                        self._ai_schedule_state = {'signature': schedule_signature(config),
                                                   'next_run_at': reserved.isoformat(timespec='seconds') if reserved else None}
                        self._persist_schedule()
                    else:
                        ai_config = {**config, 'enabled': False}
            if self._ai_cost_guard is not None:
                # Runtime objects never enter public configuration or reports.
                # Read current limits for each request, including changes made
                # while a previously admitted research round is still running.
                ai_config = {**ai_config, '_cost_guard': self._ai_cost_guard,
                             '_evidence_cache': self._ai_evidence_cache,
                             '_cost_config_provider': self._configuration}
            report = self.ai_runner(report, config=ai_config, progress=self._progress,
                                    is_current=is_current, can_start_request=can_start_request)
            ai = report.get('ai_research', {})
            if self._ai_cost_guard is not None and isinstance(ai, dict):
                # Future archive restores must not import requests already
                # recorded transactionally by this runtime.
                ai['cost_ledger_recorded'] = True
            if self.research_scope == 'sectors' and (public_only or scheduled) and current:
                from research_live_update import retain_interpretations
                retain_interpretations(report, (previous or {}).get('_public_report', {}), config)
                ai = report.setdefault('ai_research', ai)
                report.setdefault('automatic', {}).update(public_refresh=True, interval_seconds=300,
                    paid_api_calls=False, paid_api_call_count=0)
            if scheduled:
                ai.update(status='scheduled', configuration_enabled=True, error='',
                          next_run_at=due.isoformat(timespec='seconds') if due else None, schedule=schedule_settings(config))
            if public_only:
                ai.update(configuration_enabled=bool(config.get('enabled', True)), revision=revision,
                          public_refresh=True)
            if blocked:
                ai.update(status='error', terminal_error=True, blocked_until_config_change=True,
                          error='上次身份验证或余额检查失败；自动 AI 已暂停，请修复配置后重新启用。')
            if not is_current():
                # Cover the final commit race after a completed AI batch.
                discarded = copy.deepcopy(baseline)
                discarded['ai_research'] = ai
                discarded['ai_research'].update(status='superseded', analyzed_count=0, analyzed_codes=[],
                                                error='AI 配置已更改，旧配置解读已丢弃，等待自动重研。')
                if self.research_scope == 'sectors':
                    discarded['ai_research']['analyzed_sector_ids'] = []
                discarded['automatic'] = report.get('automatic', {})
                report = discarded
            elif ai.get('terminal_error'):
                self._blocked_ai_revision = revision
            if is_current() and config.get('enabled') and config.get('key') and not public_only and not scheduled and not blocked:
                with self._lock:
                    if is_current():
                        next_due = scheduled_time(schedule_settings(config), datetime.now(CHINA), after_run=True)
                        self._ai_schedule_state = {'signature': schedule_signature(config),
                                                   'next_run_at': next_due.isoformat(timespec='seconds') if next_due else None}
                        self._persist_schedule()
            if self.research_scope != 'sectors':
                _mark_forced_discovery_searches(report.get('board_coverage', []))
                forced_discovery = _forced_discovery_references(None, report.get('board_coverage', []))
                report['candidate_references'] = _merge_reference_rows(report.get('candidate_references', []), forced_discovery)
                apply_board_holdings_gate(report.get('snapshot', {}), report.get('quant', []),
                                          report.get('analysis', {}), report.get('strategy', {}))
                report['sections'] = build_sections(report.get('snapshot', {}), report.get('quant', []),
                                                    report.get('analysis', {}), report.get('strategy'),
                                                    references=report.get('candidate_references', []),
                                                    reference_catalog=report.get('snapshot', {}).get('funds', []))
            completed = now_iso()
            try:
                self._persist(report, completed)
            except OSError:
                report['snapshot']['warnings'].append('本地报告保存失败；当前结果仍可查看，下轮自动重试。')
            with self._lock:
                self._state.update(status='ready', stage='自动研究完成', report=report, completed_at=completed,
                                   error=None, restored=False,
                                   next_run_at=(datetime.now(CHINA) + timedelta(seconds=self.interval)).isoformat(timespec='seconds'))
        except Exception:
            with self._lock:
                self._state.update(status='error', stage='本轮研究失败，等待自动重试',
                                   error='本轮自动数据处理未完成，旧报告仅供回看，系统将在 5 分钟后自动重试。')

    def _report_is_stale(self, state):
        stale = bool(state.get('restored')) or state['status'] == 'error'
        if state.get('report'):
            try:
                age = (datetime.now(CHINA) - datetime.fromisoformat(state['completed_at'])).total_seconds()
                setting = schedule_settings(self._configuration())
                if self.research_scope == 'sectors' and setting['mode'] == 'market_sessions':
                    from research_live_schedule import next_quote_time
                    completed = datetime.fromisoformat(state['completed_at'])
                    next_slot = next_quote_time(completed, completed)
                    stale = stale or (datetime.now(CHINA) >= next_slot + timedelta(minutes=10) if next_slot else age > 86400)
                else:
                    stale = stale or age > max(self.interval * 2, 3600)
            except (ValueError, TypeError):
                stale = True
        return stale

    def review_histories(self, report_as_of):
        """Internal-only dated price evidence; excluded from public report APIs."""
        with self._lock:
            source = self._state.get('report') or {}
            if source.get('as_of') != report_as_of:
                return None
            histories = source.get('_quote_histories') or {}
        return copy.deepcopy(histories)

    def status(self, include_report=True):
        """Poll metadata without copying portfolios or acquiring the catalog lock.

        Published raw reports are immutable. A single-flight view cache upgrades
        them once per report/configuration/freshness change, outside _lock so a
        slow first report request cannot block the progress heartbeat.
        """
        current_config = self._configuration()
        due = self._ai_due(current_config)
        with self._lock:
            source = self._state.get('report')
            result = copy.deepcopy({key: value for key, value in self._state.items() if key != 'report'})
        stale = self._report_is_stale({**result, 'report': source})
        version = hashlib.sha256(json.dumps([
            id(source), result.get('completed_at'), stale, SCHEMA_VERSION, HOLDINGS_RULE_VERSION,
            self._revision(current_config), bool(current_config.get('enabled', True)),
            current_config.get('model'), schedule_settings(current_config)
        ], sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:24] if source else None
        result.update(report=None, has_report=bool(source), report_version=version, report_stale=stale,
                      ai_schedule=schedule_settings(current_config),
                      ai_calendar=calendar_status(),
                      ai_next_run_at=due.isoformat(timespec='seconds') if due else None)
        if self.research_scope == 'sectors':
            from research_live_schedule import next_quote_time, presentation
            now = datetime.now(CHINA)
            public_due = next_quote_time(now, self._last_public_attempt)
            market_status, label = presentation(now)
            result['public_refresh'] = {'interval_seconds':300, 'market_status':market_status, 'label':label,
                'next_run_at':public_due.isoformat(timespec='seconds') if public_due else None,
                'completed_at':result.get('completed_at'), 'running':result.get('status') == 'running',
                'provider_tokens':0, 'paid_ai_schedule':'09:20 / 14:50',
                'company_evidence_as_of':(source or {}).get('company_evidence_as_of')}
        if self._ai_cost_guard is not None:
            result['ai_cost'] = self._ai_cost_guard.summary(current_config)
        if source and isinstance(source.get('ai_research'), dict):
            ai = copy.deepcopy(source['ai_research'])
            changed = (ai.get('revision') != self._revision(current_config)
                       or ai.get('configuration_enabled', True) != bool(current_config.get('enabled', True)))
            if stale or changed:
                ai.update(previous_status=ai.get('status'), status='stale',
                          stale_reason='AI 配置已更改，等待按新配置重新研究。' if changed else
                          '历史 AI 解读仅供回看，等待本轮自动更新。')
            result['ai_research'] = ai
        if not include_report or not source:
            return result
        with self._report_view_lock:
            if version != self._report_view_version:
                # Internal scheduling evidence is never copied into a public view.
                result['report'] = copy.deepcopy({key: value for key, value in source.items()
                                                 if key not in ('holdings_index', 'holdings_check_ledger', '_quote_histories')})
                if self.research_scope == 'sectors':
                    self._render_status(result, current_config, due)
                else:
                    with board_catalog_scope(source.get('dynamic_board_registry', []),
                                             source.get('snapshot', {}).get('as_of') or now_iso()):
                        self._render_status(result, current_config, due)
                self._report_view = result['report']
                self._report_view_version = version
                self._report_view_source = source
            result['report'] = copy.deepcopy(self._report_view)
        return result

    def _render_status(self, result, current_config, due):
        if self.research_scope == 'sectors':
            return self._render_sector_status(result, current_config, due)
        result['ai_schedule'] = schedule_settings(current_config)
        result['ai_next_run_at'] = due.isoformat(timespec='seconds') if due else None
        report = result.get('report')
        stale = self._report_is_stale(result)
        result['report_stale'] = stale
        if report and isinstance(report.get('ai_research'), dict):
            ai = report['ai_research']
            latest_config = self._configuration()
            changed = (ai.get('revision') != self._revision(latest_config)
                       or ai.get('configuration_enabled', True) != bool(latest_config.get('enabled', True)))
            if stale or changed:
                ai['previous_status'] = ai.get('status')
                ai['status'] = 'stale'
                ai['stale_reason'] = ('AI 配置已更改，等待按新配置重新研究。' if changed else
                                      '历史 AI 解读仅供回看，等待本轮自动更新。')
                for fund in report.get('analysis', {}).get('funds', []):
                    if fund.get('ai_research_status'):
                        fund['ai_research_status'] = 'stale'
                if changed:
                    # A changed key/model must not display old narratives as
                    # current output from the replacement configuration.
                    analysis = report.get('analysis', {})
                    for key, marker in [('summary', '\nAI 市场概括：'), ('market_view', '\nAI 证据解读：')]:
                        if isinstance(analysis.get(key), str):
                            analysis[key] = analysis[key].split(marker, 1)[0]
                    analysis.pop('ai_summary', None)
                    analysis.pop('ai_market_view', None)
                    for fund in analysis.get('funds', []):
                        for key, marker in [('reason', '\nAI 证据解读：'), ('invalidation', '\nAI 复查条件：')]:
                            if isinstance(fund.get(key), str):
                                fund[key] = fund[key].split(marker, 1)[0]
                        fund.pop('ai_reason', None)
                        fund.pop('ai_invalidation', None)
                        fund.get('operation_plan', {}).pop('ai_observations', None)
        if report and stale:
            report['strategy']['regime'] = {'mode': 'unknown', 'label': '等待新数据', 'reason': '上次报告已过期或本轮采集失败，暂停新增候选。'}
            report['strategy']['candidates'] = []
            report['strategy']['panic'].update(score=None, label='待更新', summary='上次研究仅供回看，当前行情风险等待自动更新。')
            report['strategy']['panic']['stress_override'] = {'active': False, 'reason': '', 'rule': '上次状态仅供回看'}
            report['analysis'] = enforce_strategy(report['analysis'], report['strategy'])
        if report:
            if 'market_overview' not in report:
                report['market_overview'] = build_market_overview({}, report.get('snapshot', {}))
            report['source_connections'] = copy.deepcopy(SOURCE_CONNECTIONS)
            report.setdefault('automatic', {}).update(per_board_deep_limit=MAX_RESEARCH_PER_BOARD,
                                                       per_board_display_limit=MAX_DISPLAY_PER_BOARD)
            # Rebuild after stale-state restrictions, and upgrade older saved
            # reports without re-fetching or discarding their full evidence.
            if report.get('board_schema_version') != SCHEMA_VERSION:
                ai = report.get('ai_research')
                if isinstance(ai, dict) and (ai.get('status') in ('completed', 'partial') or ai.get('analyzed_count', 0)):
                    ai.update(status='stale', stale_reason='板块归属已切换为独立持仓核验；旧 AI 板块解读等待新一轮证据研究。')
                for fund in report.get('analysis', {}).get('funds', []):
                    fund['ai_research_status'] = 'stale'
                    fund.pop('ai_reason', None)
                    fund.pop('ai_invalidation', None)
                    for key, marker in [('reason', '\nAI 证据解读：'), ('invalidation', '\nAI 复查条件：')]:
                        if isinstance(fund.get(key), str):
                            fund[key] = fund[key].split(marker, 1)[0]
                    fund.get('operation_plan', {}).pop('ai_observations', None)
            _mark_forced_discovery_searches(report.get('board_coverage', []))
            forced_discovery = _forced_discovery_references(None, report.get('board_coverage', []))
            report['candidate_references'] = _merge_reference_rows(report.get('candidate_references', []), forced_discovery)
            apply_board_holdings_gate(report.get('snapshot', {}), report.get('quant', []),
                                      report.get('analysis', {}), report.get('strategy', {}))
            report['sections'] = build_sections(report.get('snapshot', {}), report.get('quant', []),
                                                report.get('analysis', {}), report.get('strategy'),
                                                references=report.get('candidate_references', []),
                                                reference_catalog=report.get('snapshot', {}).get('funds', []))
            displayed = {s['id']: s for s in report['sections']}
            if report.get('board_schema_version') != SCHEMA_VERSION:
                old_coverage = report.get('board_coverage', [])
                saved_codes = report.get('universe', {}).get('selected_codes') or [f.get('code') for f in report.get('snapshot', {}).get('funds', []) if f.get('code')]
                report['board_coverage'] = build_board_coverage({}, saved_codes, report.get('snapshot', {}), report.get('quant', []), report['sections'])
                _attach_web_discovery(report['board_coverage'], {'boards': []}, old_coverage, [])
                report['board_schema_version'] = SCHEMA_VERSION
                report.setdefault('universe', {}).setdefault('coverage', {})['board_classification_method'] = 'disclosed_holdings'
            if report.get('holdings_rule_version') != HOLDINGS_RULE_VERSION:
                saved_codes = report.get('universe', {}).get('selected_codes') or [
                    fund.get('code') for fund in report.get('snapshot', {}).get('funds', []) if fund.get('code')]
                report['board_coverage'] = _refresh_holdings_coverage(
                    report.get('board_coverage', []), saved_codes, report.get('snapshot', {}),
                    report.get('quant', []), report['sections'])
                report['holdings_rule_version'] = HOLDINGS_RULE_VERSION
            for board in report.get('board_coverage', []):
                funds = displayed.get(board['id'], {}).get('funds', [])
                board['displayed_count'] = len(funds)
                board['candidate_count'] = sum(f.get('role') == 'candidate' for f in funds)
                if funds:
                    board['status'] = 'candidate' if board['candidate_count'] else 'observation'
                    board['reason'] = '旧报告仅供回看，等待新数据。' if stale else '每板块最多展示三只；观察不等于买入。'
            report['board_coverage'] = enrich_board_diagnostics(
                report.get('board_coverage', []), report.get('snapshot', {}), report.get('quant', []))
            displayed_members = {(fund['code'], section['id']) for section in report['sections']
                                 for fund in section.get('funds', [])}
            for reference in report.get('candidate_references', []):
                if reference.get('forced_selection') or reference.get('source_kind') == 'web_discovery':
                    in_cards = (reference.get('code'), reference.get('requested_board_id')) in displayed_members
                    reference['status'] = 'forced_displayed' if in_cards else 'forced_pending'
                    reference['reason'] = ('已强制纳入该板块' + ('主卡片' if in_cards else '来源基金清单（主卡片最多三只）')
                                           + '；未知数据标记为 *****，后续自动研究继续核验。')
            attach_reference_candidates(report['board_coverage'], report.get('candidate_references', []))
            coverage = report.get('universe', {}).get('coverage')
            if isinstance(coverage, dict):
                coverage.update(board_count=len(report['board_coverage']),
                                researched_board_count=sum(isinstance(board.get('deep_count'), (int, float))
                                                           and board['deep_count'] > 0 for board in report['board_coverage']),
                                displayed_board_count=len(report['sections']))
        if report:
            # The persistent discovery index is server-side scheduling state,
            # not client-facing research evidence for thousands of portfolios.
            report.pop('holdings_index', None)
            report.pop('holdings_check_ledger', None)
        return result

    def _render_sector_status(self, result, current_config, due):
        """Publish sector evidence directly, without any fund classification."""
        report = result.get('report')
        if not report:
            return result
        stale = self._report_is_stale(result)
        result['report_stale'] = stale
        report['market_sentiment'] = build_market_sentiment(report)
        report['market_liquidity'] = build_market_liquidity(report)
        ai = report.get('ai_research', {})
        latest_config = self._configuration()
        changed = (ai.get('revision') != self._revision(latest_config)
                   or ai.get('configuration_enabled', True) != bool(latest_config.get('enabled', True)))
        if ai and (stale or changed):
            ai.update(previous_status=ai.get('status'), status='stale',
                      stale_reason='AI 配置已更改，等待板块重新研究。' if changed else '历史板块解读等待更新。')
            if changed:
                ai.update(analyzed_count=0, analyzed_sector_ids=[])
        event = report.get('event_analysis')
        if isinstance(event, dict) and (stale or changed):
            event['status'] = 'stale'
            for item in event.get('events', []):
                item.update(severity='normal', signal='neutral', indicator_reason='')
            if changed:
                event['events'] = []
        for sector in report.get('sector_analysis', []):
            if changed:
                for key in ('ai_reason', 'ai_risks', 'ai_invalidation', 'ai_advice', 'evidence_ids', 'ai_variants'):
                    sector.pop(key, None)
            if stale or changed:
                if sector.get('ai_research_status'):
                    sector['ai_research_status'] = 'stale'
                for variant in sector.get('ai_variants', {}).values():
                    variant['ai_research_status'] = 'stale'
            if stale:
                sector.update(recommendation_index=None, score=None, status='stale',
                              action='等待最新板块数据', severity='normal', signal='neutral', indicator_reason='')
        if stale:
            report['market_sentiment'].update(
                score=None, status='stale', label='待更新',
                summary='历史快照，当前市场情绪等待最新数据。')
            for component in report['market_sentiment'].get('components', []):
                component.update(score=None, status='stale')
            report['market_liquidity'].update(
                score=None, risk_score=None, status='stale', label='待更新',
                summary='历史快照，当前市场流动性等待最新数据。')
            report.setdefault('strategy', {})['regime'] = {
                'mode': 'unknown', 'label': '等待新数据', 'reason': '上次板块报告已过期，等待自动更新。'}
            report['strategy'].setdefault('panic', {}).update(
                score=None, label='待更新', summary='历史数据仅供回看，当前市场压力等待重新计算。')
        return result

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._ai_runtime_directory and not (self._worker and self._worker.is_alive()):
            self._ai_runtime_directory.cleanup()

