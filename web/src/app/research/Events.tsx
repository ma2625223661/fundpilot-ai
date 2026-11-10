// Port of eventCard / eventList / renderEvents. Impact scores carry their sign
// in the text; scores are compared, never read as probabilities.
import { useState } from 'react';
import { Info } from 'lucide-react';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useWatchlist } from '@/app/research/WatchlistContext';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { goTo } from '@/app/navigation';
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

type EventFilter = 'all' | 'positive' | 'negative' | 'watched';

/** Which events a filter keeps: by the event's own direction, or by a followed sector. */
function filterEvents(events: ResearchEvent[], filter: EventFilter, watched: Set<string>) {
  if (filter === 'positive' || filter === 'negative') return events.filter(event => event.direction === filter);
  if (filter === 'watched') return events.filter(event => event.sector_ids.some((id: string) => watched.has(id)));
  return events;
}

export function ImportantEvents() {
  const { report, config, state, session } = useResearch();
  const watch = useWatchlist();
  const [filter, setFilter] = useState<EventFilter>('all');
  const analysis = report?.event_analysis || sectorResearch.normalizeEvents(null);
  const allEvents: ResearchEvent[] = analysis.events;
  const watched = new Set(watch.available ? watch.items : []);
  const filters: [EventFilter, string, boolean][] = [
    ['all', '全部', true],
    ['positive', '利好', true],
    ['negative', '利空', true],
    ['watched', '我的关注', watch.available],
  ];
  // A filter that is no longer offered (watchlist unavailable) falls back to all.
  const active = filters.some(([id, , shown]) => id === filter && shown) ? filter : 'all';
  const events = filterEvents(allEvents, active, watched);
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
  const notConfigured = !report?.report_stale && analysis.status === 'not_configured' && !allEvents.length;
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
            {allEvents.length} 项中等及以上事件
          </Badge>
          <span className="text-xs text-muted-foreground">
            颜色按 A 股习惯：利好为红色正分，利空为绿色负分。
          </span>
        </div>
        {notConfigured ? (
          // One notice instead of three paragraphs: what is missing, what it means, how to fix it.
          <Alert>
            <Info aria-hidden="true" />
            <AlertTitle>事件研究尚未启用</AlertTitle>
            <AlertDescription className="text-pretty">
              {analysis.candidate_count > 0 ? `已采集 ${analysis.candidate_count} 条公告或政策，等待 AI 评估影响。` : '开启并验证 AI 后才会评估事件影响。'}
              在此之前，公司研究分不含事件维度，只显示阶段分（满分 70），不进入完整档位。
            </AlertDescription>
            {session.isAdmin && (
              <AlertAction>
                <Button size="sm" variant="outline" onClick={() => goTo('researchSettings')}>
                  去开启 AI 研究
                </Button>
              </AlertAction>
            )}
          </Alert>
        ) : (
          <>
            <p role="status" className="text-sm text-muted-foreground text-pretty">
              {status}
            </p>
            {analysis.summary && analysis.summary !== status && (
              <p className="text-sm text-muted-foreground text-pretty">{analysis.summary}</p>
            )}
            {allEvents.length > 0 && (
              <ToggleGroup
                variant="outline"
                size="sm"
                aria-label="筛选重要事件"
                value={[active]}
                onValueChange={value => value[0] && setFilter(value[0] as EventFilter)}
              >
                {filters
                  .filter(([, , shown]) => shown)
                  .map(([id, label]) => (
                    <ToggleGroupItem key={id} value={id} className="px-2.5 tabular-nums">
                      {label} {filterEvents(allEvents, id, watched).length}
                    </ToggleGroupItem>
                  ))}
              </ToggleGroup>
            )}
            {allEvents.length > 0 && !events.length ? (
              <div className="flex flex-wrap items-center gap-3 py-2">
                <p className="text-sm text-muted-foreground text-pretty">
                  {active === 'watched'
                    ? watched.size
                      ? '本轮没有涉及你关注板块的重要事件。'
                      : '你还没有关注板块，在"我的关注与订阅"添加后，这里会只显示相关事件。'
                    : `本轮没有${DIRECTION[active]}事件。`}
                </p>
                <Button size="sm" variant="outline" onClick={() => setFilter('all')}>
                  显示全部事件
                </Button>
              </div>
            ) : (
              <EventList
                events={events}
                emptyText={
                  analysis.status === 'completed'
                    ? '本轮没有达到中等影响标准的事件。'
                    : '暂无完成评估的重要事件；待按计划采集可靠公告、政策及公司证据后更新。'
                }
              />
            )}
          </>
        )}
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
