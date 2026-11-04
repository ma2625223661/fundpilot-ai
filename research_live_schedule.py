"""Free quote collection is independent of the paid AI admission windows."""
from datetime import datetime, timedelta

from research_data import CHINA
from research_trading_calendar import is_trading_day, next_trading_day

INTERVAL_SECONDS = 300
SESSIONS = ((9, 30, 11, 30), (13, 0, 15, 0))


def slots(day):
    for hour, minute, end_hour, end_minute in SESSIONS:
        current = datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHINA)
        end = current.replace(hour=end_hour, minute=end_minute)
        while current <= end:
            yield current
            current += timedelta(seconds=INTERVAL_SECONDS)
    # Providers may publish final closing bars a few minutes after 15:00.
    yield datetime(day.year, day.month, day.day, 15, 5, tzinfo=CHINA)


def quote_due(now, last_attempt=None):
    """Catch only the current five-minute slot, including a closing snapshot.

    No backlog after lunch, a holiday or shutdown. Attempts, rather than paid
    completions, prevent failed/slow collection from creating a retry storm.
    """
    now = now.astimezone(CHINA)
    if is_trading_day(now) is not True:
        return None
    recent = [s for s in slots(now.date()) if s <= now < s + timedelta(seconds=INTERVAL_SECONDS)]
    due = recent[-1] if recent else None
    return due if due and (last_attempt is None or last_attempt < due) else None


def next_quote_time(now, last_attempt=None):
    now = now.astimezone(CHINA)
    due = quote_due(now, last_attempt)
    if due:
        return now
    day = next_trading_day(now)
    while day is not None:
        for due in slots(day):
            if due > now and (last_attempt is None or due > last_attempt):
                return due
        day = next_trading_day(day, inclusive=False)
    return None


def presentation(now):
    now = now.astimezone(CHINA)
    opened = is_trading_day(now)
    if opened is None:
        return 'calendar_pending', '交易日历待核验'
    if not opened:
        return 'closed', '休市 · 展示最近有效行情'
    minute = now.hour * 60 + now.minute
    if 570 <= minute < 690 or 780 <= minute < 900:
        return 'trading', '盘中动态更新'
    if 690 <= minute < 780:
        return 'lunch', '午间休市'
    return ('before_open', '等待开盘') if minute < 570 else ('closed', '已收盘 · 展示最近有效行情')
