// Admin user and subscription management (port of mountAdmin in ai-subscription.js),
// including password resets for users.
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { UserCog } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { NumberField } from '@/components/number-field';
import { Disclosure } from '@/components/research/common';
import { subscriptions } from '@/lib/research';
import { PasswordInput, api, type Row } from '@/app/settings/account-shared';

function ResetPasswordForm({ user, onDone, onCancel }: { user: Row; onDone: (message: string) => void; onCancel: () => void }) {
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setMessage('两次密码不一致，请检查。');
      return;
    }
    setBusy(true);
    setMessage('正在重置密码…');
    try {
      await api('/api/admin/reset-password', { user_id: user.id, new_password: next });
      onDone(user.username + ' 的密码已重置，旧登录已失效。请将新密码安全告知用户。');
    } catch (error) {
      setMessage((error as Error).message);
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label={'重置 ' + user.username + ' 的密码'} className="flex flex-col gap-3 rounded-md bg-muted p-3">
      <h3 className="font-medium">重置 {user.username} 的密码</h3>
      <p className="text-xs text-muted-foreground text-pretty">设置新密码后，该用户所有设备上的旧登录立即失效。关注、记录和研究额度保留。</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <PasswordInput id={'reset-new-' + user.id} label="新密码（8～128 个字符）" autoComplete="new-password" value={next} onChange={setNext} disabled={busy} />
        <PasswordInput id={'reset-confirm-' + user.id} label="确认新密码" autoComplete="new-password" value={confirm} onChange={setConfirm} disabled={busy} />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          确认重置密码
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>
          取消
        </Button>
      </div>
      <p role="status" className="text-sm">
        {message}
      </p>
    </form>
  );
}

