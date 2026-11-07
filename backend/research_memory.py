"""Bounded evidence reuse. Saved buy plans and AI prose are never reused."""
import copy
import re
from datetime import datetime, timedelta
from research_data import CHINA

MAX_HOLDINGS_INDEX = 2000
MAX_RETAINED_FUNDS = 192
MAX_CHECK_LEDGER = 30000


def _day(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except (ValueError, TypeError):
        return None


def update_holdings_index(previous, observed, as_of):
    """A new failed observation supersedes the old successful portfolio."""
    index = {row['code']: copy.deepcopy(row) for row in previous or []
             if isinstance(row, dict) and row.get('code')}
    for fund in observed:
        if not isinstance(fund, dict) or not fund.get('code') or not isinstance(fund.get('holdings'), dict):
            continue
        index[fund['code']] = {key: copy.deepcopy(fund[key]) for key in
                              ('code', 'holdings', 'fund_type', 'share_family', 'family_id') if key in fund}
        index[fund['code']]['holdings_checked_at'] = fund.get('holdings_checked_at') or as_of
    return sorted(index.values(), key=lambda row: (str(row.get('holdings_checked_at', '')), row['code']),
                  reverse=True)[:MAX_HOLDINGS_INDEX]


def update_check_ledger(previous, observed, as_of):
    """Keep lightweight scan progress after bulky portfolios leave the cache."""
    reference = _day(as_of)
    def valid(code, stamp):
        day = _day(stamp)
        return isinstance(code, str) and re.fullmatch(r'\d{6}', code) and day is not None and reference is not None and day <= reference
    ledger = {str(code): stamp for code, stamp in (previous or {}).items()
              if isinstance(stamp, str) and valid(code, stamp)}
    for fund in observed:
        if not isinstance(fund, dict) or not isinstance(fund.get('holdings'), dict):
            continue
        stamp = str(fund.get('holdings_checked_at') or as_of)
        if valid(fund.get('code'), stamp):
            ledger[fund['code']] = stamp
    return dict(sorted(ledger.items(), key=lambda item: (item[1], item[0]), reverse=True)[:MAX_CHECK_LEDGER])


def attach_holdings_index(universe, index, check_ledger=None):
    by_code = {row['code']: row for row in index if isinstance(row, dict) and row.get('code')}
    for fund in universe.get('funds', []):
        saved = by_code.get(fund['code'], {})
        if 'holdings' in saved:
            fund['holdings'] = copy.deepcopy(saved['holdings'])
        fund['holdings_checked_at'] = (check_ledger or {}).get(fund['code']) or saved.get('holdings_checked_at')


def retain_research(snapshot, previous, universe, attempted_codes):
    """Retain fresh dated raw evidence, then let callers recompute all decisions."""
    today = _day(snapshot.get('as_of')) or datetime.now(CHINA).date()
    current = {row['code']: row for row in universe.get('funds', []) if row.get('eligible')}
    attempted = set(attempted_codes)
    present = {row['code'] for row in snapshot.get('funds', [])}
    index = {row['code']: row for row in universe.get('funds', [])}
    retained = []
    for old in previous.get('funds', []) if isinstance(previous, dict) else []:
        code = old.get('code')
        nav_day = _day(old.get('nav_date'))
        if code in attempted or code in present or code not in current or not old.get('history'):
            continue
        if nav_day is None or not 0 <= (today - nav_day).days <= 7:
            continue
        saved = copy.deepcopy(old)
        saved.update({key: copy.deepcopy(value) for key, value in current[code].items()
                      if key not in {'nav', 'nav_date', 'history', 'holdings'}})
        # Current failed/changed holdings must not be masked by a previous pass.
        if 'holdings' in index.get(code, {}):
            saved['holdings'] = copy.deepcopy(index[code]['holdings'])
        saved.update(research_origin='retained', evidence_collected_at=old.get('evidence_collected_at')
                     or old.get('fetched_at') or previous.get('as_of'))
        retained.append(saved)
    retained.sort(key=lambda row: (str(row.get('nav_date', '')), row['code']), reverse=True)
    retained = retained[:MAX_RETAINED_FUNDS]
    wanted = {row['code'] for row in retained}
    source_ids = {row.get('id') for row in snapshot.get('sources', [])}
    for source in previous.get('sources', []) if isinstance(previous, dict) else []:
        identity = str(source.get('id', ''))
        if identity in source_ids or not any(identity in {f'nav:{c}', f'holdings:{c}', f'announcements_{c}'} for c in wanted):
            continue
        snapshot.setdefault('sources', []).append(copy.deepcopy(source))
        source_ids.add(identity)
    snapshot.setdefault('funds', []).extend(retained)
    return len(retained)
