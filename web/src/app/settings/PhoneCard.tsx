// Phone binding and change (port of phone-account.js).
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Smartphone } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { usePhoneVerification } from '@/hooks/use-phone-verification';
import { PasswordInput, api, type Row } from '@/app/settings/account-shared';

export function PhoneCard() {
  const [state, setState] = useState<Row | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState('');
  const [feedback, setFeedback] = useState('');
  const verification = usePhoneVerification({ request: phone => api('/api/me/phone/send', { phone }) });

  const load = useCallback(async () => {
    try {
      setState(await api<Row>('/api/me/phone'));
      setError('');
    } catch (reason) {
      setError((reason as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function bind(event: FormEvent) {
    event.preventDefault();
    if (busy || !state?.available || state.bound) return;
    let body: Row;
    try {
      body = { ...verification.payload(), password };
    } catch (reason) {
      setFeedback((reason as Error).message);
      return;
    }
    setBusy(true);
    setFeedback('正在验证并绑定…');
    try {
      setState(await api<Row>('/api/me/phone/bind', body));
      verification.reset(true);
      setPassword('');
      setFeedback('手机号已验证并绑定。下次登录可选择短信验证码。');
    } catch (reason) {
      setFeedback((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const open = Boolean(state?.available && !state.bound);
  const badge = error ? '暂无法读取' : !state ? '正在读取' : state.bound ? '已绑定' : state.available ? '未绑定' : '暂未开通';
  const description = error
    ? '手机号绑定状态暂未读取成功，请重试。'
    : !state
      ? '正在读取手机号绑定状态…'
      : state.bound
        ? `已绑定 ${state.phone_masked}。${state.available ? '您可以使用该手机号接收验证码登录。' : '短信服务当前未开通，请继续使用账号密码登录。'}`
        : state.available
          ? '验证手机号并确认当前密码后完成绑定，同一手机号仅可绑定一个账号。'
          : '短信验证暂未开通。开通后可在这里绑定手机号，并使用短信验证码登录；当前继续使用账号密码。';
  return (
    <Card id="cloudPhone">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Smartphone className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">手机号与验证码</h2>
          <Badge variant="outline">{badge}</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {open && (
          <form onSubmit={bind}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="bindPhone">手机号（中国大陆 +86）</FieldLabel>
                <Input
                  id="bindPhone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel-national"
                  maxLength={11}
                  pattern="1[3-9][0-9]{9}"
                  required
                  placeholder="11 位手机号"
                  disabled={busy || verification.sending}
                  value={verification.phone}
                  onChange={event => verification.setPhone(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="bindCode">短信验证码</FieldLabel>
                <div className="flex gap-2">
                  <Input
                    id="bindCode"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    pattern="[0-9]{6}"
                    required
                    placeholder="6 位验证码"
                    disabled={busy}
                    value={verification.code}
                    onChange={event => verification.setCode(event.target.value)}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="shrink-0 tabular-nums"
                    disabled={busy || verification.sending || verification.seconds > 0}
                    onClick={() => void verification.send()}
                  >
                    {verification.sendLabel}
                  </Button>
                </div>
                <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
                  {verification.feedback}
                </p>
              </Field>
              <PasswordInput id="bindPassword" label="当前账号密码" autoComplete="current-password" value={password} onChange={setPassword} disabled={busy} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <small className="text-xs text-muted-foreground">验证码 5 分钟有效；绑定后可使用短信登录。</small>
                <Button type="submit" disabled={busy}>
                  {busy ? '正在绑定…' : '验证并绑定'}
                </Button>
              </div>
            </FieldGroup>
          </form>
        )}
        <p role="status" aria-live="polite" className="text-sm text-pretty">
          {feedback || error}
        </p>
        {error && (
          <Button variant="outline" className="self-start" onClick={() => void load()}>
            重新读取
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
