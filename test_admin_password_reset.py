"""Administrator password recovery against isolated accounts and HTTP servers."""
import json
import unittest

import test_cloud_accounts as accounts_tests
from research_accounts import AccountError, password_matches


NEW_PASSWORD = 'new isolated recovery password'


class AdminResetStoreTests(unittest.TestCase):
    setUp = accounts_tests.AccountsTests.setUp

    def member(self):
        return self.store.create_user('member', accounts_tests.PASSWORD)

    def reset(self, member, password=NEW_PASSWORD, actor=None):
        return self.store.reset_password_by_admin(
            (actor or self.admin)['id'], member['id'], password)

    def test_reset_revokes_target_sessions_and_preserves_personal_data(self):
        member = self.member()
        other = self.store.create_user('other', accounts_tests.PASSWORD)
        member_tokens = [self.store.issue_session(member['id'])[0] for _ in range(2)]
        admin_token = self.store.issue_session(self.admin['id'])[0]
        other_token = self.store.issue_session(other['id'])[0]
        self.store.watchlist(member['id'], 'test-sector', 'add')
        report = {'research_scope':'sectors', 'as_of':'2026-11-01T09:20:00+08:00',
                  'sector_analysis':[], 'summary':'retained research'}
        self.store.archive_report(report)
        self.store.history(member['id'], [report['as_of']])
        self.store.subscriptions.manage(self.admin['id'], member['id'], 'grant',
            'reset-test-grant-0001', credits=3, days=30)
        subscription = self.store.subscriptions.summary(member['id'])
        with self.store.connection() as db:
            before = dict(db.execute('SELECT * FROM users WHERE id=?', (member['id'],)).fetchone())

        self.reset(member)

        self.assertTrue(all(self.store.session(token) is None for token in member_tokens))
        self.assertIsNotNone(self.store.session(admin_token))
        self.assertIsNotNone(self.store.session(other_token))
        self.assertEqual(self.store.login('member', NEW_PASSWORD), member)
        with self.assertRaises(AccountError):
            self.store.login('member', accounts_tests.PASSWORD)
        self.assertEqual(self.store.watchlist(member['id']), ['test-sector'])
        self.assertEqual(self.store.historical_report(member['id'], report['as_of']), report)
        self.assertEqual(self.store.subscriptions.summary(member['id']), subscription)
        with self.store.connection() as db:
            after = dict(db.execute('SELECT * FROM users WHERE id=?', (member['id'],)).fetchone())
        self.assertNotIn(NEW_PASSWORD, after['password_hash'])
        self.assertTrue(password_matches(NEW_PASSWORD, after['password_hash']))
        self.assertNotEqual(before.pop('password_hash'), after.pop('password_hash'))
        self.assertEqual(before, after)

    def test_only_active_admin_may_reset_member(self):
        member = self.member()
        with self.assertRaises(AccountError) as error:
            self.reset(member, actor=member)
        self.assertEqual(error.exception.status, 403)
        with self.store.connection() as db:
            db.execute('UPDATE users SET disabled=1 WHERE id=?', (self.admin['id'],))
        with self.assertRaises(AccountError) as error:
            self.reset(member)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.store.login('member', accounts_tests.PASSWORD), member)

    def test_admin_targets_and_missing_accounts_are_rejected(self):
        second = self.store.create_admin_account('second_admin', accounts_tests.PASSWORD)
        for target in (self.admin, second):
            with self.assertRaises(AccountError) as error:
                self.reset(target)
            self.assertEqual(error.exception.status, 403)
        with self.assertRaises(AccountError) as error:
            self.reset({'id':'missing-account'})
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.store.login('second_admin', accounts_tests.PASSWORD), second)

    def test_invalid_password_or_target_does_not_revoke_existing_session(self):
        member = self.member()
        token = self.store.issue_session(member['id'])[0]
        for password in ('short', 'x' * 129, None):
            with self.assertRaises(AccountError):
                self.reset(member, password)
        for target in (None, [], {}):
            with self.assertRaises(AccountError):
                self.store.reset_password_by_admin(self.admin['id'], target, NEW_PASSWORD)
        self.assertIsNotNone(self.store.session(token))
        self.assertEqual(self.store.login('member', accounts_tests.PASSWORD), member)

    def test_reset_keeps_disabled_accounts_disabled_and_blocks_late_old_login(self):
        member = self.member()
        with self.store.connection() as db:
            credential = db.execute('SELECT password_hash FROM users WHERE id=?',
                                    (member['id'],)).fetchone()[0]
        self.reset(member)
        with self.assertRaises(AccountError):
            self.store.issue_session(member['id'], credential=credential)
        with self.store.connection() as db:
            db.execute('UPDATE users SET disabled=1 WHERE id=?', (member['id'],))
        self.reset(member)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT disabled FROM users WHERE id=?',
                                       (member['id'],)).fetchone()[0], 1)
        with self.assertRaises(AccountError):
            self.store.login('member', NEW_PASSWORD)


