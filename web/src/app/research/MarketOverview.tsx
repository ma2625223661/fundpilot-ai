// Port of renderMarket / renderSentiment / renderLiquidity. Every index shows its
// data date next to it; missing scores stay "—" and never become 0.
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Card, CardContent } from '@/components/ui/card';
import { Change, SourceLink } from '@/components/research/common';
import { sectorResearch } from '@/lib/research';
import { arr, finite, num, stamp, txt } from '@/lib/format';
import { indexTrend, type Report, type Sector, type Source } from '@/lib/report';
import { Sparkline } from '@/components/sparkline';
import { cn } from '@/lib/utils';

type Tone = 'good' | 'neutral' | 'caution' | 'alert' | 'unknown';
const TONE_TEXT: Record<Tone, string> = {
  good: 'text-tier-optimistic',
  neutral: 'text-foreground',
  caution: 'text-warning',
  alert: 'text-destructive',
  unknown: 'text-muted-foreground',
};
const TONE_FILL: Record<Tone, string> = {
  good: 'bg-tier-optimistic',
  neutral: 'bg-primary',
  caution: 'bg-warning',
  alert: 'bg-destructive',
  unknown: 'bg-muted-foreground',
};

/**
 * A 0–100 track with a marker. Missing scores draw the track only, so an
 * unknown value never looks like 0. Band labels sit under their fifth.
 */
