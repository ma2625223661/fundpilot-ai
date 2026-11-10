// Sector heat map, in the spirit of quote-centre sector maps: one tile per
// direction, grouped by category, coloured either by the chosen period's change
// (red up, green down, A-share convention) or by the research tier the old
// colour function gives. Every tile is a real button that opens the detail.
// Tiles are the same size: the report has no market weights, and sizing by the
// change itself would exaggerate it. The sign is always written.
import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { sectorResearch } from '@/lib/research';
import { GROUP_LABELS, direction, stamp } from '@/lib/format';
import { TONE_TEXT, sectorTone, type Report, type Sector, type Tone } from '@/lib/report';
import { PERIODS, periodChange, periodEnd, periodInfo, sortByPeriod, type Period, type PeriodChange } from '@/app/research/period';
import { cn } from '@/lib/utils';

// Four steps of the rise / fall tokens. Capped at /50 so foreground text keeps
// WCAG AA contrast on both themes. Literal strings so Tailwind keeps them.
const HEAT = {
  rise: ['bg-rise/10 hover:bg-rise/20', 'bg-rise/20 hover:bg-rise/30', 'bg-rise/35 hover:bg-rise/45', 'bg-rise/50 hover:bg-rise/60'],
  fall: ['bg-fall/10 hover:bg-fall/20', 'bg-fall/20 hover:bg-fall/30', 'bg-fall/35 hover:bg-fall/45', 'bg-fall/50 hover:bg-fall/60'],
} as const;

/** What the colour shows: the period's change, or the research tier. */
export type HeatMode = 'change' | 'tier';
const MODE_KEY = 'fundpilot_heatmap_mode_v1';

/** The last colour mode this viewer chose (a per-browser convenience only). */
function readMode(): HeatMode {
  try {
    return localStorage.getItem(MODE_KEY) === 'tier' ? 'tier' : 'change';
  } catch {
    return 'change';
  }
}

// Tier tiles: one tint of each tier token. Literal strings so Tailwind keeps them.
const TIER_SWATCH: Record<Tone, string> = {
  optimistic: 'bg-tier-optimistic/20',
  neutral: 'bg-tier-neutral/20',
  cautious: 'bg-tier-cautious/20',
  avoid: 'bg-tier-avoid/20',
  unknown: 'bg-muted',
};
const TIER_HOVER: Record<Tone, string> = {
  optimistic: 'hover:bg-tier-optimistic/30',
  neutral: 'hover:bg-tier-neutral/30',
  cautious: 'hover:bg-tier-cautious/30',
  avoid: 'hover:bg-tier-avoid/30',
  unknown: 'hover:bg-accent',
};

