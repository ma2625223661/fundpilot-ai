// Opt-in system notifications for change alerts: permission only on request,
// one notification per new change per day, only while the page is hidden, and
// a clear reason when the browser cannot show them.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { ChangesBell } from '@/app/research/Changes';
import { baseReplies, renderPage, report, sector } from './harness';

const block = {
  status: 'ok',
  baseline_date: '2026-11-04',
  items: { semiconductor: { score_before: 48, score_now: 52.4, score_delta: 4.4, flags: ['新增特大风险'], notable: true } },
};
const replies = () =>
  baseReplies({ '/api/me/watchlist': { items: ['semiconductor'] } }, report([sector()], { sector_changes: block }));

const shown: { title: string; options: NotificationOptions }[] = [];
class FakeNotification {
  static permission: NotificationPermission = 'default';
  static requestPermission = vi.fn(async () => {
    FakeNotification.permission = 'granted';
    return 'granted' as NotificationPermission;
  });
  onclick: (() => void) | null = null;
  constructor(title: string, options: NotificationOptions) {
    shown.push({ title, options });
  }
  close() {}
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
}

beforeEach(() => {
  shown.length = 0;
  FakeNotification.permission = 'default';
  FakeNotification.requestPermission.mockClear();
  Object.defineProperty(window, 'Notification', { value: FakeNotification, configurable: true, writable: true });
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
  for (const key of ['fundpilot_notify_v1', 'fundpilot_notify_sent_v1', 'fundpilot_changes_seen_v1']) localStorage.removeItem(key);
  setHidden(false);
});

afterEach(() => {
  setHidden(false);
});

describe('change notifications', () => {
  it('asks for permission only when switched on and remembers the choice', async () => {
    renderPage(<ChangesBell />, { replies: replies() });
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: /变动提醒/ }));
    fireEvent.click(await screen.findByRole('switch', { name: '后台时发系统通知' }));
    await waitFor(() => expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem('fundpilot_notify_v1')).toBe('1');
  });

  it('notifies once for a change that arrives while the page is hidden', async () => {
    FakeNotification.permission = 'granted';
    localStorage.setItem('fundpilot_notify_v1', '1');
    setHidden(true);
    renderPage(<ChangesBell />, { replies: replies() });
    await waitFor(() => expect(shown).toHaveLength(1));
    expect(shown[0].title).toBe('FundPilot 变动提醒');
    expect(shown[0].options.body).toContain('半导体：研究分 +4.40，新增特大风险');
    expect(shown[0].options.body).toContain('不构成投资建议');
    // The next report with the same change does not notify again.
    cleanup();
    renderPage(<ChangesBell />, { replies: replies() });
    await screen.findByRole('button', { name: /变动提醒/ });
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(shown).toHaveLength(1);
  });

  it('does not notify while the page is in front, where the bell already shows it', async () => {
    FakeNotification.permission = 'granted';
    localStorage.setItem('fundpilot_notify_v1', '1');
    renderPage(<ChangesBell />, { replies: replies() });
    await screen.findByRole('button', { name: /变动提醒，有 1 条未读/ });
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(shown).toHaveLength(0);
  });

  it('explains why it cannot work on a plain-http LAN address', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
    renderPage(<ChangesBell />, { replies: replies() });
    fireEvent.click(await screen.findByRole('button', { name: /变动提醒/ }));
    expect(await screen.findByText(/系统通知需要 HTTPS/)).toBeTruthy();
    expect((screen.getByRole('switch', { name: '后台时发系统通知' }) as HTMLElement).getAttribute('aria-disabled') ?? screen.getByRole('switch').hasAttribute('disabled')).toBeTruthy();
  });
});
