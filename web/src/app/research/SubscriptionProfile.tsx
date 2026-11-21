// Port of mountProfile / drawProfile / drawCreditPolicy / drawLedger in
// dist/ai-subscription.js: credits, expiry, unlocked count, reasoning depth
// choice and the last 30 credit changes.
import { Check, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { goTo } from '@/app/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Disclosure, Stat } from '@/components/research/common';
import { useResearch } from '@/app/research/ResearchContext';
import { ServiceLink } from '@/app/research/SectorAccess';
import { creditText, useSubscription } from '@/app/research/SubscriptionContext';
import { subscriptions } from '@/lib/research';
import { cn } from '@/lib/utils';
import { readQuota } from '@/lib/quota';

const LEDGER_NAMES: Record<string, string> = {
  grant: '管理员开通 / 续订',
  pause: '管理员暂停服务',
  resume: '管理员恢复服务',
  unlock: '解锁板块解读',
  limits: '管理员调整 AI 调用次数',
};
const EFFORTS: [string, string, string][] = [
  ['medium', '中度推理', '日常跟踪'],
  ['xhigh', '极高推理', '复杂证据梳理'],
];
const RATES: Record<string, number> = { medium: 1, xhigh: 1.5 };

export function SubscriptionProfile() {
  const { session } = useResearch();
  const sub = useSubscription();
  const current = sub.subscription;
  const p = current ? subscriptions.presentation(current) : null;
  const choice = current ? subscriptions.reasoningChoice(current) : null;
  const admin = session.isAdmin;
  const quota = readQuota(current?.call_quota);
  // An administrator has no personal credits to show; point to what an admin manages instead.
  if (admin)
    return (
      <Card id="aiSubscription" size="sm">
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-primary" aria-hidden="true" />
              <b className="font-semibold">管理员账号 · AI 服务统一管理</b>
            </span>
            <span className="text-sm text-muted-foreground text-pretty">
              查看和生成 AI 解读不扣个人额度。用户的研究额度、有效期与暂停在用户管理中操作；共享研究的推理强度在 AI 研究设置中选择。
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => goTo('aiSubscriptionAdmin')}>
              <Users aria-hidden="true" />
              管理用户订阅与额度
            </Button>
            <Button variant="ghost" onClick={() => goTo('researchSettings')}>
              调整推理强度
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  return (
    <Card id="aiSubscription">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">我的 AI 订阅</h2>
          <Badge variant="secondary">{p ? p.label : '读取订阅中'}</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">
          {admin
            ? '为用户分配研究额度（点）与有效期。服务商实际调用费用由后台统一承担。'
            : '点击生成后才开始个人 AI 研究，成功后扣点并解锁。同一份解读反复查看不重复扣点。'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat
            label={p?.status === 'admin' ? '全站 AI 服务' : '剩余研究额度（点）'}
            value={p ? p.credits + (p.status === 'admin' ? '' : ' 点') : '—'}
          />
          {p?.status !== 'admin' && <Stat label="有效期至" value={p ? p.expiry : '读取中'} />}
          <Stat label="已解锁解读" value={p ? p.count + ' 份' : '—'} />
          {p?.status !== 'admin' && (
            <>
              <Stat
                label="今日剩余调用"
                value={quota?.configured ? quota.dailyRemaining + ' / ' + quota.dailyLimit + ' 次' : '—'}
                note={quota && !quota.configured ? '管理员尚未设置' : '北京时间每日 0 点恢复'}
              />
              <Stat
                label="本月剩余调用"
                value={quota?.configured ? quota.monthlyRemaining + ' / ' + quota.monthlyLimit + ' 次' : '—'}
                note={quota?.month ? `${quota.month.slice(0, 4)} 年 ${Number(quota.month.slice(5))} 月，只计成功调用` : undefined}
              />
            </>
          )}
        </div>
        {current && (
          <Disclosure
            title={
              choice
                ? `我的推理深度：${choice.label} · ${creditText(choice.cost)} 点 / 份 · 点击调整`
                : '选择推理深度 · 中度 1 点 / 极高 1.5 点'
            }
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <b className="font-medium text-foreground">选择我的推理深度</b>
              <span className="text-xs">1 份 = 1 个板块的 1 期 AI 解读</span>
            </div>
            <ToggleGroup
              variant="outline"
              aria-label="个人推理深度"
              className="w-full flex-col items-stretch sm:flex-row"
              value={choice ? [choice.effort] : []}
              onValueChange={value => value[0] && void sub.savePreference(value[0])}
            >
              {EFFORTS.map(([effort, label, description]) => {
                const cost = RATES[effort];
                const plan = subscriptions.creditPlan(current.credits_remaining, cost);
                const selected = choice?.effort === effort;
                return (
                  <ToggleGroupItem
                    key={effort}
                    value={effort}
                    disabled={sub.preferenceSaving}
                    aria-label={`选择${label}，每份 ${creditText(cost)} 点`}
                    className="h-auto flex-1 flex-col items-start gap-1 p-3 text-left whitespace-normal"
                  >
                    <span className="flex w-full items-center justify-between gap-2">
                      <b className="font-medium">{label}</b>
                      <span className={cn('flex items-center gap-1 text-xs', selected ? 'text-primary' : 'text-muted-foreground')}>
                        {selected && <Check className="size-3" aria-hidden="true" />}
                        {selected ? '已选择' : '选择此档'}
                      </span>
                    </span>
                    <strong className="tabular-nums">{creditText(cost)} 点 / 份</strong>
                    <small className="text-xs text-muted-foreground">{description}</small>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {current.status === 'admin'
                        ? '管理员查看不扣个人额度'
                        : plan
                          ? `当前余额可解锁 ${plan.count} 份` + (plan.remainder ? ` · 余 ${creditText(plan.remainder)} 点` : '')
                          : '余额读取后显示可用份数'}
                    </span>
                  </ToggleGroupItem>
                );
              })}
            </ToggleGroup>
            <p className="text-pretty">
              {sub.preferenceSaving
                ? '正在保存个人选择…'
                : choice
                  ? `我的选择：${choice.label} · ${creditText(choice.cost)} 点 / 份，已随账号保存。`
                  : '请选择适合自己的推理深度；尚未选择时展示已有共享解读的实际档位。'}
            </p>
            <p className="text-pretty">
              个人研究由您在关注卡片点击“生成 AI 研究”后开始。关注板块、查看行情或切换深度都不调用 AI、不扣点；生成有效解读后按所选档位扣点并解锁，同一份重复查看免费。管理员公共研究计划独立运行。
            </p>
            <p className="text-pretty">
              未生成有效解读时不扣点。旧报告未记录推理强度时按 1 点 / 份。额度不足或到期后，已解锁内容仍可复盘；服务暂停期间不可查看。
            </p>
          </Disclosure>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => void sub.load()}>
            <RefreshCw aria-hidden="true" />
            刷新订阅状态
          </Button>
          {!admin && <ServiceLink>订阅 / 续订</ServiceLink>}
        </div>
        <Disclosure title="查看最近 30 条额度记录">
          {!sub.ledger.length && <p>暂无额度变动记录。</p>}
          {sub.ledger.map((item, index) => (
            <div key={index} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted p-2">
              <div className="flex flex-col">
                <b className="font-medium text-foreground">{LEDGER_NAMES[item.kind] || '额度变动'}</b>
                <small className="tabular-nums">
                  {new Date(item.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}
                </small>
                <small>{item.note || '账号研究服务'}</small>
              </div>
              <strong className={cn('tabular-nums', item.delta > 0 ? 'text-foreground' : 'text-muted-foreground')}>
                {(item.delta > 0 ? '+' : '') + creditText(item.delta)} 点
              </strong>
              <span className="text-xs tabular-nums">余额 {creditText(item.balance)} 点</span>
            </div>
          ))}
        </Disclosure>
        <p role="status" className="text-sm text-pretty">
          {sub.feedback}
        </p>
      </CardContent>
    </Card>
  );
}
