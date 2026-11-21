// Port of dist/login.html + login.js: password login, SMS login, registration
// (with phone verification when the server requires it) and first-run admin setup.
// Every password submit and every SMS send spends one six-character image challenge.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ExternalLink, History, LineChart, RefreshCw, ShieldAlert, Star, type LucideIcon } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Brand } from '@/components/brand';
import { request } from '@/lib/api';
import { usePhoneVerification, type SmsChallenge } from '@/hooks/use-phone-verification';

interface PhoneAuthStatus {
  available?: boolean;
  registration_required?: boolean;
  message?: string;
}

interface AuthStatus {
  needs_setup: boolean;
  setup_token_required: boolean;
  setup_available: boolean;
  registration_open: boolean;
  phone_auth?: PhoneAuthStatus;
}

type Mode = 'login' | 'register' | 'setup';
type Method = 'password' | 'sms';

const USERNAME_PATTERN =
  '[A-Za-z0-9_]{3,32}|[A-Za-z0-9._%+\\-]+@[A-Za-z0-9\\-]+(\\.[A-Za-z0-9\\-]+)*\\.[A-Za-z]{2,24}';
const LOOPBACK = ['127.0.0.1', 'localhost', '[::1]', '::1'];
const FEATURES: [LucideIcon, string, string][] = [
  [LineChart, '共用板块研究报告', '行情、公司样本、财务与重要事件汇总在一份报告里。'],
  [Star, '个人关注列表', '关注重点方向，一眼看清研究分、走势与风险。'],
  [History, '独立研究记录', '每份报告随账号保存，五日后回头复盘。'],
];

