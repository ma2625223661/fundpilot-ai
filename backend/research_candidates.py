"""User-supplied discovery references, separate from portfolio evidence."""
import copy
import json
import re
from pathlib import Path

from research_categories import BOARDS, board_for
from research_holdings import verify_board
from research_selection import _classify

REFERENCE_PATH = Path(__file__).resolve().parent.parent / 'config' / 'board-candidates.json'


def load_candidate_references(path=None):
    """Reference membership supplies codes and a board, never holdings."""
    path = Path(path) if path is not None else REFERENCE_PATH
    try:
        if path.stat().st_size > 1_000_000:
            return []
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(saved, dict) or not isinstance(saved.get('candidates'), list):
        return []
    result, seen = [], set()
    for item in saved['candidates'][:2000]:
        if not isinstance(item, dict):
            continue
        code, board_id = item.get('code'), item.get('requested_board_id')
        identity = (code, board_id)
        if (not isinstance(code, str) or not re.fullmatch(r'\d{6}', code)
                or item.get('source_kind') not in ('user_reference', 'yangjibao')
                or not isinstance(board_id, str) or identity in seen):
            continue
        seen.add(identity)
        result.append({key: copy.deepcopy(item[key]) for key in
                       ('code', 'requested_board_id', 'source_kind', 'source_label',
                        'reference_image', 'source_index', 'display_order', 'direct_selection', 'added_on') if key in item})
    return result


def prepare_reference_candidates(universe, references):
    """Prefer eligible reference members; fund titles never decide a board."""
    rows = {row.get('code'): row for row in universe.get('funds', []) if isinstance(row, dict)}
    preferred = []
    for reference in references:
        row = rows.get(reference['code'])
        if row is not None:
            row['reference_candidate'] = copy.deepcopy(reference)
            if row.get('eligible') and reference['requested_board_id'] in BOARDS:
                preferred.append(reference['code'])
    return list(dict.fromkeys(preferred))


def build_reference_candidates(references, universe, snapshot, sections, selected_codes):
    """Explain each requested destination using the same measured holdings gate."""
    rows = {row.get('code'): row for row in universe.get('funds', []) if isinstance(row, dict)}
    researched = {row.get('code'): row for row in snapshot.get('funds', []) if isinstance(row, dict)}
    displayed = {(fund['code'], section['id']) for section in sections for fund in section.get('funds', [])}
    selected = set(selected_codes)
    as_of = snapshot.get('as_of') or universe.get('as_of')
    result = []
    for reference in references:
        code, requested = reference['code'], reference['requested_board_id']
        forced_discovery = bool(reference.get('forced_selection') or reference.get('source_kind') == 'web_discovery')
        catalog = rows.get(code)
        fund = {**(catalog or {}), **researched.get(code, {})}
        board = board_for(fund, _classify(fund, {})[0], as_of=as_of)
        match = verify_board(fund, requested, as_of=as_of) if requested in BOARDS else {}
        item = {**copy.deepcopy(reference), 'name': fund.get('name') or reference.get('name') or code,
                'requested_board_label': BOARDS.get(requested, {}).get('label', requested),
                'actual_board_id': board['id'], 'actual_board_label': board['label'],
                'matched_disclosed_pct': match.get('matched_disclosed_pct'),
                'matched_weight_pct': match.get('matched_weight_pct'),
                'disclosed_weight_pct': match.get('disclosed_weight_pct'),
                'ratio_is_lower_bound': bool(match.get('ratio_is_lower_bound')),
                'report_date': match.get('report_date'), 'checked_at': as_of,
                'source_url': f'https://fund.eastmoney.com/{code}.html',
                'holdings_source_url': match.get('source_url'),
                'evidence_note': (('互联网搜索候选先强制纳入指定板块；比例根据有报告期的公开股票持仓计算，不代表全仓或实时仓位。'
                                  if forced_discovery else
                                  '按养基宝板块分类收录；比例根据有报告期的公开股票持仓计算，不代表全仓或实时仓位.'))}
        if requested not in BOARDS:
            status, reason = 'board_missing', '目标方向尚无可核验的板块规则，继续收集行业证据。'
        elif catalog is None:
            status, reason = 'not_in_catalog', '本轮公开基金目录未取得该代码，保留板块基金继续核验。'
        elif not catalog.get('eligible'):
            status, reason = 'excluded', '未通过本轮初筛：' + ('；'.join(catalog.get('exclusion_reasons', [])) or '资料条件不足')
        elif board['id'] != 'holdings_unclassified' and board['id'] != requested:
            status, reason = 'reclassified', '当前归入' + board['label'] + '；板块分类与真实持仓匹配比例分别记录。'
        elif match.get('status') != 'matched':
            status, reason = 'holdings_pending', match.get('reason') or '仍须取得有效的股票持仓与行业证据。'
        elif (code, requested) in displayed:
            status, reason = 'displayed', '持仓匹配已核验，已进入本轮板块展示；操作状态另按风险条件判断。'
        elif code in researched or code in selected:
            status, reason = 'researched', '已纳入净值与风险研究；每板块按匹配比例优先，最多展示三只。'
        else:
            status, reason = 'holdings_verified', '持仓匹配已核验，继续按板块比例和研究预算筛选。'
        if forced_discovery:
            status = 'forced_displayed' if (code, requested) in displayed else 'forced_pending'
            reason = ('公开搜索候选已强制纳入该板块并展示；真实净值、风险、持仓匹配比例和支付宝可购资格仍在自动核验。'
                      if (code, requested) in displayed else
                      '公开搜索候选已强制纳入该板块清单；等待自动核验后补充真实指标。')
        item.update(status=status, reason=reason)
        result.append(item)
    return result


def attach_reference_candidates(coverage, references):
    for board in coverage:
        entries = [copy.deepcopy(item) for item in references
                   if item.get('requested_board_id') == board.get('id')]
        if entries:
            board['reference_candidates'] = entries

