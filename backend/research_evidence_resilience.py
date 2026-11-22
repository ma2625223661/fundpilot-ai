"""Dated component recovery for free research; never carries forward a score.

Keep verified evidence across full scans and process restarts. Native dates and
security identities are checked again on every use. Failed requests may reuse
an eligible observation, but cannot make it newer or revive removed members.
"""
import copy
import math
import re
from datetime import datetime, timedelta

from research_sample_policy import financial_ready
from research_trading_calendar import is_trading_day, last_closed_trading_day, a_share_quote_fresh
from research_numbers import finite_number as finite


def complete_history(rows, as_of, code=''):
    market = 'HK' if code.endswith('.HK') else 'US' if code.endswith('.US') else 'CN'
    if market == 'CN':
        cutoff = last_closed_trading_day(as_of)
    else:
        from research_overseas import last_complete_session, is_session
        cutoff = last_complete_session(market, as_of)
    if not cutoff or not isinstance(rows, list):
        return False
    points = {p.get('date'): p.get('close') for p in rows if isinstance(p, dict)
              and isinstance(p.get('date'), str) and finite(p.get('close')) and p['close'] > 0}
    if not points or max(points) != cutoff or len(points) != len(rows):
        return False
    required, day = set(), datetime.fromisoformat(cutoff).date()
    for _ in range(240):
        opened = is_trading_day(day) if market == 'CN' else is_session(market, day)
        if opened:
            required.add(day.isoformat())
        if len(required) == 61:
            break
        day -= timedelta(days=1)
    return len(required) == 61 and required.issubset(points)


def supported_code(code):
    return bool(re.fullmatch(r'(?:\d{6}\.(?:SH|SZ|BJ)|\d{5}\.HK|[A-Z][A-Z0-9.\-]{0,12}\.US)', str(code)))


def valid_quote(row, as_of):
    code, quote = row.get('ts_code', ''), row.get('quote') or {}
    if not finite(quote.get('close')) or quote['close'] <= 0 or not finite(quote.get('pct_chg')):
        return False
    if code.endswith(('.HK', '.US')):
        from research_overseas import last_complete_session
        cutoff = last_complete_session('HK' if code.endswith('.HK') else 'US', as_of)
        return bool(cutoff and row.get('as_of') == cutoff and quote.get('trade_date') == cutoff and not quote.get('is_intraday'))
    return a_share_quote_fresh(row.get('as_of'), as_of, daily=not quote.get('is_intraday'))


def valid_member(row, as_of):
    member = row.get('membership_evidence') or {}
    try:
        age = (datetime.fromisoformat(as_of[:10]).date()
               - datetime.fromisoformat(member['snapshot_date'][:10]).date()).days
        return 0 <= age <= 45 and bool(member.get('l1_name') and row.get('source_ids'))
    except (KeyError, TypeError, ValueError):
        return False


RETAINED = ':retained'


def retained_base(identity):
    """The original source id without any (possibly repeated) ':retained' suffix."""
    identity = str(identity)
    while identity.endswith(RETAINED):
        identity = identity[:-len(RETAINED)]
    return identity


def _collapsed(identity):
    base = retained_base(identity)
    return base + RETAINED if base != str(identity) else base


