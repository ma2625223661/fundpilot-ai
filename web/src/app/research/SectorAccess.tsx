// Port of accessCard() in dist/ai-subscription.js: a locked AI interpretation
// can be unlocked with research credits, or leads to the subscription page.
import { useState } from 'react';
import { ExternalLink, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Eyebrow } from '@/components/research/common';
import { creditText, useSubscription } from '@/app/research/SubscriptionContext';
import { subscriptions } from '@/lib/research';
import type { Report, Sector } from '@/lib/report';

export function ServiceLink({ children = '联系客服订阅' }: { children?: string }) {
  return (
    <a
      href="ai-service.html#contactTitle"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
    >
      {children}
      <ExternalLink className="size-3" aria-hidden="true" />
    </a>
  );
}

export function SectorAccess({ sector, report }: { sector: Sector; report: Report }) {
  const { available, unlock, unlocking } = useSubscription();
  const [status, setStatus] = useState('');
  if (!available) return null;
  const price = creditText(subscriptions.accessPrice(sector));
  const busy = unlocking.has(sector.ai_access?.content_id);
  const effort = sector.ai_access.pricing_legacy ? '旧报告按原标准' : sector.ai_access.reasoning_effort === 'medium' ? '中度推理' : '极高推理';
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <Eyebrow>
        <span className="inline-flex items-center gap-1">
          <Sparkles className="size-3.5" aria-hidden="true" />
          AI 自动化研究
        </span>
      </Eyebrow>
      <h3 className="font-semibold text-balance">{report.report_stale ? '历史板块 AI 解读' : '本期板块 AI 解读'}</h3>
      <p className="text-sm text-muted-foreground text-pretty">
        {report.report_stale
          ? '历史解读仅供复盘，不代表当前市场判断。'
          : '结合已取得的业务、财务、走势与事件证据，查看研究理由、主要风险及后续复核条件。'}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        {sector.ai_access.can_unlock ? (
          <Button disabled={busy} onClick={async () => setStatus(await unlock(sector, report))}>
            {busy ? '正在解锁…' : `${report.report_stale ? '解锁历史' : '解锁本期'} · ${price} 点`}
          </Button>
        ) : (
          <ServiceLink />
        )}
        <small className="text-xs text-muted-foreground">
          本份解读 {price} 点 · {effort} · 重复查看不扣点
        </small>
      </div>
      <p role="status" aria-live="polite" className="text-sm text-pretty">
        {status}
      </p>
    </section>
  );
}
