// Dense sortable table for tablets and desktops.
import { Fragment } from 'react';
import { ArrowDown, ArrowUpDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { IndicatorIcon } from '@/components/research/common';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, finite, num, txt } from '@/lib/format';
import { TONE_BADGE, TONE_BORDER, TONE_TEXT, sectorEvents, sectorTone, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';
import { type SortMode } from '@/app/research/board/board-view';
import { LeadSample } from '@/app/research/board/lead-sample';

function SortHead({
  label,
  mode,
  sort,
  setSort,
  className,
}: {
  label: string;
  mode: SortMode;
  sort: SortMode;
  setSort: (mode: SortMode) => void;
  className?: string;
}) {
  const active = sort === mode;
  return (
    <TableHead aria-sort={active ? (mode === 'name' ? 'ascending' : 'descending') : 'none'} className={className}>
      <Button variant="ghost" size="xs" className={cn('-mx-2', active ? 'text-primary' : 'text-muted-foreground')} onClick={() => setSort(mode)}>
        {label}
        {active ? <ArrowDown aria-hidden="true" /> : <ArrowUpDown aria-hidden="true" />}
      </Button>
    </TableHead>
  );
}

/** Dense, sortable table for tablets and desktops; the sort keys are the old ones. */
export function SectorTable({
  sectors,
  report,
  sort,
  setSort,
  counts,
  current,
  onOpen,
}: {
  sectors: Sector[];
  report: Report;
  sort: SortMode;
  setSort: (mode: SortMode) => void;
  counts: Map<string, number>;
  current: string | null;
  onOpen: (id: string) => void;
}) {
  const historical = report.report_stale;
  let previous: string | null = null;
  return (
    <div className="hidden md:block">
      <Table containerClassName="max-h-dvh overflow-y-auto rounded-lg border border-border">
        <TableHeader className="sticky top-0 z-20 bg-card shadow-xs">
          <TableRow>
            <SortHead label="板块" mode="name" sort={sort} setSort={setSort} />
            <SortHead label="涨跌幅" mode="change" sort={sort} setSort={setSort} className="text-right" />
            <TableHead className="hidden text-xs xl:table-cell">领涨样本</TableHead>
            <SortHead label="研究分" mode="score" sort={sort} setSort={setSort} className="text-right" />
            <TableHead className="text-right text-xs">基本面 / 40</TableHead>
            <TableHead className="text-right text-xs">走势 / 30</TableHead>
            <TableHead className="text-right text-xs">事件 ±30</TableHead>
            <TableHead className="text-xs">行情风险</TableHead>
            <TableHead className="hidden text-right text-xs xl:table-cell">环境风险</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sectors.map(sector => {
            const data = sectorResearch.sectorDataPresentation(sector, {
              historical,
              companyCount: (report.company_evidence.sector_leaders[sector.id] || []).length,
              eventCount: sectorEvents(report, sector.id).length,
            });
            const tone = sectorTone(sector, historical);
            const view = sectorResearch.companyScoreView(sector);
            const indicator = historical ? null : sectorResearch.sectorIndicator(sector);
            const parts = sector.score_breakdown || {};
            const risk = sector.market_risk || {};
            const changeTone = data.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
            const family = sectorResearch.boardScoreGroup(sector);
            const heading =
              sort === 'score' && family.id !== previous ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="bg-muted/50 py-1.5">
                    <span className="text-xs font-semibold tabular-nums">
                      {family.label} · {counts.get(family.id)} 个
                    </span>
                  </TableCell>
                </TableRow>
              ) : null;
            previous = family.id;
            const part = (value: unknown, signed = false) =>
              finite(value) ? (
                <span className={cn(signed && value > 0 && 'text-rise', signed && value < 0 && 'text-fall')}>
                  {(signed && value > 0 ? '+' : '') + num(value)}
                </span>
              ) : (
                <span className="text-muted-foreground">待评估</span>
              );
            return (
              <Fragment key={sector.id}>
                {heading}
                <TableRow data-state={sector.id === current ? 'selected' : undefined} className="relative cursor-pointer">
                  <TableCell className={cn('border-l-4 py-2', TONE_BORDER[tone])}>
                    {/* The name button stretches over the whole row, so any click on the row
                        opens the detail while keyboard users still reach one real button. */}
                    <Button
                      variant="link"
                      aria-haspopup="dialog"
                      className="h-auto p-0 text-sm font-semibold text-foreground after:absolute after:inset-0"
                      onClick={() => onOpen(sector.id)}
                    >
                      {sector.title}
                    </Button>
                    <span className="block max-w-28 truncate text-xs text-muted-foreground 2xl:max-w-52" title={data.subtitle}>
                      {data.subtitle}
                    </span>
                  </TableCell>
                  <TableCell className={cn('text-right font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>{data.changeText}</TableCell>
                  <TableCell className="hidden xl:table-cell">
                    <LeadSample report={report} sector={sector} />
                  </TableCell>
                  {/* Below 1536px the tier label drops under the score instead of widening the table. */}
                  <TableCell className="text-right whitespace-normal 2xl:whitespace-nowrap">
                    <span className={cn('text-base font-semibold tabular-nums', TONE_TEXT[tone])}>{data.scoreText}</span>
                    {view && <span className={cn('ml-1 inline-block rounded-sm px-1 py-0.5 text-xs whitespace-nowrap', TONE_BADGE[tone])}>{view.label}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.fundamentals?.points) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.trend?.points) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.catalysts?.observed_adjustment, true) : '—'}</TableCell>
                  <TableCell className="text-xs whitespace-normal">
                    <span className="relative z-10 flex items-center gap-1">
                      {indicator && <IndicatorIcon indicator={indicator} />}
                      {data.riskText}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-right text-xs tabular-nums xl:table-cell" title={txt(risk.scope)}>
                    {finite(risk.score) ? num(risk.score, 0) + '/100' : '—'}
                  </TableCell>
                </TableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
