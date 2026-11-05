// Port of eventCard / eventList / renderEvents. Impact scores carry their sign
// in the text; scores are compared, never read as probabilities.
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Disclosure, IndicatorIcon, SourceLink } from '@/components/research/common';
import { VerificationDetail } from '@/app/research/Scarcity';
import { useResearch } from '@/app/research/ResearchContext';
import { sectorResearch } from '@/lib/research';
import { stamp } from '@/lib/format';
import type { Report, ResearchEvent } from '@/lib/report';
import { cn } from '@/lib/utils';

const DIRECTION: Record<string, string> = { positive: '利好', negative: '利空', mixed: '双向影响' };
const DIMENSIONS: Record<string, string> = { materiality: '经营影响', breadth: '覆盖范围', duration: '持续性', certainty: '证据明确程度' };
// Event impact follows the A-share convention too: positive news red, negative green.
const TONE_CLASS: Record<string, string> = { positive: 'text-rise', negative: 'text-fall', mixed: 'text-warning' };

export function EventCard({ event, index, report }: { event: ResearchEvent; index: number; report: Report | null }) {
  const tone = sectorResearch.eventTone(event);
  const score = sectorResearch.eventScore(event);
  const indicator = sectorResearch.eventIndicator(event);
  const historical = report?.report_stale || ['stale', 'expired'].includes(report?.event_analysis?.status);
  const dimensions = Object.entries(event.dimensions as Record<string, number>).map(([k, v]) => `${DIMENSIONS[k]} ${v}/5`);
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="text-sm text-muted-foreground tabular-nums">{String(index + 1).padStart(2, '0')}</span>
          <SourceLink url={event.url} className="font-medium">
            {event.title}
          </SourceLink>
        </div>
        <div className="flex items-center gap-2" aria-label={`${DIRECTION[event.direction]}，影响分 ${score}`}>
          <strong className={cn('text-lg tabular-nums', TONE_CLASS[tone])}>{score}</strong>
          <span className="text-xs text-muted-foreground">
            {DIRECTION[event.direction]} · {event.impact_level === 'high' ? '强影响' : '中等影响'}
          </span>
          {indicator && <IndicatorIcon indicator={indicator} withLabel />}
        </div>
      </div>
      {event.sector_labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {event.sector_labels.map((name: string) => (
            <Badge key={name} variant="secondary">
              {name}
            </Badge>
          ))}
        </div>
      )}
      <p className="text-sm text-pretty">{event.reason}</p>
      {event.verification && (
        <Disclosure title={'证据研判 · ' + event.verification.label + (event.evidence_usable ? '' : ' · 暂不计入事件催化')}>
          <VerificationDetail value={event.verification} />
        </Disclosure>
      )}
      {event.facts.length > 0 && (
        <Disclosure title="查看事实依据与评分维度">
          {event.facts.map((fact: string, i: number) => (
            <p key={i} className="text-pretty">
              {fact}
            </p>
          ))}
          {dimensions.length > 0 && <p className="tabular-nums">{dimensions.join(' · ')}</p>}
        </Disclosure>
      )}
      <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
        <span>{event.source_name || '公开来源'}</span>
        <time>发布于 {stamp(event.published_at)}</time>
        {historical && <span>历史评估</span>}
      </div>
    </article>
  );
}

export function EventList({ events, emptyText }: { events: ResearchEvent[]; emptyText: string }) {
  const { report } = useResearch();
  if (!events.length) return emptyText ? <p className="text-sm text-muted-foreground text-pretty">{emptyText}</p> : null;
  return (
    <div className="flex flex-col gap-2">
      {events.map((event, index) => (
        <EventCard key={event.id} event={event} index={index} report={report} />
      ))}
    </div>
  );
}

export function ImportantEvents() {
  const { report, config, state } = useResearch();
  const analysis = report?.event_analysis || sectorResearch.normalizeEvents(null);
  const events: ResearchEvent[] = analysis.events;
  const schedule = sectorResearch.eventScheduleText(config?.schedule || state.ai_schedule);
  const status = report?.report_stale || ['stale', 'expired'].includes(analysis.status)
    ? '正在展示历史事件评估，请按发布时间和报告时间复核。'
    : analysis.status === 'not_configured'
      ? sectorResearch.eventSetupNotice(analysis)
      : analysis.status === 'error'
        ? '本轮事件评估未完成：' + (analysis.error || '等待下一次有效研究。')
        : analysis.status === 'data_unavailable'
          ? '本轮公开公告或官方政策采集未完成，尚不能确认重要事件。'
          : analysis.status === 'scheduled'
            ? '事件研究等待下一次交易日时段，当前不补造事件影响分。'
            : analysis.summary ||
              `仅保留影响分绝对值 ≥ ${analysis.threshold} 的事件；利好为正分，利空为负分，双向影响单独标注。影响分不是涨跌概率。`;
  return (
    <Card id="importantEvents">
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg font-semibold text-balance">重要事件 · 影响排序</h2>
        </CardTitle>
        <CardDescription className="text-pretty">{schedule}；只展示中等及以上影响事件。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="tabular-nums">
            {events.length} 项中等及以上事件
          </Badge>
          <span className="text-xs text-muted-foreground">
            颜色按 A 股习惯：利好为红色正分，利空为绿色负分。
          </span>
        </div>
        <p role="status" className="text-sm text-muted-foreground text-pretty">
          {status}
        </p>
        {analysis.summary && analysis.summary !== status && (
          <p className="text-sm text-muted-foreground text-pretty">{analysis.summary}</p>
        )}
        <EventList
          events={events}
          emptyText={
            analysis.status === 'completed'
              ? '本轮没有达到中等影响标准的事件。'
              : '暂无完成评估的重要事件；待按计划采集可靠公告、政策及公司证据后更新。'
          }
        />
        <p className="text-xs text-muted-foreground tabular-nums">
          {['completed', 'stale', 'expired'].includes(analysis.status) ? '事件报告时间：' : '事件状态更新时间：'}
          {stamp(analysis.as_of || report?.as_of)} · {schedule}
        </p>
        <Disclosure title="事件影响分说明">
          <p className="text-pretty">
            {analysis.method || '事件影响分用于比较事件对相关板块的影响强度；不代表上涨概率或收益预测，不构成投资建议。'}
          </p>
        </Disclosure>
      </CardContent>
    </Card>
  );
}
