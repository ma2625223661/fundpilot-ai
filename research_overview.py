"""Build a traceable market overview from already collected public data.

This module performs no I/O. Fund breadth is a distribution of *disclosed daily
returns on one NAV date*, never an estimate made from index prices or NAV deltas.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import math
import re


CHINA = timezone(timedelta(hours=8))
RANK_SOURCE_ID = 'universe:ranking'
RANK_SOURCE_URL = 'https://fund.eastmoney.com/data/fundranking.html'
SNAPSHOT_SOURCE_ID = 'fund:nav_sample'
SNAPSHOT_SOURCE_URL = 'https://fund.eastmoney.com/'
INDEX_ORDER = {'sh000001': 0, 'sz399001': 1, 'sh000300': 2, 'sz399006': 3}
BUCKETS = (
    ('lt_minus5', '≤ -5%', 'down'),
    ('minus5_minus3', '(-5%, -3%]', 'down'),
    ('minus3_minus1', '(-3%, -1%]', 'down'),
    ('minus1_0', '(-1%, 0%)', 'down'),
    ('flat', '0%', 'flat'),
    ('zero_1', '(0%, 1%)', 'up'),
    ('one_3', '[1%, 3%)', 'up'),
    ('three_5', '[3%, 5%)', 'up'),
    ('gte5', '≥ 5%', 'up'),
)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=CHINA)
    return result.astimezone(CHINA)


def _records(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _daily(value):
    result = _number(value)
    # A disclosed percentage return cannot lose more than its entire NAV.
    # Gross source mistakes are excluded rather than placed in the edge buckets.
    return result if result is not None and -100 < result <= 100 else None


def _fund_rows(rows, history=False):
    """Select each code's newest disclosure without resurrecting older returns."""
    grouped = {}
    for row in _records(rows):
        code = row.get('code')
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
            continue
        nav_day = _day(row.get('nav_date'))
        daily_return = _daily(row.get('return_1d'))
        if history:
            entries = [item for item in _records(row.get('history')) if _day(item.get('date'))]
            latest = max((_day(item['date']) for item in entries), default=None)
            latest_entries = [item for item in entries if _day(item['date']) == latest]
            returns = {_daily(item.get('return_pct')) for item in latest_entries}
            daily_return = next(iter(returns)) if len(returns) == 1 else None
            # A conflicting head date means the history cannot establish today's
            # disclosure. It must not silently substitute an earlier history row.
            if nav_day is not None and nav_day != latest:
                daily_return = None
            nav_day = max((item for item in (nav_day, latest) if item is not None), default=None)
        grouped.setdefault(code, []).append((nav_day, daily_return))
    result = []
    for code, entries in grouped.items():
        latest = max((day for day, _ in entries if day is not None), default=None)
        newest = [value for day, value in entries if day == latest]
        values = set(newest)
        # Conflicting observations of the same code and day count as one
        # excluded share class, never two votes or an arbitrary chosen return.
        value = next(iter(values)) if len(values) == 1 else None
        result.append({'code': code, 'nav_date': latest, 'return_1d': value})
    return result


def _usable(rows, reference):
    return [row for row in rows if reference is not None and row['nav_date'] is not None
            and 0 <= (reference - row['nav_date']).days < 7 and row['return_1d'] is not None]


def _bucket(value):
    if value <= -5:
        return 0
    if value <= -3:
        return 1
    if value <= -1:
        return 2
    if value < 0:
        return 3
    if value == 0:
        return 4
    if value < 1:
        return 5
    if value < 3:
        return 6
    if value < 5:
        return 7
    return 8


def _indices(snapshot, reference):
    grouped = {}
    for row in _records(snapshot.get('market')):
        code = row.get('code')
        if not isinstance(code, str) or not code:
            continue
        stamp = _timestamp(row.get('as_of'))
        previous = grouped.get(code)
        if previous is None or (stamp is not None and (previous[1] is None or stamp > previous[1])):
            grouped[code] = (row, stamp)
    result = []
    for code in sorted(grouped, key=lambda item: (INDEX_ORDER.get(item, 99), item))[:4]:
        row, stamp = grouped[code]
        value, change = _number(row.get('last')), _number(row.get('change_pct'))
        value = value if value is not None and value > 0 else None
        status, reason = 'ok', '来源披露的指数点位与涨跌幅'
        if value is None or change is None:
            status, reason = 'unknown', '指数点位或涨跌幅缺失，不能判断方向'
        elif stamp is None:
            status, reason = 'unknown', '行情时间缺失，无法核验时效'
        elif reference is None:
            status, reason = 'unknown', '研究快照时间缺失，无法核验行情时效'
        elif stamp > reference:
            status, reason = 'unknown', '行情时间晚于研究快照，等待下一次核验'
        elif (reference.date() - stamp.date()).days > 3:
            status, reason = 'stale', '行情日期距研究快照超过 3 个自然日'
        result.append({'code': code, 'name': str(row.get('name') or code)[:100],
                       'value': value, 'change_pct': change,
                       'as_of': stamp.isoformat() if stamp else None,
                       'source_id': row.get('source_id') or 'market_tencent',
                       'source_url': row.get('source_url') or f'https://gu.qq.com/{code}/zs',
                       'status': status, 'reason': reason})
    return result


