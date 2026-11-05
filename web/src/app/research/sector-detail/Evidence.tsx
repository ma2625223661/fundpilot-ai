// Research dimensions with their evidence and sources, and the data diagnostics.
import { Badge } from '@/components/ui/badge';
import { BulletList, Disclosure, SourceLink } from '@/components/research/common';
import { EventCard } from '@/app/research/Events';
import { sectorResearch } from '@/lib/research';
import { stamp } from '@/lib/format';
import { sourceMap, type Report, type Sector } from '@/lib/report';
import { Section, Sources, type Row } from '@/app/research/sector-detail/parts';

export function ResearchDimensions({ sector, report }: { sector: Sector; report: Report }) {
  const sources = sourceMap(report);
  const panels: Row[] = sectorResearch.researchPanels(sector, report);
  return (
    <section aria-label="研究结论与证据" className="flex flex-col gap-2">
      {panels.map((item, index) => (
        <Disclosure
          key={item.id}
          title={
            <span className="flex flex-wrap items-baseline gap-x-3">
              <small className="text-xs text-muted-foreground tabular-nums">0{index + 1}</small>
              <b className="font-medium">{item.title}</b>
              <span className="text-muted-foreground tabular-nums">{item.value}</span>
            </span>
          }
        >
          {item.events?.length ? (
            <div className="flex flex-col gap-2">
              {item.events.map((event: Row, i: number) => (
                <EventCard key={event.id} event={event} index={i} report={report} />
              ))}
            </div>
          ) : (
            <BulletList items={item.lines} />
          )}
          {item.id === 'trend' && (
            <Section title={report.report_stale ? '历史分析理由' : '支持与反对证据'}>
              <BulletList items={[...sector.reasons, ...sector.risks]} fallback="当前证据不足。" />
            </Section>
          )}
          <Sources ids={item.source_ids} sources={sources} />
        </Disclosure>
      ))}
    </section>
  );
}

export function Diagnostics({ data, report }: { data: Row; report: Report }) {
  if (!(data.gaps.length || !data.hasQuote || !data.hasScore)) return null;
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <h4 className="font-semibold text-balance">{report.report_stale ? '历史数据缺口与采集状态' : '数据缺口与采集状态'}</h4>
      <p className="text-sm text-pretty">{data.subtitle}</p>
      {data.referenceExpected && <p className="text-xs text-muted-foreground text-pretty">参考行情：{data.referenceExpected}</p>}
      {data.evidenceSummary && <p className="text-sm text-pretty">{data.evidenceSummary}</p>}
      {data.gaps.length > 0 && <BulletList items={data.gaps.map((gap: Row) => gap.message)} />}
      <div className="flex flex-col gap-2">
        {data.sources.map((source: Row) => {
          const timing = [source.as_of ? '数据时间 ' + stamp(source.as_of) : '', source.fetched_at ? '采集时间 ' + stamp(source.fetched_at) : '']
            .filter(Boolean)
            .join(' · ');
          return (
            <div key={source.id} className="flex flex-col gap-1 rounded-md bg-muted p-2">
              <div className="flex flex-wrap items-center gap-2">
                <SourceLink url={source.url}>{source.name || '相关数据来源'}</SourceLink>
                <Badge variant="outline">{sectorResearch.sourceStatusLabel(source.status)}</Badge>
              </div>
              {source.error && <p className="text-xs text-pretty">{source.error}</p>}
              {timing && <small className="text-xs text-muted-foreground tabular-nums">{timing}</small>}
            </div>
          );
        })}
        {!data.sources.length && <p className="text-xs text-muted-foreground">本方向尚无可展示的行情来源记录。</p>}
      </div>
    </section>
  );
}
