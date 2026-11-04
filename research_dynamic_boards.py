"""Discover missing industries from sourced, disclosed stock classifications.

This module does no I/O and never classifies a security or fund from its name.
Plain provider concept/trading tags are deliberately insufficient to create an
industry.  Collectors must supply ``industry_tags`` with a classification URL,
or individual ``tag_evidence`` records explicitly marked ``kind='industry'``.
"""
import copy
import hashlib
import math
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

MAX_NEW_BOARDS = 24
MAX_REGISTRY_BOARDS = 128
MAX_DISCLOSURE_AGE_DAYS = 180
MAX_EVIDENCE_FUNDS = 8
RULE_VERSION = 'sourced_disclosed_industry_majority_v1'

# Even a wrongly labelled upstream "industry" must not create these channels,
# index memberships, financing statuses, corporate events, or market styles.
_NON_INDUSTRY = re.compile(
    r'融资融券|融资标的|融券标的|沪股通|深股通|港股通|陆股通|沪深股通|'
    r'沪港通|深港通|互联互通|北向|南向|QFII|RQFII|MSCI|富时罗素|'
    r'成份|成分|指数|ETF|基金重仓|机构重仓|社保重仓|证金持股|'
    r'业绩|预增|预减|预盈|预亏|扭亏|重组|举牌|回购|增持|减持|'
    r'股权转让|股权激励|高送转|送转|分红|红利|高股息|'
    r'退市|次新|新股|涨停|跌停|连板|昨日|破净|低估值|百元股|'
    r'沪深\d+|中证\d+|上证\d+|深证\d+|(?:^|[^A-Z])\*?ST(?:$|[^A-Z])', re.I)
_SECURITY_CODE = re.compile(r'\d{5,6}|[A-Z][A-Z0-9.\-]{0,11}')
_NONSTOCK_TYPES = {'fund', 'etf', 'bond', 'cash', 'trust', 'derivative'}


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return ''
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ''
    return value if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username else ''


def _tag(value):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'\s+', ' ', value).strip()
    if not 1 < len(value) <= 40 or re.search(r'[<>\r\n]', value) or _NON_INDUSTRY.search(value):
        return ''
    return value


def _industry_label_key(value):
    # Provider level suffixes on the same Chinese industry name are display
    # variants, not a newly discovered line of business. Never stem words or
    # treat an unrelated child industry as its broader parent.
    return re.sub(r'[ⅠⅡⅢⅣⅤ]+$', '', value).strip().casefold()


def _depth(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10 else 1


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return Decimal(str(value))


def _limit(value, cap):
    return max(0, min(value, cap)) if isinstance(value, int) and not isinstance(value, bool) else cap


def _registry_entries(registry):
    if isinstance(registry, dict):
        registry = registry.get('boards', [])
    return [entry for entry in (registry or []) if isinstance(entry, dict)] if isinstance(registry, (list, tuple)) else []


def _existing_tags(existing_board_tags, registry):
    result = set()
    values = existing_board_tags.values() if isinstance(existing_board_tags, dict) else (existing_board_tags or [])
    for value in values:
        if isinstance(value, dict):
            value = value.get('tags', [])
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple, set, frozenset)):
            result.update(tag for tag in value if isinstance(tag, str))
    for entry in _registry_entries(registry):
        tags = entry.get('tags', [])
        if isinstance(tags, list):
            result.update(tag for tag in tags if isinstance(tag, str))
    return result


