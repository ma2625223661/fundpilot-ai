"""Persistent accounts, opaque sessions and account-scoped research records."""
import gzip
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


# A username is either a short handle or an email address (at most 64 characters,
# the login lookup limit). Email addresses are not verified by this service.
USERNAME = re.compile(
    r'(?:[a-zA-Z0-9_]{3,32}'
    r'|(?=[^@]{1,64}@)(?=.{6,64}\Z)[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?'
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24})\Z')
USERNAME_RULE = '用户名需为 3～32 位字母、数字或下划线，或不超过 64 个字符的邮箱地址'
SESSION_SECONDS = 7 * 86400
IDLE_SECONDS = 86400
_PASSWORD_SLOTS = threading.BoundedSemaphore(2)


class AccountError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def password_hash(password, salt=None):
    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AccountError(f'密码需为 {MIN_PASSWORD_LENGTH}～{MAX_PASSWORD_LENGTH} 个字符，可包含中文、空格和符号')
    salt = salt or secrets.token_bytes(16)
    # OWASP scrypt profile: 32 MiB, three passes. Bound concurrent memory use.
    if not _PASSWORD_SLOTS.acquire(timeout=1):
        raise AccountError('登录服务繁忙，请稍后重试', 503)
    try:
        digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768,
                                r=8, p=3, dklen=32, maxmem=64 * 1024 * 1024)
    finally:
        _PASSWORD_SLOTS.release()
    return 'scrypt$32768$8$3$' + salt.hex() + '$' + digest.hex()


def password_matches(password, encoded):
    valid_input = isinstance(password, str) and MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    if not valid_input:
        # Match the ordinary expensive failure path without hashing huge input.
        password = 'invalid-password-input'
    salt = bytes.fromhex(encoded.split('$')[4])
    matches = hmac.compare_digest(password_hash(password, salt), encoded)
    return valid_input and matches


