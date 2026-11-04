"""Pure Beijing-time scheduling for optional automatic AI research."""
from datetime import datetime, timedelta

from research_data import CHINA
from research_trading_calendar import is_trading_day, next_trading_day

DEFAULT_SCHEDULE = {'mode': 'interval', 'interval_minutes': 30,
                    'daily_time': '15:30', 'end_time': None, 'timezone': 'Asia/Shanghai'}
MARKET_SCHEDULE = {**DEFAULT_SCHEDULE, 'mode': 'market_sessions', 'daily_time': '09:20'}
MARKET_SESSIONS = (('09:20', '09:30'), ('14:50', '15:00'))


def default_market_schedule():
    return dict(MARKET_SCHEDULE)


def market_session_start(now):
    """Identify an admitted slot, with a bounded window for slow collection."""
    now = now.astimezone(CHINA)
    if is_trading_day(now) is not True:
        return None
    for start_text, end_text in MARKET_SESSIONS:
        hour, minute = map(int, start_text.split(':'))
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        hour, minute = map(int, end_text.split(':'))
        end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now < end:
            return start
    return None


def market_due_is_current(due, now):
    """A persisted morning/yesterday slot must not replay in another slot."""
    return due is not None and due == market_session_start(now)


def schedule_settings(config):
    return {**DEFAULT_SCHEDULE, **(config.get('schedule') or {})}


def schedule_signature(config):
    setting = schedule_settings(config)
    signature = [config.get('revision', config.get('generation')), bool(config.get('enabled')),
                 setting['mode'], setting['interval_minutes'], setting['daily_time'], setting['timezone']]
    # An old persisted six-item signature must compare equal after this schema
    # update. A null stop time is exactly the previous unbounded schedule.
    if setting.get('end_time') is not None:
        signature.append(setting['end_time'])
    return signature


def _window(setting, now):
    """Return the current/next daily start and its exclusive end in Beijing."""
    hour, minute = map(int, setting['daily_time'].split(':'))
    end_hour, end_minute = map(int, setting['end_time'].split(':'))
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if end <= start:
        # An overnight window before today's end started yesterday.
        if now < end:
            start -= timedelta(days=1)
        else:
            end += timedelta(days=1)
    if now >= end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end


def schedule_allows_run(setting, now):
    """Whether a new AI request is inside the configured [start, end) window."""
    if setting['mode'] == 'market_sessions':
        return market_session_start(now) is not None
    if setting['mode'] == 'interval' or setting.get('end_time') is None:
        return True
    now = now.astimezone(CHINA)
    start, end = _window(setting, now)
    return start <= now < end


def schedule_stop_time(setting, now):
    """Return the active window's exclusive end, or None outside/no window."""
    if setting['mode'] == 'market_sessions':
        start = market_session_start(now)
        if start is None:
            return None
        return start.replace(hour=9, minute=30) if start.hour == 9 else start.replace(hour=15, minute=0)
    if setting['mode'] == 'interval' or setting.get('end_time') is None:
        return None
    now = now.astimezone(CHINA)
    start, end = _window(setting, now)
    return end if start <= now < end else None


def scheduled_time(setting, now, *, after_run=False):
    """Return first/next slot; intervals start after completion, never catch up."""
    now = now.astimezone(CHINA)
    if setting['mode'] == 'market_sessions':
        day = next_trading_day(now)
        while day is not None:
            for start_text, _ in MARKET_SESSIONS:
                hour, minute = map(int, start_text.split(':'))
                due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHINA)
                if due > now or (due == now and not after_run):
                    return due
            day = next_trading_day(day, inclusive=False)
        return None
    if setting['mode'] == 'scheduled_interval' and setting.get('end_time') is not None:
        start, end = _window(setting, now)
        if now < start:
            return start
        due = now + timedelta(minutes=setting['interval_minutes']) if after_run else now
        return due if due < end else start + timedelta(days=1)
    if setting['mode'] == 'interval' or (after_run and setting['mode'] == 'scheduled_interval'):
        return now + timedelta(minutes=setting['interval_minutes']) if after_run else now
    hour, minute = map(int, setting['daily_time'].split(':'))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due < now or (after_run and due <= now):
        due += timedelta(days=1)
    return due


def parse_schedule_time(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.astimezone(CHINA) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None
