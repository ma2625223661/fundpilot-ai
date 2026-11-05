// Replaces the markup checks on dist/index.html settings (test_index_markup,
// test_ai_cost_frontend, test_cloud_frontend, test_sector_frontend).
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { SettingsView } from '@/app/views/SettingsView';
import { baseReplies, renderPage, session } from './harness';

describe('settings page', () => {
  it('offers only the two A-share sessions and never the retired 09:10 / 14:30 times', async () => {
    const { container } = renderPage(<SettingsView />);
    await screen.findByText('AI 研究与执行计划');
    const text = container.textContent ?? '';
    expect(text).toContain('09:20');
    expect(text).toContain('14:50');
    expect(text).toContain('开盘前 10 分钟');
    expect(text).toContain('收盘前 10 分钟');
    expect(text).not.toMatch(/09:10|14:30/);
  });

  it('labels both reasoning depths with their credit cost', async () => {
    renderPage(<SettingsView />);
    await screen.findByText('AI 研究与执行计划');
    expect(screen.getByText('极高推理（1.5 点 / 份）')).toBeTruthy();
    expect(screen.getByText(/中度推理每份 1 点、极高推理每份 1.5 点/)).toBeTruthy();
  });

  it('guards the daily budget with bounded number fields and explains the multipliers', async () => {
    const { container } = renderPage(<SettingsView />);
    await screen.findByText('AI 研究与执行计划');
    for (const id of ['aiDailyRequestLimit', 'aiDailyTokenLimit']) expect(container.querySelector('#' + id)).toBeTruthy();
    expect(screen.getAllByLabelText('复用未变化的有效解读').length).toBeGreaterThan(0);
    expect(container.textContent).toContain('中度按 1.0 倍、极高按 1.5 倍');
  });

  it('shows the free data sources and never asks for a paid data token', async () => {
    const { container } = renderPage(<SettingsView />);
    await screen.findByText('BaoStock 数据连接');
    expect(container.textContent).toContain('中证官方成分名单 + 腾讯公司行情 + 东方财富财务');
    expect(screen.getByRole('button', { name: /检查多源连接/ })).toBeTruthy();
    expect(container.querySelector('#dataToken')).toBeNull();
    expect(container.textContent).not.toMatch(/Token 购买|输入数据 Token/);
  });

  it('keeps public settings read-only for someone who may not manage them', async () => {
    renderPage(<SettingsView />, {
      session: session({ isAdmin: false, access: { scope: 'cloud', can_manage_settings: false, lan_urls: [] } }),
      replies: baseReplies(),
    });
    await screen.findByText('AI 研究与执行计划');
    expect(screen.getByText(/公共研究报告与模型设置由管理员维护/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /保存研究设置/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText('用户订阅与额度')).toBeNull();
  });

  it('offers only private LAN addresses on this port for phone access', async () => {
    const port = location.port;
    renderPage(<SettingsView />, {
      session: session({
        user: null,
        cloud: false,
        isAdmin: true,
        access: {
          scope: 'same_network',
          can_manage_settings: true,
          lan_urls: [`http://192.168.1.8:${port}/index.html`, `http://8.8.8.8:${port}/index.html`, `http://10.0.0.2:${port}/other`],
        },
      }),
    });
    const card = (await screen.findByText('手机访问网址')).closest('[id="mobileAccess"]') as HTMLElement;
    const field = within(card).getByLabelText('手机访问网址（局域网）') as HTMLInputElement;
    expect(field.value).toBe(`http://192.168.1.8:${port}/index.html`);
    expect(card.textContent).not.toContain('8.8.8.8');
  });
});
