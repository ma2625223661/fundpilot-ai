// One status vocabulary for the research service, and the historical-snapshot
// notice living inside the status strip instead of a separate banner.
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { researchStatus } from '@/app/research/research-status';
import { DashView } from '@/app/views/DashView';
import { baseReplies, renderPage, report, sector } from './harness';

describe('research status vocabulary', () => {
  it('puts a failure first, then an update, then a historical snapshot', () => {
    expect(researchStatus({ status: 'running', connection_error: true }, true)).toMatchObject({ tone: 'error', label: '研究服务未连接' });
    expect(researchStatus({ status: 'running' }, true)).toMatchObject({ tone: 'running', label: '正在更新板块研究' });
    expect(researchStatus({ status: 'ready' }, true)).toMatchObject({ tone: 'stale', label: '显示历史快照', text: 'text-warning' });
    expect(researchStatus({ status: 'ready' }, false)).toMatchObject({ tone: 'ready', label: '研究已是最新' });
  });
});

describe('status strip', () => {
  it('shows a historical snapshot once, inside the strip, with the report time', async () => {
    const value = report([sector()], { report_stale: true });
    renderPage(<DashView />, {
      replies: baseReplies({ '/api/auto/report': { report: value, report_version: 'v1', report_stale: true } }, value),
    });
    const strip = await screen.findByLabelText('研究状态与更新计划');
    expect(await within(strip).findByText(/当前为历史快照/)).toBeTruthy();
    expect(within(strip).getByText('显示历史快照')).toBeTruthy();
    expect(strip.textContent).toContain('报告时间');
    // No second banner repeating the same notice elsewhere on the page.
    expect(screen.getAllByText(/当前为历史快照/)).toHaveLength(1);
  });
});
