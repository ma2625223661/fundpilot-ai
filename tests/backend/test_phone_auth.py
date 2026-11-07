import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from research_accounts import AccountError, AccountStore
from research_phone_auth import PhoneAuth, normalize_phone

PASSWORD='phone test password, isolated only'
PHONE='13800138000'
ENV={'FUNDPILOT_SMS_OTP_SECRET':'isolated-test-secret-'*3}


class PhoneAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000000
        self.accounts=AccountStore(Path(self.tmp.name)/'accounts.db',clock=lambda:self.now)
        self.admin=self.accounts.create_user('owner',PASSWORD,admin=True)
        self.sent=[]
        self.phone=PhoneAuth(self.accounts,ENV,sender=lambda *args:self.sent.append(args))

    def send(self,purpose='register',phone=PHONE,user_id=''):
        result=self.phone.send(phone,purpose,'test-ip',user_id)
        return result['challenge_id'],self.sent[-1][1]

    def register(self,name='member',phone=PHONE):
        challenge,code=self.send(phone=phone)
        return self.phone.register(name,PASSWORD,phone,challenge,code)

    def test_unconfigured_is_explicit_and_has_no_development_codes(self):
        empty=PhoneAuth(self.accounts,{})
        self.assertFalse(empty.status()['available']);self.assertFalse(empty.required)
        with self.assertRaises(AccountError) as error:empty.send(PHONE,'register','ip')
        self.assertEqual(error.exception.status,503)
        self.assertEqual(self.sent,[])
        for env in [{'FUNDPILOT_SMS_ENABLED':'1'}, {'FUNDPILOT_PHONE_REGISTRATION_REQUIRED':'1'},
                    {'FUNDPILOT_PHONE_REGISTRATION_REQUIRED':'typo'}]:
            phone=PhoneAuth(self.accounts,env)
            self.assertTrue(phone.required);self.assertFalse(phone.status()['available'])

    def test_validation_and_normalization(self):
        self.assertEqual(normalize_phone('+86'+PHONE),PHONE)
        for value in [None,123,PHONE+'x','12345678901','+1'+PHONE,'١٣٨٠٠١٣٨٠٠٠']:
            with self.assertRaises(AccountError):normalize_phone(value)

    def test_registration_is_verified_unique_and_one_use(self):
        challenge,code=self.send()
        self.assertNotIn('code',self.phone.status())
        with self.accounts.connection() as db:
            row=db.execute('SELECT * FROM sms_challenges').fetchone()
            self.assertEqual(len(row['code_hash']),64)
            self.assertNotEqual(row['code_hash'],code)
            self.assertNotEqual(row['phone_hash'],PHONE)
        member=self.phone.register('member',PASSWORD,PHONE,challenge,code)
        self.assertEqual(self.phone.summary(member['id'])['phone_masked'],'138****8000')
        self.assertNotIn(PHONE,str(self.phone.summary(member['id'])))
        with self.assertRaises(AccountError):self.phone.register('replay',PASSWORD,PHONE,challenge,code)
        self.now+=61
        second,code=self.send()
        with self.assertRaises(AccountError):self.phone.register('duplicate',PASSWORD,PHONE,second,code)
        with self.accounts.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],2)

    def test_five_bad_codes_lock_out_and_failure_counters_commit(self):
        challenge,code=self.send()
        wrong='000000' if code!='000000' else '111111'
        for _ in range(5):
            with self.assertRaises(AccountError):self.phone.register('member',PASSWORD,PHONE,challenge,wrong)
        with self.assertRaises(AccountError):self.phone.register('member',PASSWORD,PHONE,challenge,code)
        with self.accounts.connection() as db:
            self.assertEqual(db.execute('SELECT attempts FROM sms_challenges').fetchone()[0],5)
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],1)

    def test_expiry_resend_and_phone_and_purpose_binding(self):
        challenge,code=self.send()
        with self.assertRaises(AccountError):self.phone.send(PHONE,'register','different-ip')
        self.assertEqual(len(self.sent),1)
        with self.assertRaises(AccountError):self.phone.login(PHONE,challenge,code)
        with self.assertRaises(AccountError):self.phone.register('member',PASSWORD,'13900139000',challenge,code)
        self.now+=61
        newer,new_code=self.send()
        with self.assertRaises(AccountError):self.phone.register('member',PASSWORD,PHONE,challenge,code)
        self.now+=300
        with self.assertRaises(AccountError):self.phone.register('member',PASSWORD,PHONE,newer,new_code)

    def test_only_one_concurrent_registration_can_consume_a_code(self):
        challenge,code=self.send()
        def register(index):
            try:self.phone.register('member'+str(index),PASSWORD,PHONE,challenge,code);return 'ok'
            except AccountError:return 'rejected'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(register,range(2))),['ok','rejected'])

    def test_username_conflict_does_not_lose_verified_code_or_bind_to_wrong_account(self):
        challenge,code=self.send()
        with self.assertRaises(AccountError):self.phone.register('OWNER',PASSWORD,PHONE,challenge,code)
        member=self.phone.register('available',PASSWORD,PHONE,challenge,code)
        self.assertTrue(self.phone.summary(member['id'])['bound'])
        self.assertFalse(self.phone.summary(self.admin['id'])['bound'])

    def test_bind_requires_current_password_and_challenge_for_same_user(self):
        member=self.accounts.create_user('legacy',PASSWORD)
        challenge,code=self.send('bind',user_id=member['id'])
        with self.assertRaises(AccountError):self.phone.bind(member['id'],'wrong password long enough',PHONE,challenge,code)
        with self.assertRaises(AccountError):self.phone.bind(self.admin['id'],PASSWORD,PHONE,challenge,code)
        summary=self.phone.bind(member['id'],PASSWORD,PHONE,challenge,code)
        self.assertTrue(summary['bound'])
        self.now+=61
        with self.assertRaises(AccountError):self.send('bind',user_id=member['id'])

    def test_sms_login_only_for_bound_active_accounts_and_issues_normal_session(self):
        response=self.phone.send(PHONE,'login','ip')
        self.assertEqual(self.sent,[])
        with self.assertRaises(AccountError):self.phone.login(PHONE,response['challenge_id'],'000000')
        self.now+=61
        member=self.register()
        self.now+=61
        challenge,code=self.send('login')
        user,(token,csrf)=self.phone.login(PHONE,challenge,code)
        self.assertEqual(user['id'],member['id'])
        self.assertEqual(self.accounts.session(token)['csrf_token'],csrf)
        with self.assertRaises(AccountError):self.phone.login(PHONE,challenge,code)
        self.now+=61
        challenge,code=self.send('login')
        with self.accounts.connection() as db:db.execute('UPDATE users SET disabled=1 WHERE id=?',(member['id'],))
        with self.assertRaises(AccountError):self.phone.login(PHONE,challenge,code)

    def test_provider_failure_is_sanitized_never_retried_and_not_verifiable(self):
        sender=Mock(side_effect=RuntimeError('provider secret and phone/code'))
        self.phone.sender=sender
        with self.assertRaises(AccountError) as error:self.send()
        self.assertNotIn('provider secret',str(error.exception));self.assertEqual(sender.call_count,1)
        with self.accounts.connection() as db:self.assertEqual(db.execute('SELECT state FROM sms_challenges').fetchone()[0],'failed')
        with self.assertRaises(AccountError):self.send()
        self.assertEqual(sender.call_count,1)

    def test_paid_send_limits_persist_on_restart(self):
        self.send()
        restarted=PhoneAuth(self.accounts,ENV,sender=Mock())
        with self.assertRaises(AccountError):restarted.send(PHONE,'register','other-ip')
        restarted.sender.assert_not_called()
        self.now+=61
        with self.accounts.connection() as db:db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',('sms-global-day',self.now,200))
        with self.assertRaises(AccountError):restarted.send('13900139000','register','other-ip')
        restarted.sender.assert_not_called()

    def test_additive_idempotent_migration_and_bindings_survive_restart(self):
        member=self.register()
        for _ in range(2):
            accounts=AccountStore(self.accounts.path)
            reopened=PhoneAuth(accounts,{})
            self.assertEqual(accounts.login('member',PASSWORD)['id'],member['id'])
            self.assertEqual(reopened.summary(member['id'])['phone_masked'],'138****8000')
            self.assertFalse(reopened.status()['available'])


if __name__=='__main__':unittest.main()