export function LoginApp() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [mode, setMode] = useState<Mode>('login');
  const [method, setMethod] = useState<Method>('password');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [setupToken, setSetupToken] = useState('');
  const [captcha, setCaptcha] = useState({ id: '', image: '', failed: false });
  const [captchaCode, setCaptchaCode] = useState('');
  const captchaLoading = useRef<Promise<void> | null>(null);
  const captchaInput = useRef<HTMLInputElement>(null);

  // Each challenge is single use, so a fresh one is fetched after every failed submit.
  function loadCaptcha() {
    if (captchaLoading.current) return captchaLoading.current;
    setCaptcha({ id: '', image: '', failed: false });
    setCaptchaCode('');
    captchaLoading.current = request<{ captcha_id: string; image: string }>('/api/auth/captcha', undefined, 10000)
      .then(data => setCaptcha({ id: data.captcha_id, image: data.image, failed: false }))
      .catch((error: Error) => {
        setCaptcha({ id: '', image: '', failed: true });
        setMessage(error.message);
      })
      .finally(() => {
        captchaLoading.current = null;
      });
    return captchaLoading.current;
  }

  const captchaRef = useRef({ id: '', code: '' });
  captchaRef.current = { id: captcha.id, code: captchaCode.trim() };
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const verification = usePhoneVerification({
    precheck: () => {
      if (!captchaRef.current.id) return '图片验证码尚未加载，请点击图片刷新';
      return /^[A-Za-z0-9]{6}$/.test(captchaRef.current.code) ? '' : '请先输入上方 6 位图片验证码，再获取短信验证码';
    },
    request: phone =>
      request<SmsChallenge>('/api/auth/sms/send', {
        phone,
        purpose: modeRef.current === 'register' ? 'register' : 'login',
        captcha_id: captchaRef.current.id,
        captcha_code: captchaRef.current.code,
      }).finally(() => void loadCaptcha()),
  });

  useEffect(() => {
    request<AuthStatus>('/api/auth/status', undefined, 10000)
      .then(value => {
        setStatus(value);
        setMode(value.needs_setup ? 'setup' : 'login');
        void loadCaptcha();
      })
      .catch(() => setStatusError('账号服务暂时无法连接，请刷新页面重试。'));
    // Runs once on mount; loadCaptcha only touches state setters and a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const phone = status?.phone_auth ?? {};
  const setup = mode === 'setup';
  const creating = mode !== 'login';
  const smsLogin = mode === 'login' && method === 'sms';
  const usePhone = smsLogin || (mode === 'register' && Boolean(phone.available || phone.registration_required));
  const phoneUnavailable = usePhone && !phone.available;
  const setupBlocked = setup && status?.setup_available === false;
  // Plain HTTP to another device's address crosses the local network unencrypted.
  const lanPlainHttp = location.protocol === 'http:' && !LOOPBACK.includes(location.hostname);

  function reset() {
    verification.reset(true);
    setMessage('');
    setPassword('');
    setConfirm('');
  }

  function switchMode() {
    if (busy) return;
    setMode(mode === 'login' ? 'register' : 'login');
    setMethod('password');
    reset();
  }

  function chooseMethod(next: Method) {
    if (busy || next === method || (next === 'sms' && !phone.available)) return;
    setMethod(next);
    reset();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !status || phoneUnavailable || setupBlocked) return;
    if (creating && password !== confirm) {
      setMessage('两次密码不一致');
      return;
    }
    let body: Record<string, string> = smsLogin ? {} : { username, password };
    if (!smsLogin) {
      if (!captcha.id) {
        setMessage('图片验证码尚未加载，请点击图片刷新');
        return;
      }
      body.captcha_id = captcha.id;
      body.captcha_code = captchaCode.trim();
    }
    try {
      if (usePhone) body = { ...body, ...verification.payload() };
    } catch (error) {
      setMessage((error as Error).message);
      return;
    }
    if (setup) body.setup_token = setupToken;
    setBusy(true);
    setMessage('正在验证…');
    try {
      await request('/api/auth/' + (smsLogin ? 'sms/login' : mode), body);
      verification.reset(true);
      setPassword('');
      setConfirm('');
      setSetupToken('');
      location.replace('/index.html');
    } catch (error) {
      setMessage((error as Error).message);
      if (!smsLogin) void loadCaptcha();
      setBusy(false);
    }
  }

  const title = setup ? '创建管理员账号' : creating ? '创建个人研究账号' : '登录研究工作台';
  const intro = !status
    ? statusError || '正在连接账号服务…'
    : setup
      ? setupBlocked
        ? '请先在运行后台的电脑上完成初始化，再回到此处登录。'
        : '首次使用，请设置管理员账号和密码。'
      : creating
        ? '个人关注与研究记录单独保存。'
        : '欢迎回来，继续您的板块研究。';
  const submitLabel = busy ? '正在验证…' : setup ? '初始化并进入' : creating ? '注册并进入' : smsLogin ? '验证并登录' : '登录';

  return (
    <main className="safe-bottom mx-auto grid min-h-dvh max-w-6xl items-center gap-8 px-4 py-8 lg:grid-cols-5 lg:gap-12">
      <section className="flex flex-col gap-6 lg:col-span-3">
        <Brand subtitle="自动板块研究工作台" />
        <div className="flex flex-col gap-3">
          <h1 className="text-4xl font-semibold text-balance">登录 FundPilot AI</h1>
          <p className="text-lg text-muted-foreground text-pretty">板块研究工作台：共享市场研究，保留自己的关注与记录。</p>
        </div>
        <ul className="hidden gap-3 sm:grid sm:grid-cols-3">
          {FEATURES.map(([Icon, title, copy]) => (
            <li key={title} className="flex flex-col gap-2 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
              <Icon className="size-5 text-primary" aria-hidden="true" />
              <b className="font-semibold">{title}</b>
              <span className="text-sm text-muted-foreground text-pretty">{copy}</span>
            </li>
          ))}
        </ul>
        <p className="hidden text-xs text-muted-foreground text-pretty sm:block">
          研究分用于比较证据强弱，不代表收益概率，不构成投资建议。
        </p>
      </section>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>
            <h2 className="text-xl font-semibold text-balance">{title}</h2>
          </CardTitle>
          <CardDescription className="text-pretty">{intro}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!status && !statusError && <Skeleton className="h-64 w-full" />}
          {statusError && (
            <Button variant="outline" onClick={() => location.reload()}>
              <RefreshCw aria-hidden="true" />
              重新连接
            </Button>
          )}
          {status && (
            <>
              {mode === 'login' && (
                <ToggleGroup
                  variant="outline"
                  aria-label="登录方式"
                  value={[method]}
                  onValueChange={value => value[0] && chooseMethod(value[0] as Method)}
                >
                  <ToggleGroupItem value="password" disabled={busy}>
                    账号密码
                  </ToggleGroupItem>
                  <ToggleGroupItem value="sms" disabled={busy || !phone.available}>
                    短信验证码
                  </ToggleGroupItem>
                </ToggleGroup>
              )}
              {!setup && !phone.available && (
                <p className="text-sm text-muted-foreground text-pretty">
                  {phone.message || '短信验证暂未开通，当前可使用用户名和密码注册、登录。'}
                </p>
              )}
              {lanPlainHttp && (
                <Alert>
                  <ShieldAlert aria-hidden="true" />
                  <AlertDescription className="text-pretty">
                    当前通过局域网 HTTP 连接，未加密：密码会以明文经过网络。请只在自己信任的家庭或办公 Wi-Fi 中登录，不要在公共网络使用。
                  </AlertDescription>
                </Alert>
              )}

              <form onSubmit={submit} noValidate={false}>
                <FieldGroup>
                  {!smsLogin && (
                    <FieldSet disabled={busy}>
                      <Field>
                        <FieldLabel htmlFor="username">用户名</FieldLabel>
                        <Input
                          id="username"
                          name="username"
                          autoComplete="username"
                          pattern={USERNAME_PATTERN}
                          minLength={3}
                          maxLength={64}
                          required
                          placeholder="字母、数字或下划线（3～32 位），或邮箱"
                          value={username}
                          onChange={event => setUsername(event.target.value)}
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="password">密码</FieldLabel>
                        <Input
                          id="password"
                          name="password"
                          type="password"
                          autoComplete={creating ? 'new-password' : 'current-password'}
                          minLength={8}
                          maxLength={128}
                          required
                          placeholder="8～128 个字符"
                          value={password}
                          onChange={event => setPassword(event.target.value)}
                        />
                      </Field>
                      {creating && (
                        <Field>
                          <FieldLabel htmlFor="confirm">确认密码</FieldLabel>
                          <Input
                            id="confirm"
                            type="password"
                            autoComplete="new-password"
                            maxLength={128}
                            required
                            value={confirm}
                            onChange={event => setConfirm(event.target.value)}
                          />
                        </Field>
                      )}
                    </FieldSet>
                  )}

                  <Field>
                    <FieldLabel htmlFor="captchaCode">图片验证码</FieldLabel>
                    <div className="flex items-center gap-2">
                      <Input
                        id="captchaCode"
                        name="captcha"
                        ref={captchaInput}
                        autoComplete="off"
                        autoCapitalize="characters"
                        spellCheck={false}
                        minLength={6}
                        maxLength={6}
                        pattern="[A-Za-z0-9]{6}"
                        required={!smsLogin}
                        disabled={busy}
                        placeholder="6 位字符"
                        aria-describedby="captchaHelp"
                        value={captchaCode}
                        onChange={event => setCaptchaCode(event.target.value)}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        className="h-12 w-36 shrink-0 overflow-hidden p-0"
                        disabled={busy}
                        aria-label="看不清？点击换一张图片验证码"
                        onClick={() => void loadCaptcha().then(() => captchaInput.current?.focus())}
                      >
                        {captcha.image ? (
                          <img src={captcha.image} alt="" width={200} height={70} className="size-full object-cover" />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {captcha.failed ? '加载失败，点击重试' : '加载中'}
                          </span>
                        )}
                      </Button>
                    </div>
                    <FieldDescription id="captchaHelp">
                      {usePhone
                        ? '不区分大小写；获取短信验证码前需先填写，每张只能用一次（发送后会自动换一张）。'
                        : '不区分大小写；看不清可点击图片换一张。每张只能用一次，5 分钟内有效。'}
                    </FieldDescription>
                  </Field>

                  {usePhone && (
                    <FieldSet>
                      <FieldLegend>{smsLogin ? '使用已绑定的手机号登录' : '验证手机号 · 保护您的账号'}</FieldLegend>
                      <Field>
                        <FieldLabel htmlFor="phone">手机号</FieldLabel>
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground tabular-nums" aria-hidden="true">
                            +86
                          </span>
                          <Input
                            id="phone"
                            type="tel"
                            inputMode="tel"
                            autoComplete="tel-national"
                            maxLength={11}
                            pattern="1[3-9][0-9]{9}"
                            required
                            disabled={!phone.available || busy || verification.sending}
                            placeholder="中国大陆 11 位手机号"
                            value={verification.phone}
                            onChange={event => verification.setPhone(event.target.value)}
                          />
                        </div>
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="smsCode">短信验证码</FieldLabel>
                        <div className="flex items-center gap-2">
                          <Input
                            id="smsCode"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            pattern="[0-9]{6}"
                            maxLength={6}
                            required
                            disabled={!phone.available || busy}
                            placeholder="6 位验证码"
                            value={verification.code}
                            onChange={event => verification.setCode(event.target.value)}
                          />
                          <Button
                            type="button"
                            variant="outline"
                            className="shrink-0 tabular-nums"
                            disabled={!phone.available || busy || verification.sending || verification.seconds > 0}
                            onClick={() => void verification.send()}
                          >
                            {verification.sendLabel}
                          </Button>
                        </div>
                        <FieldDescription>验证码 5 分钟有效，请勿向他人透露。</FieldDescription>
                        <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
                          {verification.feedback}
                        </p>
                      </Field>
                    </FieldSet>
                  )}

                  {setup && status.setup_token_required && (
                    <Field>
                      <FieldLabel htmlFor="setupToken">初始化口令</FieldLabel>
                      <Input
                        id="setupToken"
                        type="password"
                        autoComplete="off"
                        maxLength={512}
                        required
                        disabled={busy}
                        value={setupToken}
                        onChange={event => setSetupToken(event.target.value)}
                      />
                      <FieldDescription>由网站所有者在托管平台设置，仅首次创建管理员使用。</FieldDescription>
                    </Field>
                  )}

                  <p role="status" aria-live="polite" className="min-h-5 text-sm text-pretty">
                    {message}
                  </p>
                  <Button type="submit" size="lg" disabled={busy || phoneUnavailable || setupBlocked}>
                    {submitLabel}
                  </Button>
                </FieldGroup>
              </form>

              {!setup && status.registration_open && (
                <Button variant="ghost" disabled={busy} onClick={switchMode}>
                  {creating ? '已有账号，返回登录' : '还没有账号？注册'}
                </Button>
              )}
            </>
          )}
          <a
            className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
            href="ai-service.html"
          >
            了解 AI 自动化研究 · QQ 客服订阅
            <ExternalLink className="size-3.5" aria-hidden="true" />
          </a>
          <p className="text-xs text-muted-foreground text-pretty">
            研究报告供比较证据与复盘使用。密码经加盐哈希保存，绑定手机号仅向您展示脱敏信息。
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