export function AdminSubscriptionsCard() {
  const [users, setUsers] = useState<Row[]>([]);
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [userId, setUserId] = useState('');
  const [credits, setCredits] = useState<number | null>(100);
  const [days, setDays] = useState<number | null>(30);
  const [note, setNote] = useState('');
  const [resetting, setResetting] = useState('');
  const [admin, setAdmin] = useState({ username: '', password: '', confirm: '' });
  const [adminBusy, setAdminBusy] = useState(false);
  const [adminFeedback, setAdminFeedback] = useState('');
  const pending = useRef<{ signature: string; request_id: string } | null>(null);
  const creditsRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setUsers((await api<{ items: Row[] }>('/api/admin/users')).items);
    } catch (error) {
      setFeedback((error as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const members = users.filter(u => u.role === 'member');
  const selected = members.some(u => String(u.id) === userId) ? userId : String(members[0]?.id ?? '');

  // A repeated submit of the same change reuses its request id, so the server
  // can recognise a retry and never grants the same credits twice.
  async function mutate(body: Row) {
    if (busy) return;
    setBusy(true);
    const signature = JSON.stringify(body);
    if (!pending.current || pending.current.signature !== signature)
      pending.current = { signature, request_id: crypto.randomUUID().replaceAll('-', '') };
    try {
      await api('/api/admin/ai-subscription', { ...body, request_id: pending.current.request_id });
      pending.current = null;
      setFeedback('订阅设置已保存。');
      await load();
    } catch (error) {
      setFeedback((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function setDisabled(user: Row) {
    if (busy) return;
    setBusy(true);
    try {
      await api('/api/admin/user-state', { user_id: user.id, disabled: !user.disabled });
      await load();
    } catch (error) {
      setFeedback((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function createAdmin(event: FormEvent) {
    event.preventDefault();
    if (admin.password !== admin.confirm) {
      setAdminFeedback('两次密码不一致');
      return;
    }
    setAdminBusy(true);
    try {
      await api('/api/admin/create-admin', { username: admin.username.trim(), password: admin.password });
      setAdminFeedback('第 2 个管理员已创建。初始密码只在创建时使用，之后不会显示。');
      setAdmin({ username: '', password: '', confirm: '' });
      await load();
    } catch (error) {
      setAdminFeedback((error as Error).message);
    } finally {
      setAdminBusy(false);
    }
  }

  return (
    <Card id="aiSubscriptionAdmin">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <UserCog className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">用户订阅与额度</h2>
          <Badge variant="outline">管理员控制</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">为用户开通研究额度（点）与有效期。中度每份 1 点，极高每份 1.5 点；增加额度、续期或暂停均会记录。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Disclosure title="管理管理员账号（最多 2 个）">
          <p className="text-pretty">可创建第 2 个管理员。密码只用于创建或重置，系统只保存加密校验值，任何管理员都不能查看明文密码。</p>
          <form onSubmit={createAdmin}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="admin-username">新管理员用户名</FieldLabel>
                <Input
                  id="admin-username"
                  autoComplete="username"
                  minLength={3}
                  maxLength={64}
                  required
                  disabled={adminBusy}
                  value={admin.username}
                  onChange={event => setAdmin({ ...admin, username: event.target.value })}
                />
              </Field>
              <PasswordInput id="admin-password" label="初始密码（8～128 个字符）" autoComplete="new-password" value={admin.password} onChange={password => setAdmin({ ...admin, password })} disabled={adminBusy} />
              <PasswordInput id="admin-confirm" label="确认初始密码" autoComplete="new-password" value={admin.confirm} onChange={confirm => setAdmin({ ...admin, confirm })} disabled={adminBusy} />
              <Button type="submit" className="self-start" disabled={adminBusy}>
                创建第 2 个管理员
              </Button>
              <p role="status" className="text-sm">
                {adminFeedback}
              </p>
            </FieldGroup>
          </form>
        </Disclosure>
        <form
          onSubmit={event => {
            event.preventDefault();
            if (!selected || credits === null || days === null) return;
            // Same body as the old form, which sent the select's string value.
            void mutate({ user_id: selected, action: 'grant', credits, days, note: note.trim() });
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel>选择用户</FieldLabel>
              <Select value={selected} onValueChange={value => setUserId(String(value))} disabled={busy || !members.length}>
                <SelectTrigger className="w-full sm:w-72" aria-label="选择用户">
                  <SelectValue>
                    {(value: string) => {
                      const user = members.find(u => String(u.id) === value);
                      return user ? user.username + (user.disabled ? ' · 账号已停用' : '') : '暂无普通用户，请让用户先注册';
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {members.map(user => (
                    <SelectItem key={user.id} value={String(user.id)}>
                      {user.username}
                      {user.disabled ? ' · 账号已停用' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2" ref={creditsRef}>
              <Field>
                <FieldLabel htmlFor="subscription-credits">新增研究额度（点）</FieldLabel>
                <NumberField id="subscription-credits" min={0} max={100000} step={0.5} value={credits} onValueChange={setCredits} required disabled={busy} />
              </Field>
              <Field>
                <FieldLabel htmlFor="subscription-days">延长有效期（天）</FieldLabel>
                <NumberField id="subscription-days" min={0} max={3660} value={days} onValueChange={setDays} required disabled={busy} />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="subscription-note">备注（用户可见）</FieldLabel>
              <Input id="subscription-note" maxLength={200} disabled={busy} value={note} onChange={event => setNote(event.target.value)} />
            </Field>
            <Button type="submit" className="self-start" disabled={busy || !selected}>
              开通 / 续订并增加额度
            </Button>
            <FieldDescription>续订从尚未到期的截止时间继续延长；已到期则从现在开始。填写 0 表示该项不增加。</FieldDescription>
          </FieldGroup>
        </form>
        <p role="status" className="text-sm text-pretty">
          {feedback}
        </p>
        <div className="flex flex-col gap-2">
          {users.map(user => {
            const summary = subscriptions.presentation(user.ai_subscription);
            const created = user.created_at ? new Date(user.created_at * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未知';
            const paused = summary.status === 'paused';
            return (
              <article key={user.id} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex flex-col">
                    <strong className="font-medium">{user.username}</strong>
                    <span className="text-sm">{user.role === 'admin' ? '管理员' : user.disabled ? '账号已停用' : summary.label}</span>
                    <small className="text-xs text-muted-foreground tabular-nums">
                      {user.role === 'admin' ? '统一管理服务商凭证与全站计划' : '余额 ' + summary.credits + ' 点 · 已解锁 ' + summary.count + ' 份'}
                    </small>
                    <small className="text-xs text-muted-foreground tabular-nums">创建于 {created}</small>
                    <small className="text-xs text-muted-foreground">{user.password_status || '密码状态未知'}</small>
                  </div>
                  {user.role === 'member' && (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => {
                          setUserId(String(user.id));
                          creditsRef.current?.querySelector('input')?.focus();
                        }}
                      >
                        分配额度
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        aria-expanded={resetting === String(user.id)}
                        onClick={() => setResetting(resetting === String(user.id) ? '' : String(user.id))}
                      >
                        重置密码
                      </Button>
                      {summary.status !== 'unsubscribed' && (
                        <Button size="sm" variant="outline" disabled={busy} onClick={() => void mutate({ user_id: user.id, action: paused ? 'resume' : 'pause' })}>
                          {paused ? '恢复 AI 服务' : '暂停 AI 服务'}
                        </Button>
                      )}
                      <Button size="sm" variant={user.disabled ? 'outline' : 'destructive'} disabled={busy} onClick={() => void setDisabled(user)}>
                        {user.disabled ? '恢复账号' : '停用账号'}
                      </Button>
                    </div>
                  )}
                </div>
                {resetting === String(user.id) && (
                  <ResetPasswordForm
                    user={user}
                    onCancel={() => setResetting('')}
                    onDone={message => {
                      setResetting('');
                      setFeedback(message);
                    }}
                  />
                )}
              </article>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