function ScaleBar({ score, tone, bands, label }: { score: number | null; tone: Tone; bands?: string[]; label: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score ?? undefined}
        aria-valuetext={score === null ? '等待数据' : String(score)}
        className="relative h-2 rounded-full bg-muted"
      >
        {score !== null && (
          <>
            <div className={cn('h-full rounded-full opacity-30', TONE_FILL[tone])} style={{ width: Math.max(0, Math.min(100, score)) + '%' }} />
            <div
              className={cn('absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card', TONE_FILL[tone])}
              style={{ left: Math.max(0, Math.min(100, score)) + '%' }}
            />
          </>
        )}
      </div>
      {bands && (
        <div className="grid grid-cols-5 text-center text-xs text-muted-foreground" aria-hidden="true">
          {bands.map(step => (
            <span key={step}>{step}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function IndexCard({
  title,
  status,
  scoreText,
  score,
  label,
  tone,
  bands,
  dateLine,
  reading,
  children,
}: {
  title: string;
  status: string;
  scoreText: string;
  score: number | null;
  label: string;
  tone: Tone;
  bands?: string[];
  dateLine: string;
  reading: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
        <Sheet>
          <SheetTrigger render={<Button variant="ghost" size="xs" aria-label={'查看' + title + '依据'} />}>
            依据
            <ChevronRight aria-hidden="true" />
          </SheetTrigger>
          <SheetContent side="right" className="gap-0 p-0">
            <SheetHeader className="border-b border-border pr-12">
              <SheetTitle>{title}</SheetTitle>
              <SheetDescription className="text-pretty">{reading}</SheetDescription>
            </SheetHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-3 p-4 text-sm text-muted-foreground">
                <p className="tabular-nums">
                  {status} · {dateLine}
                </p>
                {children}
              </div>
            </ScrollArea>
          </SheetContent>
        </Sheet>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <p className="flex items-baseline gap-1">
          <span className={cn('text-3xl font-semibold tabular-nums', score === null ? 'text-muted-foreground' : 'text-foreground')}>{scoreText}</span>
          <span className="text-xs text-muted-foreground">/ 100</span>
        </p>
        <span className={cn('text-base font-semibold text-balance', TONE_TEXT[tone])}>{label}</span>
      </div>
      <ScaleBar score={score} tone={tone} bands={bands} label={title} />
      <span className="text-xs text-muted-foreground tabular-nums">{dateLine}</span>
    </div>
  );
}

/** Detail block shown inside a side panel (the old collapsible evidence). */
function Details({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      {children}
    </section>
  );
}

function Sources({ ids, known }: { ids: string[]; known: Map<string, Source> }) {
  if (!ids.length) return <span className="text-sm text-muted-foreground">暂无有效来源记录</span>;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {ids.map(id => {
        const source = known.get(id);
        return (
          <SourceLink key={id} url={source?.url}>
            {source?.name || id}
          </SourceLink>
        );
      })}
    </div>
  );
}

function Fact({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="rounded-md bg-muted p-2">
      <p className="font-medium text-foreground tabular-nums">{value}</p>
      <p className="text-xs">{label}</p>
    </div>
  );
}

function PressureCard({ report }: { report: Report }) {
  const panic = report.strategy.panic;
  const score = !report.report_stale && finite(panic.score) ? panic.score : null;
  const label = txt(panic.label, finite(score) ? (score >= 70 ? '市场压力较高' : score >= 40 ? '市场压力中等' : '市场压力较低') : '数据待补充');
  // Same bands as the old card's data-tone (high / medium / low).
  const tone: Tone = score === null ? 'unknown' : score >= 70 ? 'alert' : score >= 40 ? 'caution' : 'good';
  const quoteDate = panic.quote_as_of || panic.data_time ? String(panic.quote_as_of || panic.data_time).slice(0, 10) : '待取得';
  return (
    <IndexCard
      title="市场压力"
      status={score === null ? '等待最新数据' : '越高越承压'}
      scoreText={score === null ? '—' : num(score, 0)}
      score={score}
      label={label}
      tone={tone}
      dateLine={'行情日期 ' + quoteDate}
      reading="分数越高，当前市场承压越明显。"
    >
      <Details title="压力依据与数据时间">
        <p className="text-pretty">{txt(panic.summary || panic.reason, '市场样本不足，当前不生成恐慌分。')}</p>
        <p className="tabular-nums">
          评估时间：{stamp(panic.calculated_at || panic.as_of || report.as_of)} · 行情时间：{stamp(panic.quote_as_of || panic.data_time)}
        </p>
      </Details>
    </IndexCard>
  );
}

function LiquidityCard({ report }: { report: Report }) {
  const s = sectorResearch.liquidityPresentation(report.market_liquidity);
  const known = new Map<string, Source>(
    [...arr<Source>(report.snapshot?.sources), ...arr<Sector>(report.sector_analysis).flatMap(x => arr<Source>(x.sources))].map(v => [v.id, v]),
  );
  const bp = (value: unknown) => (finite(value) ? num(value, 2) + 'bp' : '—');
  const tone: Tone =
    s.tone === 'unknown' ? 'unknown' : ['tight', 'slightly-tight'].includes(s.tone) ? 'caution' : ['slightly-loose', 'loose'].includes(s.tone) ? 'good' : 'neutral';
  return (
    <IndexCard
      title="市场流动性指数"
      status={s.statusLabel}
      scoreText={s.scoreText}
      score={s.score}
      label={s.label}
      tone={tone}
      bands={['偏紧', '略紧', '中性', '偏宽', '宽松']}
      dateLine={'数据时间 ' + (s.as_of || '待取得')}
      reading="分数越高表示资金利率相对平稳或趋宽；不代表股票收益或存款安全。"
    >
      <Details title="查看资金依据与来源">
        <div className="grid grid-cols-2 gap-2">
          <Fact value={finite(s.annual_rate_pct) ? num(s.annual_rate_pct, 3) + '%' : '待补充'} label="隔夜年化利率" />
          <Fact value={s.trend || '待补充'} label="资金趋势" />
        </div>
        <p className="text-pretty">{s.summary}</p>
        <p className="tabular-nums">
          1日 {bp(s.rate_change_1d_bp)} · 5日 {bp(s.rate_change_5d_bp)} · 20日 {bp(s.rate_change_20d_bp)}
        </p>
        <p className="text-pretty">
          流动性风险 {finite(s.risk_score) ? num(s.risk_score, 0) + '/100' : '待核验'}；风险分越高代表资金环境风险越高。
        </p>
        <p className="tabular-nums">{s.sample_count} 个观测点</p>
        {s.missing.length > 0 && <p className="text-pretty">缺失或限制：{s.missing.join('；')}</p>}
        <p className="text-pretty">{s.method || '沿用人民币隔夜 Shibor 专用流动性模型；分数越高表示资金利率相对平稳或趋宽。'}</p>
        <p className="text-pretty">{s.scope || '仅观察人民币隔夜资金利率，不代表股票收益或存款安全。'}</p>
        <Sources ids={s.source_ids} known={known} />
      </Details>
    </IndexCard>
  );
}

function SentimentCard({ report }: { report: Report }) {
  const s = sectorResearch.sentimentPresentation(report.market_sentiment);
  const known = new Map<string, Source>(
    [...arr<Source>(report.snapshot?.sources), ...arr<Source>(report.company_evidence?.sources)].map(v => [v.id, v]),
  );
  // Overheating means crowding risk, so it is flagged rather than celebrated.
  const tone: Tone = s.tone === 'unknown' ? 'unknown' : s.tone === 'hot' ? 'caution' : 'neutral';
  return (
    <IndexCard
      title="市场情绪指数"
      status={s.statusLabel}
      scoreText={s.scoreText}
      score={s.score}
      label={s.label}
      tone={tone}
      bands={['低迷', '偏冷', '平稳', '活跃', '过热']}
      dateLine={'报价日期 ' + (s.sample_date || '待取得')}
      reading="分数衡量样本活跃度；过热意味着拥挤风险上升，不代表买入信号。"
    >
      <Details title="查看情绪依据与来源">
        <div className="grid grid-cols-2 gap-2">
          <Fact value={`${s.sample_count} / ${s.candidate_count} 家`} label="去重有效报价 / 候选样本" />
          <Fact value={`${s.index_count} / 4 个`} label="有效主要指数" />
        </div>
        <p className="tabular-nums">
          报价日：{s.sample_date || '待取得'} · 趋势收盘日：{s.history_date || '待取得'}
        </p>
        <p className="text-pretty">{s.summary}</p>
        <p className="text-pretty">
          可用分项权重 {finite(s.coverage_pct) ? num(s.coverage_pct, 0) + '%' : '待核验'} · 不代表全市场覆盖率
        </p>
        <div className="flex flex-col gap-2">
          {arr<Record<string, any>>(s.components).map(c => (
            <div key={c.label} className="rounded-md bg-muted p-2">
              <p className="flex justify-between gap-2 text-foreground">
                <b className="font-medium">{c.label}</b>
                <span className="tabular-nums">
                  {finite(c.score) ? num(c.score) + ' / 100' : '待补充'} · 权重 {num(c.weight * 100, 0)}%
                </span>
              </p>
              <p className="text-pretty">{c.note}</p>
              <p className="text-xs tabular-nums">
                有效 {c.count} 项 · 数据时间：{stamp(c.as_of)}
              </p>
            </div>
          ))}
          {!s.components.length && <p>等待有效行情与历史样本。</p>}
        </div>
        {s.missing.length > 0 && <p className="text-pretty">缺失或限制：{s.missing.join('；')}</p>}
        <p className="text-pretty">
          {s.method || '上涨广度40% + 主要指数强弱30% + 20日均线参与度30%。至少两项有效、可用分项权重达到70%才计算；缺项按有效权重归一。'}
        </p>
        <p className="text-pretty">{s.scope || '基于已接入且去重的A股公司样本，属于情绪代理指标。'}</p>
        <p className="tabular-nums">评估时间：{stamp(s.as_of)}</p>
        <Sources ids={s.source_ids} known={known} />
      </Details>
    </IndexCard>
  );
}

function OutlookCard({ report }: { report: Report }) {
  const regime = report.strategy.regime;
  const sectors: Sector[] = report.sector_analysis;
  const coverage: [string, number][] = [
    ['研究板块', sectors.length],
    ['有效行情', sectors.filter(s => ['ok', 'partial'].includes(s.status) && finite(s.change_pct)).length],
    ['重要事件', report.event_analysis.events.length],
  ];
  return (
    <div className="flex min-w-0 flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="shrink-0 text-sm font-medium text-muted-foreground">市场环境</h2>
        <Badge variant="secondary" className="max-w-36 min-w-0 truncate" title={txt(regime.label || regime.name || regime.mode)}>
          {txt(regime.label || regime.name || regime.mode, '等待研究')}
        </Badge>
      </div>
      <h3 className="line-clamp-1 text-base font-semibold" title={report.summary || undefined}>
        {txt(regime.title || regime.label, '先看市场环境，再看板块强弱')}
      </h3>
      <dl className="grid grid-cols-3 gap-2">
        {coverage.map(([label, value]) => (
          <div key={label}>
            <dd className="text-xl font-semibold tabular-nums">{value}</dd>
            <dt className="text-xs text-muted-foreground">{label}</dt>
          </div>
        ))}
      </dl>
      <span className="text-xs text-muted-foreground tabular-nums">报告时间 {stamp(report.as_of)}</span>
    </div>
  );
}

export function MarketQuotes({ report }: { report: Report }) {
  const quotes = arr<Record<string, any>>(report.snapshot.market).slice(0, 8);
  if (!quotes.length) return null;
  return (
    <section aria-label="市场指数行情" className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {quotes.map((q, index) => {
        const name = txt(q.name || q.title || q.label, '市场指数');
        const trend = indexTrend(q);
        return (
          <Card key={index} size="sm">
            <CardContent className="flex flex-col gap-1">
              <span className="text-sm text-muted-foreground">{name}</span>
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="text-xl font-semibold tabular-nums">{num(q.price ?? q.last ?? q.value)}</span>
                <Change value={q.change_pct} historical={report.report_stale} className="text-sm font-semibold" />
              </div>
              {trend && (
                <Sparkline
                  points={trend.points}
                  className="h-7"
                  label={`${name}近 ${trend.points.length} 个交易日收盘走势，${trend.from} 至 ${trend.to}`}
                />
              )}
              <span className="text-xs text-muted-foreground tabular-nums">{stamp(q.as_of || q.data_time || q.timestamp)}</span>
              {trend && (
                <span className="text-xs text-muted-foreground tabular-nums">
                  日线 {trend.points.length} 日 · 截至 {trend.to}
                </span>
              )}
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}

export function MarketOverview({ report }: { report: Report }) {
  return (
    <section id="marketOverview" aria-label="市场风险、流动性与情绪概览" className="scroll-mt-16">
      <Card className="py-0">
        <div className="grid divide-y divide-border sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4 xl:divide-x">
          <PressureCard report={report} />
          <SentimentCard report={report} />
          <LiquidityCard report={report} />
          <OutlookCard report={report} />
        </div>
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground text-pretty">
          三项指标描述市场环境，不代表股票收益或买入信号；点击“依据”查看计算口径、数据时间与来源。
        </p>
      </Card>
    </section>
  );
}
