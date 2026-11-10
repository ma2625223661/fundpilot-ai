// The research-score history kept by the backend (sector_changes.history), as a
// small line under the score. Values are read, never recomputed; days without a
// score break the line. The dates covered are always written next to it.
import { Sparkline } from '@/components/sparkline';
import { scoreTrend } from '@/lib/changes';
import { num } from '@/lib/format';
import type { Report } from '@/lib/report';

const short = (day: string) => day.slice(5).replace('-', '/');

export function ScoreTrendLine({ report, sectorId }: { report: Report; sectorId: string }) {
  const trend = scoreTrend(report, sectorId);
  if (!trend) return null;
  const values = trend.points.filter(point => point.value !== null).map(point => `${short(point.date)} ${num(point.value, 1)} 分`);
  return (
    <figure className="flex w-32 flex-col items-end gap-0.5">
      <Sparkline
        points={trend.points}
        label={`研究分走势，${trend.from} 至 ${trend.to}，共 ${trend.known} 个交易日：${values.join('，')}`}
        className="h-6"
      />
      <figcaption className="text-xs text-muted-foreground tabular-nums">
        研究分走势 {short(trend.from)}–{short(trend.to)}
      </figcaption>
    </figure>
  );
}
