import unittest

import test_cloud_accounts as base
from research_phone_auth import PhoneAuth
from test_phone_auth import ENV,PHONE,PASSWORD


class PhoneHTTPTests(unittest.TestCase):
    request=base.CloudHTTPTests.request
    sign=base.CloudHTTPTests.sign
    cleanup=base.CloudHTTPTests.cleanup
    setUp=base.CloudHTTPTests.setUp

    def enable(self):
        self.sent=[]
        self.server.phone_auth=PhoneAuth(self.server.accounts,ENV,sender=lambda *args:self.sent.append(args))

    def test_sms_send_requires_an_image_challenge(self):
        status,value,_=self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'login'},solve_captcha=False)
        self.assertEqual(status,400);self.assertIn('图片验证码',value['error'])

    def test_unconfigured_status_and_static_assets_are_public(self):
        self.assertFalse(self.request('/api/auth/status')[1]['phone_auth']['available'])
        self.assertEqual(self.request('/phone-verification.js')[0],200)
        self.assertEqual(self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'register'})[0],503)
        self.assertEqual(self.request('/api/me/phone')[0],401)
        result=self.request('/api/me/phone',cookie=self.member_cookie)[1]
        self.assertFalse(result['bound']);self.assertNotIn('secret',str(result))

    def test_required_registration_cannot_bypass_phone_fields_or_use_fake_code(self):
        self.enable()
        self.assertTrue(self.request('/api/auth/status')[1]['phone_auth']['registration_required'])
        self.assertEqual(self.request('/api/auth/register',{'username':'bypass','password':PASSWORD})[0],400)
        status,result,_=self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'register'})
        self.assertEqual(status,200,result);self.assertNotIn('code',result)
        body={'username':'verified','password':PASSWORD,'phone':PHONE,'challenge_id':result['challenge_id'],'code':self.sent[-1][1]}
        status,result,headers=self.request('/api/auth/register',body)
        self.assertEqual(status,200,result)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertTrue(self.request('/api/me/phone',cookie=cookie)[1]['bound'])
        self.assertNotIn(PHONE,str(result))
        self.assertEqual(self.request('/api/auth/register',body)[0],400)

    def test_config_failure_is_closed_to_new_registration_only(self):
        self.server.phone_auth=PhoneAuth(self.server.accounts,{'FUNDPILOT_SMS_ENABLED':'1'})
        self.assertEqual(self.request('/api/auth/register',{'username':'bypass','password':PASSWORD})[0],400)
        self.assertEqual(self.request('/api/auth/login',{'username':'member','password':base.PASSWORD})[0],200)
        self.assertEqual(self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'register'})[0],503)

    def test_registration_closed_origin_checks_and_strict_sms_fields(self):
        self.enable();self.server.registration_open=False
        self.assertEqual(self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'register'})[0],403)
        self.assertEqual(self.sent,[])
        self.server.registration_open=True
        for path,body in [('/api/auth/sms/send',{'phone':PHONE,'purpose':'bind'}),
                          ('/api/auth/sms/login',{'phone':PHONE,'code':'000000'}),
                          ('/api/auth/sms/send',{'phone':PHONE,'purpose':'register','code':'000000'})]:
            self.assertEqual(self.request(path,body)[0],400)
        self.assertEqual(self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'register'},extra={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.sent,[])

    def test_existing_member_binding_requires_csrf_and_password_then_sms_login(self):
        self.enable()
        self.assertEqual(self.request('/api/me/phone/send',{'phone':PHONE},self.member_cookie)[0],403)
        status,challenge,_=self.request('/api/me/phone/send',{'phone':PHONE},self.member_cookie,self.member_csrf)
        self.assertEqual(status,200,challenge)
        body={'phone':PHONE,'challenge_id':challenge['challenge_id'],'code':self.sent[-1][1],'password':'bad password long enough'}
        self.assertEqual(self.request('/api/me/phone/bind',body,self.member_cookie,self.member_csrf)[0],400)
        body['password']=base.PASSWORD
        status,result,_=self.request('/api/me/phone/bind',body,self.member_cookie,self.member_csrf)
        self.assertEqual(status,200,result);self.assertEqual(result['phone_masked'],'138****8000')
        with self.server.accounts.connection() as db:db.execute("DELETE FROM attempts WHERE bucket LIKE 'sms-%'")
        status,challenge,_=self.request('/api/auth/sms/send',{'phone':PHONE,'purpose':'login'})
        self.assertEqual(status,200,challenge)
        status,result,headers=self.request('/api/auth/sms/login',{'phone':PHONE,'challenge_id':challenge['challenge_id'],'code':self.sent[-1][1]})
        self.assertEqual(status,200,result);self.assertEqual(result['user']['username'],'member')
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Lax',headers['Set-Cookie'])


if __name__=='__main__':unittest.main()
