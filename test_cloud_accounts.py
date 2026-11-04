import concurrent.futures
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from cloud_server import CloudAIConfigStore, create_cloud_server
from research_accounts import AccountError, AccountStore, IDLE_SECONDS, SESSION_SECONDS, password_hash, password_matches

PASSWORD = 'test password for isolated tests'


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000000
        self.store = AccountStore(Path(self.tmp.name) / 'accounts.db', clock=lambda: self.now)
        self.admin = self.store.create_user('owner', PASSWORD, admin=True)

    def test_hashes_are_salted_and_not_plaintext(self):
        first, second = password_hash(PASSWORD), password_hash(PASSWORD)
        self.assertNotEqual(first, second)
        self.assertNotIn(PASSWORD, first)
        self.assertTrue(password_matches(PASSWORD, first))
        self.assertFalse(password_matches('another long password', first))
        self.assertFalse(password_matches(None, password_hash('invalid-password-input')))
        for value in ['short', 'x' * 7, 'x' * 129, None]:
            with self.assertRaises(AccountError):
                password_hash(value)

    def test_eight_character_passwords_are_the_minimum_for_everyone(self):
        eight = 'pass1234'
        self.assertTrue(password_matches(eight, password_hash(eight)))
        self.assertFalse(password_matches('pass123', password_hash(eight)))
        user = self.store.create_user('member8', eight)
        self.assertEqual(self.store.login('member8', eight)['id'], user['id'])
        with self.assertRaises(AccountError) as ctx:
            self.store.create_user('member7', 'x' * 7)
        self.assertIn('8～128', str(ctx.exception))

    def test_login_and_case_insensitive_unique_name(self):
        self.assertEqual(self.store.login('OWNER', PASSWORD), self.admin)
        with self.assertRaises(AccountError):
            self.store.create_user('Owner', PASSWORD)
        errors = []
        for name in ['owner', 'nobody']:
            with self.assertRaises(AccountError) as ctx:
                self.store.login(name, 'wrong password long enough')
            errors.append(str(ctx.exception))
        self.assertEqual(errors[0], errors[1])

    def test_bootstrap_is_atomic(self):
        other = AccountStore(Path(self.tmp.name) / 'new.db')
        def setup(i):
            try:
                return other.create_user('admin_' + str(i), PASSWORD, admin=True)['role']
            except AccountError:
                return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(setup, range(2))), ['admin', 'conflict'])
        self.assertEqual(other.create_user('member', PASSWORD)['role'], 'member')

    def test_sessions_expire_logout_password_and_device_limit(self):
        tokens = [self.store.issue_session(self.admin['id'])[0] for _ in range(6)]
        self.assertIsNone(self.store.session(tokens[0]))
        self.assertEqual(sum(self.store.session(t) is not None for t in tokens), 5)
        with self.store.connection() as db:
            self.assertNotIn(tokens[-1], str([tuple(row) for row in db.execute('SELECT * FROM sessions')]))
        self.store.logout(tokens[-1]); self.assertIsNone(self.store.session(tokens[-1]))
        self.store.change_password(self.admin['id'], PASSWORD, 'a new test password here')
        self.assertTrue(all(self.store.session(t) is None for t in tokens))
        token, _ = self.store.issue_session(self.admin['id'])
        self.now += IDLE_SECONDS
        self.assertIsNone(self.store.session(token))
        token, _ = self.store.issue_session(self.admin['id'])
        with self.store.connection() as db:
            db.execute('UPDATE sessions SET seen=?,expires=?', (self.now, self.now))
        self.assertIsNone(self.store.session(token))

    def test_personal_data_isolation_and_persistence(self):
        second = self.store.create_user('member', PASSWORD)
        self.store.watchlist(self.admin['id'], 'test-sector', 'add')
        self.assertEqual(self.store.watchlist(second['id']), [])
        report = {'research_scope':'sectors', 'as_of':'2026-10-31T10:00:00+08:00', 'sector_analysis':[], 'summary':'shared'}
        self.store.archive_report(report)
        self.store.history(self.admin['id'], [report['as_of']])
        self.assertEqual(self.store.historical_report(self.admin['id'], report['as_of']), report)
        with self.assertRaises(AccountError):
            self.store.historical_report(second['id'], report['as_of'])
        self.assertEqual(self.store.history(second['id']), [])
        reopened = AccountStore(self.store.path)
        self.assertEqual(reopened.watchlist(self.admin['id']), ['test-sector'])
        self.assertEqual(len(reopened.history(self.admin['id'])), 1)
        reopened.history(self.admin['id'], [])
        self.assertEqual(reopened.history(self.admin['id']), [])

    def test_atomic_completed_record_uses_existing_personal_twenty_limit(self):
        for index in range(22):
            report={'research_scope':'sectors','as_of':'report-'+str(index),'sector_analysis':[],
                    'summary':'saved '+str(index)}
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                self.store._remember_report(db,self.admin['id'],report)
        rows=self.store.history(self.admin['id'])
        self.assertEqual(len(rows),20)
        self.assertEqual(rows[0]['as_of'],'report-21')
        self.assertEqual(rows[-1]['as_of'],'report-2')
        self.assertEqual(self.store.historical_report(self.admin['id'],'report-21')['summary'],'saved 21')

    def test_legacy_record_payload_migration_is_additive_and_repeatable(self):
        path=Path(self.tmp.name)/'legacy-records.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('CREATE TABLE records(user_id TEXT NOT NULL,report_id TEXT NOT NULL,'
                             'position INTEGER NOT NULL,PRIMARY KEY(user_id,report_id));')
            db.execute('INSERT INTO records VALUES (?,?,?)',('old-user','old-report',7))
        AccountStore(path)
        reopened=AccountStore(path)
        with reopened.connection() as db:
            columns=[row['name'] for row in db.execute('PRAGMA table_info(records)')]
            self.assertEqual(columns.count('payload'),1)
            row=db.execute('SELECT * FROM records WHERE user_id=?',('old-user',)).fetchone()
            self.assertEqual((row['report_id'],row['position'],row['payload']),('old-report',7,None))

    def test_personal_snapshot_survives_public_archive_rotation_and_is_released_on_clear(self):
        report={'research_scope':'sectors','as_of':'paid-old-report','sector_analysis':[],
                'summary':'personal snapshot'}
        # Old completion timestamps must survive their initial insert even if
        # forty newer shared reports already exist.
        for index in range(42):
            self.now+=1
            self.store.archive_report({'research_scope':'sectors','as_of':'public-'+str(index),'sector_analysis':[]})
        self.now=1
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._remember_report(db,self.admin['id'],report)
        for index in range(42,84):
            self.now=1000000+index
            self.store.archive_report({'research_scope':'sectors','as_of':'public-'+str(index),'sector_analysis':[]})
        self.assertEqual(self.store.historical_report(self.admin['id'],report['as_of'])['summary'],'personal snapshot')
        self.assertEqual(self.store.history(self.admin['id'])[0]['as_of'],report['as_of'])
        self.store.history(self.admin['id'],[])
        self.now+=1
        self.store.archive_report({'research_scope':'sectors','as_of':'public-last','sector_analysis':[]})
        with self.store.connection() as db:
            self.assertFalse(db.execute('SELECT 1 FROM reports WHERE id=?',(report['as_of'],)).fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM records WHERE user_id=?',(self.admin['id'],)).fetchone())
        with self.assertRaises(AccountError):self.store.historical_report(self.admin['id'],report['as_of'])

    def test_rate_limit(self):
        for _ in range(10):
            with self.assertRaises(AccountError) as ctx:
                self.store.login('unknown', PASSWORD)
            self.assertEqual(ctx.exception.status, 401)
        with self.assertRaises(AccountError) as ctx:
            self.store.login('unknown', PASSWORD)
        self.assertEqual(ctx.exception.status, 429)
        self.now += 601
        with self.assertRaises(AccountError) as ctx:
            self.store.login('unknown', PASSWORD)
        self.assertEqual(ctx.exception.status, 401)

    def test_changed_credential_cannot_issue_late_session(self):
        with self.store.connection() as db:
            credential=db.execute('SELECT password_hash FROM users WHERE id=?',(self.admin['id'],)).fetchone()[0]
        self.store.change_password(self.admin['id'],PASSWORD,'a newer password for race test')
        with self.assertRaises(AccountError):
            self.store.issue_session(self.admin['id'],credential=credential)
        user,(token,csrf)=self.store.login('owner','a newer password for race test',with_session=True)
        self.assertEqual(self.store.session(token)['id'],user['id'])
        self.assertEqual(self.store.session(token)['csrf_token'],csrf)


class CloudHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = create_cloud_server(port=0, state_dir=self.tmp.name, development=True, environ={})
        self.server.auto_engine = Mock()
        self.server.auto_engine.status.return_value = {'status':'idle','has_report':False}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.cleanup)
        self.origin = self.server.public_url
        self.admin_cookie, self.admin_csrf = self.sign('/api/auth/setup', 'owner')
        self.member_cookie, self.member_csrf = self.sign('/api/auth/register', 'member')

    def cleanup(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def request(self, path, body=None, cookie=None, csrf=None, extra=None, method=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Origin':self.origin}
        if cookie: headers['Cookie'] = cookie
        if csrf: headers['X-CSRF-Token'] = csrf
        if body is not None: headers['Content-Type'] = 'application/json'
        headers.update(extra or {})
        connection.request(method or ('POST' if body is not None else 'GET'), path,
                           body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = connection.getresponse(); raw = response.read(); response_headers = dict(response.getheaders()); status = response.status
        connection.close()
        try: value = json.loads(raw)
        except (ValueError, UnicodeError): value = raw
        return status, value, response_headers

    def sign(self, path, username):
        status, value, headers = self.request(path, {'username':username,'password':PASSWORD,'role':'admin'})
        self.assertEqual(status, 200, value)
        return headers['Set-Cookie'].split(';')[0], value['csrf_token']

    def test_authentication_boundary_and_static(self):
        for path in ['/api/auto/report','/api/me/watchlist','/session-context.js','/api/ai/config']:
            self.assertEqual(self.request(path)[0],401,path)
        self.assertEqual(self.request('/index.html')[0],302)
        self.assertEqual(self.request('/login.html')[0],200)
        self.assertEqual(self.request('/login.js', method='HEAD')[1],b'')
        self.assertEqual(self.request('/api/health')[0],200)
        for path in ['/../cloud_server.py','/data/accounts.sqlite3','/%69ndex.html/']:
            self.assertNotEqual(self.request(path,cookie=self.member_cookie)[0],200,path)
        self.assertEqual(self.request('//index.html')[0],302)
        status, html, _ = self.request('/index.html',cookie=self.member_cookie)
        self.assertEqual(status,200)
        self.assertLess(html.index(b'session-context.js'), html.index(b'cloud-account.js'))
        self.assertIn(b'cloud-session.js',html)

    def test_origin_host_csrf_and_forwarded_are_not_trusted(self):
        path = '/api/me/watchlist'
        body = {'board_id':'semiconductor','action':'add'}
        self.assertEqual(self.request(path,body,self.member_cookie)[0],403)
        self.assertEqual(self.request(path,body,self.member_cookie,'wrong')[0],403)
        self.assertEqual(self.request(path,body,self.member_cookie,self.member_csrf,{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/auth/me',cookie=self.member_cookie,extra={'Host':'evil.example','X-Forwarded-Host':self.origin})[0],403)
        self.assertEqual(self.request(path,body,self.member_cookie,'é')[0],403)

    def test_public_support_page_does_not_unlock_research_or_accounts(self):
        for path in ['/ai-service.html','/ai-service.css','/qq-support.png']:
            status,body,headers=self.request(path)
            self.assertEqual(status,200,path)
            self.assertGreater(len(body),100)
        for path in ['/api/auto/report','/api/me/watchlist','/api/me/history','/session-context.js']:
            self.assertEqual(self.request(path)[0],401,path)
        self.assertEqual(self.request('/index.html')[0],302)

    def test_members_cannot_change_public_research(self):
        me = self.request('/api/auth/me',cookie=self.member_cookie)[1]
        self.assertEqual(me['role'],'member')
        for path in ['/api/auto/refresh','/api/ai/config','/api/ai/test','/api/data/test','/api/data/public/test','/api/admin/user-state']:
            self.assertEqual(self.request(path,{},self.member_cookie,self.member_csrf)[0],403,path)
        self.server.auto_engine.request_scan.assert_not_called()
        self.assertEqual(self.request('/api/admin/users',cookie=self.member_cookie)[0],403)
        self.assertEqual(self.request('/api/auth/setup',{'username':'new_admin','password':PASSWORD})[0],409)

    def test_watchlist_and_history_cannot_select_other_account(self):
        from research_categories import BOARDS
        board = next(iter(BOARDS))
        self.assertEqual(self.request('/api/me/watchlist',{'board_id':board,'action':'add','user_id':'forged'},self.admin_cookie,self.admin_csrf)[0],200)
        self.assertEqual(self.request('/api/me/watchlist',cookie=self.member_cookie)[1]['items'],[])
        report = {'research_scope':'sectors','as_of':'2026-10-31T10:00:00+08:00','sector_analysis':[]}
        self.server.auto_engine.status.return_value = {'report':report}
        self.assertEqual(self.request('/api/auto/report',cookie=self.member_cookie)[1]['report'],report)
        self.assertEqual(self.request('/api/me/history',{'report_ids':[report['as_of']]},self.admin_cookie,self.admin_csrf)[0],200)
        self.assertEqual(self.request('/api/me/history/report?as_of='+report['as_of'],cookie=self.member_cookie)[0],404)
        self.assertEqual(self.request('/api/me/history',{},self.admin_cookie,self.admin_csrf)[0],400)

    def test_logout_password_change_and_disable_revoke(self):
        login_cookie, login_csrf = self.sign('/api/auth/login','member')
        self.assertEqual(self.request('/api/auth/logout',{},login_cookie,login_csrf)[0],200)
        self.assertEqual(self.request('/api/auth/me',cookie=login_cookie)[0],401)
        self.assertEqual(self.request('/api/auth/password',{'old_password':PASSWORD,'new_password':'a newer long test password'},self.member_cookie,self.member_csrf)[0],200)
        self.assertEqual(self.request('/api/auth/me',cookie=self.member_cookie)[0],401)
        member = self.server.accounts.login('member','a newer long test password')
        token, _ = self.server.accounts.issue_session(member['id'])
        self.assertEqual(self.request('/api/admin/user-state',{'user_id':member['id'],'disabled':True},self.admin_cookie,self.admin_csrf)[0],200)
        self.assertIsNone(self.server.accounts.session(token))

    def test_duplicate_headers_and_large_body_fail_closed(self):
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.putrequest('POST','/api/auth/login')
        connection.putheader('Origin',self.origin); connection.putheader('Content-Type','application/json')
        connection.putheader('Content-Length','2'); connection.putheader('Content-Length','3');connection.endheaders(b'{}')
        response = connection.getresponse();self.assertEqual(response.status,400);response.read();connection.close()
        self.assertEqual(self.request('/api/auth/login',{'payload':'x'*9000})[0],400)
        self.assertEqual(self.request('/api/auth/me',cookie=self.member_cookie+'; '+self.member_cookie)[0],401)


class ProductionTests(unittest.TestCase):
    def test_https_and_setup_token_required(self):
        with tempfile.TemporaryDirectory() as folder:
            for origin, env in [('http://example.com',{}),('https://example.com',{})]:
                with self.assertRaises(RuntimeError):
                    create_cloud_server(0, folder, origin, environ=env)
            service = create_cloud_server(0,folder,'https://example.com',environ={'FUNDPILOT_SETUP_TOKEN':'s'*40})
            self.addCleanup(service.server_close)
            # Inspect generated production cookies without network/TLS infrastructure.
            from cloud_server import CloudHandler
            handler = object.__new__(CloudHandler); handler.server=service
            cookie=handler.cookie('token')
            for flag in ['Secure','HttpOnly','SameSite=Lax']:
                self.assertIn(flag,cookie)

    def test_service_key_not_persisted_or_returned(self):
        with tempfile.TemporaryDirectory() as folder:
            key='sk-unit-test-service-secret-123456789'
            path=Path(folder)/'settings.json'
            store=CloudAIConfigStore(path,{'DEEPSEEK_API_KEY':key},probe=lambda k,m:{'models':[m]})
            self.assertNotIn(key,json.dumps(store.status()))
            store.configure(enabled=True)
            store.verify()
            self.assertNotIn(key,path.read_text())
            restored=CloudAIConfigStore(path,{'DEEPSEEK_API_KEY':key})
            self.assertTrue(restored.snapshot()['enabled'])
            with self.assertRaises(ValueError): store.configure(key='other')


if __name__ == '__main__': unittest.main()
