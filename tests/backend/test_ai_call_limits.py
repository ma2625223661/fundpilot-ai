"""Per-user daily and monthly limits on personal AI calls (issue #5).

Every model response is a local fixture. The limits sit on top of points:
a call needs both. Only a completed call that actually asked the model counts;
missing limits, failures and reused interpretations never use a call.
"""
import time
import unittest
from datetime import datetime
from unittest.mock import Mock

from research_accounts import AccountError
from research_subscriptions import BEIJING, call_period, quota_message
import test_manual_sector_ai as manual


class CallLimitTests(unittest.TestCase):
    # Reuse the manual-research fixture (accounts, engine, report, fake model).
    # Imported through the module so the runner does not collect those tests twice.
    setUp = manual.ManualResearchTests.setUp
    finish = manual.ManualResearchTests.finish
    run_job = manual.ManualResearchTests.run_job

    def limits(self, daily, monthly, request):
        return self.sub.manage(self.admin['id'], self.user['id'], 'limits', request + '-request-id',
                               daily_limit=daily, monthly_limit=monthly)

    def quota(self):
        return self.sub.summary(self.user['id'])['call_quota']

    def test_member_without_limits_cannot_start_and_nothing_is_counted(self):
        with self.accounts.connection() as db:
            db.execute('DELETE FROM ai_call_limits WHERE user_id=?', (self.user['id'],))
        quota = self.quota()
        self.assertEqual((quota['configured'], quota['can_call']), (False, False))
        with self.assertRaisesRegex(AccountError, '尚未设置你的每日和每月 AI 调用次数'):
            self.jobs.start(self.user['id'], 'sector_0', self.report['as_of'], 'medium')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'], 5)

    def test_daily_limit_blocks_the_next_call_and_names_both_remaining_counts(self):
        self.limits(1, 9, 'limits-one-a-day')
        first = self.run_job('medium', 'sector_0')
        self.assertEqual(first['status'], 'completed', first)
        quota = first['subscription']['call_quota']
        self.assertEqual((quota['daily_used'], quota['daily_remaining'], quota['monthly_remaining']), (1, 0, 8))
        with self.assertRaises(AccountError) as caught:
            self.jobs.start(self.user['id'], 'sector_1', self.report['as_of'], 'medium')
        self.assertIn('今日剩余 0 次，本月剩余 8 次', str(caught.exception))
        self.assertIn('未发起请求', str(caught.exception))
        self.assertEqual(len(self.calls), 1)

    def test_monthly_limit_holds_across_days_while_the_daily_count_resets(self):
        now = [time.time()]
        self.accounts.clock = lambda: now[0]
        self.limits(1, 1, 'limits-monthly-one')
        self.assertEqual(self.run_job('medium', 'sector_0')['status'], 'completed')
        # Next Beijing day: the daily count is back, the monthly total is not,
        # unless the day also starts a new month.
        now[0] += 86400
        day, month = call_period(now[0])
        quota = self.quota()
        self.assertEqual(quota['daily_used'], 0)
        if month == call_period(now[0] - 86400)[1]:
            self.assertEqual(quota['monthly_remaining'], 0)
            with self.assertRaisesRegex(AccountError, '本月 AI 调用次数已用完'):
                self.jobs.start(self.user['id'], 'sector_1', self.report['as_of'], 'medium')

    def test_failed_calls_and_reused_interpretations_do_not_count(self):
        self.limits(3, 30, 'limits-failure')
        self.jobs.requester = Mock(side_effect=TimeoutError('fixture-only'))
        self.assertEqual(self.run_job('medium', 'sector_0')['status'], 'failed')
        self.assertEqual(self.quota()['daily_used'], 0)
        self.jobs.requester = self.send
        # After a timeout the same evidence is held back for 30 minutes, so use the other sector.
        self.assertEqual(self.run_job('medium', 'sector_1')['status'], 'completed')
        # Opening the same, already unlocked interpretation again asks no model.
        again = self.run_job('medium', 'sector_1')
        self.assertFalse(again['charged'])
        self.assertEqual(self.quota()['daily_used'], 1)
        self.assertEqual(len(self.calls), 1)

    def test_changing_limits_applies_at_once_and_keeps_used_calls(self):
        self.limits(1, 10, 'limits-before')
        self.run_job('medium', 'sector_0')
        self.assertEqual(self.quota()['daily_remaining'], 0)
        self.limits(3, 10, 'limits-raised')
        quota = self.quota()
        self.assertEqual((quota['daily_used'], quota['daily_remaining'], quota['monthly_remaining']), (1, 2, 9))
        self.assertEqual(self.run_job('medium', 'sector_1')['status'], 'completed')
        ledger = [row for row in self.sub.ledger(self.user['id']) if row['kind'] == 'limits']
        self.assertIn('每日 3 次 · 每月 10 次', ledger[0]['note'])
        # Points and expiry are untouched by a limit change.
        self.assertEqual(self.sub.summary(self.user['id'])['credits_remaining'], 3)

    def test_limit_validation_and_who_can_set_them(self):
        with self.assertRaisesRegex(AccountError, '每月调用总次数不能少于每日调用次数'):
            self.limits(5, 4, 'limits-inverted')
        with self.assertRaisesRegex(AccountError, '每日调用次数需为'):
            self.limits(-1, 4, 'limits-negative')
        with self.assertRaisesRegex(AccountError, '每月调用总次数需为'):
            self.limits(1, 1.5, 'limits-fraction')
        with self.assertRaisesRegex(AccountError, '请选择普通用户账号'):
            self.sub.manage(self.admin['id'], self.admin['id'], 'limits', 'limits-admin-request-id', daily_limit=1, monthly_limit=1)
        with self.assertRaisesRegex(AccountError, '仅管理员'):
            self.sub.manage(self.other['id'], self.user['id'], 'limits', 'limits-member-request-id', daily_limit=1, monthly_limit=1)
        admin = self.sub.summary(self.admin['id'])['call_quota']
        self.assertEqual((admin['unlimited'], admin['can_call']), (True, True))

    def test_periods_follow_beijing_time_and_messages(self):
        # 2026-11-30 16:30 UTC is already 2026-12-01 00:30 in Beijing.
        moment = datetime(2026, 12, 1, 0, 30, tzinfo=BEIJING).timestamp()
        self.assertEqual(call_period(moment), ('2026-12-01', '2026-12'))
        self.assertEqual(quota_message({'unlimited': True}), '')
        message = quota_message({'configured': True, 'daily_remaining': 2, 'monthly_remaining': 0})
        self.assertIn('本月 AI 调用次数已用完（今日剩余 2 次，本月剩余 0 次）', message)


if __name__ == '__main__':
    unittest.main()
