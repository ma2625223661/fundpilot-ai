// Password change (port of the cloud-account.js password block).
import { useState, type FormEvent } from 'react';
import { KeyRound } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldGroup } from '@/components/ui/field';
import { toLogin } from '@/lib/session';
import { PasswordInput, api } from '@/app/settings/account-shared';

export function PasswordCard() {
  const [fields, setFields] = useState({ old: '', next: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (fields.next !== fields.confirm) {
      setFeedback('两次新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await api('/api/auth/password', { old_password: fields.old, new_password: fields.next });
      setFields({ old: '', next: '', confirm: '' });
      toLogin();
    } catch (error) {
      setFeedback((error as Error).message);
      setBusy(false);
    }
  }
  return (
    <Card id="cloudAccount">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <KeyRound className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">账号与密码</h2>
          <Badge variant="outline">个人账号</Badge>
        </CardTitle>
        <CardDescription>修改密码后，所有设备上的旧登录都会失效。请妥善保存新密码。</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit}>
          <FieldGroup>
            <PasswordInput id="old_password" label="原密码" autoComplete="current-password" value={fields.old} onChange={old => setFields({ ...fields, old })} disabled={busy} />
            <PasswordInput id="new_password" label="新密码（8～128 个字符）" autoComplete="new-password" value={fields.next} onChange={next => setFields({ ...fields, next })} disabled={busy} />
            <PasswordInput id="confirm_password" label="确认新密码" autoComplete="new-password" value={fields.confirm} onChange={confirm => setFields({ ...fields, confirm })} disabled={busy} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">密码长度：8～128 个字符</span>
              <Button type="submit" disabled={busy}>
                {busy ? '正在更新…' : '更新密码'}
              </Button>
            </div>
            <p role="status" aria-live="polite" className="text-sm text-pretty">
              {feedback}
            </p>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}
