// ECharts, imported piece by piece. Colours come from the theme's CSS variables
// and are re-read whenever the theme switches. No gradients, shadows or 3D.
import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

echarts.use([LineChart, GridComponent, TooltipComponent, SVGRenderer]);

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
