// The heat map and rankings switch between today and the backend's 5 / 20 / 60
// day closing returns; a missing return stays "—" and uncoloured.
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { DashView } from '@/app/views/DashView';
import { baseReplies, renderPage, report, sector } from './harness';

beforeEach(() => {
  localStorage.removeItem('fundpilot_heatmap_period_v1');
  localStorage.setItem('fundpilot_dash_tab_v1', 'overview');
});

function render() {
  const value = report([
    sector({ metrics: { return_5d: 3.2, return_20d: 12.5, return_60d: -8.4, history_date: '2026-11-04', is_intraday: false } }),
    sector({
      id: 'media',
      title: '传媒',
      change_pct: 2,
      quote: { change_pct: 2 },
      metrics: { return_20d: 4.1, history_date: '2026-11-05', is_intraday: true },
    }),
    sector({ id: 'liquor', title: '白酒', change_pct: -0.8, quote: { change_pct: -0.8 }, metrics: {} }),
  ]);
  return renderPage(<DashView />, { replies: baseReplies({}, value) });
}

const tile = (name: string) =>
  screen.getAllByRole('button').find(node => node.getAttribute('aria-label')?.startsWith(name + '，'))!;

describe('heat map periods', () => {
  it('shows the 20-day closing return with its sign and end date after switching', async () => {
    render();
    await screen.findByText('板块热力图');
    fireEvent.click(screen.getByRole('button', { name: '20 日' }));
    const semiconductor = tile('半导体');
    expect(semiconductor.getAttribute('aria-label')).toContain('近 20 日涨跌 +12.50%');
    expect(semiconductor.getAttribute('aria-label')).toContain('截至 2026-11-04 收盘');
    expect(semiconductor.className).toContain('bg-rise/');
    expect(localStorage.getItem('fundpilot_heatmap_period_v1')).toBe('20d');
    // A window that ends on today's intraday price is not called a close.
    expect(tile('传媒').getAttribute('aria-label')).toContain('截至 2026-11-05 盘中');
    expect(screen.getByText(/其中 1 个方向末点为当日盘中价/)).toBeTruthy();
  });

  it('leaves a sector without that return as "—" and uncoloured, never 0', async () => {
    render();
    await screen.findByText('板块热力图');
    fireEvent.click(screen.getByRole('button', { name: '60 日' }));
    const liquor = tile('白酒');
    expect(liquor.getAttribute('aria-label')).toContain('近 60 日涨跌 —');
    expect(liquor.className).toContain('bg-muted');
    expect(tile('半导体').className).toContain('bg-fall/');
  });
});
