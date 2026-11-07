// Port of the state half of dist/ai-subscription.js: the account's AI research
// subscription (credits, expiry, preferred reasoning depth), one-off unlocks and
// personal AI research jobs that survive a page reload (resumed from the server).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, request } from '@/lib/api';
import { subscriptions } from '@/lib/research';
import { useResearch } from '@/app/research/ResearchContext';
import type { Report, Sector } from '@/lib/report';

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Subscription = Record<string, any>;
export type LedgerItem = Record<string, any>;
export type ResearchJob = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

const CREDIT_RATES: Record<string, number> = { medium: 1, xhigh: 1.5 };

export function creditText(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) : '—';
}

const researchKey = (sectorId: string, reportId: string, effort: string) => JSON.stringify([sectorId, reportId, effort]);
export const jobBusy = (job?: ResearchJob) => Boolean(job && ['submitting', 'running', 'query_error'].includes(job.status));

// The old api() turned network failures into a message that says retrying is safe.
async function api<T>(path: string, body?: unknown): Promise<T> {
  try {
    return await request<T>(path, body);
  } catch (error) {
    if (error instanceof ApiError && error.status === 0)
      throw new Error('结果暂未确认，请重新读取状态；重试同一操作不会重复扣减或增加额度。');
    throw error;
  }
}

function progress(job: ResearchJob, value: ResearchJob = {}) {
  job.phase = value.phase === 'connecting' ? 'connecting' : value.phase === 'researching' ? 'researching' : job.phase || 'researching';
  job.message =
    job.phase === 'connecting'
      ? '正在连接并核验 AI 服务；连接成功后开始研究，连接失败不扣研究点数。生成成功后自动保存至研究记录，刷新后可恢复任务。'
      : 'AI 正在梳理本板块证据与详细建议。' +
        (job.reasoning_effort === 'xhigh' ? '极高推理可能需要数分钟。' : '') +
        '可保持页面或稍后回来查询，刷新后可恢复任务；请勿重复提交。生成成功后自动保存至研究记录。';
}

interface SubscriptionValue {
  available: boolean;
  subscription: Subscription | null;
  ledger: LedgerItem[];
  feedback: string;
  setFeedback: (value: string) => void;
  preferenceSaving: boolean;
  unlocking: Set<string>;
  jobs: Map<string, ResearchJob>;
  load: () => Promise<void>;
  savePreference: (effort: string) => Promise<void>;
  unlock: (sector: Sector, report: Report) => Promise<string>;
  startResearch: (sector: Sector, report: Report, choice: { effort: string }) => Promise<void>;
  queryResearch: (job: ResearchJob) => Promise<void>;
  jobFor: (sectorId: string, reportId: string, effort: string) => ResearchJob | undefined;
  /** Registered by the dashboard; returns the unregister function. */
  onOpenSector: (handler: (id: string) => void) => () => void;
  openSector: (id: string) => void;
}

const SubscriptionContext = createContext<SubscriptionValue | null>(null);

export function useSubscription() {
  const value = useContext(SubscriptionContext);
  if (!value) throw new Error('useSubscription must be used inside SubscriptionProvider');
  return value;
}

