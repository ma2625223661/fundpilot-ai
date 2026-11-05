// One vocabulary for the research service state, shared by the dashboard status
// strip and the sidebar status card, so the same state always has the same
// words, icon and colour: blue while updating or up to date, amber for a
// historical snapshot, red when the service fails.
import { CircleAlert, CircleCheck, History, LoaderCircle, type LucideIcon } from 'lucide-react';
import type { AutoState } from '@/lib/report';

export type ResearchTone = 'running' | 'ready' | 'stale' | 'error' | 'idle';

export interface ResearchStatus {
  tone: ResearchTone;
  label: string;
  icon: LucideIcon;
  /** Text colour for the icon or label. */
  text: string;
  /** Fill for a small status dot. */
  dot: string;
}

const LOOK: Record<ResearchTone, Pick<ResearchStatus, 'icon' | 'text' | 'dot'>> = {
  running: { icon: LoaderCircle, text: 'text-primary', dot: 'bg-primary' },
  ready: { icon: CircleCheck, text: 'text-primary', dot: 'bg-primary' },
  idle: { icon: LoaderCircle, text: 'text-muted-foreground', dot: 'bg-muted-foreground' },
  stale: { icon: History, text: 'text-warning', dot: 'bg-warning' },
  error: { icon: CircleAlert, text: 'text-destructive', dot: 'bg-destructive' },
};

/**
 * Failure first, then an update in progress, then whether the report on screen
 * is a historical snapshot. `stale` comes from the report (report_stale).
 */
export function researchStatus(state: AutoState, stale: boolean): ResearchStatus {
  const [tone, label]: [ResearchTone, string] = state.connection_error
    ? ['error', '研究服务未连接']
    : state.status === 'error'
      ? ['error', '本轮研究暂未完成']
      : state.status === 'running'
        ? ['running', '正在更新板块研究']
        : stale
          ? ['stale', '显示历史快照']
          : state.status === 'ready'
            ? ['ready', '研究已是最新']
            : ['idle', '正在连接研究服务'];
  return { tone, label, ...LOOK[tone] };
}
