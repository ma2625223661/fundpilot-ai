// CSV export of the sector table and the page / settings entries in Ctrl+K.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { toCsv } from '@/lib/csv';
import { DashView } from '@/app/views/DashView';
import { SectorSearchDialog } from '@/components/sector-search';
import { baseReplies, renderPage, report, sector } from './harness';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('csv', () => {
  it('quotes commas and quotes, keeps signed numbers, and defuses formula text', () => {
    expect(toCsv([['a,b', 'say "hi"', '+1.25%', '-0.80%', '=1+1', '@x']])).toBe('"a,b","say ""hi""",+1.25%,-0.80%,\'=1+1,\'@x');
  });
});

describe('sector table export', () => {
  it('downloads the listed rows with the report time and the score note', async () => {
    let saved: Blob | null = null;
    Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        saved = blob;
        return 'blob:test';
      }),
      revokeObjectURL: vi.fn(),
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    localStorage.setItem('fundpilot_dash_tab_v1', 'boards');
    const value = report([sector(), sector({ id: 'liquor', title: '白酒', score: 41.1, change_pct: -0.8, quote: { change_pct: -0.8 } })]);
    renderPage(<DashView />, { replies: baseReplies({}, value) });
    fireEvent.click(await screen.findByRole('button', { name: /导出 CSV/ }));
    expect(click).toHaveBeenCalled();
    // jsdom's Blob has no text(); read it the way a page would.
    const bytes = await new Promise<Uint8Array>(resolve => {
      const reader = new FileReader();
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.readAsArrayBuffer(saved as unknown as Blob);
    });
    // UTF-8 byte-order mark first, so Excel opens Chinese text correctly.
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    const text = new TextDecoder().decode(bytes);
    const lines = text.split('\r\n');
    expect(lines[0]).toContain('研究分不代表收益概率，不构成投资建议');
    expect(lines[1].split(',')[0]).toBe('板块');
    expect(lines).toHaveLength(4);
    expect(text).toContain('半导体,行业主题,+1.25%');
    expect(text).toContain('白酒,行业主题,-0.80%');
  });
});

describe('search palette', () => {
  it('lists pages and settings sections next to sectors', async () => {
    renderPage(<SectorSearchDialog open setOpen={() => {}} />);
    expect(await screen.findByText('数据依据')).toBeTruthy();
    expect(screen.getByText('数据连接')).toBeTruthy();
    expect(screen.getByText('AI 研究设置')).toBeTruthy();
  });
});
