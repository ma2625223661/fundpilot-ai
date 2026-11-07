"""Shared, bounded company sampling; missing evidence never becomes a zero."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from research_numbers import finite_number as finite

MAX_SAMPLES = 8
CANDIDATE_LIMIT = 12
CORE_SAMPLES = 4
SELECTION_METHOD = ('每方向在已核验归属池内按有效市值或明示固定名单取至多12家候选；'
    '核对披露日财务及近期61个交易日走势后，取至多8家等权研究样本。'
    '通常优先保留4家大市值或固定池代表，微盘方向按小市值选样；其余按已披露盈利、ROE和收入/利润增长条件补充；'
    '缺项不当作0，未通过数据核验的候选单列。不是全市场选股或上涨承诺。')


# The verification sentence appended below. A sample reused from the previous
# report already carries it, so it is cut off before appending again; without
# this, every refresh repeated it and one string grew past 2 KB.
VERIFIED_MARK = '；数据核验通过；'


def provider_basis(text):
    """The provider's own selection basis, without any verification sentences added earlier."""
    text = text if isinstance(text, str) else ''
    return text.split(VERIFIED_MARK, 1)[0]


def fair_codes(pools):
    """Round-robin sectors so a request deadline cannot starve later sectors."""
    rows = list(pools.values())
    seen, result = set(), []
    for index in range(max((len(r) for r in rows), default=0)):
        for members in rows:
            if index < len(members):
                code = members[index].get('ts_code')
                if code and code not in seen:
                    result.append(code)
                    seen.add(code)
    return result


def financial_ready(row, as_of):
    fin = row.get('financials') or {}
    try:
        published = datetime.fromisoformat(fin['ann_date'][:10]).date()
        end = datetime.fromisoformat(fin['end_date'][:10]).date()
        now = datetime.fromisoformat(as_of[:10]).date()
    except (KeyError, TypeError, ValueError):
        return False
    return (end <= published < now and 0 <= (now-end).days <= 550
            and any(finite(fin.get(k)) for k in ('roe','eps','netprofit_yoy','tr_yoy','grossprofit_margin')))


def quality_conditions(row):
    fin = row.get('financials') or {}
    return {label: fin[key] > 0 for key, label in (
        ('eps', '每股收益为正'), ('roe', '净资产收益率为正'),
        ('tr_yoy', '营业收入同比增长'), ('netprofit_yoy', '净利润同比增长')) if finite(fin.get(key))}


def finalize_company_samples(company, as_of):
    """Select complete research objects; retain every rejected candidate's reason."""
    from research_trading_calendar import last_closed_trading_day, is_trading_day, a_share_quote_fresh
    from research_overseas import last_complete_session, is_session
    pools = company.get('sector_leaders', {})
    company['sample_selection'] = {}
    for identity, rows in pools.items():
        ready, pending = [], []
        for row in rows:
            code = row.get('ts_code', '')
            market = 'HK' if code.endswith('.HK') else 'US' if code.endswith('.US') else 'CN'
            cutoff = last_closed_trading_day(as_of) if market == 'CN' else last_complete_session(market, as_of)
            recent = set()
            if cutoff:
                day = datetime.fromisoformat(cutoff).date()
                for _ in range(240):
                    opened = is_trading_day(day) if market == 'CN' else is_session(market, day)
                    if opened:
                        recent.add(day.isoformat())
                    if len(recent) >= 61:
                        break
                    day -= timedelta(days=1)
            history = {p.get('date') for p in row.get('history', []) if finite(p.get('close')) and p['close'] > 0}
            quote = row.get('quote') or {}
            member = row.get('membership_evidence') or {}
            try:
                age = (datetime.fromisoformat(as_of[:10]).date()-datetime.fromisoformat(member['snapshot_date'][:10]).date()).days
                member_ok = 0 <= age <= 45 and bool(member.get('l1_name') and row.get('source_ids'))
            except (TypeError, KeyError, ValueError):
                member_ok = False
            quote_ok = (finite(quote.get('close')) and quote['close'] > 0 and finite(quote.get('pct_chg'))
                and (a_share_quote_fresh(row.get('as_of'), as_of, daily=not quote.get('is_intraday')) if market == 'CN'
                     else quote.get('trade_date') == cutoff))
            checks = {'业务或成分归属': member_ok, '有效报价': bool(quote_ok),
                      '披露日财务': financial_ready(row, as_of),
                      '近期61日走势': len(recent) == 61 and recent.issubset(history)}
            row['sample_checks'] = checks
            row['quality_conditions'] = quality_conditions(row)
            if all(checks.values()):
                ready.append(row)
            else:
                pending.append({'ts_code': code, 'name': row.get('name', code),
                    'reason': '、'.join(k for k, passed in checks.items() if not passed) + '尚未核验完整',
                    'sample_checks': checks, 'source_ids': row.get('source_ids', [])})
        # Existing provider order is size descending (or a declared fixed pool).
        core = ready[:CORE_SAMPLES]
        others = sorted(ready[CORE_SAMPLES:], key=lambda r: (
            -sum(quality_conditions(r).values()),
            -(r.get('market_metrics', {}).get('total_mv') or 0), r.get('ts_code', '')))
        selected = (core + others)[:MAX_SAMPLES]
        for row in selected:
            positive = [k for k, value in row['quality_conditions'].items() if value]
            row['selection_basis'] = (provider_basis(row.get('selection_basis', '')) + VERIFIED_MARK
                + (('小市值代表样本' if company.get('selection_universes', {}).get(identity, {}).get('order') == 'smallest_market_cap' else '市值/固定池代表样本') if row in core else '财务条件补充样本')
                + ('；' + '、'.join(positive) if positive else '；未声称业绩增长')
                + '；近期61个交易日走势完整。')
        # Retain incomplete evidence when fewer than two can form an indicator.
        pools[identity] = selected if len(selected) >= 2 else rows[:MAX_SAMPLES]
        universe = company.get('selection_universes', {}).get(identity, {})
        company['sample_selection'][identity] = {**universe, 'candidate_count': len(rows), 'ready_count': len(ready),
            'selected_count': len(selected), 'maximum_samples': MAX_SAMPLES,
            'pending': pending, 'method': SELECTION_METHOD}
    company['selection_method'] = SELECTION_METHOD
    return company
