// CSV export of the listed sector rows.
import { sectorResearch } from '@/lib/research';
import { GROUP_LABELS, finite, num, pct, stamp } from '@/lib/format';
import { type Report, type Sector } from '@/lib/report';
import { downloadCsv, toCsv } from '@/lib/csv';
import { leadSample } from '@/app/research/board/lead-sample';

/**
 * The listed rows (current filter and order) as a spreadsheet, using the same
 * texts as the table. The first line carries the report time and the score note.
 */
export function exportSectors(report: Report, sectors: Sector[]) {
  const historical = report.report_stale === true;
  const part = (value: unknown, signed = false) => (finite(value) ? (signed && value > 0 ? '+' : '') + num(value) : '待评估');
  const rows: unknown[][] = [
    [`报告时间 ${stamp(report.as_of)}${historical ? '（历史快照）' : ''}；研究分不代表收益概率，不构成投资建议。`],
    ['板块', '分类', '涨跌幅', '研究分', '分制', '档位', '基本面 / 40', '走势 / 30', '事件 ±30', '领涨样本', '行情风险', '环境风险 / 100', '行情时间'],
  ];
  for (const sector of sectors) {
    const data = sectorResearch.sectorDataPresentation(sector, { historical });
    const view = sectorResearch.companyScoreView(sector);
    const parts = sector.score_breakdown || {};
    const lead = leadSample(report, sector);
    const risk = sector.market_risk || {};
    rows.push([
      sector.title,
      GROUP_LABELS[sector.group] || sector.group,
      data.changeText,
      data.scoreText,
      data.scoreUnit,
      view?.label ?? '',
      view ? part(parts.fundamentals?.points) : '—',
      view ? part(parts.trend?.points) : '—',
      view ? part(parts.catalysts?.observed_adjustment, true) : '—',
      lead ? `${lead.name} ${pct(lead.change)}` : '—',
      data.riskText,
      finite(risk.score) ? num(risk.score, 0) : '—',
      stamp(sector.as_of),
    ]);
  }
  const day = String(report.as_of || '').slice(0, 10).replace(/-/g, '') || 'report';
  downloadCsv(`fundpilot-板块-${day}.csv`, toCsv(rows));
}
