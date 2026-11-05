// Sector heat map, in the spirit of quote-centre sector maps: one tile per
// direction, grouped by category, coloured by the chosen period's change (red
// up, green down, A-share convention). Every tile is a real button that opens
// the detail. Tiles are the same size: the report has no market weights, and
// sizing by the change itself would exaggerate it. The sign is always written.
import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { sectorResearch } from '@/lib/research';
import { GROUP_LABELS, direction, stamp } from '@/lib/format';
import type { Report, Sector } from '@/lib/report';
import { PERIODS, periodChange, periodEnd, periodInfo, sortByPeriod, type Period, type PeriodChange } from '@/app/research/period';
import { cn } from '@/lib/utils';

// Four steps of the rise / fall tokens. Capped at /50 so foreground text keeps
// WCAG AA contrast on both themes. Literal strings so Tailwind keeps them.
const HEAT = {
  rise: ['bg-rise/10 hover:bg-rise/20', 'bg-rise/20 hover:bg-rise/30', 'bg-rise/35 hover:bg-rise/45', 'bg-rise/50 hover:bg-rise/60'],
  fall: ['bg-fall/10 hover:bg-fall/20', 'bg-fall/20 hover:bg-fall/30', 'bg-fall/35 hover:bg-fall/45', 'bg-fall/50 hover:bg-fall/60'],
} as const;

function heat(change: PeriodChange, steps: number[]) {
  const tone = direction(change.value);
  if (!change.coloured || (tone !== 'rise' && tone !== 'fall')) return 'bg-muted hover:bg-accent';
  const size = Math.abs(change.value as number);
  return HEAT[tone][steps.filter(limit => size >= limit).length];
}

function legend(steps: [number, number, number]): [string, string][] {
  const [a, b, c] = steps;
  return [
    ['bg-fall/50', `≤−${c}%`],
    ['bg-fall/35', `−${b}%`],
    ['bg-fall/20', `−${a}%`],
    ['bg-muted', '0'],
    ['bg-rise/20', `+${a}%`],
    ['bg-rise/35', `+${b}%`],
    ['bg-rise/50', `≥+${c}%`],
  ];
}

function Tile({
  sector,
  report,
  period,
  onOpen,
  folded,
}: {
  sector: Sector;
  report: Report;
  period: Period;
  onOpen: (id: string) => void;
  folded: boolean;
}) {
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, { historical });
  const info = periodInfo(period);
  const change = periodChange(sector, report, period);
  const when = periodEnd(change) ?? `行情时间 ${stamp(sector.as_of)}`;
  const label = period === 'day' ? data.changeLabel : info.phrase + '涨跌';
  return (
    <Button
      variant="ghost"
      aria-haspopup="dialog"
      aria-label={`${sector.title}，${label} ${change.text}，${when}，研究分 ${data.scoreText}`}
      onClick={() => onOpen(sector.id)}
      className={cn(
        'h-auto min-w-0 flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left whitespace-normal',
        heat(change, info.steps),
        folded && 'hidden sm:inline-flex',
      )}
    >
      <span className="w-full truncate text-sm font-medium text-foreground">{sector.title}</span>
      <span className={cn('text-sm font-semibold tabular-nums', change.coloured ? 'text-foreground' : 'text-muted-foreground')}>{change.text}</span>
      {data.hasScore && <span className="hidden text-xs font-normal text-muted-foreground tabular-nums sm:block">研究分 {data.scoreText}</span>}
    </Button>
  );
}

// Phones show the first rows of a long group; the rest are one tap away.
const PHONE_LIMIT = 12;

