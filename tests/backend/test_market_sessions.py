"""Calendar and session admission, all offline with a controlled clock."""
import unittest
import copy
from datetime import date, datetime, timedelta
from unittest.mock import patch

from research_ai_config import validate_schedule
from research_schedule import (MARKET_SCHEDULE, default_market_schedule,
                               market_due_is_current, scheduled_time,
                               schedule_allows_run, schedule_stop_time)
from research_trading_calendar import (calendar_status, is_trading_day,
                                       next_trading_day, register_trade_calendar,
                                       a_share_quote_fresh, last_closed_trading_day)


def at(value):
    return datetime.fromisoformat(value + '+08:00')


class TradingCalendarTests(unittest.TestCase):
    def test_sse_holidays_and_makeup_working_weekends_remain_closed(self):
        for text in ['2026-01-01', '2026-02-23', '2026-04-06', '2026-05-05',
                     '2026-06-19', '2026-09-25', '2026-10-07', '2026-10-10']:
            self.assertIs(is_trading_day(text), False, text)
        self.assertIs(is_trading_day('2026-10-08'), True)

    def test_october_31_weekend_advances_to_november_2(self):
        self.assertEqual(next_trading_day('2026-10-31'), date(2026, 11, 2))
        self.assertEqual(next_trading_day('2026-10-30', inclusive=False), date(2026, 11, 2))

    def test_unverified_year_never_assumes_weekday_is_open(self):
        self.assertIsNone(is_trading_day('2027-01-04'))
        self.assertIsNone(next_trading_day('2027-01-04'))
        self.assertEqual(calendar_status('2027-01-04')['status'], 'unavailable')
        self.assertEqual(calendar_status('2026-11-02')['status'], 'verified')

    def test_quote_clock_checks_current_session_lunch_holiday_and_unknown_year(self):
        self.assertEqual(last_closed_trading_day('2026-10-08T09:10:00+08:00'), '2026-09-30')
        self.assertTrue(a_share_quote_fresh('2026-09-30T15:00:00+08:00', '2026-10-08T09:10:00+08:00'))
        self.assertFalse(a_share_quote_fresh('2026-09-30T15:00:00+08:00', '2026-10-08T14:30:00+08:00'))
        self.assertTrue(a_share_quote_fresh('2026-09-30', '2026-10-08T14:30:00+08:00', daily=True))
        self.assertTrue(a_share_quote_fresh('2026-10-08T11:30:00+08:00', '2026-10-08T12:30:00+08:00'))
        self.assertTrue(a_share_quote_fresh('2026-10-08T12:00:00+08:00', '2026-10-08T12:30:00+08:00'))
        self.assertFalse(a_share_quote_fresh('2026-10-08T10:00:00+08:00', '2026-10-08T14:30:00+08:00'))
        self.assertFalse(a_share_quote_fresh('2026-10-08T15:00:00+08:00', '2026-10-08T14:30:00+08:00'))
        self.assertIsNone(last_closed_trading_day('2027-01-04T09:10:00+08:00'))
        self.assertFalse(a_share_quote_fresh('2026-12-31T15:00:00+08:00', '2027-01-04T09:10:00+08:00'))

    def test_partial_or_wrong_exchange_api_calendar_is_rejected(self):
        with self.assertRaises(ValueError):
            register_trade_calendar([{'exchange': 'SSE', 'cal_date': '20270104', 'is_open': 1}],
                                    2027, 'https://api.tushare.pro', '2026-10-31')
        with self.assertRaises(ValueError):
            register_trade_calendar([{'exchange': 'HKEX', 'cal_date': '20270104', 'is_open': 1}],
                                    2027, 'https://api.tushare.pro', '2026-10-31')
        self.assertIsNone(is_trading_day('2027-01-04'))

    def test_complete_calendar_can_be_registered_without_weekend_opening(self):
        import research_trading_calendar as module
        rows, day = [], date(2028, 1, 1)
        while day.year == 2028:
            rows.append({'exchange': 'SSE', 'cal_date': day.strftime('%Y%m%d'),
                         'is_open': int(day.weekday() < 5)})
            day += timedelta(days=1)
        with patch.dict(module._calendars, clear=False):
            register_trade_calendar(rows, 2028, 'https://api.tushare.pro', '2027-12-01')
            self.assertIs(is_trading_day('2028-01-03'), True)
            self.assertIs(is_trading_day('2028-01-01'), False)


