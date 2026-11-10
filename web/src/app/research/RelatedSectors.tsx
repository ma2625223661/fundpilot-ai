// "同类板块" under a sector page: other sectors of the same category, in the
// table's default order (old sortSectors by score group), as links. Scores and
// changes are the old presentation texts; nothing is recalculated.
import { sectorHref } from '@/app/navigation';
import { periodChange } from '@/app/research/period';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, GROUP_LABELS, direction, stamp } from '@/lib/format';
import { TONE_TEXT, sectorTone, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

const LIMIT = 8;

export function relatedSectors(report: Report, sector: Sector): Sector[] {
  const same = report.sector_analysis.filter((s: Sector) => s.group === sector.group && s.id !== sector.id);
  return (sectorResearch.sortSectors(same, 'score') as Sector[]).slice(0, LIMIT);
}

export function RelatedSectors({ report, sector }: { report: Report; sector: Sector }) {
  const rows = relatedSectors(report, sector);
  if (!rows.length) return null;
  const historical = report.report_stale === true;
  const group = GROUP_LABELS[sector.group] || sector.group;
  return (
    <section aria-label={'同类板块：' + group} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-balance">同类板块 · {group}</h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          报告时间 {stamp(report.as_of)}；研究分不代表收益概率，不构成投资建议
        </span>
      </div>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {rows.map(row => {
          const data = sectorResearch.sectorDataPresentation(row, { historical });
          const change = periodChange(row, report, 'day');
          return (
            <li key={row.id}>
              <a
                href={sectorHref(row.id)}
                className="flex h-full flex-col gap-1 rounded-lg border border-border p-3 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span className="truncate text-sm font-medium">{row.title}</span>
                <span className="flex items-baseline justify-between gap-2 tabular-nums">
                  <span className={cn('text-sm font-semibold', TONE_TEXT[sectorTone(row, historical)])}>
                    {data.scoreText}
                    <span className="ml-1 text-xs font-normal text-muted-foreground">{data.hasScore ? data.scoreUnit : ''}</span>
                  </span>
                  <span className={cn('text-xs font-medium', change.coloured ? DIRECTION_CLASS[direction(change.value)] : 'text-muted-foreground')}>
                    {change.text}
                  </span>
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
