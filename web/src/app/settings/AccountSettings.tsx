// Ports of the account blocks: password change (cloud-account.js), phone
// binding (phone-account.js), AI support / QR code, mobile access addresses
// (device-access.js) and admin subscription management (mountAdmin in
// ai-subscription.js).
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Copy, Download, Eye, EyeOff, KeyRound, MessageCircle, Smartphone, UserCog } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { NumberField } from '@/components/number-field';
import { Disclosure } from '@/components/research/common';
import { ServiceLink } from '@/app/research/SectorAccess';
import { useResearch } from '@/app/research/ResearchContext';
import { usePhoneVerification } from '@/hooks/use-phone-verification';
import { ApiError, request } from '@/lib/api';
import { subscriptions } from '@/lib/research';
import { toLogin } from '@/lib/session';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

async function api<T>(path: string, body?: unknown) {
  try {
    return await request<T>(path, body);
  } catch (error) {
    if (error instanceof ApiError && error.status === 0) throw new Error('无法连接账号服务，请检查连接后重试');
    throw error;
  }
}

/** A password input with a show / hide toggle; pasting is never blocked. */
function PasswordInput({ id, label, autoComplete, value, onChange, disabled }: { id: string; label: string; autoComplete: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const [visible, setVisible] = useState(false);
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div className="flex gap-2">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          autoComplete={autoComplete}
          minLength={8}
          maxLength={128}
          required
          disabled={disabled}
          value={value}
          onChange={event => onChange(event.target.value)}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={(visible ? '隐藏' : '显示') + label}
          aria-controls={id}
          aria-pressed={visible}
          disabled={disabled}
          onClick={() => setVisible(!visible)}
        >
          {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </Button>
      </div>
    </Field>
  );
}

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

export function SupportCard() {
  return (
    <Card id="aiSupport" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <MessageCircle className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">AI 订阅与 QQ 客服</h2>
          <Badge variant="outline">扫码咨询</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-4 sm:flex-row">
          <a
            href="qq-support.png"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="查看 QQ 客服二维码大图"
            className="shrink-0 self-start rounded-lg focus-visible:outline-2 focus-visible:outline-ring"
          >
            <img src="qq-support.png" alt="QQ 客服加好友二维码" width={1200} height={1174} loading="lazy" className="size-40 rounded-lg border border-border bg-card object-contain" />
          </a>
          <div className="flex flex-col gap-2">
            <h3 className="font-semibold text-balance">让研究按计划自动进行</h3>
            <p className="text-sm text-pretty">中度推理每份 1 点，极高推理每份 1.5 点。咨询服务开通、额度与使用方式，了解板块解读、事件分析和风险梳理。</p>
            <ServiceLink>了解作用 / 联系客服</ServiceLink>
            <a
              href="qq-support.png"
              download="QQ客服二维码.png"
              className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
            >
              <Download className="size-3.5" aria-hidden="true" />
              保存二维码，使用 QQ 添加
            </a>
          </div>
        </div>
        <p className="text-xs text-muted-foreground text-pretty">手机可保存二维码，在 QQ 扫一扫中从相册选择。具体服务范围、使用额度与有效期，请先向客服确认。</p>
      </CardContent>
    </Card>
  );
}

// The server only ever offers private IPv4 links on this port; anything else is ignored.
function lanUrl(value: string) {
  try {
    const url = new URL(value);
    const octets = url.hostname.split('.').map(Number);
    return (
      octets.length === 4 &&
      octets.every(n => Number.isInteger(n) && n >= 0 && n <= 255) &&
      (octets[0] === 10 || (octets[0] === 192 && octets[1] === 168) || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)) &&
      url.protocol === 'http:' &&
      url.port === location.port &&
      url.pathname === '/index.html' &&
      !url.search &&
      !url.hash &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

export function MobileAccessCard() {
  const { session } = useResearch();
  const access = session.access;
  const field = useRef<HTMLInputElement>(null);
  const cloud = access.scope === 'cloud';
  let urls: string[] = [];
  let siteError = false;
  if (cloud) {
    try {
      const url = new URL(access.site_url || '');
      if (url.origin !== location.origin || url.pathname !== '/index.html' || url.search || url.hash || url.username || url.password) throw new Error();
      urls = [url.href];
    } catch {
      siteError = true;
    }
  } else urls = (Array.isArray(access.lan_urls) ? access.lan_urls : []).filter(lanUrl);
  const [chosen, setChosen] = useState('');
  const current = urls.includes(chosen) ? chosen : urls.find(url => new URL(url).hostname === location.hostname) || urls[0] || '';
  const preview = cloud && access.preview === true;
  const defaultStatus = cloud
    ? preview
      ? '本机预览网址不能直接分享给手机或外网用户。'
      : '云端访问网址；手机可使用 Wi-Fi 或移动网络。'
    : urls.length
      ? access.can_manage_settings
        ? '切换 Wi-Fi 后，请刷新页面获取新的手机访问网址。'
        : '已连接同一局域网，可用此网址继续访问。'
      : '请先将电脑连接到 Wi-Fi 或有线网络，再刷新页面。';
  const [status, setStatus] = useState('');
  const tips = cloud
    ? preview
      ? ['当前网址只用于这台电脑的本地预览。', '手机访问需先配置局域网入口或完成云端上线。']
      : ['复制上方网址，在手机浏览器中打开。', '使用自己的账号登录，关注与研究记录独立保存。', '网站由云端运行，个人电脑可以关机。']
    : [
        '手机与电脑连接同一 Wi-Fi，在手机浏览器打开上方网址。',
        access.scope === 'account_local' ? '登录自己的账号查看研究；使用期间电脑和网站后台需保持运行。' : '使用期间电脑和网站后台需保持运行。',
        '不要使用 127.0.0.1，它只代表打开网页的设备本身。',
      ];

  async function copy() {
    if (!current) return;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(current);
      else throw new Error('manual copy');
      setStatus('网址已复制，请在手机浏览器的地址栏中粘贴打开。');
    } catch {
      field.current?.focus();
      field.current?.select();
      setStatus('地址已选中，请长按或使用复制快捷键。');
    }
  }

  return (
    <Card id="mobileAccess" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Smartphone className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">手机访问网址</h2>
          <Badge variant="outline">{cloud ? (preview ? '仅本机预览' : '无需同一 Wi-Fi') : '同一 Wi-Fi'}</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">
          {cloud
            ? preview
              ? '当前为本机账号版预览，正式托管后可跨网络访问。'
              : '在手机或电脑浏览器打开同一网址，登录自己的账号即可使用。'
            : '手机与运行网站的电脑连接同一网络后，用下方局域网地址访问。'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field>
          <FieldLabel htmlFor="mobileAccessUrl">{cloud ? (preview ? '当前电脑预览网址' : '手机与电脑通用网址') : '手机访问网址（局域网）'}</FieldLabel>
          <div className="flex gap-2">
            <Input
              id="mobileAccessUrl"
              ref={field}
              readOnly
              value={siteError ? '访问地址无效' : current || '未检测到可用的局域网地址'}
              className="tabular-nums"
            />
            <Button variant="outline" disabled={!current} onClick={() => void copy()}>
              <Copy aria-hidden="true" />
              复制网址
            </Button>
          </div>
          {urls.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {urls.map(url => (
                <Button key={url} size="sm" variant={url === current ? 'secondary' : 'outline'} onClick={() => setChosen(url)}>
                  {new URL(url).hostname}
                </Button>
              ))}
            </div>
          )}
          <FieldDescription role="status">{status || defaultStatus}</FieldDescription>
        </Field>
        <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
          {tips.map(tip => (
            <li key={tip} className="text-pretty">
              {tip}
            </li>
          ))}
        </ol>
        <Disclosure title="为什么手机打不开？">
          <p className="text-pretty">
            {cloud
              ? preview
                ? '请先由管理员配置手机可访问的入口；127.0.0.1 只代表打开网页的设备本身。'
                : '先检查手机网络和网址；若提示备案限制，请联系管理员完成备案。'
              : '请确认手机与电脑在同一网络、网站后台仍在运行，并检查电脑防火墙是否允许该端口。手机需使用电脑的局域网 IP，不能使用 127.0.0.1。'}
          </p>
        </Disclosure>
      </CardContent>
    </Card>
  );
}

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
