// Small trend lines: gaps stay gaps, too little data draws nothing, and the
// sector trend comes only from the report's own sample-index history.
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { Sparkline } from '@/components/sparkline';
import { indexTrend, sectorTrend } from '@/lib/report';
import { MarketQuotes } from '@/app/research/MarketOverview';

describe('Sparkline', () => {
  it('breaks the line at a missing point instead of drawing it at zero', () => {
    const { container } = render(
      <Sparkline
        label="测试走势"
        points={[
          { date: '2026-11-01', value: 100 },
          { date: '2026-11-02', value: 101 },
          { date: '2026-11-03', value: null },
          { date: '2026-11-04', value: 99 },
          { date: '2026-11-05', value: 102 },
        ]}
      />,
    );
    expect(container.querySelectorAll('polyline')).toHaveLength(2);
    expect(container.querySelector('svg')?.getAttribute('aria-label')).toBe('测试走势');
  });

  it('draws nothing with fewer than two known values', () => {
    const { container } = render(<Sparkline points={[{ date: '2026-11-04', value: 100 }, { date: '2026-11-05', value: null }]} />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('is hidden from screen readers when it has no label of its own', () => {
    const { container } = render(<Sparkline points={[{ date: 'a', value: 1 }, { date: 'b', value: 2 }]} />);
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });
});

describe('sectorTrend', () => {
  const history = Array.from({ length: 70 }, (_, i) => ({ date: `2026-08-${String(i + 1).padStart(2, '0')}`, value: 100 + i }));

  it('keeps the last days of the sample index and ends on the intraday estimate', () => {
    const trend = sectorTrend({ custom_index: { history, live_point: { date: '2026-09-99', value: 180 } } }, 60)!;
    expect(trend.points).toHaveLength(60);
    expect(trend.to).toBe('2026-09-99');
    expect(trend.intraday).toBe(true);
  });

  it('returns nothing for a sector without its own sample index', () => {
    expect(sectorTrend({ custom_index: null })).toBeNull();
    expect(sectorTrend({})).toBeNull();
  });
});

describe('index card trend', () => {
  const row = {
    code: 'sh000001',
    name: '上证指数',
    last: 3900,
    change_pct: 0.5,
    as_of: '2026-11-04T15:00:00+08:00',
    history: [
      { date: '2026-11-02', close: 3850 },
      { date: '2026-11-03', close: 'bad' },
      { date: 'not-a-date', close: 1 },
      { date: '2026-11-04', close: 3900 },
    ],
  };

  it('reads the daily closes, turning a bad close into a gap and dropping bad dates', () => {
    const trend = indexTrend(row)!;
    expect(trend.points.map(point => point.value)).toEqual([3850, null, 3900]);
    expect(trend.to).toBe('2026-11-04');
    expect(indexTrend({ ...row, history: undefined })).toBeNull();
  });

  it('draws the line on the card with its end date', () => {
    const { container } = render(<MarketQuotes report={{ report_stale: false, snapshot: { market: [row] } }} />);
    expect(container.querySelector('svg[role="img"]')?.getAttribute('aria-label')).toContain('2026-11-02 至 2026-11-04');
    expect(container.textContent).toContain('截至 2026-11-04');
  });
});
