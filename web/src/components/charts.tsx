// ECharts, imported piece by piece. Colours come from the theme's CSS variables
// and are re-read whenever the theme switches. No gradients, shadows or 3D.
import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { GaugeChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

echarts.use([GaugeChart, LineChart, GridComponent, TooltipComponent, SVGRenderer]);

export function cssColor(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function useChart(build: () => EChartsCoreOption, deps: unknown[]) {
  const box = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  useEffect(() => {
    if (!box.current) return;
    const chart = echarts.init(box.current, undefined, { renderer: 'svg' });
    chart.setOption(build());
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(box.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
    // build reads the deps listed by the caller plus the theme colours.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, ...deps]);
  return box;
}

/**
 * A 0–100 gauge for a single index. A missing score draws an empty track and no
 * pointer, never a zero. The number itself is printed next to the chart by the
 * caller, so the chart is decorative for assistive technology.
 */
export function ScoreGauge({ score, colorVar = '--chart-1', className }: { score: number | null; colorVar?: string; className?: string }) {
  const box = useChart(() => {
    const border = cssColor('--border');
    const color = cssColor(colorVar);
    return {
      animation: true,
      series: [
        {
          type: 'gauge',
          startAngle: 200,
          endAngle: -20,
          min: 0,
          max: 100,
          radius: '100%',
          center: ['50%', '62%'],
          progress: { show: score !== null, width: 10, itemStyle: { color } },
          axisLine: { lineStyle: { width: 10, color: [[1, border]] } },
          pointer: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          anchor: { show: false },
          title: { show: false },
          detail: { show: false },
          data: score === null ? [] : [{ value: score }],
        },
      ],
    };
  }, [score, colorVar]);
  return <div ref={box} aria-hidden="true" className={cn('h-24 w-40', className)} />;
}

/**
 * A line of dated points (for example a sample index from base 100). Points with
 * no value are left as gaps instead of being joined through zero.
 */
export function DatedLine({
  points,
  unit,
  label,
  className,
}: {
  points: { date: string; value: number | null }[];
  unit: string;
  label: string;
  className?: string;
}) {
  const box = useChart(() => {
    const muted = cssColor('--muted-foreground');
    const border = cssColor('--border');
    const line = cssColor('--chart-1');
    return {
      grid: { left: 40, right: 12, top: 12, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: cssColor('--popover'),
        borderColor: border,
        textStyle: { color: cssColor('--popover-foreground') },
        valueFormatter: (value: unknown) => (typeof value === 'number' ? value.toFixed(2) + ' ' + unit : '—'),
      },
      xAxis: {
        type: 'category',
        data: points.map(point => point.date),
        axisLine: { lineStyle: { color: border } },
        axisLabel: { color: muted, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        scale: true,
        name: unit,
        nameTextStyle: { color: muted },
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: border } },
      },
      series: [
        {
          type: 'line',
          data: points.map(point => point.value),
          connectNulls: false,
          showSymbol: false,
          lineStyle: { color: line, width: 2 },
          itemStyle: { color: line },
        },
      ],
    };
  }, [JSON.stringify(points), unit]);
  return <div ref={box} role="img" aria-label={label} className={cn('h-40 w-full', className)} />;
}
