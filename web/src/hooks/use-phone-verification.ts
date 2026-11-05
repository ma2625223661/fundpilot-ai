// Port of dist/phone-verification.js, shared by registration, SMS login and
// phone binding. Keeps the challenge only in memory and never stores codes.
import { useEffect, useRef, useState } from 'react';

export interface SmsChallenge {
  challenge_id: string;
  expires_in?: number;
  retry_after?: number;
  message?: string;
}

export interface PhonePayload {
  phone: string;
  challenge_id: string;
  code: string;
}

const PHONE = /^1[3-9][0-9]{9}$/;

export function normalizePhone(value: string) {
  return value.trim().replace(/^\+86/, '');
}

export function usePhoneVerification(options: {
  request: (phone: string) => Promise<SmsChallenge>;
  /** Local check (for example the image CAPTCHA) that must not start the resend cooldown. */
  precheck?: () => string;
}) {
  const [phone, setPhoneValue] = useState('');
  const [code, setCode] = useState('');
  const [feedback, setFeedback] = useState('');
  const [sending, setSending] = useState(false);
  const [nextSend, setNextSend] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const challenge = useRef({ id: '', expires: 0 });
  const revision = useRef(0);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const seconds = Math.max(0, Math.ceil((nextSend - now) / 1000));
  useEffect(() => {
    if (!seconds) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [seconds, now]);

  function reset(clearPhone = false) {
    revision.current++;
    challenge.current = { id: '', expires: 0 };
    setCode('');
    setFeedback('');
    if (clearPhone) setPhoneValue('');
  }

  function setPhone(value: string) {
    setPhoneValue(value);
    reset();
  }

  async function send() {
    if (sending || seconds > 0) return;
    const number = normalizePhone(phone);
    if (!PHONE.test(number)) {
      setFeedback('请输入中国大陆 11 位手机号');
      return;
    }
    const problem = optionsRef.current.precheck?.() ?? '';
    if (problem) {
      setFeedback(problem);
      return;
    }
    reset();
    const ticket = revision.current;
    setNextSend(Date.now() + 60000);
    setNow(Date.now());
    setSending(true);
    setFeedback('正在请求验证码…');
    try {
      const data = await optionsRef.current.request(number);
      setNextSend(Date.now() + Math.max(60, Number(data.retry_after) || 60) * 1000);
      setNow(Date.now());
      if (ticket !== revision.current) return;
      challenge.current = {
        id: data.challenge_id,
        expires: Date.now() + Math.min(300, Number(data.expires_in) || 300) * 1000,
      };
      setFeedback(data.message ?? '');
    } catch (error) {
      if (ticket === revision.current) setFeedback((error as Error).message);
    } finally {
      setSending(false);
    }
  }

  function payload(): PhonePayload {
    const number = normalizePhone(phone);
    if (!PHONE.test(number)) throw new Error('请输入中国大陆 11 位手机号');
    if (!challenge.current.id || challenge.current.expires <= Date.now()) throw new Error('请先获取有效的短信验证码');
    if (!/^[0-9]{6}$/.test(code)) throw new Error('请输入 6 位短信验证码');
    return { phone: number, challenge_id: challenge.current.id, code };
  }

  const sendLabel = sending ? '正在发送…' : seconds ? `${seconds} 秒后重发` : '获取验证码';
  return { phone, setPhone, code, setCode, feedback, sending, seconds, sendLabel, send, reset, payload };
}
