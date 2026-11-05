// Port of renderDetail and its helpers (independent sample index, score summary,
// research dimensions, detailed AI advice, data diagnostics). The research and
// risk scores keep their "not a return probability / not investment advice" notes.
import type { ReactNode } from 'react';
import { Check, Circle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Progress, ProgressLabel } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DatedLine } from '@/components/charts-lazy';
import { BulletList, Disclosure, Eyebrow, IndicatorIcon, SourceLink, Stat } from '@/components/research/common';
import { CompanyEvidence } from '@/app/research/CompanyEvidence';
import { EventCard, EventList } from '@/app/research/Events';
import { ScarcityDetail } from '@/app/research/Scarcity';
import { SectorAccess } from '@/app/research/SectorAccess';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, GROUP_LABELS, arr, direction, finite, num, pct, stamp, txt } from '@/lib/format';
import { TONE_BORDER, TONE_TEXT, sectorEvents, sectorTone, sourceMap, type Report, type Sector, type Source } from '@/lib/report';
import { cn } from '@/lib/utils';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

// Same wording as componentLabel() in the old sector-research.js (not exported there).
const COMPONENT_LABELS: Record<string, string> = {
  fundamental_points: '基本面得分',
  trend_points: '走势得分',
  catalyst_points: '事件催化调整',
  base: '基准',
  daily_change: '日涨跌',
  breadth: '样本涨跌广度',
  momentum_5d: '5日趋势',
  momentum_20d: '20日趋势',
  momentum_60d: '60日趋势',
  trend_20d: '20日均线',
  volatility_penalty: '波动扣分',
  drawdown_penalty: '回撤扣分',
  financial_adjustment: '业绩调整',
  event_adjustment: '重要事件调整',
  easing_5d: '5日利率变化',
  easing_20d: '20日利率变化',
  easing_60d: '60日利率变化',
  rate_volatility_penalty: '利率波动扣分',
  daily_tightening_penalty: '当日资金收紧扣分',
};

const REQUIREMENT: Record<string, string> = { ok: '已满足', partial: '部分满足', missing: '数据缺失' };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="font-semibold text-balance">{title}</h4>
      {children}
    </section>
  );
}

function Sources({ ids, sources }: { ids: string[]; sources: Map<string, Source> }) {
  const rows = [...new Set(ids)].map(id => sources.get(id)).filter(Boolean) as Source[];
  if (!rows.length) return null;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {rows.map(source => (
        <SourceLink key={source.id} url={source.url}>
          {source.name || source.id}
        </SourceLink>
      ))}
    </div>
  );
}

