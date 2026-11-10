// Side-by-side comparison of up to four sectors (#compare/<id>,<id>…). Every
// figure is what the report or the old presentation functions give; nothing is
// recalculated. The sample-index lines are drawn as delivered (each starts at
// 100 on its own base date), so no rebasing happens here either.
import type { ReactNode } from 'react';
import { ArrowLeft, X } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DatedLines } from '@/components/charts-lazy';
import { compareHref, goTo, sectorHref, useHashCompare } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { leadSample } from '@/app/research/BoardExplorer';
import { WatchButton } from '@/app/research/WatchButton';
import { PERIODS, periodChange, periodEnd } from '@/app/research/period';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, finite, num, pct, stamp } from '@/lib/format';
import { TONE_BADGE, TONE_TEXT, sectorTone, sectorTrend, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

type Row = [string, (sector: Sector) => ReactNode];

function rows(report: Report): Row[] {
  const historical = report.report_stale === true;
  const data = (s: Sector) => sectorResearch.sectorDataPresentation(s, { historical });
  const part = (s: Sector, key: 'fundamentals' | 'trend' | 'catalysts') => {
    if (!sectorResearch.companyScoreView(s)) return <span className="text-muted-foreground">—</span>;
    const b = s.score_breakdown || {};
    const value = key === 'catalysts' ? b.catalysts?.observed_adjustment : b[key]?.points;
    if (!finite(value)) return <span className="text-muted-foreground">待评估</span>;
    const signed = key === 'catalysts';
    return <span className={cn(signed && DIRECTION_CLASS[direction(value)])}>{(signed && value > 0 ? '+' : '') + num(value)}</span>;
  };
  return [
    [
      '研究分',
      s => {
        const d = data(s);
        const view = sectorResearch.companyScoreView(s);
        return (
          <span className="flex flex-col items-end gap-0.5">
            <span className={cn('text-lg font-semibold', TONE_TEXT[sectorTone(s, historical)])}>
              {d.scoreText}
              <span className="ml-1 text-xs font-normal text-muted-foreground">{d.scoreUnit}</span>
            </span>
            {view && <span className={cn('rounded-sm px-1 py-0.5 text-xs', TONE_BADGE[sectorTone(s, historical)])}>{view.label}</span>}
          </span>
        );
      },
    ],
    ['基本面 / 40', s => part(s, 'fundamentals')],
    ['走势 / 30', s => part(s, 'trend')],
    ['事件 ±30', s => part(s, 'catalysts')],
    ...PERIODS.map(
      (period): Row => [
        period.id === 'day' ? '当日涨跌' : period.phrase + '涨跌',
        s => {
          const change = periodChange(s, report, period.id);
          const end = periodEnd(change);
          return (
            <span className="flex flex-col items-end">
              <span className={cn('font-medium', change.coloured ? DIRECTION_CLASS[direction(change.value)] : 'text-muted-foreground')}>{change.text}</span>
              {end && <span className="text-xs text-muted-foreground">{end}</span>}
            </span>
          );
        },
      ],
    ),
    [
      '领涨样本',
      s => {
        const lead = leadSample(report, s);
        if (!lead) return <span className="text-muted-foreground">—</span>;
        return (
          <span className="flex flex-col items-end">
            <span>
              {lead.name} <span className={historical ? 'text-muted-foreground' : DIRECTION_CLASS[direction(lead.change)]}>{pct(lead.change)}</span>
            </span>
            <span className="text-xs text-muted-foreground">
              {lead.up} 涨 · {lead.down} 跌 / {lead.total} 家
            </span>
          </span>
        );
      },
    ],
    ['行情风险', s => data(s).riskText],
    ['环境风险', s => (finite(s.market_risk?.score) ? num(s.market_risk.score, 0) + ' / 100' : <span className="text-muted-foreground">—</span>)],
    ['行情时间', s => <span className="text-xs">{stamp(s.as_of)}</span>],
  ];
}

export function CompareView() {
  const ids = useHashCompare();
  const { report } = useResearch();

  const back = (
    <Button variant="ghost" size="sm" className="-ml-2 self-start" onClick={() => goTo('dash')}>
      <ArrowLeft aria-hidden="true" />
      返回板块研究
    </Button>
  );

  if (!report)
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="正在载入对比">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-96" />
      </div>
    );

  const all = new Map<string, Sector>(report.sector_analysis.map((s: Sector) => [s.id, s]));
  const sectors = ids.map(id => all.get(id)).filter((s): s is Sector => Boolean(s));
  const missing = ids.filter(id => !all.has(id));
  const lines = sectors.map(s => [s, sectorTrend(s, 1000)] as const);
  const drawn = lines.filter(([, trend]) => trend);
  const undrawn = lines.filter(([, trend]) => !trend).map(([s]) => s.title);
  const bases = [...new Set(drawn.map(([s]) => s.custom_index?.base_date).filter(Boolean))];

  return (
    <div className="flex flex-col gap-4">
      {back}
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-balance">板块对比</h1>
        <p className="text-sm text-muted-foreground text-pretty">
          并排查看研究分、分项、不同周期涨跌与风险。研究分不代表收益概率，不构成投资建议。报告时间 {stamp(report.as_of)}
          {report.report_stale ? '（历史快照，仅供复盘）' : ''}。
        </p>
      </header>
      {missing.length > 0 && (
        <p className="text-sm text-warning text-pretty">本期报告中没有这些方向，已略过：{missing.join('、')}。</p>
      )}
      {sectors.length < 2 ? (
        <Card>
          <CardContent className="flex flex-col items-start gap-3">
            <p className="text-sm text-pretty">至少需要 2 个板块才能对比。在板块详情或板块页点"加入对比"，选好后从页面底部的对比栏进入。</p>
            <Button variant="outline" onClick={() => goTo('dash')}>
              去板块研究挑选
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">项目</TableHead>
                    {sectors.map(s => (
                      <TableHead key={s.id} className="text-right">
                        <span className="flex items-center justify-end gap-1">
                          <a href={sectorHref(s.id)} className="font-semibold text-foreground underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring">
                            {s.title}
                          </a>
                          <WatchButton id={s.id} title={s.title} compact />
                          {sectors.length > 2 && (
                            <a
                              href={compareHref(sectors.filter(x => x.id !== s.id).map(x => x.id))}
                              aria-label={`从对比中移除${s.title}`}
                              className={buttonVariants({ variant: 'ghost', size: 'icon-xs' })}
                            >
                              <X aria-hidden="true" />
                            </a>
                          )}
                        </span>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows(report).map(([label, cell]) => (
                    <TableRow key={label}>
                      <TableCell className="text-xs text-muted-foreground">{label}</TableCell>
                      {sectors.map(s => (
                        <TableCell key={s.id} className="text-right whitespace-normal tabular-nums">
                          {cell(s)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>
                <h2 className="text-lg font-semibold text-balance">样本指标走势</h2>
              </CardTitle>
              <CardDescription className="text-pretty tabular-nums">
                各板块自建的公司样本等权指标，起点为 100，非官方指数或回测收益。
                {bases.length > 1 ? `各线起点日期不同（${bases.join('、')}），起点后的水平不可直接比较。` : bases.length ? `共同起点 ${bases[0]}。` : ''}
                {undrawn.length > 0 && ` ${undrawn.join('、')} 没有独立样本指标，未画线。`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {drawn.length ? (
                <DatedLines
                  unit="点"
                  label={`样本指标走势对比：${drawn.map(([s, trend]) => `${s.title} ${trend!.from} 至 ${trend!.to}`).join('；')}`}
                  series={drawn.map(([s, trend]) => ({ name: s.title, points: trend!.points }))}
                />
              ) : (
                <p className="text-sm text-muted-foreground">所选板块都没有独立样本指标，暂无可比走势。</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