// Same bands and wording as the board legend.
const TIERS: [Tone, string, string][] = [
  ['optimistic', '乐观', '≥65 乐观'],
  ['neutral', '中性', '50～<65 中性'],
  ['cautious', '谨慎', '30～<50 谨慎'],
  ['avoid', '规避', '<30 规避'],
  ['unknown', '待评估', '待评估'],
];
const TIER_LABEL = Object.fromEntries(TIERS.map(([tone, label]) => [tone, label])) as Record<Tone, string>;

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
  mode,
  onOpen,
  folded,
}: {
  sector: Sector;
  report: Report;
  period: Period;
  mode: HeatMode;
  onOpen: (id: string) => void;
  folded: boolean;
}) {
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, { historical });
  const info = periodInfo(period);
  const change = periodChange(sector, report, period);
  const when = periodEnd(change) ?? `行情时间 ${stamp(sector.as_of)}`;
  const label = period === 'day' ? data.changeLabel : info.phrase + '涨跌';
  const tone = sectorTone(sector, historical);
  const tier = mode === 'tier';
  return (
    <Button
      variant="ghost"
      aria-haspopup="dialog"
      aria-label={
        tier
          ? `${sector.title}，研究分 ${data.scoreText}，${TIER_LABEL[tone]}，${label} ${change.text}，${when}`
          : `${sector.title}，${label} ${change.text}，${when}，研究分 ${data.scoreText}`
      }
      onClick={() => onOpen(sector.id)}
      className={cn(
        'h-auto min-w-0 flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left whitespace-normal',
        tier ? cn(TIER_SWATCH[tone], TIER_HOVER[tone]) : heat(change, info.steps),
        folded && 'hidden sm:inline-flex',
      )}
    >
      <span className="w-full truncate text-sm font-medium text-foreground">{sector.title}</span>
      {tier ? (
        <>
          <span className={cn('text-sm font-semibold tabular-nums', data.hasScore ? 'text-foreground' : 'text-muted-foreground')}>
            {data.scoreText}
          </span>
          <span className="hidden text-xs font-normal text-muted-foreground sm:block">{TIER_LABEL[tone]}</span>
        </>
      ) : (
        <>
          <span className={cn('text-sm font-semibold tabular-nums', change.coloured ? 'text-foreground' : 'text-muted-foreground')}>
            {change.text}
          </span>
          {data.hasScore && <span className="hidden text-xs font-normal text-muted-foreground tabular-nums sm:block">研究分 {data.scoreText}</span>}
        </>
      )}
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
  mode,
  onOpen,
}: {
  label: string;
  rows: Sector[];
  report: Report;
  period: Period;
  mode: HeatMode;
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
          <Tile
            key={sector.id}
            sector={sector}
            report={report}
            period={period}
            mode={mode}
            onOpen={onOpen}
            folded={!expanded && index >= PHONE_LIMIT}
          />
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
  const [mode, setMode] = useState(readMode);
  const chooseMode = (value: HeatMode) => {
    setMode(value);
    try {
      localStorage.setItem(MODE_KEY, value);
    } catch {
      // Storage unavailable: the choice lasts for this page only.
    }
  };
  const historical = report.report_stale;
  const sectors: Sector[] = report.sector_analysis;
  const info = periodInfo(period);
  const changes = new Map(sectors.map(s => [s.id, periodChange(s, report, period)] as const));
  // Tier mode keeps the board's default order (the old sortSectors by score).
  const order = (rows: Sector[]) => (mode === 'tier' ? (sectorResearch.sortSectors(rows, 'score') as Sector[]) : sortByPeriod(rows, report, period));
  const groups = Object.entries(GROUP_LABELS)
    .map(([id, label]) => [id, label, order(sectors.filter(s => s.group === id))] as const)
    .filter(([, , rows]) => rows.length);
  const valued = sectors.filter(s => changes.get(s.id)?.value !== null);
  const up = valued.filter(s => (changes.get(s.id)?.value as number) > 0).length;
  const down = valued.filter(s => (changes.get(s.id)?.value as number) < 0).length;
  const dates = period === 'day' ? dateRange(valued.map(s => s.as_of)) : dateRange(valued.map(s => changes.get(s.id)?.date));
  const intraday = period === 'day' ? 0 : valued.filter(s => changes.get(s.id)?.intraday).length;
  const tones = sectors.map(s => sectorTone(s, historical));
  const tierCounts = TIERS.map(([tone, label]) => [tone, label, tones.filter(value => value === tone).length] as const).filter(
    ([, , count]) => count,
  );
  const swatches: [string, string][] = mode === 'tier' ? TIERS.map(([tone, , text]) => [TIER_SWATCH[tone], text]) : legend(info.steps);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-lg font-semibold text-balance">板块热力图</h2>
          {mode === 'tier' && !historical && (
            <span className="flex flex-wrap gap-x-3 text-sm font-normal tabular-nums">
              {tierCounts.map(([tone, label, count]) => (
                <span key={tone} className={TONE_TEXT[tone]}>
                  {label} {count}
                </span>
              ))}
            </span>
          )}
          {mode === 'change' && !historical && (
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
          <span className="ml-auto flex flex-wrap gap-2">
            <ToggleGroup
              variant="outline"
              size="sm"
              aria-label="方块颜色"
              value={[mode]}
              onValueChange={value => value[0] && chooseMode(value[0] as HeatMode)}
            >
              <ToggleGroupItem value="change" className="px-2.5">
                涨跌
              </ToggleGroupItem>
              <ToggleGroupItem value="tier" className="px-2.5">
                研究档位
              </ToggleGroupItem>
            </ToggleGroup>
            {mode === 'change' && <PeriodToggle period={period} onChange={onPeriod} />}
          </span>
        </CardTitle>
        <CardDescription className="text-pretty tabular-nums">
          {mode === 'tier' ? (
            <>
              {historical ? '历史快照，研究档位仅供复盘，不着色。' : '颜色表示研究档位，与板块总览一致，方块大小相同。'}
              报告时间 {stamp(report.as_of)}。研究分不代表收益概率，不构成投资建议。点击方块查看依据。
            </>
          ) : (
            <>
              {historical
                ? '历史快照，涨跌仅供复盘，不着色。'
                : period === 'day'
                  ? '颜色表示当日涨跌，红涨绿跌，方块大小相同。'
                  : `颜色表示${info.phrase}涨跌（日线口径），红涨绿跌，方块大小相同。`}
              {period === 'day' ? '行情日期 ' : '截至 '}
              {dates}
              {intraday > 0 && `，其中 ${intraday} 个方向末点为当日盘中价`}。点击方块查看依据。
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map(([id, label, rows]) => (
          <Group key={id} label={label} rows={rows} report={report} period={period} mode={mode} onOpen={onOpen} />
        ))}
        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground" aria-label="颜色图例">
          {swatches.map(([swatch, text]) => (
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