def _industry_evidence(row):
    """Keep only classifications whose collector identified an industry field."""
    if row.get('tag_status') != 'ok':
        return {}
    candidates = []
    raw_evidence = row.get('tag_evidence', [])
    if isinstance(raw_evidence, list):
        for item in raw_evidence[:120]:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get('tags'), list):
                candidates.extend({**item, 'tag': tag} for tag in item['tags'][:120])
            else:
                candidates.append(item)
    industry_tags = row.get('industry_tags', [])
    if isinstance(industry_tags, list):
        for item in industry_tags[:120]:
            if isinstance(item, str):
                candidates.append({'tag': item, 'kind': 'industry',
                    'source_url': row.get('industry_source_url') or row.get('tag_source_url'),
                    'source_field': row.get('industry_source_field', ''),
                    'hierarchy_depth': row.get('industry_level', 1)})
            elif isinstance(item, dict):
                candidates.append({**item, 'kind': item.get('kind', 'industry')})
    result = {}
    for item in candidates:
        if item.get('kind') != 'industry':
            continue
        label = _tag(item.get('tag'))
        source_url = _url(item.get('source_url'))
        identity = str(item.get('security_code', row.get('code', '')))
        if not label or not source_url or identity != str(row.get('code', '')):
            continue
        detail = {'tag': label, 'kind': 'industry', 'source_url': source_url,
                  'source_field': str(item.get('source_field') or '')[:80],
                  'hierarchy_depth': _depth(item.get('hierarchy_depth', item.get('level', 1)))}
        if label not in result or detail['hierarchy_depth'] > result[label]['hierarchy_depth']:
            result[label] = detail
    return result


def _validated_portfolio(fund, as_of):
    if not isinstance(fund, dict) or not re.fullmatch(r'\d{6}', str(fund.get('code', ''))):
        return None
    holdings = fund.get('holdings')
    if not isinstance(holdings, dict) or holdings.get('status') != 'ok' or holdings.get('invalid_row_count'):
        return None
    try:
        report_day = _day(holdings.get('report_date'))
        if not 0 <= (as_of - report_day).days <= MAX_DISCLOSURE_AGE_DAYS:
            return None
    except (ValueError, TypeError):
        return None
    if not _url(holdings.get('source_url')):
        return None
    from research_holdings import holdings_row_limit
    rows = holdings.get('rows')
    if not isinstance(rows, list) or not rows or len(rows) > holdings_row_limit(holdings):
        return None
    stocks, seen, total = [], set(), Decimal(0)
    for row in rows:
        if not isinstance(row, dict):
            return None
        if isinstance(row.get('instrument_type'), str) and row['instrument_type'] in _NONSTOCK_TYPES:
            continue
        if row.get('instrument_type') != 'stock':
            return None
        code, weight = str(row.get('code', '')), row.get('weight_pct')
        if not _SECURITY_CODE.fullmatch(code) or code in seen:
            return None
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 < weight <= 100:
            return None
        seen.add(code)
        exact_weight = Decimal(str(weight))
        total += exact_weight
        stocks.append((row, exact_weight, _industry_evidence(row)))
    if not 0 < total <= 101:
        return None
    return holdings, report_day.isoformat(), stocks, total


