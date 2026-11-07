// Which change the heat map and the rankings show: the day's change, or the
// 5 / 20 / 60-day returns the backend already calculates on closing prices
// (sector.metrics). Nothing is calculated here; values are only read and ordered.
import { useState } from 'react';
import { sectorResearch } from '@/lib/research';
import { finite, pct } from '@/lib/format';
import type { Report, Sector } from '@/lib/report';

export type Period = 'day' | '5d' | '20d' | '60d';

export interface PeriodInfo {
  id: Period;
  /** Toggle label. */
  label: string;
  /** Wording inside sentences, e.g. "近 20 日". */
  phrase: string;
  field: 'return_5d' | 'return_20d' | 'return_60d' | null;
  /** |change| limits for the four colour steps; longer windows move further. */
  steps: [number, number, number];
}

export const PERIODS: PeriodInfo[] = [
  { id: 'day', label: '当日', phrase: '当日', field: null, steps: [1, 3, 5] },
  { id: '5d', label: '5 日', phrase: '近 5 日', field: 'return_5d', steps: [2, 5, 10] },
  { id: '20d', label: '20 日', phrase: '近 20 日', field: 'return_20d', steps: [5, 10, 20] },
  { id: '60d', label: '60 日', phrase: '近 60 日', field: 'return_60d', steps: [5, 10, 20] },
];

export function periodInfo(period: Period) {
  return PERIODS.find(item => item.id === period) ?? PERIODS[0];
}

export interface PeriodChange {
  /** The value, or null when the report has none. */
  value: number | null;
  /** Text with its sign, or the old presentation's placeholder. */
  text: string;
  /** Whether the value may be coloured red / green. */
  coloured: boolean;
  /** Date the window ends on (multi-day windows only). */
  date: string | null;
  /** The window ends on today's intraday price, not a close. */
  intraday: boolean;
}

/** "截至 2026-11-04 收盘" or "截至 2026-11-05 盘中"; null for the day's change. */
export function periodEnd(change: PeriodChange) {
  return change.date ? `截至 ${change.date} ${change.intraday ? '盘中' : '收盘'}` : null;
}

/** The change a sector shows for a period, read from the report. */
export function periodChange(sector: Sector, report: Report, period: Period): PeriodChange {
  const historical = report.report_stale === true;
  // A rate move is not a price change.
  const rate = sector.quote?.asset_type === 'money_rate';
  const info = periodInfo(period);
  if (!info.field) {
    const data = sectorResearch.sectorDataPresentation(sector, { historical });
    const value = data.hasQuote && finite(sector.change_pct) ? (sector.change_pct as number) : null;
    return { value, text: data.changeText, coloured: value !== null && !historical && !rate, date: null, intraday: false };
  }
  const raw = sector.metrics?.[info.field];
  const value = finite(raw) && !rate ? (raw as number) : null;
  return {
    value,
    text: value === null ? '—' : pct(value),
    coloured: value !== null && !historical,
    date: typeof sector.metrics?.history_date === 'string' ? sector.metrics.history_date : null,
    intraday: sector.metrics?.is_intraday === true,
  };
}

/** Largest first, sectors without a value last, then by name (ordering only). */
export function sortByPeriod(sectors: Sector[], report: Report, period: Period): Sector[] {
  if (period === 'day') return sectorResearch.sortSectors(sectors, 'change');
  return [...sectors].sort((a, b) => {
    const x = periodChange(a, report, period).value;
    const y = periodChange(b, report, period).value;
    return (y ?? -Infinity) - (x ?? -Infinity) || String(a.title).localeCompare(String(b.title), 'zh-CN');
  });
}

const KEY = 'fundpilot_heatmap_period_v1';

/** The chosen period, remembered in this browser (a convenience only). */
export function usePeriod() {
  const [period, setPeriod] = useState<Period>(() => {
    try {
      const saved = localStorage.getItem(KEY);
      return PERIODS.some(item => item.id === saved) ? (saved as Period) : 'day';
    } catch {
      return 'day';
    }
  });
  const choose = (next: Period) => {
    setPeriod(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Storage unavailable: the choice lasts for this page only.
    }
  };
  return [period, choose] as const;
}