class AdminResetHTTPTests(unittest.TestCase):
    setUp = accounts_tests.CloudHTTPTests.setUp
    cleanup = accounts_tests.CloudHTTPTests.cleanup
    request = accounts_tests.CloudHTTPTests.request
    sign = accounts_tests.CloudHTTPTests.sign
    path = '/api/admin/reset-password'

    def body(self):
        return {'user_id':self.server.accounts.login('member', accounts_tests.PASSWORD)['id'],
                'new_password':NEW_PASSWORD}

    def test_admin_reset_revokes_all_target_logins_without_affecting_admin(self):
        body = self.body()
        second_cookie, _ = self.sign('/api/auth/login', 'member')
        status, value, _ = self.request(self.path, body, self.admin_cookie, self.admin_csrf)
        self.assertEqual(status, 200, value)
        self.assertTrue(value['ok'])
        self.assertNotIn(NEW_PASSWORD, json.dumps(value))
        for cookie in (self.member_cookie, second_cookie):
            self.assertEqual(self.request('/api/auth/me', cookie=cookie)[0], 401)
        self.assertEqual(self.request('/api/auth/me', cookie=self.admin_cookie)[0], 200)
        self.assertEqual(self.request('/api/auth/login',
            {'username':'member', 'password':NEW_PASSWORD})[0], 200)
        self.assertEqual(self.request('/api/auth/login',
            {'username':'member', 'password':accounts_tests.PASSWORD})[0], 401)

    def test_login_admin_role_origin_and_csrf_are_required(self):
        body = self.body()
        self.assertEqual(self.request(self.path, body)[0], 401)
        self.assertEqual(self.request(self.path, body, self.member_cookie, self.member_csrf)[0], 403)
        self.assertEqual(self.request(self.path, body, self.admin_cookie)[0], 403)
        self.assertEqual(self.request(self.path, body, self.admin_cookie, 'wrong')[0], 403)
        self.assertEqual(self.request(self.path, body, self.admin_cookie, self.admin_csrf,
                                     {'Origin':'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/auth/me', cookie=self.member_cookie)[0], 200)
        self.server.accounts.login('member', accounts_tests.PASSWORD)

    def test_malformed_request_invalid_password_and_admin_target_fail_without_change(self):
        body = self.body()
        admin = self.server.accounts.login('owner', accounts_tests.PASSWORD)
        second = self.server.accounts.create_admin_account('second_admin', accounts_tests.PASSWORD)
        for invalid in ({}, {**body, 'unexpected':True}, {**body, 'new_password':'short'},
                        {**body, 'new_password':'x' * 129}, {**body, 'user_id':None}):
            self.assertEqual(self.request(self.path, invalid, self.admin_cookie, self.admin_csrf)[0], 400)
        self.assertEqual(self.request(self.path, {**body, 'user_id':admin['id']},
                                     self.admin_cookie, self.admin_csrf)[0], 400)
        self.assertEqual(self.request(self.path, {**body, 'user_id':second['id']},
                                     self.admin_cookie, self.admin_csrf)[0], 403)
        self.assertEqual(self.request(self.path, {**body, 'user_id':'missing'},
                                     self.admin_cookie, self.admin_csrf)[0], 404)
        self.assertEqual(self.request('/api/auth/me', cookie=self.member_cookie)[0], 200)
        self.server.accounts.login('member', accounts_tests.PASSWORD)


if __name__ == '__main__':
    unittest.main()