def discover_dynamic_boards(funds, existing_board_tags, as_of, *, limit=MAX_NEW_BOARDS, registry=None):
    """Return at most 24 new industries and bounded updates to registered ones.

    ``existing_board_tags`` accepts the existing ``board_id -> set[str]`` map.
    Existing standalone tags suppress duplicate proposals; callers should pass
    dedicated board coverage rather than all evidence tags of broad parents.
    Roman industry-level display suffixes do not create duplicate directions.
    Unknown classifications remain in the stock-weight denominator, so the
    reported match may be a confirmed lower bound.  More than 50%, calculated
    before rounding, is required.  No minimum 75% rule or fund-name inference is
    applied. ``registry`` may be a list of prior definitions or ``{'boards':...}``.
    The inputs are never mutated, and the caller owns persistence/registration.
    """
    try:
        as_of_day = _day(as_of)
    except (ValueError, TypeError):
        return []
    count = _limit(limit, MAX_NEW_BOARDS)
    if not isinstance(funds, (list, tuple)):
        return []
    registered = merge_dynamic_board_registry([], registry, as_of_day)
    registered_by_tag = {entry['tags'][0]: entry for entry in registered}
    registered_labels = {_industry_label_key(tag) for tag in registered_by_tag}
    if not count and not registered:
        return []
    existing_tags = _existing_tags(existing_board_tags, registered)
    existing_labels = {_industry_label_key(tag) for tag in existing_tags}
    proposals = {}
    for fund in funds:
        portfolio = _validated_portfolio(fund, as_of_day)
        if portfolio is None:
            continue
        holdings, report_date, stocks, total = portfolio
        tags = {tag for _, _, classifications in stocks for tag in classifications
                if _industry_label_key(tag) not in existing_labels or tag in registered_by_tag}
        known = sum((weight for _, weight, classifications in stocks if classifications), Decimal(0))
        for tag in sorted(tags):
            matched = [(row, weight, classifications[tag]) for row, weight, classifications in stocks if tag in classifications]
            weight = sum((item[1] for item in matched), Decimal(0))
            if weight * 100 <= total * 50:
                continue
            ratio = weight / total * 100
            depth = max(item[2]['hierarchy_depth'] for item in matched)
            evidence = {'fund_code': str(fund['code']), 'fund_name': str(fund.get('name') or fund['code']),
                'report_date': report_date, 'source_url': holdings['source_url'],
                'matched_weight_pct': float(weight), 'disclosed_weight_pct': float(total),
                'matched_disclosed_pct': float(ratio),
                'coverage_pct': float(known / total * 100),
                'ratio_is_lower_bound': known < total,
                'unclassified_disclosed_pct': float((total - known) / total * 100),
                'classification_sources': sorted({item[2]['source_url'] for item in matched}),
                'stock_evidence': [{'code': str(row['code']), 'name': str(row.get('name') or row['code']),
                    'nav_weight_pct': float(stock_weight),
                    'disclosed_stock_weight_pct': float(stock_weight / total * 100),
                    **classification} for row, stock_weight, classification in matched],
                'scope': '占已披露股票持仓的比例；仅代表已披露部分，不代表实时总仓位或行业业务收入占比'}
            if isinstance(holdings.get('lookthrough'), dict):
                evidence['lookthrough'] = copy.deepcopy(holdings['lookthrough'])
            proposal = proposals.setdefault(tag, {'tag': tag, 'depth': depth, 'best_ratio': ratio, 'evidence': {}})
            proposal['depth'] = max(proposal['depth'], depth)
            proposal['best_ratio'] = max(proposal['best_ratio'], ratio)
            key = (str(fund['code']), report_date)
            proposal['evidence'].setdefault(key, evidence)
    ordered = sorted(proposals.values(), key=lambda item: (-item['best_ratio'], -item['depth'], -len(item['evidence']), item['tag']))
    updates = [item for item in ordered if item['tag'] in registered_by_tag][:MAX_REGISTRY_BOARDS]
    additions, accepted_labels = [], set(registered_labels)
    for item in ordered:
        label_key = _industry_label_key(item['tag'])
        if label_key not in accepted_labels and len(additions) < count:
            additions.append(item)
            accepted_labels.add(label_key)
    result = []
    for item in [*updates, *additions]:
        tag = item['tag']
        evidence = sorted(item['evidence'].values(), key=lambda entry: (-entry['matched_disclosed_pct'], entry['fund_code'], entry['report_date']))[:MAX_EVIDENCE_FUNDS]
        result.append({'id': 'sector_dynamic_' + hashlib.sha256(tag.encode('utf-8')).hexdigest()[:12],
            'label': tag, 'group': 'industry', 'aliases': [], 'tags': [tag],
            'description': '根据已披露股票的明确行业分类新增，匹配比例越高越优先；仅代表已披露股票部分。',
            'requires_holdings_match': True, 'dynamic': True, 'specificity': 1,
            'hierarchy_depth': item['depth'], 'rule_version': RULE_VERSION,
            'discovered_at': registered_by_tag.get(tag, {}).get('discovered_at') or as_of_day.isoformat(),
            'updated_at': as_of_day.isoformat(),
            'best_matched_disclosed_pct': float(item['best_ratio']),
            'supporting_fund_count': len(item['evidence']), 'evidence': evidence})
    return result


