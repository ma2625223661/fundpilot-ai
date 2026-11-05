// Replaces the markup checks on dist/index.html and dist/login.html for the
// dashboard, events, history and login (test_index_markup, test_event_frontend,
// test_research_review, test_sector_frontend), plus the CLAUDE.md data rules.
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { LoginApp } from '@/app/LoginApp';
import { DashView } from '@/app/views/DashView';
import { HistoryView } from '@/app/views/HistoryView';
import { Change, SourceLink } from '@/components/research/common';
import { baseReplies, renderPage, report, sector } from './harness';

describe('dashboard', () => {
  it('renders the sector workspace only, with no retired fund wording', async () => {
    const { container } = renderPage(<DashView />);
    await screen.findByText('板块机会总览');
    expect(container.textContent).not.toMatch(/基金|净值|持仓/);
  });

  it('shows changes with their sign and A-share colours, and missing scores as unscored, never 0', async () => {
    const value = report([
      sector(),
      sector({ id: 'liquor', title: '白酒', score: 41.1, change_pct: -0.8, quote: { change_pct: -0.8 } }),
      sector({ id: 'empty', title: '待补方向', score: null, change_pct: null, status: 'missing', quote: {} }),
    ]);
    const { container } = renderPage(<DashView />, { replies: baseReplies({}, value) });
    await screen.findByText('板块机会总览');
    const rise = (await screen.findAllByText('+1.25%'))[0];
    expect(rise.className).toContain('text-rise');
    const fall = screen.getAllByText('-0.80%')[0];
    expect(fall.className).toContain('text-fall');
    // An unscored direction is listed only after it is selected, and then as unscored.
    expect(container.textContent).not.toMatch(/待补方向[^]*?\b0\.00\b/);
  });

  it('explains the event colours in A-share terms and that impact scores are not probabilities', async () => {
    const { container } = renderPage(<DashView />);
    await screen.findByText('重要事件 · 影响排序');
    expect(container.textContent).toContain('利好为红色正分，利空为绿色负分');
    expect(container.textContent).toMatch(/影响分不是涨跌概率/);
  });

  it('keeps the "not a return probability / not investment advice" note next to scores', async () => {
    const { container } = renderPage(<DashView />);
    await screen.findByText('板块机会总览');
    expect(container.textContent).toContain('不代表收益概率，不构成投资建议');
  });
});

describe('history', () => {
  it('places the five-day review before the saved reports and confirms before clearing', async () => {
    const { container } = renderPage(<HistoryView />);
    await screen.findByText('历史研究报告');
    const text = container.textContent ?? '';
    expect(text.indexOf('AI 自动化复盘')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('AI 自动化复盘')).toBeLessThan(text.indexOf('历史研究报告'));
    // Clearing records asks first; nothing is removed until the dialog is confirmed.
    await waitFor(() => expect((screen.getByRole('button', { name: /清空板块记录/ }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: /清空板块记录/ }));
    expect(await screen.findByText('清空全部板块研究记录？')).toBeTruthy();
    expect(screen.getByRole('button', { name: '保留记录' })).toBeTruthy();
  });
});

describe('login', () => {
  it('accepts a plain handle or an email address as the username', async () => {
    const replies = baseReplies({
      '/api/auth/status': { needs_setup: false, setup_token_required: false, setup_available: true, registration_open: true, phone_auth: {} },
      '/api/auth/captcha': { captcha_id: 'c', image: '' },
    });
    (globalThis as unknown as { __replies: unknown }).__replies = replies;
    render(
      <TooltipProvider>
        <LoginApp />
      </TooltipProvider>,
    );
    const input = (await screen.findByLabelText('用户名')) as HTMLInputElement;
    expect(input.maxLength).toBe(64);
    // Browsers compile the pattern attribute with the v flag and anchor it.
    const pattern = new RegExp('^(?:' + input.getAttribute('pattern') + ')$', 'v');
    for (const ok of ['owner', 'abc_123', 'ma2625223661@gmail.com', 'first.last+tag@mail.example.cn']) expect(pattern.test(ok), ok).toBe(true);
    for (const bad of ['ab', 'has space', 'name@host', '@gmail.com', 'a@b.c']) expect(pattern.test(bad), bad).toBe(false);
  });

  it('always asks for the six-character image challenge on password login', async () => {
    (globalThis as unknown as { __replies: unknown }).__replies = baseReplies({
      '/api/auth/status': { needs_setup: false, setup_token_required: false, setup_available: true, registration_open: false, phone_auth: {} },
      '/api/auth/captcha': { captcha_id: 'c', image: '' },
    });
    render(
      <TooltipProvider>
        <LoginApp />
      </TooltipProvider>,
    );
    const captcha = (await screen.findByLabelText('图片验证码')) as HTMLInputElement;
    expect(captcha.required).toBe(true);
    expect(captcha.getAttribute('pattern')).toBe('[A-Za-z0-9]{6}');
    await waitFor(() => expect(screen.queryByText('还没有账号？注册')).toBeNull());
  });
});

describe('shared rules', () => {
  it('links sources only over https, in a new tab without a referrer', () => {
    render(
      <>
        <SourceLink url="https://example.com/a">安全来源</SourceLink>
        <SourceLink url="http://example.com/b">明文来源</SourceLink>
        <SourceLink url="javascript:alert(1)">脚本</SourceLink>
      </>,
    );
    const link = screen.getByText('安全来源').closest('a')!;
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.getByText('明文来源').closest('a')).toBeNull();
    expect(screen.getByText('脚本').closest('a')).toBeNull();
  });

  it('prints the sign with every change and never colours a missing value', () => {
    render(
      <>
        <Change value={2} />
        <Change value={-2} />
        <Change value={null} />
        <Change value={3} historical />
      </>,
    );
    expect(screen.getByText('+2.00%').className).toContain('text-rise');
    expect(screen.getByText('-2.00%').className).toContain('text-fall');
    expect(screen.getByText('*****').className).toContain('text-muted-foreground');
    expect(screen.getByText('+3.00%').className).toContain('text-muted-foreground');
  });
});
