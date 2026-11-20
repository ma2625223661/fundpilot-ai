// Port of researchControl() in dist/ai-subscription.js: the "generate AI research"
// button on a watchlist card, with every state the old button could be in.
import { Button } from '@/components/ui/button';
import { goTo } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { creditText, jobBusy, useSubscription } from '@/app/research/SubscriptionContext';
import { subscriptions } from '@/lib/research';
import type { Report, Sector } from '@/lib/report';
import { quotaBlock, quotaText, readQuota } from '@/lib/quota';

// Same wording as `labels` in the old ai-subscription.js (not exported there).
export const STATUS_LABELS: Record<string, string> = {
  active: '服务已开通',
  unsubscribed: '尚未订阅',
  expired: '订阅已到期',
  exhausted: '研究额度不足',
  paused: '服务已暂停',
  admin: '管理员',
};

export function openSubscriptionChoices() {
  goTo('dash');
  requestAnimationFrame(() => document.getElementById('aiSubscription')?.scrollIntoView({ block: 'start' }));
}

export function ResearchControl({ sector, report, onOpen }: { sector: Sector; report: Report; onOpen: () => void }) {
  const research = useResearch();
  const sub = useSubscription();
  const subscription = sub.subscription || research.state.ai_subscription || (research.session.isAdmin ? { status: 'admin' } : {});
  const config = research.config;
  const runtime = { subscription, config, state: research.state };
  const choice = subscriptions.manualResearchChoice(sector, subscription, runtime);
  const job = sub.jobFor(sector.id, report.as_of, choice.effort);
  const active = [...sub.jobs.values()].find(jobBusy);
  const isAdmin = subscription.status === 'admin';
  const existingEffort = sector.ai_reasoning_effort || sector.ai_access?.reasoning_effort;
  const viewable =
    sector.ai_research_status === 'completed' &&
    Boolean(sector.ai_analysis) &&
    (isAdmin || sector.ai_access?.status === 'unlocked') &&
    subscription.status !== 'paused';
  const detailed = subscriptions.hasDetailedResearch(sector);
  const legacyViewable = viewable && !detailed;
  const reusable = viewable && existingEffort === choice.effort && detailed;
  const enough = Number.isFinite(subscription.credits_remaining) && subscription.credits_remaining >= choice.cost;
  // Daily / monthly call limits (issue #5). Reopening a current interpretation asks no model, so it is never blocked.
  const quota = readQuota(subscription.call_quota);
  const quotaIssue = isAdmin || reusable ? '' : quotaBlock(quota);
  const allowed =
    (isAdmin || (subscription.status === 'active' && enough) || (reusable && ['active', 'expired', 'exhausted'].includes(subscription.status))) &&
    !quotaIssue;
  const historical = report.report_stale === true;
  const serviceIssue = !config
    ? 'AI 连接状态尚未确认，读取成功后可开始研究。'
    : !config.configured
      ? 'AI 服务尚未配置，请联系管理员完成连接配置。'
      : config.enabled === false
        ? 'AI 服务当前未启用，请联系管理员启用服务后再生成。'
        : '';
  const needsConnection = !serviceIssue && (config?.verification !== 'verified' || config?.effective_enabled === false);
  const busy = jobBusy(job);
  const price = creditText(choice.cost);

  const label = historical
    ? '历史快照仅供复盘'
    : job?.status === 'query_error'
      ? '查询研究进度'
      : busy
        ? job?.phase === 'connecting'
          ? '正在连接 AI…'
          : '正在生成 AI 研究…'
        : reusable
          ? '查看 AI 研究 · 不重复扣点'
          : serviceIssue
            ? 'AI 连接未就绪'
            : (legacyViewable ? '生成详细 AI 建议' : needsConnection ? '连接并生成研究' : job?.status === 'failed' ? '重试生成 AI 研究' : '生成 AI 研究') +
              ' · ' +
              choice.label +
              (isAdmin ? '' : ' ' + price + ' 点');
  const disabled =
    historical ||
    (!allowed && job?.status !== 'query_error') ||
    Boolean(serviceIssue && !reusable && !busy) ||
    Boolean(active && active !== job) ||
    Boolean(job && ['submitting', 'running'].includes(job.status));

  let message = historical
    ? '请返回最新报告后生成个人 AI 研究。'
    : job?.message ||
      (quotaIssue
        ? quotaIssue + '；未发起请求，也不扣次数。'
        : !allowed
        ? (subscription.status === 'active' && !enough
            ? '当前余额不足 ' + price + ' 点'
            : subscription.status
              ? STATUS_LABELS[subscription.status] || '请先开通订阅'
              : '正在确认订阅状态') + '；开通有效订阅并有足够额度后可生成。'
        : reusable
          ? '已有所选档位的有效解读，重复查看不扣点。'
          : isAdmin
            ? '点击后才生成个人板块研究，管理员不扣个人研究额度。'
            : '点击后才生成；本次' + choice.label + '成功后扣 ' + price + ' 点，失败不扣点。同一份已解锁结果重复查看不扣点。');
  if (needsConnection && !historical && !reusable && !busy && !job?.message && allowed)
    message =
      '点击后先连接并核验 AI 服务，通过后生成详细建议。' +
      (isAdmin
        ? '管理员不扣个人研究额度。'
        : '本次' + choice.label + '生成有效解读后扣 ' + price + ' 点；连接或研究失败不扣点，同一份已解锁结果重复查看免费。');
  if (legacyViewable && !historical && !job?.message && allowed)
    message =
      '已有研究可继续查看。点击后' +
      (needsConnection ? '先连接并核验服务，再' : '') +
      '生成包含依据、研究步骤和情景分析的详细建议；' +
      (isAdmin ? '管理员不扣个人研究额度。' : '新的详细建议成功后按' + choice.label + '扣 ' + price + ' 点，连接或研究失败不扣点。');
  if (!viewable && !job?.message && !historical && !serviceIssue && allowed) message += ' 生成成功后自动保存至研究记录，刷新后可恢复任务。';
  if (serviceIssue && !historical && !reusable && !busy) message = serviceIssue + ' 当前不会发起新研究或扣点。';
  if (active && active !== job) message = '另一份个人 AI 研究正在处理，请等待完成后再开始本板块。';

  return (
    <section className="flex flex-col gap-2">
      <small className="text-xs text-muted-foreground tabular-nums">
        中度推理 1 点 / 份 · 极高推理 1.5 点 / 份{isAdmin ? '' : ' · ' + quotaText(quota)}
      </small>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={disabled}
          aria-label={sector.title + '：' + label}
          onClick={() => {
            if (job?.status === 'query_error') void sub.queryResearch(job);
            else if (reusable) onOpen();
            else void sub.startResearch(sector, report, choice);
          }}
        >
          {label}
        </Button>
        <Button variant="outline" onClick={openSubscriptionChoices}>
          调整推理深度
        </Button>
        {legacyViewable && (
          <Button variant="ghost" onClick={onOpen}>
            查看已有 AI 研究 · 不重复扣点
          </Button>
        )}
      </div>
      <p role="status" aria-live="polite" className="text-sm text-muted-foreground text-pretty">
        {message}
      </p>
    </section>
  );
}
