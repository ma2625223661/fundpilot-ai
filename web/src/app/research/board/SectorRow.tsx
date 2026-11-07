// Phone card for one sector, with its sub-score bars.
import { Button } from '@/components/ui/button';
import { IndicatorIcon } from '@/components/research/common';
import { ScarcityBadge } from '@/app/research/Scarcity';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, finite, num, txt } from '@/lib/format';
import { TONE_BADGE, TONE_BORDER, TONE_TEXT, sectorEvents, sectorTone, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';
import { LeadSample, leadSample } from '@/app/research/board/lead-sample';

/** Sub-score as a short bar: points of its maximum; a missing part stays empty. */
function Part({ label, value, max, signed = false }: { label: string; value: number | null; max: number; signed?: boolean }) {
  const measured = finite(value);
  const width = measured ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <b
          className={cn(
            'font-medium tabular-nums',
            signed && measured && value > 0 && 'text-rise',
            signed && measured && value < 0 && 'text-fall',
            !measured && 'text-muted-foreground',
          )}
        >
          {measured ? (signed && value > 0 ? '+' : '') + num(value) : '待评估'}
          <span className="text-muted-foreground">{signed ? ' / ±' + max : ' / ' + max}</span>
        </b>
      </span>
      <span className="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <span
          className={cn('block h-full rounded-full', signed && measured && value < 0 ? 'bg-fall' : signed ? 'bg-rise' : 'bg-primary')}
          style={{ width: width + '%' }}
        />
      </span>
    </span>
  );
}

export function SectorRow({ sector, report, active, onSelect }: { sector: Sector; report: Report; active: boolean; onSelect: () => void }) {
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, {
    historical,
    companyCount: (report.company_evidence.sector_leaders[sector.id] || []).length,
    eventCount: sectorEvents(report, sector.id).length,
  });
  const tone = sectorTone(sector, historical);
  const view = sectorResearch.companyScoreView(sector);
  const indicator = historical ? null : sectorResearch.sectorIndicator(sector);
  const risk = sector.market_risk || {};
  const changeTone = data.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
  const parts = sector.score_breakdown || {};
  return (
    <Button
      variant="ghost"
      aria-haspopup="dialog"
      aria-pressed={active}
      onClick={onSelect}
      className={cn(
        'h-auto w-full flex-col items-stretch gap-3 rounded-lg border border-l-4 border-border bg-card p-4 text-left whitespace-normal hover:bg-muted aria-pressed:bg-muted',
        TONE_BORDER[tone],
      )}
    >
      <span className="grid w-full grid-cols-2 items-center gap-x-4 gap-y-2 md:grid-cols-12">
        <span className="col-span-2 flex min-w-0 flex-col gap-1 md:col-span-5">
          <span className="flex flex-wrap items-center gap-2">
            <b className="text-base font-semibold">{sector.title}</b>
            <ScarcityBadge value={sector.scarcity} />
          </span>
          <small className="line-clamp-2 text-xs font-normal text-muted-foreground" title={data.subtitle}>
            {data.subtitle}
          </small>
        </span>
        <span className="flex flex-col md:col-span-2 md:items-end">
          <span className="text-xs font-normal text-muted-foreground">{data.changeLabel}</span>
          <span className={cn('text-lg font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>{data.changeText}</span>
        </span>
        <span className="flex flex-col items-end md:col-span-2">
          <span className="flex items-baseline gap-1">
            <b className={cn('text-2xl font-semibold tabular-nums', TONE_TEXT[tone])}>{data.scoreText}</b>
            <small className="text-xs font-normal text-muted-foreground">{data.scoreUnit}</small>
          </span>
          {view && <span className={cn('rounded-sm px-1.5 py-0.5 text-xs font-medium', TONE_BADGE[tone])}>{view.label}</span>}
        </span>
        <span className="col-span-2 flex flex-col gap-0.5 text-xs font-normal md:col-span-3 md:items-end" title={txt(risk.scope)}>
          <span className="flex items-center gap-1 text-foreground">
            {indicator && <IndicatorIcon indicator={indicator} />}
            行情 {data.riskText}
            {indicator ? ' · ' + indicator.label : ''}
          </span>
          {finite(risk.score) && (
            <span className="text-muted-foreground tabular-nums">
              环境 {txt(risk.level)} {num(risk.score, 0)}/100{risk.status !== 'complete' ? '（部分）' : ''}
            </span>
          )}
        </span>
      </span>
      {view && (
        <span className="grid w-full gap-x-6 gap-y-2 font-normal sm:grid-cols-3">
          <Part label="基本面" value={parts.fundamentals?.points ?? null} max={40} />
          <Part label="走势" value={parts.trend?.points ?? null} max={30} />
          <Part label="事件催化" value={parts.catalysts?.observed_adjustment ?? null} max={30} signed />
        </span>
      )}
      {leadSample(report, sector) && (
        <span className="flex items-center gap-2 text-xs font-normal">
          <span className="text-muted-foreground">领涨样本</span>
          <LeadSample report={report} sector={sector} className="flex-row items-baseline gap-2" />
        </span>
      )}
      {view?.gates && <span className="text-xs font-normal text-muted-foreground">{view.gates}</span>}
    </Button>
  );
}
