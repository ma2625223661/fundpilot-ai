// Administrator form for one user's daily and monthly personal AI call limits
// (issue #5). A change applies at once and never gives back calls already used.
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { NumberField } from '@/components/number-field';
import { readQuota } from '@/lib/quota';
import type { Row } from '@/app/settings/account-shared';

// Suggested starting values for a user who has no limits yet.
const SUGGESTED = { daily: 5, monthly: 100 };

export function CallLimitsForm({ user, busy, onSave }: { user: Row | undefined; busy: boolean; onSave: (body: Row) => void }) {
  const quota = readQuota(user?.ai_subscription?.call_quota);
  const id = String(user?.id ?? '');
  // The saved limits fill the fields until the administrator edits them for this user.
  const [draft, setDraft] = useState<{ id: string; daily: number | null; monthly: number | null } | null>(null);
  const shown =
    draft && draft.id === id
      ? draft
      : { id, daily: quota?.dailyLimit ?? SUGGESTED.daily, monthly: quota?.monthlyLimit ?? SUGGESTED.monthly };
  const invalid = shown.daily === null || shown.monthly === null || shown.monthly < shown.daily;
  return (
    <form
      aria-label="AI 调用次数"
      onSubmit={event => {
        event.preventDefault();
        if (!user || invalid) return;
        onSave({ user_id: user.id, action: 'limits', daily_limit: shown.daily, monthly_limit: shown.monthly });
      }}
    >
      <FieldGroup>
        <div className="flex flex-col gap-0.5">
          <h3 className="font-medium">AI 调用次数</h3>
          <p className="text-xs text-muted-foreground text-pretty tabular-nums">
            {!user
              ? '请先选择用户。'
              : quota?.configured
                ? `${user.username} 当前：每日 ${quota.dailyLimit} 次、每月 ${quota.monthlyLimit} 次；今日已用 ${quota.dailyUsed} 次，本月已用 ${quota.monthlyUsed} 次（北京时间）。`
                : `${user.username} 尚未设置调用次数，暂不能自行发起 AI 研究。`}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="limit-daily">每天可调用次数</FieldLabel>
            <NumberField
              id="limit-daily"
              min={0}
              max={1000}
              value={shown.daily}
              onValueChange={daily => setDraft({ ...shown, daily })}
              required
              disabled={busy || !user}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="limit-monthly">每个自然月可调用总次数</FieldLabel>
            <NumberField
              id="limit-monthly"
              min={0}
              max={30000}
              value={shown.monthly}
              onValueChange={monthly => setDraft({ ...shown, monthly })}
              required
              disabled={busy || !user}
            />
          </Field>
        </div>
        {invalid && shown.daily !== null && shown.monthly !== null && (
          <p className="text-sm text-destructive">每月调用总次数不能少于每天可调用次数。</p>
        )}
        <Button type="submit" variant="outline" className="self-start" disabled={busy || !user || invalid}>
          保存调用次数
        </Button>
        <FieldDescription className="text-pretty">
          按北京时间计算，保存后立即生效，不追溯已用次数。只有成功调用模型才计 1 次；失败、复用已有解读、未设置次数或密钥不可用时不计。研究点数与有效期仍照常检查。
        </FieldDescription>
      </FieldGroup>
    </form>
  );
}
