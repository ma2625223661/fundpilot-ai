"""Optional real SMS verification. No development codes, logging or fake sends."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3

from research_accounts import AccountError, USERNAME, digest_token, password_hash, password_matches

CODE_SECONDS = 300
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5


def normalize_phone(value):
    if not isinstance(value, str) or len(value) > 24:
        raise AccountError('请输入中国大陆 11 位手机号')
    value = value.strip()
    if value.startswith('+86'):
        value = value[3:]
    if not re.fullmatch(r'1[3-9][0-9]{9}', value):
        raise AccountError('请输入中国大陆 11 位手机号')
    return value


def mask_phone(value):
    return value[:3] + '****' + value[-4:]


class AliyunSmsSender:
    """Official 4.6 SDK, fixed HTTPS destination, no automatic paid retries."""
    def __init__(self, environment):
        from alibabacloud_dysmsapi20170525.client import Client
        from alibabacloud_tea_openapi.utils_models import Config
        from darabonba.runtime import RuntimeOptions
        from alibabacloud_dysmsapi20170525.models import SendSmsRequest
        self.request_type, self.runtime_type = SendSmsRequest, RuntimeOptions
        self.sign = environment['FUNDPILOT_SMS_SIGN_NAME']
        self.template = environment['FUNDPILOT_SMS_TEMPLATE_CODE']
        config = Config(access_key_id=environment['ALIBABA_CLOUD_ACCESS_KEY_ID'],
                        access_key_secret=environment['ALIBABA_CLOUD_ACCESS_KEY_SECRET'],
                        endpoint='dysmsapi.aliyuncs.com', protocol='HTTPS', region_id='cn-hangzhou')
        self.client = Client(config)

    def __call__(self, phone, code, purpose):
        request = self.request_type(phone_numbers=phone, sign_name=self.sign,
            template_code=self.template, template_param=json.dumps({'code':code}))
        response = self.client.send_sms_with_options(request,
            self.runtime_type(autoretry=False, connect_timeout=5000, read_timeout=8000))
        if not response.body or response.body.code != 'OK':
            raise AccountError('短信发送未成功，请稍后重试或联系管理员', 503)


class PhoneAuth:
    def __init__(self, accounts, environ=None, sender=None):
        self.accounts = accounts
        env = os.environ if environ is None else environ
        self.sender, self.secret = None, (env.get('FUNDPILOT_SMS_OTP_SECRET') or '').encode()
        self.required_setting = env.get('FUNDPILOT_PHONE_REGISTRATION_REQUIRED')
        self.state = 'unconfigured'
        if sender is not None:
            if len(self.secret) < 32:
                raise ValueError('SMS OTP secret must contain at least 32 bytes')
            self.sender, self.state = sender, 'ready'
        elif env.get('FUNDPILOT_SMS_ENABLED') == '1':
            self.state = 'configuration_error'
            values = ('ALIBABA_CLOUD_ACCESS_KEY_ID','ALIBABA_CLOUD_ACCESS_KEY_SECRET',
                      'FUNDPILOT_SMS_SIGN_NAME','FUNDPILOT_SMS_TEMPLATE_CODE')
            if (env.get('FUNDPILOT_SMS_PROVIDER') == 'aliyun' and len(self.secret) >= 32
                    and all(isinstance(env.get(key),str) and env[key].strip() for key in values)
                    and re.fullmatch(r'SMS_[0-9]+',env['FUNDPILOT_SMS_TEMPLATE_CODE'])):
                try:
                    self.sender = AliyunSmsSender(env)
                    self.state = 'ready'
                except Exception:
                    pass
        with accounts.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS user_phones (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    phone TEXT NOT NULL UNIQUE, verified_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sms_challenges (
                    id TEXT PRIMARY KEY, phone_hash TEXT NOT NULL, purpose TEXT NOT NULL,
                    user_id TEXT NOT NULL, code_hash TEXT NOT NULL, state TEXT NOT NULL,
                    expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sms_challenge_phone ON sms_challenges(phone_hash,purpose);
            ''')

    @property
    def required(self):
        return self.required_setting != '0' if self.required_setting is not None else self.state != 'unconfigured'

    def status(self):
        ready = self.sender is not None
        message = ('注册时验证手机号，验证码 5 分钟有效；已绑定用户也可使用短信登录。' if ready else
                   '短信验证暂未开通，当前可使用用户名和密码注册、登录。')
        if self.required and not ready:
            message = '当前要求手机号验证，但短信服务尚未就绪；新用户注册暂不可用，请联系管理员。'
        return {'available':ready, 'registration_required':self.required, 'state':self.state,
                'message':message, 'expires_in':CODE_SECONDS, 'retry_after':RESEND_SECONDS}

    def _ready(self):
        if self.sender is None:
            raise AccountError('短信验证暂未开通，请联系管理员配置短信服务', 503)

    def _hash(self, *values):
        return hmac.new(self.secret,json.dumps(values,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

    def summary(self, user_id):
        with self.accounts.connection() as db:
            row = db.execute('SELECT phone,verified_at FROM user_phones WHERE user_id=?',(user_id,)).fetchone()
        return {**self.status(),'bound':bool(row),'phone_masked':mask_phone(row['phone']) if row else '',
                'verified_at':row['verified_at'] if row else None}

    def send(self, phone, purpose, ip, user_id=''):
        self._ready()
        phone = normalize_phone(phone)
        if purpose not in ('register','login','bind') or (purpose == 'bind') != bool(user_id):
            raise AccountError('验证码用途无效')
        phone_hash, now = self._hash('phone',phone), self.accounts.clock()
        # Count paid attempts before I/O, including failures and uncertain sends.
        for bucket, limit, period in (
            ('sms-ip-hour:'+digest_token(ip),10,3600),('sms-ip-day:'+digest_token(ip),30,86400),
            ('sms-global-day',200,86400),('sms-phone-minute:'+phone_hash,1,60),
            ('sms-phone-hour:'+phone_hash,5,3600),('sms-phone-day:'+phone_hash,10,86400)):
            self.accounts.rate_limit(bucket,limit,period)
        challenge, code = secrets.token_urlsafe(32), f'{secrets.randbelow(1000000):06d}'
        deliver = True
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if purpose == 'bind':
                user = db.execute('SELECT disabled FROM users WHERE id=?',(user_id,)).fetchone()
                if not user or user['disabled']:
                    raise AccountError('请重新登录',401)
                if db.execute('SELECT 1 FROM user_phones WHERE user_id=?',(user_id,)).fetchone():
                    raise AccountError('当前账号已绑定手机号，无需重复绑定',409)
            elif purpose == 'login':
                deliver = bool(db.execute('SELECT 1 FROM user_phones JOIN users ON users.id=user_phones.user_id '
                                          'WHERE phone=? AND disabled=0',(phone,)).fetchone())
            db.execute("UPDATE sms_challenges SET state='used' WHERE phone_hash=? AND purpose=? AND user_id=?",
                       (phone_hash,purpose,user_id))
            db.execute('DELETE FROM sms_challenges WHERE created<?',(now-86400,))
            db.execute('INSERT INTO sms_challenges VALUES (?,?,?,?,?,?,?,?,?)',
                       (challenge,phone_hash,purpose,user_id,self._hash(challenge,phone,purpose,user_id,code),
                        'pending',now+CODE_SECONDS,0,now))
        try:
            if deliver:
                self.sender(phone,code,purpose)
        except Exception:
            with self.accounts.connection() as db:
                db.execute("UPDATE sms_challenges SET state='failed' WHERE id=?",(challenge,))
            # Provider exceptions may contain a phone number, code or credential.
            raise AccountError('短信发送未成功，请稍后重试或联系管理员',503) from None
        with self.accounts.connection() as db:
            db.execute("UPDATE sms_challenges SET state='sent' WHERE id=? AND state='pending'",(challenge,))
        return {'challenge_id':challenge,'expires_in':CODE_SECONDS,'retry_after':RESEND_SECONDS,
                'message':('若该手机号已绑定账号，验证码将通过短信发送，5 分钟内有效。' if purpose == 'login'
                           else '验证码请求已提交，请查收短信，5 分钟内有效。')}

    def _consume(self, db, phone, challenge, code, purpose, user_id=''):
        """Return an error so failed-attempt increments commit, not roll back."""
        if not isinstance(challenge,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',challenge):
            return AccountError('验证码无效或已过期，请重新获取')
        row = db.execute('SELECT * FROM sms_challenges WHERE id=?',(challenge,)).fetchone()
        if (not row or row['state'] != 'sent' or row['expires'] <= self.accounts.clock()
                or row['purpose'] != purpose or row['user_id'] != user_id
                or row['phone_hash'] != self._hash('phone',phone) or row['attempts'] >= MAX_ATTEMPTS):
            return AccountError('验证码无效或已过期，请重新获取')
        db.execute('UPDATE sms_challenges SET attempts=attempts+1 WHERE id=?',(challenge,))
        if (not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code)
                or not hmac.compare_digest(row['code_hash'],self._hash(challenge,phone,purpose,user_id,code))):
            remaining = MAX_ATTEMPTS-row['attempts']-1
            return AccountError(f'验证码不正确，还可尝试 {remaining} 次' if remaining else '验证码已失效，请重新获取')
        db.execute("UPDATE sms_challenges SET state='used' WHERE id=?",(challenge,))
        return None

    def register(self, username, password, phone, challenge, code):
        self._ready()
        phone = normalize_phone(phone)
        if not isinstance(username,str) or not USERNAME.fullmatch(username):
            raise AccountError('用户名需为 3～32 位字母、数字或下划线')
        encoded = password_hash(password)
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            error = self._consume(db,phone,challenge,code,'register')
            if not error:
                if db.execute('SELECT 1 FROM user_phones WHERE phone=?',(phone,)).fetchone():
                    raise AccountError('该手机号暂不可用于新注册，请使用登录入口',409)
                user = self.accounts._create_user(db,username,encoded)
                db.execute('INSERT INTO user_phones VALUES (?,?,?)',(user['id'],phone,self.accounts.clock()))
        if error:
            raise error
        return user

    def login(self, phone, challenge, code):
        self._ready()
        phone = normalize_phone(phone)
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            error = self._consume(db,phone,challenge,code,'login')
            row = None if error else db.execute('SELECT users.* FROM users JOIN user_phones ON users.id=user_phones.user_id '
                                                'WHERE phone=? AND disabled=0',(phone,)).fetchone()
            if not error and not row:
                error = AccountError('手机号或验证码不正确',401)
        if error:
            raise error
        user = self.accounts.user(row)
        # A concurrent password reset or disable cannot issue a late session.
        return user,self.accounts.issue_session(user['id'],credential=row['password_hash'])

    def bind(self, user_id, password, phone, challenge, code):
        self._ready()
        phone = normalize_phone(phone)
        with self.accounts.connection() as db:
            row = db.execute('SELECT password_hash,disabled FROM users WHERE id=?',(user_id,)).fetchone()
        if not row or row['disabled']:
            raise AccountError('请重新登录',401)
        if not password_matches(password,row['password_hash']):
            raise AccountError('当前密码不正确')
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT password_hash,disabled FROM users WHERE id=?',(user_id,)).fetchone()
            if not current or current['disabled'] or current['password_hash'] != row['password_hash']:
                raise AccountError('账号状态已变化，请重新登录',401)
            error = self._consume(db,phone,challenge,code,'bind',user_id)
            if not error:
                try:
                    db.execute('INSERT INTO user_phones VALUES (?,?,?)',(user_id,phone,self.accounts.clock()))
                except sqlite3.IntegrityError:
                    raise AccountError('该手机号或当前账号已绑定，请勿重复绑定',409) from None
        if error:
            raise error
        return self.summary(user_id)
