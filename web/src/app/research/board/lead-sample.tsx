// The leading company sample of a sector and how many samples rose or fell.
import { DIRECTION_CLASS, direction, finite, pct } from '@/lib/format';
import { type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

/**
 * The company sample with the largest change today, and how many samples rose or
 * fell (as quote centres show a sector's leading stock). Only picks and counts
 * the quotes the report already holds; nothing is recalculated.
 */
export function leadSample(report: Report, sector: Sector) {
  const rows: Sector[] = report.company_evidence.sector_leaders[sector.id] || [];
  const quoted = rows.filter(row => finite(row.quote?.pct_chg));
  if (!quoted.length) return null;
  const top = quoted.reduce((best, row) => (row.quote.pct_chg > best.quote.pct_chg ? row : best));
  return {
    name: top.name as string,
    change: top.quote.pct_chg as number,
    date: String(top.quote.trade_date || top.as_of || '').slice(5, 10),
    up: quoted.filter(row => row.quote.pct_chg > 0).length,
    down: quoted.filter(row => row.quote.pct_chg < 0).length,
    total: rows.length,
  };
}

export function LeadSample({ report, sector, className }: { report: Report; sector: Sector; className?: string }) {
  const lead = leadSample(report, sector);
  if (!lead) return <span className={cn('text-xs text-muted-foreground', className)}>—</span>;
  const tone = report.report_stale ? 'unknown' : direction(lead.change);
  return (
    <span className={cn('flex flex-col', className)}>
      <span className="flex items-baseline gap-1.5 whitespace-nowrap">
        <span className="max-w-24 truncate text-sm">{lead.name}</span>
        <span className={cn('text-sm font-medium tabular-nums', DIRECTION_CLASS[tone])}>{pct(lead.change)}</span>
      </span>
      <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
        {lead.up} 涨 · {lead.down} 跌 / {lead.total} 家{lead.date && ' · ' + lead.date}
      </span>
    </span>
  );
}
