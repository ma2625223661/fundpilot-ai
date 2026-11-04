"""Verified A-share trading dates; unknown years are never presumed open.

The embedded calendar is transcribed from SSE's annual closure notice. Calendar
lookups are pure/local so polling or paid-request admission never needs HTTP.
"""
from datetime import date, datetime, timedelta
from threading import RLock

from research_data import CHINA

SSE_2026_NOTICE = 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'
_lock = RLock()


def _dates(start, end):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    while current <= last:
        yield current
        current += timedelta(days=1)


_CLOSURES_2026 = set()
for _start, _end in [('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'),
                      ('2026-04-04', '2026-04-06'), ('2026-05-01', '2026-05-05'),
                      ('2026-06-19', '2026-06-21'), ('2026-09-25', '2026-09-27'),
                      ('2026-10-01', '2026-10-07')]:
    _CLOSURES_2026.update(_dates(_start, _end))

_calendars = {2026: {
    'open_dates': frozenset(day for day in _dates('2026-01-01', '2026-12-31')
                            if day.weekday() < 5 and day not in _CLOSURES_2026),
    'source': '上海证券交易所 · 2026年部分节假日休市安排',
    'source_url': SSE_2026_NOTICE,
    'verified_at': '2026-10-31',
}}


def _day(value):
    if isinstance(value, datetime):
        return value.astimezone(CHINA).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def calendar_status(value=None):
    day = _day(value or datetime.now(CHINA))
    with _lock:
        calendar = _calendars.get(day.year)
        result = {'year': day.year, 'known_years': sorted(_calendars),
                  'timezone': 'Asia/Shanghai', 'exchange': 'SSE',
                  'status': 'verified' if calendar else 'unavailable',
                  'reason': '' if calendar else f'{day.year}年交易日历尚未核验，暂停自动付费研究。'}
        if calendar:
            result.update({key: calendar[key] for key in ('source', 'source_url', 'verified_at')})
        return result


def is_trading_day(value):
    """Return None for unverified years, including their ordinary weekdays."""
    day = _day(value)
    with _lock:
        calendar = _calendars.get(day.year)
        return day in calendar['open_dates'] if calendar else None


def next_trading_day(value, inclusive=True):
    day = _day(value) + timedelta(days=0 if inclusive else 1)
    for _ in range(370):
        open_ = is_trading_day(day)
        if open_ is None:
            return None
        if open_:
            return day
        day += timedelta(days=1)
    return None


def last_closed_trading_day(value):
    """Latest completed A-share session, or None across an unknown calendar."""
    try:
        now = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        now = now.replace(tzinfo=CHINA) if now.tzinfo is None else now.astimezone(CHINA)
    except (TypeError, ValueError):
        return None
    if is_trading_day(now.date()) is None:
        return None
    day = now.date() - timedelta(days=int(now.hour < 15))
    for _ in range(370):
        opened = is_trading_day(day)
        if opened is None:
            return None
        if opened:
            return day.isoformat()
        day -= timedelta(days=1)
    return None


def a_share_quote_fresh(value, as_of, daily=False, published_hour=None):
    """Check a dated close or live quote against verified exchange sessions.

    A long known closure does not expire the latest close. During an open
    session, a live feed must be from today and recent; daily series retain
    the latest completed session until today's close becomes available.
    """
    try:
        quote = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        now = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
        quote = quote.replace(tzinfo=CHINA) if quote.tzinfo is None else quote.astimezone(CHINA)
        now = now.replace(tzinfo=CHINA) if now.tzinfo is None else now.astimezone(CHINA)
    except (TypeError, ValueError):
        return False
    opened = is_trading_day(now.date())
    if opened is None or quote > now or not is_trading_day(quote.date()):
        return False
    current = (now.hour, now.minute, now.second)
    if not daily and opened and (9, 30, 0) <= current < (15, 0, 0):
        if quote.date() != now.date() or (quote.hour, quote.minute) < (9, 30):
            return False
        # The morning close remains the latest live observation over lunch.
        reference = now.replace(hour=11, minute=30, second=0, microsecond=0) if (11, 30, 0) <= current < (13, 0, 0) else now
        return (reference - quote).total_seconds() <= 1200
    expected = last_closed_trading_day(now.isoformat())
    if daily and published_hour is not None and expected == now.date().isoformat() and now.hour < published_hour:
        # Publisher end-of-day files (e.g. CSI bond indices) appear hours after
        # the close; until then the previous completed session is the latest.
        expected = last_closed_trading_day(now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
    return bool(expected and quote.date().isoformat() == expected
                and (len(str(value)) == 10 or quote.hour >= 15))


def register_trade_calendar(rows, year, source_url, fetched_at):
    """Accept a complete, internally fetched SSE trade_cal year atomically.

    The data-source connector may call this after an authenticated calendar
    request. A partial response, mixed exchange or malformed flags cannot turn
    an unknown year into an assumed Monday-Friday calendar.
    """
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise ValueError('交易日历年份无效')
    if not isinstance(rows, list) or not isinstance(source_url, str) or not source_url.startswith('https://'):
        raise ValueError('交易日历来源无效')
    expected = set(_dates(f'{year}-01-01', f'{year}-12-31'))
    seen, opened = set(), set()
    for row in rows:
        if not isinstance(row, dict) or row.get('exchange', 'SSE') != 'SSE':
            raise ValueError('交易日历交易所无效')
        text = str(row.get('cal_date', ''))
        try:
            day = datetime.strptime(text, '%Y%m%d').date() if len(text) == 8 else date.fromisoformat(text)
        except ValueError:
            raise ValueError('交易日历日期无效') from None
        flag = row.get('is_open')
        if day not in expected or day in seen or flag not in (0, 1, '0', '1') or isinstance(flag, bool):
            raise ValueError('交易日历内容不完整或无效')
        seen.add(day)
        if str(flag) == '1':
            if day.weekday() >= 5:
                raise ValueError('A股周末不得作为交易日')
            opened.add(day)
    if seen != expected or not opened:
        raise ValueError('交易日历必须覆盖完整年份')
    try:
        _day(fetched_at)
    except (ValueError, TypeError):
        raise ValueError('交易日历核验时间无效') from None
    with _lock:
        _calendars[year] = {'open_dates': frozenset(opened), 'source': '已验证 SSE 交易日历接口',
                            'source_url': source_url, 'verified_at': str(fetched_at)}
