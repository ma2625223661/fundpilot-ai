// Day-over-day changes from the backend: validated, shown with signs and
// colours, and the header bell lists followed sectors with an unread dot.
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { normalizeChanges } from '@/lib/changes';
import { ChangesBell } from '@/app/research/Changes';
import { Watchlist } from '@/app/research/Watchlist';
import { baseReplies, renderPage, report, sector } from './harness';

const block = {
  status: 'ok',
  baseline_as_of: '2026-11-04T15:00:00+08:00',
  baseline_date: '2026-11-04',
  note: '变动对比的是上一交易日最后一份报告，只描述研究证据的变化，不代表收益方向，不构成投资建议。',
  items: {
    semiconductor: { score_before: 48, score_now: 52.4, score_delta: 4.4, flags: ['新增特大风险'], notable: true },
    liquor: { score_before: 42, score_now: 41.1, score_delta: -0.9, notable: false },
  },
};

function replies(changes: unknown = block) {
  const value = report([sector(), sector({ id: 'liquor', title: '白酒', score: 41.1 })], { sector_changes: changes });
  return baseReplies({ '/api/me/watchlist': { items: ['semiconductor', 'liquor'] } }, value);
}

beforeEach(() => {
  localStorage.removeItem('fundpilot_changes_seen_v1');
});

describe('change block', () => {
  it('keeps only well-formed fields and never makes up a delta', () => {
    const value = normalizeChanges({ status: 'ok', items: { a: { score_delta: 'x', flags: ['新增趋势优', 3], tier: { before: '中性' } } } });
    expect(value.items.a).toMatchObject({ scoreDelta: null, flags: ['新增趋势优'], tier: null, notable: false });
    expect(normalizeChanges(undefined).status).toBe('unavailable');
  });
});

describe('header bell', () => {
  it('lists notable changes of followed sectors and clears the dot once opened', async () => {
    renderPage(<ChangesBell />, { replies: replies() });
    const bell = await screen.findByRole('button', { name: /变动提醒，有 1 条未读/ });
    fireEvent.click(bell);
    expect(await screen.findByText('新增特大风险')).toBeTruthy();
    expect(screen.getByText('+4.40').className).toContain('text-rise');
    // A small move is not an alert.
    expect(screen.queryByText('-0.90')).toBeNull();
    expect(screen.getByText(/不代表收益方向，不构成投资建议/)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: '变动提醒' })).toBeTruthy());
  });

  it('explains when there is no previous trading day yet', async () => {
    renderPage(<ChangesBell />, {
      replies: replies({ status: 'no_baseline', items: {}, reason: '尚无上一交易日的报告，下一个交易日起显示变动。' }),
    });
    fireEvent.click(await screen.findByRole('button', { name: '变动提醒' }));
    expect(await screen.findByText(/下一个交易日起显示变动/)).toBeTruthy();
  });
});

describe('watchlist card', () => {
  it('shows the change against the previous trading day with sign and colour', async () => {
    renderPage(<Watchlist />, { replies: replies() });
    expect(await screen.findAllByText('较上一交易日（2026-11-04）', {}, { timeout: 3000 })).toHaveLength(2);
    expect(screen.getByText('+4.40').className).toContain('text-rise');
    expect(screen.getByText('-0.90').className).toContain('text-fall');
  });
});