def build_market_overview(universe, snapshot):
    """Return index quotes and a single-date fund daily-return histogram.

    The selected NAV date has the most usable, unique six-digit share codes in
    the seven calendar days ending on the snapshot date. Ties use the latest
    date. A/C classes count independently. An older report with no usable public
    daily ranking data may use disclosed history.return_pct from its deep
    research sample; weekly/monthly returns and bare NAV deltas are never used.
    """
    universe = universe if isinstance(universe, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    reference = _timestamp(snapshot.get('as_of')) or _timestamp(universe.get('as_of'))
    reference_day = reference.date() if reference else None
    public_rows = _fund_rows(universe.get('funds'))
    rows, source_id, source_url = public_rows, RANK_SOURCE_ID, RANK_SOURCE_URL
    scope = '天天基金公开排行样本；A/C 等份额按独立六位代码计数，并非支付宝全部在售基金'
    fallback = False
    usable = _usable(rows, reference_day)
    if not usable:
        history_rows = _fund_rows(snapshot.get('funds'), history=True)
        history_usable = _usable(history_rows, reference_day)
        if history_usable or (not rows and history_rows):
            rows, usable, fallback = history_rows, history_usable, True
            source_id, source_url = SNAPSHOT_SOURCE_ID, SNAPSHOT_SOURCE_URL
            scope = '本次深入研究的有限基金样本；A/C 等份额按独立六位代码计数，不代表全市场或支付宝全部在售基金'
    dates = Counter(row['nav_date'] for row in usable)
    selected_day = max(dates, key=lambda day: (dates[day], day)) if dates else None
    selected = [row for row in usable if row['nav_date'] == selected_day] if selected_day else []
    excluded = Counter()
    for row in rows:
        day = row['nav_date']
        if reference_day is None:
            excluded['missing_reference_date'] += 1
        elif day is None:
            excluded['missing_nav_date'] += 1
        elif day > reference_day:
            excluded['future_nav_date'] += 1
        elif (reference_day - day).days >= 7:
            excluded['stale_nav_date'] += 1
        elif row['return_1d'] is None:
            excluded['missing_daily_return'] += 1
        elif day != selected_day:
            excluded['other_nav_date'] += 1
    counts = Counter(_bucket(row['return_1d']) for row in selected)
    total, scope_count = len(selected), len(rows)
    buckets = [{'id': item[0], 'label': item[1], 'count': counts[i],
                'percent': round(100 * counts[i] / total, 2) if total else 0.0,
                'direction': item[2]} for i, item in enumerate(BUCKETS)]
    up = sum(row['return_1d'] > 0 for row in selected)
    down = sum(row['return_1d'] < 0 for row in selected)
    flat = total - up - down
    coverage = universe.get('coverage')
    complete = isinstance(coverage, dict) and coverage.get('complete') is True
    if not total:
        status = 'insufficient'
        reason = ('研究快照日期缺失，无法确定可比净值日期' if reference_day is None else
                  '近 7 个自然日内没有可核验的单日收益样本，暂不绘制涨跌分布')
    else:
        status = 'ok' if not fallback and complete and total == scope_count else 'partial'
        prefix = '公开排行缺少可用日收益，改用有限深入研究样本。' if fallback else ''
        reason = (f'{prefix}采用 {selected_day.isoformat()} 披露的日收益，共 {total} 个份额代码；'
                  f'排除 {scope_count - total} 个日期不同、过期或日收益缺失的份额，未混合不同净值日期')
        if not fallback and not complete:
            reason += '；公开排行覆盖未确认完整'
    valid_dates = [row['nav_date'] for row in usable]
    as_of = reference.isoformat() if reference else None
    breadth = {'status': status, 'scope': scope, 'total': total,
               'scope_count': scope_count, 'covered_count': total, 'excluded_count': scope_count - total,
               'up': up, 'down': down, 'flat': flat, 'buckets': buckets, 'as_of': as_of,
               'nav_date': selected_day.isoformat() if selected_day else None,
               'date_range': {'min': min(valid_dates).isoformat() if valid_dates else None,
                              'max': max(valid_dates).isoformat() if valid_dates else None},
               'reason': reason, 'source_id': source_id, 'source_url': source_url,
               'excluded_reasons': dict(excluded)}
    return {'as_of': as_of, 'indices': _indices(snapshot, reference), 'breadth': breadth}
