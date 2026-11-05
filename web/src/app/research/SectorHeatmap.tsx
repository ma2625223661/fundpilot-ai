// Sector heat map, in the spirit of quote-centre sector maps: one tile per
// direction, grouped by category, coloured by the day's change (red up, green
// down, A-share convention). Every tile is a real button that opens the detail.
// Tiles are the same size: the report has no market weights, and sizing by the
// change itself would exaggerate it. The sign is always written in the tile.
import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { sectorResearch } from '@/lib/research';
import { GROUP_LABELS, direction, finite, stamp } from '@/lib/format';
import type { Report, Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

// Four steps of the rise / fall tokens. Capped at /50 so foreground text keeps
// WCAG AA contrast on both themes. Literal strings so Tailwind keeps them.
const HEAT = {
  rise: ['bg-rise/10 hover:bg-rise/20', 'bg-rise/20 hover:bg-rise/30', 'bg-rise/35 hover:bg-rise/45', 'bg-rise/50 hover:bg-rise/60'],
  fall: ['bg-fall/10 hover:bg-fall/20', 'bg-fall/20 hover:bg-fall/30', 'bg-fall/35 hover:bg-fall/45', 'bg-fall/50 hover:bg-fall/60'],
} as const;
const STEPS = [1, 3, 5]; // |change| below 1%, 1–3%, 3–5%, 5% and above

const LEGEND: [string, string][] = [
  ['bg-fall/50', '≤−5%'],
  ['bg-fall/35', '−3%'],
  ['bg-fall/20', '−1%'],
  ['bg-muted', '0'],
  ['bg-rise/20', '+1%'],
  ['bg-rise/35', '+3%'],
  ['bg-rise/50', '≥+5%'],
];

function heat(sector: Sector, coloured: boolean) {
  const tone = direction(sector.change_pct);
  if (!coloured || (tone !== 'rise' && tone !== 'fall')) return 'bg-muted hover:bg-accent';
  const size = Math.abs(sector.change_pct);
  const step = STEPS.filter(limit => size >= limit).length;
  return HEAT[tone][step];
}

function Tile({ sector, report, onOpen, folded }: { sector: Sector; report: Report; onOpen: (id: string) => void; folded: boolean }) {
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, { historical });
  // A rate move is not a price change, and a historical report is only for review.
  const coloured = data.hasQuote && !historical && sector.quote?.asset_type !== 'money_rate';
  return (
    <Button
      variant="ghost"
      aria-haspopup="dialog"
      aria-label={`${sector.title}，${data.changeLabel} ${data.changeText}，研究分 ${data.scoreText}，行情时间 ${stamp(sector.as_of)}`}
      onClick={() => onOpen(sector.id)}
      className={cn(
        'h-auto min-w-0 flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left whitespace-normal',
        heat(sector, coloured),
        folded && 'hidden sm:inline-flex',
      )}
    >
      <span className="w-full truncate text-sm font-medium text-foreground">{sector.title}</span>
      <span className={cn('text-sm font-semibold tabular-nums', coloured ? 'text-foreground' : 'text-muted-foreground')}>{data.changeText}</span>
      {data.hasScore && <span className="hidden text-xs font-normal text-muted-foreground tabular-nums sm:block">研究分 {data.scoreText}</span>}
    </Button>
  );
}

// Phones show the first rows of a long group; the rest are one tap away.
const PHONE_LIMIT = 12;

function Group({ label, rows, report, onOpen }: { label: string; rows: Sector[]; report: Report; onOpen: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const hidden = expanded ? 0 : Math.max(0, rows.length - PHONE_LIMIT);
  return (
    <section aria-label={label} className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground tabular-nums">
        {label} {rows.length}
      </h3>
      <div className="grid grid-cols-4 gap-1 sm:grid-cols-5 lg:grid-cols-7 xl:grid-cols-9">
        {rows.map((sector, index) => (
          <Tile key={sector.id} sector={sector} report={report} onOpen={onOpen} folded={!expanded && index >= PHONE_LIMIT} />
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

export function SectorHeatmap({ report, onOpen }: { report: Report; onOpen: (id: string) => void }) {
  const historical = report.report_stale;
  const sectors: Sector[] = report.sector_analysis;
  const groups = Object.entries(GROUP_LABELS)
    .map(([id, label]) => [id, label, sectorResearch.sortSectors(sectors.filter(s => s.group === id), 'change') as Sector[]] as const)
    .filter(([, , rows]) => rows.length);
  const quoted = sectors.filter(s => finite(s.change_pct));
  const up = quoted.filter(s => s.change_pct > 0).length;
  const down = quoted.filter(s => s.change_pct < 0).length;
  const dates = [...new Set(quoted.map(s => String(s.as_of || '').slice(0, 10)).filter(Boolean))].sort();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold text-balance">板块热力图</h2>
          {!historical && (
            <span className="text-sm font-normal tabular-nums">
              <span className="text-rise">上涨 {up}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-fall">下跌 {down}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-muted-foreground">无行情 {sectors.length - quoted.length}</span>
            </span>
          )}
        </CardTitle>
        <CardDescription className="text-pretty tabular-nums">
          {historical ? '历史快照，涨跌仅供复盘，不着色。' : '颜色表示当日涨跌，红涨绿跌，方块大小相同。'}行情日期{' '}
          {dates.length ? (dates.length > 1 ? `${dates[0]} ～ ${dates[dates.length - 1]}（各市场收盘时间不同）` : dates[0]) : '—'}
          。点击方块查看依据。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map(([id, label, rows]) => (
          <Group key={id} label={label} rows={rows} report={report} onOpen={onOpen} />
        ))}
        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground" aria-label="颜色图例">
          {LEGEND.map(([swatch, text]) => (
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