def collapse_retained(value):
    """Repair ids nested by earlier rounds ('x:retained:retained…', issue #10).

    Each source list keeps one entry per collapsed id (the last one, the newest),
    and every 'source_ids' list is rewritten the same way. Changes in place.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'sources' and isinstance(item, list):
                kept = {}
                for source in item:
                    if isinstance(source, dict) and isinstance(source.get('id'), str):
                        source['id'] = _collapsed(source['id'])
                        kept.pop(source['id'], None)
                        kept[source['id']] = source
                    else:
                        kept[id(source)] = source
                item[:] = list(kept.values())
                for source in item:
                    collapse_retained(source)
            elif key == 'source_ids' and isinstance(item, list):
                item[:] = list(dict.fromkeys(_collapsed(i) if isinstance(i, str) else i for i in item))
            else:
                collapse_retained(item)
    elif isinstance(value, list):
        for item in value:
            collapse_retained(item)
    return value


def retain_company_components(company, previous, as_of, catalog=None):
    from research_public_data import _get
    pools = company.setdefault('sector_leaders', {})
    prior_pools = previous.get('sector_leaders', {})
    source_map = {s.get('id'): s for s in company.get('sources', [])}
    old_sources = {s.get('id'): s for s in previous.get('sources', [])}
    retained_sources, recovered = {}, []
    identities = set(prior_pools) | set(pools) | {b['id'] for b in (catalog or [])}
    # Durable last-good rows also cover a restart after an incomplete report.
    for identity in list(identities):
        cached = _get('company_last_good:' + identity) or {}
        originals = {r.get('ts_code'): r for r in cached.get('rows', [])}
        originals.update({r.get('ts_code'): r for r in prior_pools.get(identity, [])})
        old_sources.update({s.get('id'): s for s in cached.get('sources', [])})
        membership = source_map.get('public:members:' + identity) or {}
        verified = company.get('selection_universes', {}).get(identity, {}).get('verified_member_codes', [])
        authoritative = (membership.get('status') == 'ok' and membership.get('complete_membership') is not False
                         and verified and membership.get('count') == len(verified))
        if authoritative:
            originals = {code: r for code, r in originals.items() if code in verified}
            # Persist removal even if fewer than two usable samples remain.
            # Otherwise an outage on a later day could revive an old member.
            if cached:
                from research_public_data import _remember
                cached['rows'] = [r for r in cached.get('rows', []) if r.get('ts_code') in verified]
                _remember('company_last_good:' + identity, cached, 45*86400)
        rows = pools.setdefault(identity, [])
        current = {r.get('ts_code'): r for r in rows}
        for code, prior in originals.items():
            if not supported_code(code) or not valid_member(prior, as_of):
                continue
            row = current.get(code)
            if row is None:
                member_ids = [s for s in prior.get('source_ids', []) if s.startswith(('public:members:', 'public:business:'))]
                failures = [source_map[s] for s in member_ids if s in source_map and source_map[s].get('status') in {'error', 'timeout'}]
                verified = company.get('selection_universes', {}).get(identity, {}).get('verified_member_codes', [])
                quote_failed = code in verified and any(s.get('status') in {'error', 'timeout'}
                    and s.get('id', '').startswith('public:quotes:')
                    and code[-2:].lower() + code[:6] in s.get('url', '') for s in source_map.values())
                if code.endswith(('.HK', '.US')):
                    from research_overseas import sample_specs
                    allowed = {r['code'] for r in sample_specs(identity)}
                    failure = source_map.get('overseas:sample:' + code) or {}
                    if code in allowed and failure.get('status') in {'error', 'timeout'}:
                        failures.append(failure)
                # Do not restore an old constituent when the publisher has
                # successfully supplied a changed list or changed business.
                if (not failures and not quote_failed) or any('事实核对' in s.get('error', '') or '身份发生变化' in s.get('error', '') for s in failures):
                    continue
                row = copy.deepcopy(prior)
                quote = row.get('quote') or {}
                if quote.get('is_intraday') or not valid_quote(row, as_of):
                    row.update(quote={}, as_of=None)
                rows.append(row)
                current[code] = row
                recovered.append({'sector_id': identity, 'code': code, 'component': 'membership',
                                  'as_of': prior['membership_evidence']['snapshot_date']})
            if not financial_ready(row, as_of) and financial_ready(prior, as_of):
                fin = prior['financials']
                if fin.get('ts_code', code) == code:
                    row['financials'] = copy.deepcopy(fin)
                    recovered.append({'sector_id': identity, 'code': code, 'component': 'financials', 'as_of': fin['ann_date']})
            if not complete_history(row.get('history'), as_of, code) and complete_history(prior.get('history'), as_of, code):
                row['history'] = copy.deepcopy(prior['history'])
                row['history_count'] = len(row['history'])
                row['price_adjustment'] = prior.get('price_adjustment')
            for key in prior.get('source_ids', []):
                # Work from the original id so the suffix is added at most once (issue #10).
                base = retained_base(key)
                live = source_map.get(base)
                if live and live.get('status') not in {'error', 'timeout'}:
                    continue
                old = old_sources.get(key) or old_sources.get(base + RETAINED) or old_sources.get(base)
                # Only good evidence is carried forward; an old failure is not evidence.
                if not old or old.get('status') in {'error', 'timeout'}:
                    continue
                source = copy.deepcopy(old)
                source.update(cache_used=True, checked_at=as_of)
                retained_id = base + RETAINED if base in source_map else base
                source['id'] = retained_id
                retained_sources[retained_id] = source
                ids = [i for i in row.get('source_ids', []) if retained_base(i) != base or i == base]
                row['source_ids'] = list(dict.fromkeys(ids + [retained_id]))
    company.setdefault('sources', []).extend(retained_sources.values())
    company['evidence_recovery'] = recovered
    return company


def retain_closed_baskets(company, as_of):
    """Use a consistent latest-closed basket if some live samples are missing."""
    cutoff = last_closed_trading_day(as_of)
    for identity, rows in company.get('sector_leaders', {}).items():
        if len(rows) < 2 or any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(r.get('ts_code'))) for r in rows):
            continue
        valid = [valid_quote(r, as_of) for r in rows]
        sessions = {(str(r.get('as_of'))[:10], bool((r.get('quote') or {}).get('is_intraday'))) for r in rows}
        if all(valid) and len(sessions) == 1:
            continue
        if not all(complete_history(r.get('history'), as_of) and r.get('price_adjustment') == 'forward_adjusted' for r in rows):
            continue
        for row in rows:
            points = sorted(row['history'], key=lambda p: p['date'])
            last, prior = points[-1], points[-2]
            row.update(as_of=cutoff + 'T15:00:00+08:00', quote={
                'trade_date': cutoff, 'close': last['close'], 'pct_chg': (last['close'] / prior['close'] - 1) * 100,
                'amount': None, 'is_intraday': False, 'data_kind': 'daily_close', 'retained_close': True,
                'retained_reason': '盘中报价未齐，统一使用最近已收盘交易日的前复权日线；保留真实日期。'})
        company.setdefault('closed_basket_recovery', []).append({'sector_id': identity, 'as_of': cutoff})
    return company


def remember_company_evidence(company, as_of):
    from research_public_data import _remember, _save
    sources = {s.get('id'): s for s in company.get('sources', [])}
    for identity, rows in company.get('sector_leaders', {}).items():
        good = [r for r in rows if supported_code(r.get('ts_code')) and valid_quote(r, as_of)
                and valid_member(r, as_of) and financial_ready(r, as_of) and complete_history(r.get('history'), as_of, r['ts_code'])
                and (r.get('financials') or {}).get('ts_code', r['ts_code']) == r['ts_code']]
        if len(good) >= 2:
            ids = {i for r in good for i in r.get('source_ids', [])}
            _remember('company_last_good:' + identity, {'rows': good, 'sources': [s for i, s in sources.items() if i in ids]}, 45*86400)
    _save()
