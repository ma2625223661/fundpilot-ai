"""Small, dated AI evidence views; full price series remain in the local report."""
import copy
import math


def pick(row, fields):
    return {key: copy.deepcopy(row[key]) for key in fields if key in row} if isinstance(row, dict) else {}


def compact_source(row):
    return pick(row, ('id', 'name', 'url', 'status', 'as_of', 'fetched_at', 'count', 'error'))


def compact_company(row, as_of=None, business_only=False):
    result = pick(row, ('ts_code', 'name', 'industry', 'role', 'leader_verified', 'as_of',
                        'source_ids', 'sample_checks', 'quality_conditions', 'financials_note', 'price_adjustment'))
    result['membership_evidence'] = pick(row.get('membership_evidence'),
        ('l1_name', 'l2_name', 'l3_name', 'in_date', 'out_date', 'snapshot_date',
         'published_date', 'observed_at', 'evidence_type', 'source_id', 'url', 'source_url', 'business_summary', 'reason'))
    # Some independently verified thematic members carry their own business evidence.
    result.update(pick(row, ('business_evidence',)))
    if business_only:
        return result
    result['quote'] = pick(row.get('quote'), ('close', 'pct_chg', 'amount', 'trade_date',
        'currency', 'data_kind', 'is_intraday', 'source_id', 'close_kind'))
    result['market_metrics'] = pick(row.get('market_metrics'),
        ('total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio', 'pe_ttm', 'pb'))
    result['financials'] = pick(row.get('financials'), ('ts_code', 'ann_date', 'end_date',
        'roe', 'eps', 'netprofit_yoy', 'tr_yoy', 'grossprofit_margin', 'currency', 'source_note')) or None
    # Reuse the deterministic model's metric definitions. Never send every daily
    # observation, nor accept undated, nonpositive or future observations here.
    history = {}
    for point in row.get('history', []):
        if not isinstance(point, dict):
            continue
        date, close = point.get('date'), point.get('close')
        if (isinstance(date, str) and len(date) == 10 and (not as_of or date <= str(as_of)[:10])
                and isinstance(close, (int, float)) and not isinstance(close, bool)
                and math.isfinite(close) and close > 0):
            history[date] = {'date': date, 'close': close}
    points = [history[date] for date in sorted(history)][-121:]
    from research_sectors import history_metrics
    result['history_metrics'] = history_metrics(points, as_of)
    result['history_metrics']['start_date'] = points[0]['date'] if points else None
    return result


def compact_index(row):
    result = pick(row, ('id', 'version', 'name', 'scope', 'method', 'weighting', 'base_value',
        'base_date', 'history_end', 'history_count', 'sample_count', 'minimum_samples',
        'ready', 'is_intraday', 'value', 'as_of', 'excluded'))
    result['constituents'] = [pick(member, ('ts_code', 'code', 'name', 'weight', 'weight_pct', 'as_of',
        'membership_date', 'price_adjustment', 'source_ids')) for member in row.get('constituents', []) if isinstance(member, dict)]
    return result


def event_company_context(report, candidates=None):
    """One business record per company, with explicit sector memberships.

    Keep all selected sectors for policy events that lack stock codes; do not
    infer missing company/sector relationships from the model's memory.
    """
    companies = {}
    membership_fields = ('l1_name', 'l2_name', 'l3_name', 'snapshot_date', 'published_date', 'evidence_type')
    def nonempty(values):
        return {key: value for key, value in values.items() if value is not None and value != '' and value != [] and value != {}}
    codes = {str(code) for event in (candidates or []) for code in event.get('stock_codes', [])}
    sector_ids = {str(identity) for event in (candidates or []) for identity in event.get('sector_ids', [])}
    # Policy notices without company/sector mappings need the complete business
    # graph. Company notices only need the explicitly linked companies/sectors.
    broad = candidates is None or any(not event.get('stock_codes') and not event.get('sector_ids') for event in candidates)
    for sector_id, rows in report.get('company_evidence', {}).get('sector_leaders', {}).items():
        for row in rows:
            if not isinstance(row, dict) or not row.get('ts_code'):
                continue
            code = row['ts_code']
            if not broad and code not in codes and code.split('.')[0] not in codes and sector_id not in sector_ids:
                continue
            if code not in companies:
                companies[code] = nonempty(pick(row, ('ts_code', 'name', 'industry', 'leader_verified', 'business_evidence')))
                # Event assessment needs business relationships, not duplicate
                # quote/finance provenance URLs or price-quality check prose.
                # Keep each dated membership exactly once under its sector.
                companies[code]['sector_memberships'] = []
            membership = {'sector_id': sector_id,
                'membership_evidence': nonempty(pick(row.get('membership_evidence'), membership_fields))}
            companies[code]['sector_memberships'].append(membership)
    return list(companies.values())