class MarketSessionTests(unittest.TestCase):
    def test_fixed_times_and_beijing_timezone(self):
        setting = default_market_schedule()
        self.assertEqual(scheduled_time(setting, at('2026-10-31T00:00:00')).isoformat(),
                         '2026-11-02T09:20:00+08:00')
        self.assertEqual(scheduled_time(setting, datetime.fromisoformat('2026-11-02T01:00:00+00:00')),
                         at('2026-11-02T09:20:00'))
        self.assertEqual(scheduled_time(setting, at('2026-11-02T09:20:00')),
                         at('2026-11-02T09:20:00'))
        self.assertEqual(scheduled_time(setting, at('2026-11-02T09:20:00'), after_run=True),
                         at('2026-11-02T14:50:00'))

    def test_initial_start_does_not_catch_up_a_missed_slot(self):
        self.assertEqual(scheduled_time(MARKET_SCHEDULE, at('2026-11-02T09:20:01')),
                         at('2026-11-02T14:50:00'))
        self.assertEqual(scheduled_time(MARKET_SCHEDULE, at('2026-11-02T14:50:01')),
                         at('2026-11-03T09:20:00'))

    def test_run_windows_close_exclusively_and_never_admit_weekends(self):
        for text in ['2026-11-02T09:20:00', '2026-11-02T09:29:59',
                     '2026-11-02T14:50:00', '2026-11-02T14:59:59']:
            self.assertTrue(schedule_allows_run(MARKET_SCHEDULE, at(text)), text)
        for text in ['2026-11-02T09:19:59', '2026-11-02T09:30:00',
                     '2026-11-02T14:49:59', '2026-11-02T15:00:00',
                     '2026-10-31T09:20:00', '2026-10-01T09:20:00']:
            self.assertFalse(schedule_allows_run(MARKET_SCHEDULE, at(text)), text)
        self.assertEqual(schedule_stop_time(MARKET_SCHEDULE, at('2026-11-02T09:26:00')),
                         at('2026-11-02T09:30:00'))
        self.assertEqual(schedule_stop_time(MARKET_SCHEDULE, at('2026-11-02T14:51:00')),
                         at('2026-11-02T15:00:00'))

    def test_morning_reservation_cannot_replay_in_afternoon(self):
        self.assertFalse(market_due_is_current(at('2026-11-02T09:20:00'), at('2026-11-02T14:51:00')))
        self.assertFalse(market_due_is_current(at('2026-10-30T09:20:00'), at('2026-11-02T09:26:00')))
        self.assertTrue(market_due_is_current(at('2026-11-02T14:50:00'), at('2026-11-02T14:51:00')))

    def test_year_boundary_waits_for_verified_next_calendar(self):
        self.assertIsNone(scheduled_time(MARKET_SCHEDULE, at('2026-12-31T15:00:00')))
        self.assertIsNone(scheduled_time(MARKET_SCHEDULE, at('2027-01-04T09:00:00')))
        self.assertFalse(schedule_allows_run(MARKET_SCHEDULE, at('2027-01-04T09:20:00')))

    def test_market_mode_validates_and_canonicalizes_hidden_times(self):
        result = validate_schedule({**MARKET_SCHEDULE, 'daily_time': '15:30', 'end_time': '15:30'})
        self.assertEqual(result['daily_time'], '09:20')
        self.assertIsNone(result['end_time'])
        self.assertEqual(result['mode'], 'market_sessions')
        detached = default_market_schedule()
        detached['daily_time'] = '01:00'
        self.assertEqual(MARKET_SCHEDULE['daily_time'], '09:20')

    def test_legacy_wide_window_times_are_no_longer_admitted(self):
        for text in ['2026-11-02T09:10:00','2026-11-02T09:19:59',
                     '2026-11-02T14:30:00','2026-11-02T14:49:59']:
            self.assertFalse(schedule_allows_run(MARKET_SCHEDULE,at(text)),text)
        self.assertIsNone(schedule_stop_time(MARKET_SCHEDULE,at('2026-11-02T09:19:59')))
        self.assertIsNone(schedule_stop_time(MARKET_SCHEDULE,at('2026-11-02T14:49:59')))

    def test_request_gate_stops_at_end_and_cannot_spill_into_another_session(self):
        from research_auto import AutoResearchEngine
        from test_research_sector_ai import evidence
        for start,end in [('2026-11-02T09:20:00','2026-11-02T09:30:00'),
                          ('2026-11-02T09:20:00','2026-11-02T14:50:00'),
                          ('2026-11-02T14:50:00','2026-11-02T15:00:00')]:
            with self.subTest(start=start,end=end):
                clock=[at(start)];gates=[]
                class ControlledDateTime(datetime):
                    @classmethod
                    def now(cls,tz=None):
                        return clock[0] if tz is None else clock[0].astimezone(tz)
                config={'key':'offline-schedule-key','enabled':True,'revision':'fixed-slots',
                        'schedule':dict(MARKET_SCHEDULE)}
                def ai_runner(report,config,can_start_request,**options):
                    gates.append(can_start_request())
                    clock[0]=at(end)
                    gates.append(can_start_request())
                    output=copy.deepcopy(report)
                    output['ai_research']={'status':'completed','revision':config['revision']}
                    return output
                engine=AutoResearchEngine(research_scope='sectors',config_provider=lambda:config,
                    runner=lambda **kwargs:evidence(1),ai_runner=ai_runner)
                try:
                    with patch('research_auto.datetime',ControlledDateTime):
                        engine._run(None,False,config)
                    self.assertEqual(engine._state['status'],'ready')
                    self.assertEqual(gates,[True,False])
                finally:
                    engine.close()


if __name__ == '__main__':
    unittest.main()
