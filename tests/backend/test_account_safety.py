"""Issue #5 account fixes: failed logins are counted after the password check,
a history save with an expired report id is rejected as a whole, and older
records keep their shared report when the archive rotates."""
import tempfile
import unittest
from pathlib import Path

import test_cloud_accounts as http_tests
from research_accounts import AccountError, AccountStore


def report(as_of):
    return {'research_scope': 'sectors', 'as_of': as_of, 'summary': as_of, 'sector_analysis': []}


class AccountSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1_800_000_000.0]
        self.accounts = AccountStore(Path(self.tmp.name) / 'accounts.db', clock=lambda: self.now[0])
        self.accounts.create_user('owner', http_tests.PASSWORD, admin=True)
        self.user = self.accounts.create_user('reader', http_tests.PASSWORD)

    def test_wrong_passwords_cannot_lock_out_the_right_one(self):
        for _ in range(12):
            with self.assertRaises(AccountError):
                self.accounts.login('reader', 'wrong-password-1')
        # The owner still gets in with the right password, which also clears the count.
        self.assertEqual(self.accounts.login('reader', http_tests.PASSWORD)['username'], 'reader')
        with self.assertRaises(AccountError) as caught:
            self.accounts.login('reader', 'wrong-password-1')
        self.assertEqual(caught.exception.status, 401)

    def test_repeated_wrong_passwords_are_still_slowed_down(self):
        statuses = []
        for _ in range(12):
            try:
                self.accounts.login('reader', 'wrong-password-1')
            except AccountError as error:
                statuses.append(error.status)
        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10:], [429, 429])

    def test_a_save_with_an_expired_report_id_changes_nothing(self):
        for day in ('2026-11-19', '2026-11-20'):
            self.accounts.archive_report(report(day + 'T15:00:00+08:00'))
        kept = ['2026-11-20T15:00:00+08:00', '2026-11-19T15:00:00+08:00']
        self.accounts.history(self.user['id'], kept)
        with self.assertRaises(AccountError) as caught:
            self.accounts.history(self.user['id'], ['2026-11-20T15:00:00+08:00', '2025-01-01T15:00:00+08:00'])
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('本次未保存，原有记录未改动', str(caught.exception))
        self.assertEqual([row['as_of'] for row in self.accounts.history(self.user['id'])], kept)

    def test_records_keep_their_shared_report_when_the_archive_rotates(self):
        oldest = '2026-01-01T15:00:00+08:00'
        self.accounts.archive_report(report(oldest))
        self.accounts.history(self.user['id'], [oldest])
        for index in range(45):
            self.now[0] += 60
            self.accounts.archive_report(report(f'2026-02-01T15:{index:02d}:00+08:00'))
        self.assertEqual([row['as_of'] for row in self.accounts.history(self.user['id'])], [oldest])
        self.assertEqual(self.accounts.historical_report(self.user['id'], oldest)['as_of'], oldest)


if __name__ == '__main__':
    unittest.main()
