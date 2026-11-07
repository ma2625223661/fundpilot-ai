// The sector's own company-sample index: level, samples, history line and constituents.
import { Badge } from '@/components/ui/badge';
import { DatedLine } from '@/components/charts-lazy';
import { Stat } from '@/components/research/common';
import { num } from '@/lib/format';
import { type Sector } from '@/lib/report';
import { type Row } from '@/app/research/sector-detail/parts';

export function IndependentIndex({ sector }: { sector: Sector }) {
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