export function SubscriptionProvider({ children }: { children: ReactNode }) {
  const research = useResearch();
  const available = research.accountMode;
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [ledger, setLedger] = useState<LedgerItem[]>([]);
  const [feedback, setFeedback] = useState('');
  const [preferenceSaving, setPreferenceSaving] = useState(false);
  const [unlocking, setUnlocking] = useState<Set<string>>(new Set());
  const [, setRevision] = useState(0);
  const jobs = useRef(new Map<string, ResearchJob>());
  const loading = useRef(false);
  const resuming = useRef(false);
  // The dashboard registers how to open a sector; a request made while it is not
  // mounted (from another page) waits until it is.
  const openSector = useRef<((id: string) => void) | null>(null);
  const pendingOpen = useRef<string | null>(null);
  const researchRef = useRef(research);
  researchRef.current = research;
  const changed = useCallback(() => setRevision(value => value + 1), []);

  const accept = useCallback((value?: Subscription | null) => {
    if (value) setSubscription(value);
  }, []);

  const load = useCallback(async () => {
    if (!available || loading.current) return;
    loading.current = true;
    try {
      const data = await api<{ subscription: Subscription; items: LedgerItem[] }>('/api/me/ai-subscription');
      accept(data.subscription);
      setLedger(Array.isArray(data.items) ? data.items : []);
      setFeedback('');
    } catch (error) {
      setFeedback((error as Error).message);
    } finally {
      loading.current = false;
    }
  }, [accept, available]);

  const finish = useCallback(
    async (job: ResearchJob, result: ResearchJob) => {
      clearTimeout(job.timer);
      job.status = result.status;
      accept(result.subscription);
      if (result.status === 'completed') {
        if (result.saved === true) void researchRef.current.poll();
        if (result.stale === true || result.applicable === false) {
          job.message =
            '该次研究已完成，但结果已不适用于当前证据：' +
            (result.stale_reason || '报告或配置已更新') +
            '。' +
            (result.charged ? '该次已扣除 ' + creditText(result.charged_cost) + ' 点。' : '该次未扣点。') +
            ' 请刷新最新报告后再决定是否生成。';
          if (result.saved === true) job.message += ' 结果已自动保存至研究记录。';
          void load();
          changed();
          return;
        }
        job.message = result.charged
          ? (result.reused ? '已复用有效研究并解锁' : 'AI 研究已生成并解锁') + ' · 本次扣除 ' + creditText(result.charged_cost) + ' 点。'
          : 'AI 研究已可查看 · 本次未扣点，同一份重复查看不重复扣点。';
        if (result.saved === true) job.message += ' 已自动保存至研究记录。';
        const applied = researchRef.current.applyUnlockedSector(result.sector, result.report_id);
        if (!applied) job.message += ' 最新结果已保存，可刷新报告后查看。';
        else if (job.openOnComplete) openSector.current?.(job.sector_id);
        void load();
      } else {
        const reason = String(result.error || '未取得有效解读')
          .trim()
          .replace(/[。.!！?？；;\s]+$/u, '');
        job.message = /相同证据.*(?:30\s*分钟|暂缓重发)|30\s*分钟.*(?:暂缓|重发)/.test(reason)
          ? '相同证据近期已发送，为避免重复调用，请等待上次发送满 30 分钟后再生成；本次未扣点。'
          : /今日.*请求数.*(?:上限|保护)|每日.*请求.*上限|request_limit|daily.*request.*limit/i.test(reason)
            ? '今日 AI 请求数已达到保护上限，请等待北京时间次日 00:00 额度恢复，或联系管理员调整；本次未扣点。'
            : /预算|budget/i.test(reason)
              ? '今日 API 预算不足，请等待预算恢复或联系管理员调整；本次未扣点。'
              : '生成未完成：' + reason + '。本次未扣点，可重试。';
      }
      changed();
    },
    [accept, changed, load],
  );

  const queryResearch = useCallback(
    async (job: ResearchJob) => {
      if (job.querying || !job.job_id) return;
      job.querying = true;
      job.status = 'running';
      progress(job);
      changed();
      try {
        const result = await api<ResearchJob>('/api/me/ai-research?job_id=' + encodeURIComponent(job.job_id));
        if (result.status === 'completed' || result.status === 'failed') await finish(job, result);
        else if (result.status === 'running' || result.status === 'queued') {
          progress(job, result);
          clearTimeout(job.timer);
          job.timer = window.setTimeout(() => void queryResearch(job), 1500);
          changed();
        } else throw new Error('研究状态暂未确认');
      } catch (error) {
        job.status = 'query_error';
        job.message = '暂时无法确认研究进度：' + (error as Error).message + ' 可点击“查询研究进度”，不会重新提交生成。';
        changed();
      } finally {
        job.querying = false;
      }
    },
    [changed, finish],
  );

  const startResearch = useCallback(
    async (sector: Sector, report: Report, choice: { effort: string }) => {
      const key = researchKey(sector.id, report.as_of, choice.effort);
      const existing = jobs.current.get(key);
      if (existing?.status === 'query_error') return queryResearch(existing);
      if ([...jobs.current.values()].some(jobBusy)) return;
      const job: ResearchJob = {
        sector_id: sector.id,
        report_id: report.as_of,
        reasoning_effort: choice.effort,
        status: 'submitting',
        openOnComplete: true,
        message: '正在提交研究请求…',
      };
      jobs.current.set(key, job);
      changed();
      try {
        const result = await api<ResearchJob>('/api/me/ai-research', {
          sector_id: sector.id,
          report_id: report.as_of,
          reasoning_effort: choice.effort,
        });
        if (result.status === 'completed' || result.status === 'failed') await finish(job, result);
        else if ((result.status === 'running' || result.status === 'queued') && typeof result.job_id === 'string') {
          job.job_id = result.job_id;
          job.status = 'running';
          progress(job, result);
          job.timer = window.setTimeout(() => void queryResearch(job), 1500);
          changed();
        } else throw new Error('研究请求状态暂未确认，请重试查询');
      } catch (error) {
        job.status = 'failed';
        job.message = '请求未确认：' + (error as Error).message + ' 重试会先核对已有任务与结果，避免重复扣点。';
        changed();
      }
    },
    [changed, finish, queryResearch],
  );

  const resume = useCallback(async () => {
    if (!available || resuming.current) return;
    resuming.current = true;
    try {
      const data = await api<{ jobs?: ResearchJob[] }>('/api/me/ai-research');
      for (const value of Array.isArray(data.jobs) ? data.jobs : []) {
        if (
          !value ||
          typeof value.job_id !== 'string' ||
          typeof value.sector_id !== 'string' ||
          typeof value.report_id !== 'string' ||
          !CREDIT_RATES[value.reasoning_effort]
        )
          continue;
        const key = researchKey(value.sector_id, value.report_id, value.reasoning_effort);
        if (jobBusy(jobs.current.get(key))) continue;
        const job: ResearchJob = { ...value, status: 'running', openOnComplete: false };
        progress(job, value);
        jobs.current.set(key, job);
        job.timer = window.setTimeout(() => void queryResearch(job), 1500);
      }
      changed();
    } catch {
      // Resuming is best effort; the next visibility change tries again.
    } finally {
      resuming.current = false;
    }
  }, [available, changed, queryResearch]);

  useEffect(() => {
    if (!available) return;
    void load();
    void resume();
    const onVisible = () => {
      if (!document.hidden) {
        void load();
        void resume();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    const current = jobs.current;
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      current.forEach(job => clearTimeout(job.timer));
    };
  }, [available, load, resume]);

  // The research status carries the subscription too; keep the two in step.
  const runtimeSubscription = research.state.ai_subscription;
  useEffect(() => {
    if (runtimeSubscription) setSubscription(runtimeSubscription);
  }, [runtimeSubscription]);

  const savePreference = useCallback(
    async (effort: string) => {
      if (preferenceSaving || subscriptions.reasoningChoice(subscription)?.effort === effort) return;
      setPreferenceSaving(true);
      try {
        const data = await api<{ subscription: Subscription }>('/api/me/ai-preference', { reasoning_effort: effort });
        accept(data.subscription);
        setFeedback('已保存' + (effort === 'medium' ? '中度' : '极高') + '推理，切换未扣点。请在关注卡片点击“生成 AI 研究”开始。');
        await researchRef.current.poll();
      } catch (error) {
        setFeedback((error as Error).message);
      } finally {
        setPreferenceSaving(false);
      }
    },
    [accept, preferenceSaving, subscription],
  );

  const unlock = useCallback(
    async (sector: Sector, report: Report) => {
      const key = sector.ai_access?.content_id;
      if (!key || unlocking.has(key)) return '';
      setUnlocking(current => new Set(current).add(key));
      try {
        const result = await api<Record<string, unknown> & { subscription: Subscription; sector: Sector; report_id: string; charged?: boolean; charged_cost?: number }>(
          '/api/me/ai-unlock',
          { sector_id: sector.id, content_id: key, report_id: report.as_of },
        );
        accept(result.subscription);
        const applied = researchRef.current.applyUnlockedSector(result.sector, result.report_id);
        void load();
        return (
          (result.charged
            ? '已解锁，消耗 ' + creditText(result.charged_cost ?? subscriptions.accessPrice(sector)) + ' 点研究额度。'
            : '已解锁，本次未重复扣点。') + (applied ? '' : ' 请打开对应历史报告查看。')
        );
      } catch (error) {
        return (error as Error).message;
      } finally {
        setUnlocking(current => {
          const next = new Set(current);
          next.delete(key);
          return next;
        });
      }
    },
    [accept, load, unlocking],
  );

  const value: SubscriptionValue = {
    available,
    subscription,
    ledger,
    feedback,
    setFeedback,
    preferenceSaving,
    unlocking,
    jobs: jobs.current,
    load,
    savePreference,
    unlock,
    startResearch,
    queryResearch,
    jobFor: (sectorId, reportId, effort) => jobs.current.get(researchKey(sectorId, reportId, effort)),
    onOpenSector: handler => {
      openSector.current = handler;
      if (pendingOpen.current) {
        const id = pendingOpen.current;
        pendingOpen.current = null;
        handler(id);
      }
      return () => {
        if (openSector.current === handler) openSector.current = null;
      };
    },
    openSector: id => {
      if (openSector.current) openSector.current(id);
      else pendingOpen.current = id;
    },
  };
  return <SubscriptionContext.Provider value={value}>{children}</SubscriptionContext.Provider>;
}
