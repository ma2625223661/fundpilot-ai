// Long-wave page (issue #7): verified official CPI and credit releases show with
// their statistical period, publication date and sign; the long-wave phase stays
// unverified while a group of evidence is missing.
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { CycleView } from '@/app/views/CycleView';
import { baseReplies, renderPage } from './harness';

const missing = (id: string, title: string, detail: string) => ({ id, title, status: 'missing', value: null, detail });

const cycle = {
  version: 'long_wave_workspace_v1', access: true, status: 'ready', as_of: '2026-11-21T10:00:00+08:00',
  phase: 'unverified', phase_label: '长期阶段待验证',
  phase_detail: '已核验 4/5 组证据，缺少：生产率与投资。证据不足 5 组时不判定康波阶段，短期景气与资金数据只描述当前环境。',
  phase_basis: [], method: '以长期主题提出研究命题。', coverage: 4, coverage_total: 5, current_scenario: 'unverified',
  scenarios: [], themes: [], scarcity_sectors: [], scarcity_summary: {}, references: [],
  signals: [
    missing('demand', '景气与订单', '等待有效的官方PMI及发布时间核验。'),
    missing('funding', '短端资金', '等待近期有效的人民币隔夜资金利率。'),
    {
      id: 'inflation', title: '通胀与实际利率', status: 'ready', value: 0.7, unit: '% · CPI 同比', signed: true,
      detail: 'PPI 同比 -1.2%，工业生产者购进价格同比 -2.0%（2026 年 10 月）。', period: '2026-10',
      as_of: '2026-11-09T09:30:00+08:00', url: 'https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html',
      related: [{ title: 'PPI 公告', url: 'https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html' }],
      scope: '统计期 2026 年 10 月，发布于 2026-11-09；全国月度同比，不是长期通胀趋势。',
    },
    {
      id: 'credit', title: '信用与债务', status: 'ready', value: 7.2, unit: '% · 社融存量同比', signed: true,
      detail: '2026 年 10 月末社会融资规模存量 469.16 万亿元。', period: '2026-10', as_of: '2026-11-13T00:00:00+08:00',
      url: 'https://www.pbc.gov.cn/diaochatongjisi/116219/116225/2026111317040354319/index.html', scope: '月末存量增速。',
    },
    missing('productivity', '生产率与投资', '待接入：生产率、研发与资本开支尚无可核验的官方月度口径，不用估计值填补。'),
  ],
};

describe('long-wave page', () => {
  it('shows verified official releases with period, date and sign, and keeps the phase unverified', async () => {
    renderPage(<CycleView />, { replies: baseReplies({ '/api/me/cycle': cycle }) });
    expect(await screen.findByText('通胀与实际利率')).toBeTruthy();
    expect(screen.getByText('+0.7')).toBeTruthy();
    expect(screen.getByText('+7.2')).toBeTruthy();
    expect(screen.getByText('统计期 2026-10 · 发布 2026-11-09')).toBeTruthy();
    expect(screen.getByRole('link', { name: /PPI 公告/ })).toBeTruthy();
    expect(screen.getByText('长期阶段待验证')).toBeTruthy();
    expect(screen.getByText(/缺少：生产率与投资/)).toBeTruthy();
    expect(screen.getByText('还有 1 组数据待补齐 · 查看缺口')).toBeTruthy();
  });
});