function IndependentIndex({ sector }: { sector: Sector }) {
  const index = sector.custom_index;
  if (!index) return null;
  const tag =
    sector.id === 'sector_brain_computer'
      ? '独立编制 · 研究关联样本分析'
      : sector.id === 'commodities'
        ? '独立编制 · 资源企业股票样本分析'
        : sector.id === 'style_microcap'
          ? '独立编制 · 小市值样本分析'
          : '独立编制 · 龙头样本分析';
  const points: { date: string; value: number }[] = index.live_point
    ? [...index.history.filter((p: Row) => p.date !== index.live_point.date), index.live_point]
    : index.history;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge variant="secondary">{tag}</Badge>
        <small className="text-xs text-muted-foreground">{index.is_intraday ? '盘中样本快照' : '最近收盘样本'}</small>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="样本指标点位" value={num(index.value)} />
        <Stat label="等权样本" value={index.sample_count + ' 只'} />
        <Stat label="共同历史" value={index.history_count + ' 日'} />
        <Stat label="历史起点" value={index.base_date || '等待日线'} />
      </div>
      {points.length > 1 && (
        <DatedLine
          points={points}
          unit="点"
          label={`当前公司样本等权指标回溯走势，从${index.base_date}至${index.live_point?.date || index.history_end}${index.live_point ? '（末点为盘中估值）' : ''}；起点100，非官方指数或回测收益`}
        />
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        {index.constituents.map((r: Row) => (
          <div key={r.code} className="flex flex-wrap items-baseline justify-between gap-x-2 rounded-md bg-muted p-2 text-sm">
            <b className="font-medium">{r.name}</b>
            <small className="text-xs text-muted-foreground tabular-nums">{r.code}</small>
            <strong className="tabular-nums">{num(r.weight_pct)}%</strong>
            <small className="w-full text-xs text-muted-foreground tabular-nums">归属核对日期 {r.membership_date}</small>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground text-pretty">{index.scope} 历史起点100，采用当前样本回溯；换样后重算，不与旧组合拼接。</p>
    </section>
  );
}

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

function ScoreSummary({ sector }: { sector: Sector }) {
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

function ResearchDimensions({ sector, report }: { sector: Sector; report: Report }) {
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

function DetailedAdvice({ sector, advice, report }: { sector: Sector; advice: Row; report: Report }) {
  const sources = sourceMap(report);
  const group = (title: string, rows: Row[], fields: [string, string][]) =>
    rows.length > 0 && (
      <Section title={title}>
        <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm">
          {rows.map((row, index) => (
            <li key={index} className="flex flex-col gap-1">
              {fields.map(([key, label]) => (
                <p key={key} className="text-pretty">
                  {label}：{txt(row[key])}
                </p>
              ))}
              <div className="flex flex-wrap gap-x-3">
                {arr<string>(row.evidence_ids).map((id, i) => {
                  const source: Row | undefined = sources.get(id);
                  const name = txt(source?.name || source?.title || source?.label, '来源 ' + (i + 1));
                  return source ? (
                    <SourceLink key={id} url={source.url}>
                      {name}
                    </SourceLink>
                  ) : (
                    <span key={id} className="text-sm text-muted-foreground">
                      {name}
                    </span>
                  );
                })}
              </div>
            </li>
          ))}
        </ol>
      </Section>
    );
  const scope = advice.historical
    ? '范围：生成时保存的' + (advice.scope === 'reference' ? '参考指标研究' : '公司研究') + '，请结合当时证据复盘。'
    : advice.scope === 'reference'
      ? '范围：参考指标研究，观察其走势及覆盖市场。'
      : sector.score_status !== 'complete'
        ? '范围：公司基础/阶段研究，保留 ' + sector.score_maximum + ' 分口径，先核验尚缺证据。'
        : '范围：公司研究，按当前完整研究分及其证据形成条件判断。';
  return (
    <section aria-label={advice.historical ? advice.label : '详细研究建议与核验计划'} className="flex flex-col gap-3">
      <h4 className="font-semibold text-balance">{advice.historical ? advice.label : '详细研究建议与核验计划'}</h4>
      {advice.historical && <p className="text-sm text-warning text-pretty">{advice.notice}</p>}
      <p className="text-xs text-muted-foreground text-pretty">{scope}</p>
      {group('判断依据：事实与解释', advice.evidenceChain, [
        ['fact', '证据事实'],
        ['interpretation', '研究解释'],
      ])}
      {group('下一步怎么核验', advice.actionPlan, [
        ['trigger', '触发条件'],
        ['step', '核验步骤'],
      ])}
      {group('不同情况如何调整关注', advice.scenarios, [
        ['condition', '观察到的变化'],
        ['response', '研究应对'],
      ])}
      {advice.reviewConditions.length > 0 && (
        <Section title="暂停原结论并重新复核的条件">
          <BulletList items={advice.reviewConditions} />
        </Section>
      )}
    </section>
  );
}

function AiAnalysis({ sector, report }: { sector: Sector; report: Report }) {
  if (!(sector.ai_analysis && sector.ai_research_status === 'completed' && (report.report_stale || report.ai_research.status !== 'stale')))
    return null;
  const advice = sectorResearch.researchAdvicePresentation(sector, report);
  const historicalAdvice = sectorResearch.researchHistoricalAdvicePresentation(sector, report);
  const saved = sectorResearch.researchSavedPresentation(sector, report);
  return (
    <section className="flex flex-col gap-3 rounded-lg bg-muted p-3">
      <h4 className="font-semibold text-balance">{report.report_stale ? '历史 AI 板块解读' : 'AI 板块解读'}</h4>
      {saved.saved && (
        <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
          {saved.generatedAt ? <time dateTime={saved.generatedAt}>{saved.label}</time> : <span>{saved.label}</span>}
          <small>{saved.note}</small>
          <small>{saved.dataLabel}</small>
        </div>
      )}
      {!report.report_stale ? (
        <>
          <b className="font-medium">{advice.label}</b>
          {advice.summary && <p className="text-sm text-pretty">{advice.summary}</p>}
          {advice.watchPoints.length > 0 && (
            <Section title="后续核验重点">
              <BulletList items={advice.watchPoints} />
            </Section>
          )}
          {advice.detailed && <DetailedAdvice sector={sector} advice={advice} report={report} />}
        </>
      ) : (
        historicalAdvice && <DetailedAdvice sector={sector} advice={historicalAdvice} report={report} />
      )}
      <p className="text-sm text-pretty">{sector.ai_analysis}</p>
      {sector.ai_risks.length > 0 && (
        <Section title="AI 补充风险">
          <BulletList items={sector.ai_risks} />
        </Section>
      )}
      {sector.ai_invalidation && <p className="text-sm text-pretty">失效条件：{sector.ai_invalidation}</p>}
      <p className="text-xs text-muted-foreground">AI 解读用于整理证据，不代表收益概率，不构成投资建议。</p>
    </section>
  );
}

function Diagnostics({ data, report }: { data: Row; report: Report }) {
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

export function SectorDetail({ report, sectorId, framed = true }: { report: Report; sectorId: string | null; framed?: boolean }) {
  const sector: Sector | undefined = report.sector_analysis.find((s: Sector) => s.id === sectorId);
  if (!sector) return null;
  const historical = report.report_stale;
  const related = sectorEvents(report, sector.id);
  const data = sectorResearch.sectorDataPresentation(sector, {
    historical,
    sources: report.snapshot.sources,
    companyCount: (report.company_evidence.sector_leaders[sector.id] || []).length,
    eventCount: related.length,
  });
  const tone = sectorTone(sector, historical);
  const indicator = historical ? null : sectorResearch.sectorIndicator(sector);
  const scoreLabel = data.hasScore
    ? sector.score_model === 'company_research_v2'
      ? data.scoreUnit
      : historical
        ? '历史研究分数 / 100'
        : sector.score_label
          ? sector.score_label + ' / 100'
          : sector.custom_index
            ? '综合研究分数 / 100'
            : '研究分数 / 100'
    : data.scoreNote;
  const metrics: [string, string][] = [
    [data.changeLabel, data.changeText],
    ['趋势判断', data.trendText],
    ['风险程度', data.riskText],
    ['行情时间', stamp(sector.as_of)],
  ];
  const hasCompanies = !['bond', 'convertible_bond', 'money_rate'].includes(sector.quote.asset_type);
  const hasAi =
    sector.ai_access?.status === 'locked' ||
    Boolean(sector.ai_analysis && sector.ai_research_status === 'completed' && (report.report_stale || report.ai_research.status !== 'stale'));
  const components = Object.entries(sector.score_components as Record<string, unknown>).filter(([, v]) => finite(v)) as [string, number][];
  const body = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col">
            <Eyebrow>{historical ? '历史板块分析' : '板块分析'}</Eyebrow>
            <h2 className="text-xl font-semibold text-balance">{sector.title}</h2>
            <p className="text-sm text-muted-foreground">{GROUP_LABELS[sector.group] || sector.group}</p>
          </div>
          <div className="flex flex-col items-end">
            <strong className={cn('text-3xl font-semibold tabular-nums', TONE_TEXT[tone])}>{data.scoreText}</strong>
            <span className="text-xs text-muted-foreground">{scoreLabel}</span>
            <span className="text-xs text-muted-foreground tabular-nums">数据时间 {stamp(sector.as_of)}</span>
          </div>
        </div>
        {historical && (
          <p className="text-sm text-warning text-pretty">
            历史板块分析 · 报告时间 {stamp(report.as_of)}；以下理由与风险反映当时数据，当前信号已清除。
          </p>
        )}
        <Tabs defaultValue="overview">
          <div className="-mx-1 overflow-x-auto overflow-y-hidden border-b border-border">
            <TabsList variant="line" aria-label="板块详情分类">
              <TabsTrigger value="overview">概览</TabsTrigger>
              <TabsTrigger value="evidence">研究依据</TabsTrigger>
              {hasCompanies && <TabsTrigger value="companies">公司样本</TabsTrigger>}
              <TabsTrigger value="events" className="tabular-nums">
                相关事件 {related.length}
              </TabsTrigger>
              <TabsTrigger value="ai">AI 解读</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview" className="flex flex-col gap-4 pt-4">
            <p className="text-sm text-pretty">{sector.summary}</p>
            <p className="text-xs text-muted-foreground">研究分用于比较证据强弱，不代表收益概率，不构成投资建议。</p>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {metrics.map(([label, value]) => {
                const showIndicator =
                  indicator &&
                  ((label === '趋势判断' && indicator.className === 'trend-strong') || (label === '风险程度' && indicator.className === 'risk-critical'));
                return (
                  <div key={label} className="rounded-md bg-muted p-2">
                    <dt className="text-xs text-muted-foreground">{historical && label !== '行情时间' ? '历史' + label : label}</dt>
                    <dd
                      className={cn(
                        'flex items-center gap-1 font-medium tabular-nums',
                        label === data.changeLabel && data.hasQuote && !historical && sector.quote.asset_type !== 'money_rate' && DIRECTION_CLASS[direction(sector.change_pct)],
                      )}
                    >
                      {showIndicator && <IndicatorIcon indicator={indicator} />}
                      {value}
                      {showIndicator ? ' · ' + indicator.label : ''}
                    </dd>
                  </div>
                );
              })}
            </dl>
            {indicator?.reason && (
              <p className={cn('text-sm text-pretty', indicator.className === 'risk-critical' ? 'text-destructive' : 'text-tier-optimistic')}>
                {indicator.label}：{indicator.reason}
              </p>
            )}
            <ScoreSummary sector={sector} />
            {sector.requirements?.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-3">
                {sector.requirements.map((r: Row) => (
                  <div key={r.id || r.label} className="rounded-md bg-muted p-2 text-sm">
                    <b className="font-medium">{r.label}</b>
                    <span className={cn('block text-xs', r.status === 'ok' ? 'text-tier-optimistic' : 'text-warning')}>
                      {REQUIREMENT[r.status] || '待检查'}
                    </span>
                    <small className="text-xs text-muted-foreground text-pretty">{r.note}</small>
                  </div>
                ))}
              </div>
            )}
            <ScarcityDetail value={sector.scarcity} />
          </TabsContent>
          <TabsContent value="evidence" className="flex flex-col gap-4 pt-4">
            <IndependentIndex sector={sector} />
            <ResearchDimensions sector={sector} report={report} />
            <Section title={historical ? '当时观察与条件' : '后续观察与条件'}>
              <BulletList items={sector.next_steps} fallback="等待有效公司样本与可靠来源，再复核研究结论。" />
            </Section>
            <Diagnostics data={data} report={report} />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <b className="font-medium">行情依据</b>
              {sector.quote.name && (
                <span className="text-muted-foreground tabular-nums">
                  {sector.quote.name}
                  {sector.quote.code ? ' · ' + sector.quote.code : ''}
                </span>
              )}
              {sector.sources.length ? (
                sector.sources.map((source: Source) => (
                  <SourceLink key={source.id} url={source.url}>
                    {source.name || '查看来源'}
                  </SourceLink>
                ))
              ) : (
                <span className="text-muted-foreground">暂无可用来源记录</span>
              )}
            </div>
            {sector.score_method && (
              <Disclosure title="查看评分模型与计算依据">
                <p className="text-pretty">{sector.score_method}</p>
                {components.length > 0 && (
                  <p className="tabular-nums text-pretty">
                    各项得分：{components.map(([k, v]) => (COMPONENT_LABELS[k] || k) + ' ' + v.toFixed(2)).join('；')}
                  </p>
                )}
              </Disclosure>
            )}
          </TabsContent>
          {hasCompanies && (
            <TabsContent value="companies" className="pt-4">
              <CompanyEvidence sector={sector} report={report} />
            </TabsContent>
          )}
          <TabsContent value="events" className="pt-4">
            <EventList
              events={related}
              emptyText={
                report.event_analysis.status === 'completed'
                  ? '本轮已评估的证据中，没有与本板块相关、达到展示门槛的事件；不代表全网没有事件。'
                  : '重要事件尚未完成本轮评估；不代表没有利好或利空。'
              }
            />
          </TabsContent>
          <TabsContent value="ai" className="flex flex-col gap-4 pt-4">
            {sector.ai_access?.status === 'locked' && <SectorAccess sector={sector} report={report} />}
            <AiAnalysis sector={sector} report={report} />
            {!hasAi && (
              <p className="text-sm text-muted-foreground text-pretty">
                本板块暂无可查看的 AI 解读。可在首页“我的关注”中为关注板块生成个人 AI 研究，或等待管理员的公共研究计划。
              </p>
            )}
          </TabsContent>
        </Tabs>
      </div>
  );
  if (!framed) return <div id="sectorDetail">{body}</div>;
  return (
    <Card id="sectorDetail" className={cn('scroll-mt-16 border-l-4', TONE_BORDER[tone])}>
      <CardContent>{body}</CardContent>
    </Card>
  );
}
