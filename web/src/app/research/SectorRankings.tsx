// Compact ranking lists (top gainers, top decliners, highest research scores),
// a dense layout common to quote centres. Ordering uses the old sortSectors();
// nothing is recalculated here. Each name opens the sector detail.
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, finite } from '@/lib/format';
import { periodChange, periodInfo, sortByPeriod, type Period } from '@/app/research/period';
import { TONE_TEXT, sectorTone, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

function RankList({
  title,
  note,
  rows,
  value,
  onOpen,
}: {
  title: string;
  note: string;
  rows: Sector[];
  value: (sector: Sector) => React.ReactNode;
  onOpen: (id: string) => void;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2 border-b border-border pb-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="text-xs text-muted-foreground">{note}</span>
      </div>
      {rows.length ? (
        <ol className="flex flex-col">
          {rows.map((sector, index) => (
            <li key={sector.id} className="flex items-center gap-2 py-1">
              <span
                className={cn(
                  'w-5 shrink-0 text-center text-xs font-semibold tabular-nums',
                  index < 3 ? 'text-primary' : 'text-muted-foreground',
                )}
              >
                {index + 1}
              </span>
              <Button variant="link" className="h-auto min-w-0 flex-1 justify-start truncate p-0 text-sm font-normal text-foreground" onClick={() => onOpen(sector.id)}>
                {sector.title}
              </Button>
              <span className="shrink-0 text-sm font-medium tabular-nums">{value(sector)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="py-2 text-sm text-muted-foreground">暂无有效数据</p>
      )}
    </section>
  );
}

export function SectorRankings({ report, period, onOpen }: { report: Report; period: Period; onOpen: (id: string) => void }) {
  const historical = report.report_stale;
  const sectors: Sector[] = report.sector_analysis;
  const info = periodInfo(period);
  const ordered = sortByPeriod(
    sectors.filter(s => periodChange(s, report, period).value !== null),
    report,
    period,
  );
  const value = (s: Sector) => periodChange(s, report, period).value as number;
  const gainers = ordered.filter(s => value(s) > 0).slice(0, 6);
  const decliners = [...ordered].reverse().filter(s => value(s) < 0).slice(0, 6);
  const scored: Sector[] = sectorResearch.sortSectors(
    sectors.filter(s => finite(s.score)),
    'score',
  ).slice(0, 6);
  const change = (sector: Sector) => {
    const item = periodChange(sector, report, period);
    return <span className={item.coloured ? DIRECTION_CLASS[direction(item.value)] : 'text-muted-foreground'}>{item.text}</span>;
  };
  const note = historical ? '历史涨跌' : period === 'day' ? '当日涨跌' : info.phrase + '涨跌';
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">板块排行</h2>
          <span className="text-xs font-normal text-muted-foreground">
            {historical ? '历史快照，仅供复盘' : '涨跌周期与热力图一致'} · 点击名称查看依据
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-3">
        <RankList title="涨幅榜" note={note} rows={gainers} value={change} onOpen={onOpen} />
        <RankList title="跌幅榜" note={note} rows={decliners} value={change} onOpen={onOpen} />
        <RankList
          title="研究分榜"
          note="同口径优先，不代表收益概率"
          rows={scored}
          value={sector => {
            const data = sectorResearch.sectorDataPresentation(sector, { historical });
            return (
              <span className={TONE_TEXT[sectorTone(sector, historical)]}>
                {data.scoreText}
                <span className="ml-1 text-xs font-normal text-muted-foreground">{data.scoreUnit}</span>
              </span>
            );
          }}
          onOpen={onOpen}
        />
      </CardContent>
    </Card>
  );
}
