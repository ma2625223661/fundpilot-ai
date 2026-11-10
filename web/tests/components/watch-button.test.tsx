// The follow button now also sits on the comparison table (and in the detail
// drawer); it saves through the same watchlist API and reflects the new state.
import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { compareHref } from '@/app/navigation';
import { CompareView } from '@/app/views/CompareView';
import { baseReplies, renderPage, report, requests, sector } from './harness';

afterEach(() => {
  location.hash = '';
});

describe('follow button on the comparison page', () => {
  it('follows a sector through the watchlist API and then offers to unfollow it', async () => {
    let saved: string[] = [];
    const value = report([sector(), sector({ id: 'liquor', title: '白酒', score: 41.1 })]);
    location.hash = compareHref(['semiconductor', 'liquor']);
    renderPage(<CompareView />, {
      replies: baseReplies(
        {
          '/api/me/watchlist': (body: unknown) => {
            const change = body as { board_id: string; action: string } | undefined;
            if (change) saved = change.action === 'add' ? [...saved, change.board_id] : saved.filter(id => id !== change.board_id);
            return { items: saved };
          },
        },
        value,
      ),
    });
    fireEvent.click(await screen.findByRole('button', { name: '加入关注白酒' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '取消关注白酒' })).toBeTruthy());
    expect(requests().find(item => item.path === '/api/me/watchlist' && item.body)?.body).toEqual({ board_id: 'liquor', action: 'add' });
    expect(screen.getByRole('button', { name: '取消关注白酒' }).getAttribute('aria-pressed')).toBe('true');
  });
});
