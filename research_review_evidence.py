"""Local, typed review evidence. Reading a review never downloads or calls AI."""
import copy
import re
from datetime import datetime, timedelta

from research_trading_calendar import is_trading_day, last_closed_trading_day


def company_market(sector):
    index = sector.get('custom_index') or {}
    members = index.get('constituents') or []
    if not index.get('ready') or len(members) < 2 or not all(isinstance(r, dict) for r in members):
        return None
    codes = [str(r.get('code', '')) for r in members]
    if len(set(codes)) != len(codes):
        return None
    if sector.get('group') != 'overseas' and all(re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', c) for c in codes):
        return 'CN'
    for market, pattern in [('HK', r'\d{5}\.HK'), ('US', r'[A-Z][A-Z.\-]*\.US')]:
        if index.get('market') == market and all(re.fullmatch(pattern, c) for c in codes):
            return market
    return None


def closed_day(market, as_of):
    if market == 'CN':
        return last_closed_trading_day(as_of)
    if market in ('HK', 'US'):
        from research_overseas import last_complete_session
        return last_complete_session(market, as_of)
    if market == 'CN_HK':
        from research_sector_references import last_completed_reference_day
        return last_completed_reference_day(market, as_of)
    return None


def session_days(market, end, count):
    if not end:
        return []
    try:
        day = datetime.fromisoformat(str(end)[:10]).date()
    except (ValueError, TypeError):
        return []
    from research_overseas import is_session
    result = []
    for _ in range(count * 5 + 40):
        if market == 'CN':
            opened = is_trading_day(day)
        elif market in ('HK', 'US'):
            opened = is_session(market, day)
        elif market == 'CN_HK':
            cn, hk = is_trading_day(day), is_session('HK', day)
            opened = None if cn is None or hk is None else cn or hk
        else:
            return []
        if opened is None:
            return []
        if opened:
            result.append(day.isoformat())
            if len(result) == count:
                return list(reversed(result))
        day -= timedelta(days=1)
    return []


def local_history(sector, report):
    quote = sector.get('quote') or {}
    key = quote.get('history_secid')
    entry = (report.get('_quote_histories') or {}).get(key) or {}
    rows = entry.get('rows') if isinstance(entry, dict) else None
    if rows:
        return copy.deepcopy(rows)
    # Earlier snapshots omitted publisher series. Reuse only the exact dated
    # local record; never download, splice providers, or extend dates here.
    if str(key).startswith('official:'):
        from research_sector_references import CACHE_PATH
        from research_evidence_cache import load_record
        record = load_record(CACHE_PATH, sector.get('id')) or {}
        cached = record.get('quote') or {}
        if all(cached.get(k) == quote.get(k) for k in ('code', 'history_secid', 'as_of', 'currency')):
            return copy.deepcopy(record.get('history') or [])
    return []


def review_input(sector, report, as_of):
    """Resolve one exact company basket, publisher index, or interest rate."""
    index, quote = sector.get('custom_index') or {}, sector.get('quote') or {}
    market = company_market(sector)
    if market:
        kind, rows = 'company', index.get('history') or []
        end = closed_day(market, as_of)
        ids = [index['id']]
        members = copy.deepcopy(index.get('constituents') or [])
        currency = index.get('currency') or ('CNY' if market == 'CN' else None)
        scope = '本轮公司样本回溯，不是全行业表现或历史选样策略收益。'
    else:
        kind = 'rate' if quote.get('asset_type') == 'money_rate' else 'reference'
        rows = local_history(sector, report)
        market = quote.get('market') or ('CN' if sector.get('group') != 'overseas' else 'PROVIDER')
        ids = ([quote.get('source_id'), 'sector_history:' + str(quote.get('history_secid'))] if quote else
               ['sector_reference:'+str(sector.get('id')), 'overseas_reference:'+str(sector.get('id'))])
        members, currency = [], quote.get('currency')
        scope = quote.get('scope_note') or sector.get('analysis_scope') or '仅观察已明确映射的价格指数，不含公司财务和事件判断。'
        end = closed_day(market, as_of)
        if market not in ('CN', 'CN_HK', 'HK', 'US'):
            from research_overseas_references import reference_quote_fresh
            end = str(quote.get('as_of', ''))[:10] if reference_quote_fresh(quote, as_of) else None
    days = session_days(market, end, 26)
    observation_only = market not in ('CN', 'CN_HK', 'HK', 'US')
    if observation_only and end:
        # Other markets use actual published observations, not an invented
        # Monday-Friday calendar. The UI discloses that continuity is unverified.
        days = sorted({r.get('date') for r in rows if isinstance(r, dict)
                       and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(r.get('date', '')))
                       and r['date'] <= end})[-26:]
    labels = {'CN': 'A股已核验交易日', 'HK': '香港已核验交易日', 'US': '纽约已核验交易日',
              'CN_HK': '内地与香港开市日并集'}
    sources = {s.get('id'): s for s in (report.get('snapshot') or {}).get('sources', [])
               if isinstance(s, dict) and s.get('id')}
    sources.update({s.get('id'): s for s in sector.get('sources', []) if isinstance(s, dict) and s.get('id')})
    for member in members:
        ids.extend(member.get('source_ids') or [])
    selected = [copy.deepcopy(sources[i]) for i in dict.fromkeys(ids) if i in sources]
    adjustments = sorted({m.get('price_adjustment') or 'forward_adjusted' for m in members})
    adjustment_note = ('含未复权价格，除权除息可能造成跳变；不是含股息或人民币换算收益。'
                       if 'unadjusted' in adjustments else
                       '公司价格使用来源声明的复权口径，不含交易成本。' if members else
                       '按来源指数价格口径计算；股息、利息或汇率仅以来源明确声明为准。')
    return {'kind': kind, 'market': market, 'end': end, 'days': days, 'rows': copy.deepcopy(rows),
            'id': index.get('id') if kind == 'company' else quote.get('history_secid'),
            'source_ids': list(dict.fromkeys(i for i in ids if i)), 'sources': selected,
            'members': members, 'currency': currency, 'scope': scope, 'adjustment_note': adjustment_note,
            'calendar_label': labels.get(market, '来源已发布收盘观测日；当地完整交易日历未核验'),
            'observation_only': observation_only,
            'is_intraday': bool(index.get('is_intraday')) if kind == 'company' else bool(quote.get('is_intraday'))}


def reference_company(report, market):
    """Native, disclosed broad-market reference for overseas company baskets."""
    identity = {'HK': 'overseas_hang_seng', 'US': 'overseas_sp500'}.get(market)
    return next((s for s in report.get('sector_analysis', []) if s.get('id') == identity), None)
