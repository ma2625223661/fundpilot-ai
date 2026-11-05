// The standalone sector page (#sector/<id>) and the leading-sample column of
// the sector table.
import { afterEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { SectorView } from '@/app/views/SectorView';
import { DashView } from '@/app/views/DashView';
import { sectorHref } from '@/app/navigation';
import { baseReplies, renderPage, report, sector } from './harness';

afterEach(() => {
  location.hash = '';
});

describe('sector page', () => {
  it('opens a sector from its own address, with a way back and the score note', async () => {
    location.hash = sectorHref('semiconductor');
    const { container } = renderPage(<SectorView />);
    expect(await screen.findByRole('heading', { name: '半导体' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /返回板块研究/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /复制链接/ })).toBeTruthy();
    expect(container.textContent).toContain('不代表收益概率，不构成投资建议');
  });

  it('explains an unknown sector instead of showing an empty page', async () => {
    location.hash = sectorHref('no-such-sector');
    renderPage(<SectorView />);
    expect(await screen.findByText('没有找到这个板块')).toBeTruthy();
  });
});

describe('leading sample column', () => {
  it('names the sample with the largest change and counts samples up and down', async () => {
    const leader = (code: string, name: string, change: number) => ({
      ts_code: code,
      name,
      quote: { pct_chg: change, trade_date: '2026-11-04' },
    });
    const value = report([sector()], {
      company_evidence: {
        status: 'ready',
        sector_leaders: {
          semiconductor: [leader('688981.SH', '中芯国际', 9), leader('603501.SH', '韦尔股份', -1.2), leader('688256.SH', '寒武纪', 3.5)],
        },
      },
    });
    const { container } = renderPage(<DashView />, { replies: baseReplies({}, value) });
    await screen.findByText('板块机会总览');
    const change = screen.getAllByText('+9.00%');
    expect(change.some(node => node.className.includes('text-rise'))).toBe(true);
    expect(container.textContent).toContain('中芯国际');
    expect(container.textContent).toContain('2 涨 · 1 跌 / 3 家');
  });
});
