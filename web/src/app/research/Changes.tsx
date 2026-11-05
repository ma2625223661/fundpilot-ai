// Day-over-day changes from the backend (report.sector_changes): a one-line
// summary for cards, and the "变动提醒" bell in the header. Deltas are read,
// never computed; signs always accompany colours (red up, green down).
import { useState } from 'react';
import { Bell } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { sectorHref } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { useWatchlist } from '@/app/research/WatchlistContext';
import { hasChange, type SectorChange, type SectorChanges } from '@/lib/changes';
import { DIRECTION_CLASS, direction, num } from '@/lib/format';
import type { Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

const FLAG_TONE: Record<string, string> = {
  新增特大风险: 'text-destructive',
  新增趋势优: 'text-tier-optimistic',
};

/** "研究分 +2.10 · 档位由中性变为乐观 · 新增特大风险 · 风险由常规波动变为高风险". */
export function ChangeParts({ change, className }: { change: SectorChange; className?: string }) {
  const parts: React.ReactNode[] = [];
  if (change.scoreDelta !== null) {
    parts.push(
      <span key="score">
        研究分{' '}
        <span className={cn('font-medium', DIRECTION_CLASS[direction(change.scoreDelta)])}>
          {(change.scoreDelta > 0 ? '+' : '') + num(change.scoreDelta)}
        </span>
      </span>,
    );
  }
  if (change.tier) parts.push(<span key="tier">档位由{change.tier.before}变为{change.tier.now}</span>);
  for (const flag of change.flags) parts.push(<span key={flag} className={cn('font-medium', FLAG_TONE[flag])}>{flag}</span>);
  if (change.risk) parts.push(<span key="risk">风险由{change.risk.before}变为{change.risk.now}</span>);
  return (
    <span className={cn('flex flex-wrap items-baseline gap-x-2 gap-y-0.5 tabular-nums', className)}>
      {parts.map((part, index) => (
        <span key={index} className="flex items-baseline gap-2">
          {index > 0 && <span className="text-muted-foreground" aria-hidden="true">·</span>}
          {part}
        </span>
      ))}
    </span>
  );
}

/** One line for a sector card, with the baseline date; says so when nothing is comparable. */
export function ChangeLine({ sectorId }: { sectorId: string }) {
  const { report } = useResearch();
  const block = report?.sector_changes as SectorChanges | undefined;
  if (!block) return null;
  const change = block.items[sectorId] ?? null;
  return (
    <div className="flex flex-col gap-0.5 text-xs">
      <span className="text-muted-foreground tabular-nums">
        {block.baselineDate ? `较上一交易日（${block.baselineDate}）` : '较上一交易日'}
      </span>
      {block.status !== 'ok' ? (
        <span className="text-muted-foreground">无可比基线</span>
      ) : hasChange(change) ? (
        <ChangeParts change={change} />
      ) : (
        <span className="text-muted-foreground">研究证据无变化</span>
      )}
    </div>
  );
}

const SEEN_KEY = 'fundpilot_changes_seen_v1';

function readSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) || '';
  } catch {
    return '';
  }
}

/**
 * Header bell: notable changes of followed sectors (account edition), or of all
 * sectors when there is no watchlist. The dot marks a report not yet looked at.
 */
export function ChangesBell() {
  const { report } = useResearch();
  const watch = useWatchlist();
  const [seen, setSeen] = useState(readSeen);
  const block = report?.sector_changes as SectorChanges | undefined;
  if (!report || !block) return null;
  const scope = watch.available ? new Set(watch.items) : null;
  const sectors = new Map<string, Sector>(report.sector_analysis.map((s: Sector) => [s.id, s]));
  const rows = Object.entries(block.items)
    .filter(([id, change]) => change.notable && sectors.has(id) && (!scope || scope.has(id)))
    .sort(([, a], [, b]) => Math.abs(b.scoreDelta ?? 0) - Math.abs(a.scoreDelta ?? 0));
  const stamp = String(report.as_of || '');
  const unread = rows.length > 0 && seen !== stamp;
  const markSeen = () => {
    setSeen(stamp);
    try {
      localStorage.setItem(SEEN_KEY, stamp);
    } catch {
      // Storage unavailable: the dot returns on the next visit.
    }
  };
  return (
    <Popover onOpenChange={open => open && markSeen()}>
      <PopoverTrigger
        render={
          <Button variant="ghost" size="icon" className="relative" aria-label={unread ? `变动提醒，有 ${rows.length} 条未读` : '变动提醒'} />
        }
      >
        <Bell aria-hidden="true" />
        {unread && <span className="absolute top-2 right-2 size-2 rounded-full bg-destructive" aria-hidden="true" />}
      </PopoverTrigger>
      <PopoverContent align="end" className="max-h-(--available-height) w-80 gap-3 overflow-y-auto sm:w-96">
        <PopoverHeader>
          <PopoverTitle className="font-semibold">{scope ? '我关注的板块有这些变动' : '有明显变动的板块'}</PopoverTitle>
          <PopoverDescription className="text-pretty tabular-nums">
            {block.baselineDate ? `较上一交易日（${block.baselineDate}）。` : ''}
            {block.note}
          </PopoverDescription>
        </PopoverHeader>
        {block.status !== 'ok' ? (
          <p className="text-sm text-muted-foreground text-pretty">{block.reason}</p>
        ) : !rows.length ? (
          <p className="text-sm text-muted-foreground text-pretty">
            {scope && !scope.size ? '还没有关注的板块。在"我的关注与订阅"添加后，这里会提示它们的变动。' : '没有明显变动（研究分变化不足 3 分，档位、风险标记和风险等级未变）。'}
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {rows.map(([id, change]) => (
              <li key={id}>
                <a
                  href={sectorHref(id)}
                  className="flex flex-col gap-0.5 rounded-md p-2 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <span className="font-medium">{sectors.get(id)?.title ?? id}</span>
                  <ChangeParts change={change} className="text-xs" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