def digest_token(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class AccountStore:
    def __init__(self, path, clock=time.time, max_users=500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.max_users = clock, max_users
        # Unknown-user verification performs the same scrypt work as a known user.
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))
        with self.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, role TEXT NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL,
                watchlist TEXT NOT NULL DEFAULT '[]');
              CREATE TABLE IF NOT EXISTS sessions (
                digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf TEXT NOT NULL, created REAL NOT NULL, seen REAL NOT NULL, expires REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
              CREATE TABLE IF NOT EXISTS attempts (
                bucket TEXT PRIMARY KEY, since REAL NOT NULL, count INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, payload BLOB NOT NULL, summary TEXT NOT NULL,
                sectors INTEGER NOT NULL, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS records (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, payload BLOB, PRIMARY KEY(user_id, report_id));
            ''')
            # Older installations keep their record IDs/order. A nullable
            # personal snapshot prevents another account replacing old evidence.
            if 'payload' not in {row['name'] for row in db.execute('PRAGMA table_info(records)')}:
                db.execute('ALTER TABLE records ADD COLUMN payload BLOB')
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        from research_subscriptions import SubscriptionStore
        self.subscriptions = SubscriptionStore(self)
        from research_review import ReviewStore
        self.reviews = ReviewStore(self)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def needs_setup(self):
        with self.connection() as db:
            return not db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()

    @staticmethod
    def user(row):
        return {'id': row['id'], 'username': row['username'], 'role': row['role']}

    def rate_limit(self, bucket, maximum, period):
        now = self.clock()
        rejected = False
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT since,count FROM attempts WHERE bucket=?', (bucket,)).fetchone()
            since, count = (row['since'], row['count']) if row and row['since'] > now - period else (now, 0)
            rejected = count >= maximum
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (bucket, since, count + 1))
            db.execute('DELETE FROM attempts WHERE since<?', (now - 86400,))
        if rejected:
            raise AccountError('尝试次数过多，请稍后再试', 429)

    def create_user(self, username, password, admin=False):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise AccountError(USERNAME_RULE)
        encoded = password_hash(password)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._create_user(db, username, encoded, admin)

    def _create_user(self, db, username, encoded, admin=False):
        """Allow verified phone registration to commit with its one-use code."""
        if admin and db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            raise AccountError('管理员已创建，请使用登录入口', 409)
        if not admin and not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            raise AccountError('请先完成管理员初始化', 409)
        if db.execute('SELECT count(*) FROM users').fetchone()[0] >= self.max_users:
            raise AccountError('当前注册名额已满，请联系管理员', 409)
        user = {'id': secrets.token_hex(16), 'username': username, 'role': 'admin' if admin else 'member'}
        try:
            db.execute('INSERT INTO users(id,username,password_hash,role,created) VALUES (?,?,?,?,?)',
                       (user['id'], username, encoded, user['role'], self.clock()))
        except sqlite3.IntegrityError:
            raise AccountError('该用户名暂不可用，请换一个', 409) from None
        return user

    def create_admin_account(self, username, password):
        """Create the second administrator; plaintext passwords never leave this method."""
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise AccountError(USERNAME_RULE)
        encoded = password_hash(password)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0]
            if count == 0:
                raise AccountError('请先完成首个管理员初始化', 409)
            if count >= 2:
                raise AccountError('最多只能有 2 个管理员账号', 409)
            if db.execute('SELECT count(*) FROM users').fetchone()[0] >= self.max_users:
                raise AccountError('当前注册名额已满，请联系管理员', 409)
            user = {'id': secrets.token_hex(16), 'username': username, 'role': 'admin'}
            try:
                db.execute('INSERT INTO users(id,username,password_hash,role,created) VALUES (?,?,?,?,?)',
                           (user['id'], username, encoded, 'admin', self.clock()))
            except sqlite3.IntegrityError:
                raise AccountError('该用户名暂不可用，请换一个', 409) from None
        return user

    def reset_password_by_admin(self, actor_id, user_id, new_password):
        """Reset a member credential without changing their account or subscription."""
        if not isinstance(actor_id, str) or not isinstance(user_id, str):
            raise AccountError('请选择需要重置密码的普通用户')
        encoded = password_hash(new_password)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = db.execute('SELECT role,disabled FROM users WHERE id=?', (actor_id,)).fetchone()
            if not actor or actor['role'] != 'admin' or actor['disabled']:
                raise AccountError('仅管理员可重置用户密码', 403)
            target = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
            if not target:
                raise AccountError('账号不存在', 404)
            if target['role'] != 'member':
                raise AccountError('仅支持重置普通用户密码；管理员请在账号设置中修改自己的密码', 403)
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def login(self, username, password, with_session=False):
        if not isinstance(username, str) or len(username) > 64:
            username = ''
        self.rate_limit('login:' + digest_token(username.casefold()), 10, 600)
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
        matches = password_matches(password, row['password_hash'] if row else self.dummy_hash)
        if not row or not matches or row['disabled']:
            raise AccountError('用户名或密码不正确', 401)
        with self.connection() as db:
            db.execute('DELETE FROM attempts WHERE bucket=?', ('login:' + digest_token(username.casefold()),))
        user = self.user(row)
        if with_session:
            return user, self.issue_session(row['id'], credential=row['password_hash'])
        return user

    def issue_session(self, user_id, credential=None):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT password_hash,disabled FROM users WHERE id=?', (user_id,)).fetchone()
            if not user or user['disabled'] or credential is not None and user['password_hash'] != credential:
                raise AccountError('账号状态已变化，请重新登录', 401)
            db.execute('DELETE FROM sessions WHERE expires<? OR seen<?', (now, now - IDLE_SECONDS))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)',
                       (digest_token(token), user_id, csrf, now, now, now + SESSION_SECONDS))
            # Bound session growth; a user may stay signed in on five devices.
            db.execute('DELETE FROM sessions WHERE user_id=? AND digest NOT IN '
                       '(SELECT digest FROM sessions WHERE user_id=? ORDER BY created DESC,rowid DESC LIMIT 5)', (user_id, user_id))
        return token, csrf

    def session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        now = self.clock()
        with self.connection() as db:
            row = db.execute('SELECT users.*, sessions.csrf, sessions.seen, sessions.expires FROM sessions '
                             'JOIN users ON users.id=sessions.user_id WHERE sessions.digest=?', (digest_token(token),)).fetchone()
            if not row or row['disabled'] or row['expires'] <= now or row['seen'] <= now - IDLE_SECONDS:
                return None
            if now - row['seen'] > 60:
                db.execute('UPDATE sessions SET seen=? WHERE digest=?', (now, digest_token(token)))
        return {**self.user(row), 'csrf_token': row['csrf']}

    def logout(self, token):
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE digest=?', (digest_token(token),))

    def change_password(self, user_id, old_password, new_password):
        with self.connection() as db:
            row = db.execute('SELECT password_hash FROM users WHERE id=?', (user_id,)).fetchone()
        if not row or not password_matches(old_password, row['password_hash']):
            raise AccountError('原密码不正确', 401)
        encoded = password_hash(new_password)
        with self.connection() as db:
            # Another password change cannot be overwritten with an old credential.
            result = db.execute('UPDATE users SET password_hash=? WHERE id=? AND password_hash=?',
                                (encoded, user_id, row['password_hash']))
            if result.rowcount != 1:
                raise AccountError('账号密码已变化，请重新登录', 409)
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def watchlist(self, user_id, board_id=None, action=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT watchlist FROM users WHERE id=?', (user_id,)).fetchone()
            values = json.loads(row['watchlist'])
            if action == 'add' and board_id not in values:
                if len(values) >= 100:
                    raise AccountError('最多关注 100 个板块')
                values.append(board_id)
            elif action == 'remove':
                values = [value for value in values if value != board_id]
            if action:
                db.execute('UPDATE users SET watchlist=? WHERE id=?', (json.dumps(values), user_id))
        return values

    def archive_report(self, report):
        with self.connection() as db:
            self._archive_report(db,report)

    def _archive_report(self, db, report, replace=False, protected_id=None):
        """Archive inside the caller's transaction, including paid completions."""
        if not isinstance(report, dict) or report.get('research_scope') != 'sectors':
            return False
        report_id = report.get('as_of')
        if not isinstance(report_id, str) or not 1 <= len(report_id) <= 64:
            return False
        if not replace and db.execute('SELECT 1 FROM reports WHERE id=?', (report_id,)).fetchone():
            return True
        payload = json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(payload) > 20 * 1024 * 1024:
            return False
        compressed = gzip.compress(payload, compresslevel=3, mtime=0)
        statement = ('INSERT INTO reports VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                     'payload=excluded.payload,summary=excluded.summary,sectors=excluded.sectors') if replace else \
                    'INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?)'
        db.execute(statement,(report_id,compressed,str(report.get('summary') or '')[:500],
                              len(report.get('sector_analysis',[])),self.clock()))
        db.execute('DELETE FROM reports WHERE id NOT IN (SELECT id FROM reports ORDER BY created DESC LIMIT 40) '
                   'AND id NOT IN (SELECT report_id FROM records WHERE payload IS NOT NULL) AND id!=?',
                   (protected_id or '',))
        return True

    def _remember_report(self, db, user_id, report):
        """Promote one completed report using the existing personal-20 limit."""
        if not self._archive_report(db,report,protected_id=report.get('as_of')):
            raise AccountError('研究结果无法完整保存，本次未扣减额度，请稍后重试',503)
        report_id=report['as_of']
        payload=json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        if len(payload)>20*1024*1024:
            raise AccountError('研究结果无法完整保存，本次未扣减额度，请稍后重试',503)
        snapshot=gzip.compress(payload,compresslevel=3,mtime=0)
        previous=[(row['report_id'],row['payload']) for row in db.execute(
            'SELECT report_id,payload FROM records WHERE user_id=? AND report_id!=? ORDER BY position LIMIT 19',
            (user_id,report_id))]
        db.execute('DELETE FROM records WHERE user_id=?',(user_id,))
        for position,(identity,saved) in enumerate([(report_id,snapshot),*previous]):
            db.execute('INSERT INTO records(user_id,report_id,position,payload) VALUES (?,?,?,?)',
                       (user_id,identity,position,saved))

    def history(self, user_id, report_ids=None):
        with self.connection() as db:
            if report_ids is not None:
                if not isinstance(report_ids, list) or len(report_ids) > 20 or any(
                        not isinstance(value, str) or len(value) > 64 for value in report_ids):
                    raise AccountError('研究记录格式无效')
                db.execute('BEGIN IMMEDIATE')
                snapshots={row['report_id']:row['payload'] for row in db.execute(
                    'SELECT report_id,payload FROM records WHERE user_id=?',(user_id,))}
                db.execute('DELETE FROM records WHERE user_id=?', (user_id,))
                for position, report_id in enumerate(dict.fromkeys(report_ids)):
                    if db.execute('SELECT 1 FROM reports WHERE id=?', (report_id,)).fetchone():
                        db.execute('INSERT INTO records(user_id,report_id,position,payload) VALUES (?,?,?,?)',
                                   (user_id,report_id,position,snapshots.get(report_id)))
            rows = db.execute('SELECT reports.id,summary,sectors FROM records JOIN reports ON reports.id=records.report_id '
                              'WHERE user_id=? ORDER BY position LIMIT 20', (user_id,)).fetchall()
        return [{'cloud_record': True, 'research_scope': 'sectors', 'as_of': row['id'],
                 'summary': row['summary'], 'sector_count': row['sectors']} for row in rows]

    def historical_report(self, user_id, report_id):
        with self.connection() as db:
            row = db.execute('SELECT coalesce(records.payload,reports.payload) AS payload,records.payload IS NOT NULL AS personal_snapshot '
                             'FROM records JOIN reports ON reports.id=records.report_id '
                             'WHERE user_id=? AND report_id=?', (user_id, report_id)).fetchone()
        if not row:
            raise AccountError('该研究记录不存在或已过期', 404)
        report=json.loads(gzip.decompress(row['payload']))
        if row['personal_snapshot']:
            report['_personal_record_snapshot']=True
        return report
