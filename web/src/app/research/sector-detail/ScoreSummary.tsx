// Research score summary: sub-score bars with their factor scores, the event
// adjustment drawn from the centre, the tier conditions and the environment risk.
import { Check, Circle } from 'lucide-react';
import { Progress, ProgressLabel } from '@/components/ui/progress';
import { DIRECTION_CLASS, arr, direction, finite, num, pct, txt } from '@/lib/format';
import { type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';
import { type Row } from '@/app/research/sector-detail/parts';

// Same wording as researchPanels() in the old sector-research.js.
const FIELD_LABELS: Record<string, string> = {
  tr_yoy: '营收增长',
  netprofit_yoy: '净利增长',
  profitability: '盈利状态',
  return_20d: '20日收益',
  return_60d: '60日收益',
  ma20_gap: '20日均线差',
};

/** One part of the research score as a bar of its maximum; a missing part stays an empty track. */
function ScoreBar({ label, value, max, details, note }: { label: string; value: unknown; max: number; details: [string, string][]; note?: string }) {
  const measured = finite(value);
  return (
    <div className="flex flex-col gap-1.5">
      {measured ? (
        <Progress value={value} max={max} getAriaValueText={() => `${num(value)} / ${max} 分`} className="gap-1.5">
          <ProgressLabel className="text-sm">{label}</ProgressLabel>
          <span className="ml-auto text-sm font-semibold tabular-nums">
            {num(value)}
            <span className="font-normal text-muted-foreground"> / {max}</span>
          </span>
        </Progress>
      ) : (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium">{label}</span>
            <span className="text-muted-foreground">待评估 / {max}</span>
          </div>
          <div className="h-1 rounded-full bg-muted" aria-hidden="true" />
        </div>
      )}
      {details.length > 0 && (
        <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
          {details.map(([name, text]) => (
            <div key={name} className="flex gap-1">
              <dt>{name}</dt>
              <dd className="tabular-nums text-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      )}
      {note && <p className="text-xs text-muted-foreground text-pretty">{note}</p>}
    </div>
  );
}

/** The event adjustment runs from −30 to +30, so it is drawn out from the centre. */
function CatalystBar({ value, note }: { value: unknown; note?: string }) {
  const measured = finite(value);
  const width = measured ? Math.min(50, (Math.abs(value) / 30) * 50) : 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium">事件催化</span>
        <span className={cn('tabular-nums', measured ? 'font-semibold' : 'text-muted-foreground', measured && DIRECTION_CLASS[direction(value)])}>
          {measured ? (value > 0 ? '+' : '') + num(value) : '待评估'}
          <span className="font-normal text-muted-foreground"> / −30～+30</span>
        </span>
      </div>
      <div className="relative h-1 rounded-full bg-muted" aria-hidden="true">
        <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
        {measured && value !== 0 && (
          <span
            className={cn('absolute inset-y-0 rounded-full', value > 0 ? 'left-1/2 bg-rise' : 'right-1/2 bg-fall')}
            style={{ width: width + '%' }}
          />
        )}
      </div>
      {note && <p className="text-xs text-muted-foreground text-pretty">{note}</p>}
    </div>
  );
}

export function ScoreSummary({ sector }: { sector: Sector }) {
  if (sector.score_model !== 'company_research_v2') return null;
  const b = sector.score_breakdown || {};
  const pending = sector.score_status !== 'complete';
  const risk = sector.market_risk || {};
  const conditions: [string, string][] = [
    ['total_at_least_65', '总分≥65'],
    ['fundamentals_at_least_28', '基本面≥28/40'],
    ['trend_at_least_18_or_positive_catalyst', '走势≥18/30或催化>0'],
    ['evidence_complete', '评分证据完整'],
  ];
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border p-3">
      <h3 className="font-semibold text-balance">
        {pending ? '阶段研究分 · ' : '板块研究分 · '}
        {txt(sector.research_tier?.label, '待完成评估')}
      </h3>
      {sector.research_tier?.reason && <p className="text-sm text-muted-foreground text-pretty">{sector.research_tier.reason}</p>}
      <div className="flex flex-col gap-3">
        <ScoreBar
          label="基本面"
          value={b.fundamentals?.points}
          max={40}
          details={arr<Row>(b.fundamentals?.details).map(d => [FIELD_LABELS[d.field] || d.field, num(d.score, 0) + ' / 100'])}
          note={b.fundamentals?.scope}
        />
        <ScoreBar
          label="走势"
          value={b.trend?.points}
          max={30}
          details={arr<Row>(b.trend?.details).map(d => [FIELD_LABELS[d.field] || d.field, pct(d.value) + ' · ' + num(d.score, 0) + ' / 100'])}
        />
        <CatalystBar value={b.catalysts?.observed_adjustment} note={b.catalysts?.note} />
      </div>
      {pending && (
        <p className="text-sm text-warning text-pretty">
          事件或财务评分证据尚未齐全，阶段分不进入完整档位。可能范围 {arr<number>(sector.score_possible_range).map(v => num(v)).join('～')} /
          100；范围为缺项上下界，不是预测区间。
        </p>
      )}
      <ul className="grid gap-x-4 gap-y-1 sm:grid-cols-2" aria-label="完整档位条件">
        {conditions.map(([key, label]) => {
          const met = sector.research_tier?.conditions?.[key] === true;
          return (
            <li key={key} className={cn('flex items-center gap-2 text-sm', met ? 'text-foreground' : 'text-muted-foreground')}>
              {met ? (
                <Check className="size-4 shrink-0 text-tier-optimistic" aria-hidden="true" />
              ) : (
                <Circle className="size-4 shrink-0" aria-hidden="true" />
              )}
              {label}
              <span className="sr-only">{met ? '（已满足）' : '（未满足）'}</span>
            </li>
          );
        })}
      </ul>
      <p className="text-sm text-pretty">
        环境风险独立评分：{finite(risk.score) ? num(risk.score, 0) + '/100 · ' + risk.level : '待核验'} · {txt(risk.profile)} · 证据覆盖{' '}
        {num(risk.coverage_pct, 0)}%；分数越高风险越高。
      </p>
      <p className="text-xs text-muted-foreground text-pretty">
        完整档位：≥65且附加条件满足为乐观；50～&lt;65为中性；30～&lt;50为谨慎；&lt;30为规避。≥65但附加条件不足按中性观察。研究分不代表收益概率，不构成投资建议。
      </p>
    </section>
  );
}
