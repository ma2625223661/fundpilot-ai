// The parts of the AI settings form: the service introduction and the three
// numbered steps (research depth, schedule, budget). They only display values
// and report edits; state, saving and the connection check stay in AiSettings.
import type { RefObject } from 'react';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldDescription, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { NumberField } from '@/components/number-field';
import { Disclosure } from '@/components/research/common';
import { MODEL, REASONING, SectionTitle } from '@/app/settings/research-settings/shared';
import type { AiForm, EditAiForm } from '@/app/settings/research-settings/ai-form';

/** What the subscription service offers, shown above the form. */
export function ServicePitch() {
  return (
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
  );
}

/** 01: model, reasoning depth and (for administrators) the service connection. */
export function DepthSection({
  shown,
  edit,
  locked,
  cloud,
  accountMode,
  configured,
  keyInput,
}: {
  shown: AiForm;
  edit: EditAiForm;
  /** Not allowed to manage, or a save / check is running. */
  locked: boolean;
  cloud: boolean;
  accountMode: boolean;
  configured: boolean;
  keyInput: RefObject<HTMLInputElement | null>;
}) {
  return (
    <FieldSet disabled={locked}>
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
        <Select value={shown.reasoning} onValueChange={value => edit({ reasoning: String(value) })} disabled={locked}>
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
            disabled={cloud || locked}
            placeholder={cloud ? '由托管平台环境变量管理' : configured ? '留空保留已保存的密钥' : '输入 AI API Key'}
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
          <Input id="aiBaseUrl" type="url" autoComplete="off" value={shown.baseUrl} onChange={event => edit({ baseUrl: event.target.value })} />
          <FieldDescription>服务商实际调用费用由后台统一承担。</FieldDescription>
        </Field>
      </Disclosure>
    </FieldSet>
  );
}

/** 02: the fixed 09:20 / 14:50 trading-day schedule and the on / off switch. */
export function ScheduleSection({
  shown,
  edit,
  locked,
  cloud,
  calendarText,
  nextText,
}: {
  shown: AiForm;
  edit: EditAiForm;
  locked: boolean;
  cloud: boolean;
  calendarText: string;
  nextText: string;
}) {
  return (
    <FieldSet disabled={locked}>
      <SectionTitle index="02" title="安排研究时间" />
      <Field orientation="horizontal">
        <Switch id="autoAiEnabled" checked={shown.enabled} onCheckedChange={value => edit({ enabled: value })} disabled={locked} />
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
  );
}

/** 03: reuse of unchanged interpretations and the daily request / token budget. */
export function BudgetSection({ shown, edit, locked }: { shown: AiForm; edit: EditAiForm; locked: boolean }) {
  return (
    <FieldSet disabled={locked}>
      <SectionTitle index="03" title="管理用量预算" />
      <Field orientation="horizontal">
        <Checkbox id="aiReuse" checked={shown.reuse} onCheckedChange={value => edit({ reuse: value === true })} disabled={locked} />
        <div className="flex flex-col">
          <Label htmlFor="aiReuse">复用未变化的有效解读</Label>
          <span className="text-xs text-muted-foreground">保留原研究日期，证据或模型变化后重新研究。</span>
        </div>
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="aiDailyRequestLimit">每日请求上限</FieldLabel>
          <NumberField id="aiDailyRequestLimit" min={1} max={10000} value={shown.requests} onValueChange={value => edit({ requests: value })} disabled={locked} />
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
            disabled={locked}
          />
        </Field>
      </div>
      <FieldDescription className="text-pretty">
        按北京时间每日重置。中度按 1.0 倍、极高按 1.5 倍折算请求与 Token。实际用量与折算用量分别展示，不等于人民币账单。
      </FieldDescription>
    </FieldSet>
  );
}
