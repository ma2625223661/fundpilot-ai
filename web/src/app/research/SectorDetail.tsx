// Port of renderDetail: the sector detail with its tabs (overview, evidence,
// company samples, events, AI). The parts live in ./sector-detail/. The research
// and risk scores keep their "not a return probability / not investment advice" notes.
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { BulletList, Disclosure, Eyebrow, IndicatorIcon, SourceLink } from '@/components/research/common';
import { CompanyEvidence } from '@/app/research/CompanyEvidence';
import { EventList } from '@/app/research/Events';
import { ScarcityDetail } from '@/app/research/Scarcity';
import { SectorAccess } from '@/app/research/SectorAccess';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, GROUP_LABELS, direction, finite, stamp } from '@/lib/format';
import { TONE_BORDER, TONE_TEXT, sectorEvents, sectorTone, type Report, type Sector, type Source } from '@/lib/report';
import { cn } from '@/lib/utils';
import { AiAnalysis } from '@/app/research/sector-detail/AiAnalysis';
import { Diagnostics, ResearchDimensions } from '@/app/research/sector-detail/Evidence';
import { IndependentIndex } from '@/app/research/sector-detail/IndependentIndex';
import { ScoreSummary } from '@/app/research/sector-detail/ScoreSummary';
import { ScoreTrendLine } from '@/app/research/sector-detail/ScoreTrendLine';
import { Section, type Row } from '@/app/research/sector-detail/parts';

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
            <ScoreTrendLine report={report} sectorId={sector.id} />
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
