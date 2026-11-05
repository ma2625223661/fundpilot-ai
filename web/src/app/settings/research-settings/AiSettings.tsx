// AI research settings (applyConfig, the AI settings form and testAi).
// Saving a schedule never calls the model; it only applies to later runs.
import { useRef, useState, type FormEvent } from 'react';
import { PlugZap, Save, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { NumberField } from '@/components/number-field';
import { Disclosure } from '@/components/research/common';
import { useNextAiText } from '@/app/research/AiPanel';
import { useResearch } from '@/app/research/ResearchContext';
import { request } from '@/lib/api';
import { txt } from '@/lib/format';
import { DEFAULT_COST, MODEL, REASONING, SCHEDULE, SectionTitle, reasoningLabel, type Row } from '@/app/settings/research-settings/shared';

export function AiSettings({ canManage }: { canManage: boolean }) {
  const { config, configError, applyConfig, poll, state, accountMode, session } = useResearch();
  const nextText = useNextAiText();
  const cloud = session.access.scope === 'cloud';
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState({
    reasoning: 'xhigh',
    enabled: false,
    key: '',
    baseUrl: '',
    reuse: DEFAULT_COST.reuse_enabled,
    requests: DEFAULT_COST.daily_request_limit as number | null,
    tokens: DEFAULT_COST.daily_token_limit as number | null,
  });
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('保存计划不会立即调用研究模型。');
  const keyInput = useRef<HTMLInputElement>(null);

  // Saved values fill the form until the person starts editing it.
  const shown = dirty || !config
    ? form
    : {
        ...form,
        reasoning: config.reasoning_effort === 'medium' ? 'medium' : 'xhigh',
        enabled: config.enabled === true,
        baseUrl: txt(config.responses_base_url),
        reuse: { ...DEFAULT_COST, ...config.cost_controls }.reuse_enabled,
        requests: { ...DEFAULT_COST, ...config.cost_controls }.daily_request_limit,
        tokens: { ...DEFAULT_COST, ...config.cost_controls }.daily_token_limit,
      };
  const edit = (patch: Partial<typeof form>) => {
    setForm({ ...shown, ...patch });
    setDirty(true);
  };

  const saved = configError
    ? configError
    : !config
      ? '正在读取后台配置…'
      : config.configured
        ? '已保存 ' +
          txt(config.key_hint, '密钥') +
          ' · ' +
          (config.verification === 'verified' ? '校验通过' : txt(config.error, '等待校验')) +
          (config.model === MODEL ? ' · ' + MODEL + ' / ' + reasoningLabel(config.reasoning_effort) : '')
        : '尚未配置 API Key，量化板块分析可独立运行。';
  const calendar = state.ai_calendar || config?.ai_calendar;
  const calendarText = calendar
    ? calendar.status === 'verified'
      ? '交易日历已核验' + (calendar.year ? '（' + calendar.year + ' 年）' : '') + (calendar.source ? ' · ' + calendar.source : '') + '。'
      : txt(calendar.reason, '交易日历尚未核验，暂停自动研究。')
    : '';

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !canManage) return;
    const limits = { reuse_enabled: shown.reuse, daily_request_limit: Number(shown.requests), daily_token_limit: Number(shown.tokens) };
    if (!Number.isInteger(limits.daily_request_limit) || limits.daily_request_limit < 1 || limits.daily_request_limit > 10000) {
      setStatus('请输入1至10000的每日请求上限。');
      return;
    }
    if (!Number.isInteger(limits.daily_token_limit) || limits.daily_token_limit < 1000 || limits.daily_token_limit > 1000000000) {
      setStatus('请输入1000至1000000000的每日Token预算。');
      return;
    }
    const key = shown.key.trim();
    if ((!accountMode || !cloud) && !key && !config?.configured) {
      toast.error('请输入 AI API Key');
      keyInput.current?.focus();
      return;
    }
    if (/\s/.test(key)) {
      toast.error('API Key 不能包含空白字符');
      return;
    }
    setBusy(true);
    setStatus('正在保存设置并检查配置…');
    try {
      const data = await request<Row>(
        '/api/ai/config',
        {
          ...(key ? { key } : {}),
          responses_base_url: shown.baseUrl.trim(),
          model: MODEL,
          reasoning_effort: shown.reasoning,
          enabled: shown.enabled,
          schedule: SCHEDULE,
          cost_controls: limits,
        },
        60000,
      );
      setDirty(false);
      setForm({ ...shown, key: '' });
      applyConfig(data.config || data);
      const message =
        data.connection?.ok === false && !data.connection?.skipped
          ? '设置已保存，连接校验未通过：' + txt(data.connection.error, '请检查密钥或模型')
          : '研究设置已保存，按北京时间计划运行。';
      setStatus(message);
      toast.success(message);
      void poll();
    } catch (error) {
      setStatus((error as Error).message);
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    if (busy) return;
    setBusy(true);
    setStatus('正在检查连接与模型权限…');
    try {
      const data = await request<Row>('/api/ai/test', {}, 60000);
      applyConfig(data.config || config);
      setStatus(
        data.connection?.ok === true
          ? '连接与模型权限检查通过；实际研究用量见首页。'
          : '连接检查未通过：' + txt(data.connection?.error || data.error, '请检查配置'),
      );
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="researchSettings" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">AI 研究与执行计划</h2>
          <Badge variant="outline">研究控制台</Badge>
        </CardTitle>
        <CardDescription role="status" className="text-pretty">
          {saved}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} noValidate>
          <FieldGroup>
            <div className="flex flex-col gap-2 rounded-lg bg-muted p-3">
              <span className="text-xs text-muted-foreground">AI 自动化研究服务</span>
              <h3 className="font-semibold text-balance">少花时间找资料，多一份研究依据</h3>
              <p className="text-sm text-pretty">订阅后由管理员提供统一额度，无需自行填写 API Key。查看板块解读，持续跟踪变化。</p>
              <ul className="grid gap-3 text-sm sm:grid-cols-3">
                {(
                  [
                    ['有据可查', '汇总业务、财务、走势与重要事件'],
                    ['重点清楚', '整理研究建议、风险与后续观察点'],
                    ['持续跟踪', '按计划更新报告，保留记录供复盘'],
                  ] as [string, string][]
                ).map(([title, copy]) => (
                  <li key={title} className="flex flex-col gap-0.5">
                    <b className="font-medium">{title}</b>
                    <span className="text-muted-foreground text-pretty">{copy}</span>
                  </li>
                ))}
              </ul>
            </div>
            <FieldSet disabled={!canManage || busy}>
              <SectionTitle index="01" title="选择研究深度" />
              <Field>
                <FieldLabel>研究模型</FieldLabel>
                <Select value={MODEL} disabled>
                  <SelectTrigger className="w-full sm:w-64">
                    <SelectValue>{() => MODEL}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={MODEL}>{MODEL}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel>订阅用户专属 · 管理员选择推理强度</FieldLabel>
                <Select value={shown.reasoning} onValueChange={value => edit({ reasoning: String(value) })} disabled={!canManage || busy}>
                  <SelectTrigger className="w-full sm:w-64">
                    <SelectValue>{(value: string) => REASONING[value]}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(REASONING).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FieldDescription className="text-pretty">
                  管理员可自由选择订阅服务共享研究的推理强度。订阅用户解锁中度推理每份 1 点、极高推理每份 1.5 点，解锁前显示实际点数。个人偏好仍可在首页“我的 AI 订阅”单独选择，切换不扣点。
                </FieldDescription>
              </Field>
              <Disclosure title="管理员服务连接设置">
                <Field>
                  <FieldLabel htmlFor="aiKey">服务商 API Key（留空保留已有密钥）</FieldLabel>
                  <Input
                    id="aiKey"
                    ref={keyInput}
                    type="password"
                    autoComplete="off"
                    disabled={cloud || !canManage || busy}
                    placeholder={cloud ? '由托管平台环境变量管理' : config?.configured ? '留空保留已保存的密钥' : '输入 AI API Key'}
                    value={shown.key}
                    onChange={event => edit({ key: event.target.value })}
                  />
                  <FieldDescription className="text-pretty">
                    {cloud
                      ? '服务密钥由管理员在云端托管平台配置，不发送到浏览器。'
                      : accountMode
                        ? '由当前 Windows 账号加密保存。只有管理员在此电脑上可修改，页面不读取已保存的密钥原文。'
                        : '管理员统一提供服务连接，普通用户无需填写密钥。'}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="aiBaseUrl">服务商接口地址</FieldLabel>
                  <Input
                    id="aiBaseUrl"
                    type="url"
                    autoComplete="off"
                    value={shown.baseUrl}
                    onChange={event => edit({ baseUrl: event.target.value })}
                  />
                  <FieldDescription>服务商实际调用费用由后台统一承担。</FieldDescription>
                </Field>
              </Disclosure>
            </FieldSet>
            <FieldSet disabled={!canManage || busy}>
              <SectionTitle index="02" title="安排研究时间" />
              <Field orientation="horizontal">
                <Switch id="autoAiEnabled" checked={shown.enabled} onCheckedChange={value => edit({ enabled: value })} disabled={!canManage || busy} />
                <div className="flex flex-col">
                  <Label htmlFor="autoAiEnabled">启用自动 AI 研究</Label>
                  <span className="text-xs text-muted-foreground">在固定时段执行，按实际用量计费。</span>
                </div>
              </Field>
              <p className="text-sm font-medium">研究时间 · 北京时间</p>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-md bg-muted p-2">
                  <b className="font-semibold tabular-nums">09:20</b>
                  <span className="block text-xs text-muted-foreground">开盘前 10 分钟</span>
                </div>
                <div className="rounded-md bg-muted p-2">
                  <b className="font-semibold tabular-nums">14:50</b>
                  <span className="block text-xs text-muted-foreground">收盘前 10 分钟</span>
                </div>
              </div>
              <p className="text-xs text-muted-foreground text-pretty">
                {cloud
                  ? '仅 A 股交易日，休市日跳过。云端后台按北京时间运行，错过的时段不补跑。'
                  : '仅 A 股交易日，休市日跳过。电脑与后台需保持运行，错过的时段不补跑。'}
              </p>
              <p className="text-sm text-pretty">
                每个 A 股交易日固定分析两次：09:20、14:50。休市日跳过；交易日历无法核验时暂停自动调用并提示。{calendarText && ' ' + calendarText}
              </p>
              <p className="text-sm text-muted-foreground tabular-nums">{nextText}</p>
            </FieldSet>
            <FieldSet disabled={!canManage || busy}>
              <SectionTitle index="03" title="管理用量预算" />
              <Field orientation="horizontal">
                <Checkbox id="aiReuse" checked={shown.reuse} onCheckedChange={value => edit({ reuse: value === true })} disabled={!canManage || busy} />
                <div className="flex flex-col">
                  <Label htmlFor="aiReuse">复用未变化的有效解读</Label>
                  <span className="text-xs text-muted-foreground">保留原研究日期，证据或模型变化后重新研究。</span>
                </div>
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="aiDailyRequestLimit">每日请求上限</FieldLabel>
                  <NumberField
                    id="aiDailyRequestLimit"
                    min={1}
                    max={10000}
                    value={shown.requests}
                    onValueChange={value => edit({ requests: value })}
                    disabled={!canManage || busy}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="aiDailyTokenLimit">每日 Token 预算</FieldLabel>
                  <NumberField
                    id="aiDailyTokenLimit"
                    min={1000}
                    max={1000000000}
                    step={1000}
                    value={shown.tokens}
                    onValueChange={value => edit({ tokens: value })}
                    disabled={!canManage || busy}
                  />
                </Field>
              </div>
              <FieldDescription className="text-pretty">
                按北京时间每日重置。中度按 1.0 倍、极高按 1.5 倍折算请求与 Token。实际用量与折算用量分别展示，不等于人民币账单。
              </FieldDescription>
            </FieldSet>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">保存后应用于后续研究，不会立即发起模型调用。</p>
              <div className="flex gap-2">
                <Button type="button" variant="outline" disabled={!canManage || busy || !config?.configured} onClick={() => void test()}>
                  <PlugZap aria-hidden="true" />
                  检查连接
                </Button>
                <Button type="submit" disabled={!canManage || busy}>
                  <Save aria-hidden="true" />
                  保存研究设置
                </Button>
              </div>
            </div>
            <p role="status" aria-live="polite" className="text-sm text-pretty">
              {status}
            </p>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}
