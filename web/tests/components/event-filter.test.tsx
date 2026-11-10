// Important events can be narrowed to good news, bad news or followed sectors,
// using each event's own direction; an empty filter offers a way back.
import { describe, expect, it } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { ImportantEvents } from '@/app/research/Events';
import { baseReplies, renderPage, report, sector } from './harness';

const event = (id: string, title: string, direction: string, impact: number, sectorId: string) => ({
  id,
  title,
  direction,
  impact_score: impact,
  sector_ids: [sectorId],
  reason: '影响说明',
  published_at: '2026-11-04T10:00:00+08:00',
  url: 'https://example.com/' + id,
});

function render(watchlist: string[]) {
  const value = report([sector(), sector({ id: 'liquor', title: '白酒' })], {
    event_analysis: {
      status: 'completed',
      events: [
        event('a', '半导体利好公告', 'positive', 72, 'semiconductor'),
        event('b', '白酒利空政策', 'negative', -55, 'liquor'),
        event('c', '半导体双向影响', 'mixed', 48, 'semiconductor'),
      ],
    },
  });
  return renderPage(<ImportantEvents />, { replies: baseReplies({ '/api/me/watchlist': { items: watchlist } }, value) });
}

describe('important event filter', () => {
  it('keeps only good or bad news by the event direction, with counts on the choices', async () => {
    render([]);
    expect(await screen.findByText('半导体利好公告')).toBeTruthy();
    expect(screen.getByRole('button', { name: '全部 3' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '利空 1' }));
    expect(screen.getByText('白酒利空政策')).toBeTruthy();
    expect(screen.queryByText('半导体利好公告')).toBeNull();
    expect(screen.queryByText('半导体双向影响')).toBeNull();
  });

  it('shows only events touching a followed sector', async () => {
    render(['liquor']);
    fireEvent.click(await screen.findByRole('button', { name: '我的关注 1' }));
    expect(screen.getByText('白酒利空政策')).toBeTruthy();
    expect(screen.queryByText('半导体利好公告')).toBeNull();
  });

  it('explains an empty result and offers to show everything again', async () => {
    render([]);
    fireEvent.click(await screen.findByRole('button', { name: '我的关注 0' }));
    expect(screen.getByText(/你还没有关注板块/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '显示全部事件' }));
    expect(screen.getByText('半导体利好公告')).toBeTruthy();
  });
});