function Group({
  label,
  rows,
  report,
  period,
  onOpen,
}: {
  label: string;
  rows: Sector[];
  report: Report;
  period: Period;
  onOpen: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hidden = expanded ? 0 : Math.max(0, rows.length - PHONE_LIMIT);
  return (
    <section aria-label={label} className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground tabular-nums">
        {label} {rows.length}
      </h3>
      <div className="grid grid-cols-4 gap-1 sm:grid-cols-5 lg:grid-cols-7 xl:grid-cols-9">
        {rows.map((sector, index) => (
          <Tile key={sector.id} sector={sector} report={report} period={period} onOpen={onOpen} folded={!expanded && index >= PHONE_LIMIT} />
        ))}
      </div>
      {hidden > 0 && (
        <Button variant="ghost" size="sm" className="self-start sm:hidden" onClick={() => setExpanded(true)}>
          展开其余 {hidden} 个
        </Button>
      )}
    </section>
  );
}

/** Today / 5 / 20 / 60 days, shared by the heat map and the rankings. */
export function PeriodToggle({ period, onChange }: { period: Period; onChange: (period: Period) => void }) {
  return (
    <ToggleGroup
      variant="outline"
      size="sm"
      aria-label="涨跌周期"
      value={[period]}
      onValueChange={value => value[0] && onChange(value[0] as Period)}
    >
      {PERIODS.map(item => (
        <ToggleGroupItem key={item.id} value={item.id} className="px-2.5 tabular-nums">
          {item.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

function dateRange(values: (string | null | undefined)[]) {
  const dates = [...new Set(values.map(value => String(value || '').slice(0, 10)).filter(Boolean))].sort();
  if (!dates.length) return '—';
  return dates.length > 1 ? `${dates[0]} ～ ${dates[dates.length - 1]}（各市场收盘时间不同）` : dates[0];
}

export function SectorHeatmap({
  report,
  period,
  onPeriod,
  onOpen,
}: {
  report: Report;
  period: Period;
  onPeriod: (period: Period) => void;
  onOpen: (id: string) => void;
}) {
  const historical = report.report_stale;
  const sectors: Sector[] = report.sector_analysis;
  const info = periodInfo(period);
  const changes = new Map(sectors.map(s => [s.id, periodChange(s, report, period)] as const));
  const groups = Object.entries(GROUP_LABELS)
    .map(([id, label]) => [id, label, sortByPeriod(sectors.filter(s => s.group === id), report, period)] as const)
    .filter(([, , rows]) => rows.length);
  const valued = sectors.filter(s => changes.get(s.id)?.value !== null);
  const up = valued.filter(s => (changes.get(s.id)?.value as number) > 0).length;
  const down = valued.filter(s => (changes.get(s.id)?.value as number) < 0).length;
  const dates = period === 'day' ? dateRange(valued.map(s => s.as_of)) : dateRange(valued.map(s => changes.get(s.id)?.date));
  const intraday = period === 'day' ? 0 : valued.filter(s => changes.get(s.id)?.intraday).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-lg font-semibold text-balance">板块热力图</h2>
          {!historical && (
            <span className="text-sm font-normal tabular-nums">
              <span className="text-rise">上涨 {up}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-fall">下跌 {down}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-muted-foreground">无数据 {sectors.length - valued.length}</span>
            </span>
          )}
          {/* In the title row rather than CardAction, so on a phone it wraps below
              the title instead of squeezing the description into a narrow column. */}
          <span className="ml-auto">
            <PeriodToggle period={period} onChange={onPeriod} />
          </span>
        </CardTitle>
        <CardDescription className="text-pretty tabular-nums">
          {historical
            ? '历史快照，涨跌仅供复盘，不着色。'
            : period === 'day'
              ? '颜色表示当日涨跌，红涨绿跌，方块大小相同。'
              : `颜色表示${info.phrase}涨跌（日线口径），红涨绿跌，方块大小相同。`}
          {period === 'day' ? '行情日期 ' : '截至 '}
          {dates}
          {intraday > 0 && `，其中 ${intraday} 个方向末点为当日盘中价`}。点击方块查看依据。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map(([id, label, rows]) => (
          <Group key={id} label={label} rows={rows} report={report} period={period} onOpen={onOpen} />
        ))}
        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground" aria-label="颜色图例">
          {legend(info.steps).map(([swatch, text]) => (
            <span key={text} className="flex items-center gap-1 pr-2 tabular-nums">
              <span className={cn('size-3 rounded-sm', swatch)} aria-hidden="true" />
              {text}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
