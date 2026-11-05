// Sector sources sent as ids are expanded from snapshot.sources before the page
// reads the report; full records still work.
import { describe, expect, it } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { expandSourceRefs } from '@/lib/source-refs';
import { SectorView } from '@/app/views/SectorView';
import { sectorHref } from '@/app/navigation';
import { baseReplies, renderPage, report, sector } from './harness';

const shared = { id: 'quote:semi', name: '半导体行情来源', url: 'https://example.com/semi', status: 'ok', as_of: '2026-11-04', fetched_at: '', error: '' };

describe('expandSourceRefs', () => {
  it('turns ids into the snapshot records, keeps full records and drops unknown ids', () => {
    const own = { id: 'own', name: '自有', url: null, status: 'ok' };
    const value = expandSourceRefs({
      snapshot: { sources: [shared] },
      sector_analysis: [{ id: 'semi', sources: ['quote:semi', own, 'missing'] }, { id: 'none' }],
    });
    expect(value.sector_analysis[0].sources).toEqual([shared, own]);
    expect(value.sector_analysis[1]).toEqual({ id: 'none' });
  });

  it('leaves a report without ids untouched', () => {
    const input = { snapshot: { sources: [] }, sector_analysis: [{ id: 'a', sources: [shared] }] };
    expect(expandSourceRefs(input)).toBe(input);
  });
});

describe('compact report on the page', () => {
  it('shows the expanded source as a link in the sector detail', async () => {
    location.hash = sectorHref('semiconductor');
    const value = report([sector({ sources: ['quote:semi'] })], {
      snapshot: { as_of: '2026-11-04T15:00:00+08:00', market: [], sources: [shared], warnings: [] },
      source_refs: 'snapshot',
    });
    renderPage(<SectorView />, { replies: baseReplies({}, value) });
    fireEvent.click(await screen.findByRole('tab', { name: '研究依据' }));
    const link = (await screen.findAllByText('半导体行情来源')).map(node => node.closest('a')).find(Boolean);
    expect(link?.getAttribute('href')).toBe('https://example.com/semi');
    location.hash = '';
  });
});