def _validated_registry_evidence(item, tag, as_of):
    """Do not allow corrupt or obsolete saved evidence to poison a new scan."""
    if not isinstance(item, dict) or not re.fullmatch(r'\d{6}', str(item.get('fund_code', ''))):
        return None
    try:
        report_day = _day(item.get('report_date'))
        if not 0 <= (as_of - report_day).days <= MAX_DISCLOSURE_AGE_DAYS:
            return None
    except (ValueError, TypeError):
        return None
    if not _url(item.get('source_url')):
        return None
    matched, total, ratio, coverage = (_number(item.get(key)) for key in (
        'matched_weight_pct', 'disclosed_weight_pct', 'matched_disclosed_pct', 'coverage_pct'))
    if (any(value is None for value in (matched, total, ratio, coverage))
            or not 0 < matched <= total <= 101 or matched * 100 <= total * 50
            or not 50 < ratio <= 100 or not ratio <= coverage <= 100
            or abs(ratio - matched / total * 100) > Decimal('.000001')):
        return None
    sources = item.get('classification_sources')
    if not isinstance(sources, list) or not sources or any(not _url(source) for source in sources):
        return None
    from research_holdings import holdings_row_limit
    rows = item.get('stock_evidence')
    row_limit = holdings_row_limit({'report_date': report_day.isoformat(), 'lookthrough': item.get('lookthrough')})
    if not isinstance(rows, list) or not rows or len(rows) > row_limit:
        return None
    seen, weight_sum, actual_sources = set(), Decimal(0), set()
    for row in rows:
        if not isinstance(row, dict) or not _SECURITY_CODE.fullmatch(str(row.get('code', ''))):
            return None
        identity, weight = str(row['code']), _number(row.get('nav_weight_pct'))
        source_url = _url(row.get('source_url'))
        if (identity in seen or weight is None or not 0 < weight <= 100
                or row.get('kind') != 'industry' or row.get('tag') != tag or not source_url):
            return None
        seen.add(identity)
        weight_sum += weight
        actual_sources.add(source_url)
    if abs(weight_sum - matched) > Decimal('.000001') or actual_sources != set(sources):
        return None
    return copy.deepcopy(item)


def merge_dynamic_board_registry(registry, proposals, as_of, *, limit=MAX_REGISTRY_BOARDS):
    """Merge bounded registry definitions without file access or eviction.

    Existing valid definitions retain their order; accepted proposals fill free
    places.  A repeated tag updates its evidence, rather than consuming another
    slot. This helper never infers a board from names or plain provider tags.
    """
    try:
        as_of_day = _day(as_of)
        today = as_of_day.isoformat()
    except (ValueError, TypeError):
        return []
    count = _limit(limit, MAX_REGISTRY_BOARDS)
    result, by_tag = [], {}
    for entry in [*_registry_entries(registry), *_registry_entries(proposals)]:
        tags = entry.get('tags')
        if not entry.get('dynamic') or not isinstance(tags, list) or len(tags) != 1:
            continue
        tag = _tag(tags[0])
        expected_id = 'sector_dynamic_' + hashlib.sha256(tag.encode('utf-8')).hexdigest()[:12] if tag else ''
        if not tag or entry.get('id') != expected_id or not isinstance(entry.get('evidence'), list) or not entry['evidence']:
            continue
        valid_evidence = [validated for item in entry['evidence'][:MAX_EVIDENCE_FUNDS]
                          if (validated := _validated_registry_evidence(item, tag, as_of_day)) is not None]
        if not valid_evidence:
            continue
        if tag in by_tag:
            stored = by_tag[tag]
            merged = {}
            for evidence in [*stored.get('evidence', []), *valid_evidence]:
                merged[(evidence['fund_code'], evidence['report_date'])] = evidence
            stored['evidence'] = sorted(merged.values(), key=lambda item: (-float(item.get('matched_disclosed_pct', 0)), str(item.get('fund_code', ''))))[:MAX_EVIDENCE_FUNDS]
            stored['updated_at'] = today
            stored['hierarchy_depth'] = max(_depth(stored.get('hierarchy_depth')), _depth(entry.get('hierarchy_depth')))
        elif len(result) < count:
            stored = copy.deepcopy(entry)
            stored.update(id=expected_id, label=tag, group='industry', aliases=[], tags=[tag],
                          dynamic=True, requires_holdings_match=True, specificity=1,
                          hierarchy_depth=_depth(entry.get('hierarchy_depth')), rule_version=RULE_VERSION,
                          evidence=valid_evidence)
            result.append(stored)
            by_tag[tag] = stored
    for stored in result:
        stored['best_matched_disclosed_pct'] = max(item['matched_disclosed_pct'] for item in stored['evidence'])
        stored['supporting_fund_count'] = len({item['fund_code'] for item in stored['evidence']})
    return result
