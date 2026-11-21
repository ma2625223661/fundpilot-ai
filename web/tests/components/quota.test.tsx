// Daily and monthly AI call limits (issue #5): the administrator form and the
// wording users see. Counts come from the backend; nothing is worked out here.
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { AdminSubscriptionsCard } from '@/app/settings/AdminSubscriptionsCard';
import { quotaBlock, quotaText, readQuota } from '@/lib/quota';
import { baseReplies, renderPage, requests } from './harness';

const member = (call_quota: Record<string, unknown>) => ({
  id: 'u1',
  username: 'reader',
  role: 'member',
  disabled: false,
  created_at: 1762300000,
  ai_subscription: { status: 'active', credits_remaining: 10, expires_at: '2026-12-31T00:00:00+00:00', unlocked_count: 0, call_quota },
});

const configured = {
  configured: true, unlimited: false, daily_limit: 3, monthly_limit: 60, daily_used: 1, monthly_used: 12,
  daily_remaining: 2, monthly_remaining: 48, can_call: true, day: '2026-11-21', month: '2026-11',
};

describe('call limit wording', () => {
  it('names both remaining counts and why a call cannot start', () => {
    expect(quotaText(readQuota(configured))).toBe('今日剩余 2 次，本月剩余 48 次');
    expect(quotaBlock(readQuota(configured))).toBe('');
    expect(quotaBlock(readQuota({ ...configured, daily_remaining: 0, can_call: false }))).toContain('今日调用次数已用完（今日剩余 0 次，本月剩余 48 次）');
    expect(quotaBlock(readQuota({ ...configured, monthly_remaining: 0, can_call: false }))).toContain('本月调用次数已用完');
    expect(quotaBlock(readQuota({ configured: false, can_call: false }))).toContain('管理员尚未设置');
    expect(quotaText(readQuota({ unlimited: true, configured: true }))).toBe('管理员调用不限次数');
  });
});

describe('administrator call limits', () => {
  it('shows the saved limits and usage, and saves both numbers as one change', async () => {
    renderPage(<AdminSubscriptionsCard />, {
      replies: baseReplies({
        '/api/admin/users': { items: [member(configured)] },
        '/api/admin/ai-subscription': { subscription: {}, items: [] },
      }),
    });
    expect(await screen.findByText(/当前：每日 3 次、每月 60 次；今日已用 1 次，本月已用 12 次/)).toBeTruthy();
    expect(screen.getByText('AI 调用：今日 1/3 次 · 本月 12/60 次')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存调用次数' }));
    await waitFor(() => expect(requests().some(item => item.path === '/api/admin/ai-subscription')).toBe(true));
    const sent = requests().find(item => item.path === '/api/admin/ai-subscription')?.body as Record<string, unknown>;
    expect(sent).toMatchObject({ user_id: 'u1', action: 'limits', daily_limit: 3, monthly_limit: 60 });
    expect(typeof sent.request_id).toBe('string');
    expect(await screen.findByText('AI 调用次数已保存，立即生效。')).toBeTruthy();
  });

  it('tells the administrator when a user has no limits yet', async () => {
    renderPage(<AdminSubscriptionsCard />, {
      replies: baseReplies({ '/api/admin/users': { items: [member({ configured: false, can_call: false })] } }),
    });
    expect(await screen.findByText(/reader 尚未设置调用次数，暂不能自行发起 AI 研究/)).toBeTruthy();
    expect(screen.getByText('AI 调用次数未设置，不能自行发起')).toBeTruthy();
  });
});
