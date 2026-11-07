// Port of renderCompanyEvidence: the representative company samples behind a
// sector, with their quote date, verification checks, membership basis and
// disclosed financials. Missing values stay "—" and are labelled as such.
import { Check, CircleDashed, Settings } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Disclosure, Eyebrow, SourceLink } from '@/components/research/common';
import { goTo } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { CURRENCY, DIRECTION_CLASS, MAX_COMPANY_SAMPLES, compactDate, direction, finite, num, pct } from '@/lib/format';
import { sourceMap, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

const CHECKS: [string, string][] = [
  ['业务或成分归属', '归属'],
  ['有效报价', '行情'],
  ['披露日财务', '财务'],
  ['近期61日走势', '61日走势'],
];
const STAGES: [string, string][] = [
  ['membership_count', '归属池'],
  ['quoted_count', '有效报价'],
  ['candidate_count', '本轮候选'],
  ['ready_count', '数据完整'],
  ['selected_count', '最终选入'],
];

function Cell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col" title={value === '—' ? '本项数据尚未取得' : undefined}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <b className={cn('font-medium tabular-nums', tone)}>{value}</b>
    </div>
  );
}

function CompanyCard({ row, report, microcap }: { row: Row; report: Report; microcap: boolean }) {
  const sources = sourceMap(report);
  const quoteLabel = row.quote.data_kind === 'daily_close' || !row.quote.is_intraday ? '收盘' : '行情';
  const changeTone = report.report_stale ? 'unknown' : direction(row.quote.pct_chg);
  const membership = ['l1_name', 'l2_name', 'l3_name'].map(k => row.membership_evidence[k]).filter(Boolean);
  const f = row.financials || {};
  const financialVerified = row.sample_checks['披露日财务'] === true;
  const refs = (row.source_ids as string[]).map(id => sources.get(id)).filter(Boolean);
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <b className="font-medium">{row.name}</b>
          <small className="text-xs text-muted-foreground tabular-nums">{row.ts_code}</small>
        </div>
        <Badge variant={row.leader_verified ? 'default' : 'outline'}>
          {microcap ? '小市值代表样本' : row.leader_verified ? '已核验业务龙头' : '行业代表样本'}
        </Badge>
      </div>
      {row.industry && <p className="text-xs text-muted-foreground">{row.industry}</p>}
      <p className="text-xs text-muted-foreground tabular-nums">
        {report.report_stale ? '历史' : ''}
        {quoteLabel} · {compactDate(row.quote.trade_date || row.as_of)}
      </p>
      <div className="grid grid-cols-2 gap-2">
        <Cell
          label={row.quote.close_kind === 'forward_adjusted_close' ? '前复权收盘参考值' : '收盘价'}
          value={finite(row.quote.close) ? num(row.quote.close) + ' ' + (CURRENCY[row.quote.currency] || '（币种未核验）') : '—'}
        />
        <Cell label="日涨跌" value={finite(row.quote.pct_chg) ? pct(row.quote.pct_chg) : '—'} tone={DIRECTION_CLASS[changeTone]} />
        <Cell label="换手率" value={finite(row.market_metrics.turnover_rate) ? num(row.market_metrics.turnover_rate) + '%' : '—'} />
        <Cell label="量比" value={finite(row.market_metrics.volume_ratio) ? num(row.market_metrics.volume_ratio) : '—'} />
      </div>
      <div className="flex flex-wrap gap-1" aria-label="数据核验结果">
        {CHECKS.map(([key, label]) => {
          const passed = row.sample_checks[key] === true;
          const known = typeof row.sample_checks[key] === 'boolean';
          const title = key + '：' + (passed ? '已通过' : known ? '待补齐' : '尚未核验');
          return (
            <Badge key={key} variant={passed ? 'secondary' : 'outline'} title={title} aria-label={title}>
              {passed ? <Check aria-hidden="true" /> : <CircleDashed aria-hidden="true" />}
              {label}
            </Badge>
          );
        })}
      </div>
      {!row.leader_verified && (
        <p className="text-xs text-warning text-pretty">
          {microcap ? '有限小市值样本，不能代表全市场微盘股。' : '行业代表样本，业务龙头身份尚未核验。'}
        </p>
      )}
      <Disclosure title="归属与入选依据">
        <p>归属依据：{membership.length ? membership.join(' / ') : '尚未取得'}</p>
        {row.role && <p className="text-pretty">{row.role}</p>}
        {row.selection_basis && <p className="text-pretty">{row.selection_basis}</p>}
        {row.membership_evidence.snapshot_date && (
          <p className="tabular-nums">归属名单日期：{compactDate(row.membership_evidence.snapshot_date)}</p>
        )}
        {row.membership_evidence.published_date && (
          <p className="tabular-nums">归属证据发布：{compactDate(row.membership_evidence.published_date)}</p>
        )}
      </Disclosure>
      <Disclosure title={row.financials ? (financialVerified ? '已核验财务 · 查看报告期' : '财务数据 · 待核验') : '财务数据待取得'}>
        <p className="tabular-nums">
          报告期：{compactDate(f.end_date)} · 披露日期：{compactDate(f.ann_date)}
        </p>
        {row.financials && !financialVerified && <p className="text-warning">财务核验尚未通过，不能视为已核验业绩依据。</p>}
        <div className="grid grid-cols-2 gap-2">
          <Cell label="营收同比" value={finite(f.tr_yoy) ? pct(f.tr_yoy) : '—'} />
          <Cell label="净利润同比" value={finite(f.netprofit_yoy) ? pct(f.netprofit_yoy) : '—'} />
          <Cell label="ROE" value={finite(f.roe) ? num(f.roe) + '%' : '—'} />
          <Cell label="每股收益" value={finite(f.eps) ? num(f.eps) + ' ' + (CURRENCY[f.currency] || '（币种未核验）') : '—'} />
        </div>
        {f.currency_note && <p className="text-pretty">{f.currency_note}</p>}
        {row.financials_note && <p className="text-pretty">{row.financials_note}</p>}
      </Disclosure>
      {refs.length > 0 && (
        <Disclosure title={`查看数据来源 · ${refs.length} 项`}>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {refs.map(source => (
              <SourceLink key={source!.id} url={source!.url}>
                {source!.name || source!.id}
              </SourceLink>
            ))}
          </div>
        </Disclosure>
      )}
    </article>
  );
}

export function CompanyEvidence({ sector, report }: { sector: Sector; report: Report }) {
  const { dataConfig } = useResearch();
  const evidence = report.company_evidence;
  const rows: Row[] = evidence.sector_leaders[sector.id] || [];
  const microcap = sector.id === 'style_microcap';
  const selection = evidence.sample_selection?.[sector.id];
  const unconfigured = evidence.status === 'not_configured' && !dataConfig?.configured;
  const method = microcap
    ? [sector.custom_index?.scope, sector.custom_index?.method].filter(Boolean).join(' ')
    : evidence.selection_method;
  return (
    <section className="flex flex-col gap-3" aria-label="公司证据">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-col">
          <Eyebrow>公司证据</Eyebrow>
          <h4 className="font-semibold text-balance">{microcap ? '小市值优选研究样本' : '龙头与优选研究样本'}</h4>
        </div>
        <Badge variant="secondary" className="tabular-nums">
          {rows.length ? rows.length + ' 家研究样本' : '等待有效样本'}
        </Badge>
      </div>
      <p className="text-sm text-muted-foreground text-pretty">
        {microcap
          ? '在国证A股核验池内按市值从小到大选样，再核对财务与近期走势。有限样本表现不等同全市场微盘股。'
          : '核对归属、行情、财务与近期走势，再筛选研究对象。样本表现不等同整个板块。'}
      </p>
      {selection && (
        <>
          <dl className="grid grid-cols-3 gap-2 sm:grid-cols-5" aria-label="样本筛选概览">
            {STAGES.map(([key, label]) => (
              <div key={key} className="rounded-md bg-muted p-2">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="font-medium tabular-nums">
                  {finite(selection[key]) ? selection[key] : '—'}
                  <small className="ml-0.5 text-xs text-muted-foreground">家</small>
                </dd>
              </div>
            ))}
          </dl>
          {selection.pending.length > 0 && (
            <Disclosure title={`${selection.pending.length} 家候选待核验 · 查看缺口`}>
              {selection.pending.map((r: Row, index: number) => (
                <p key={index} className="text-pretty">
                  {r.name} {r.ts_code}：{r.reason}
                </p>
              ))}
            </Disclosure>
          )}
        </>
      )}
      {!rows.length ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-muted-foreground text-pretty">
            {unconfigured
              ? '等待连接 BaoStock 数据源，取得行业成分及财务数据后核对代表公司；当前不代表该板块没有龙头。'
              : '本份报告尚未取得该板块的有效公司样本。需继续核对行业归属与经营证据，不能据此判断该板块没有龙头。'}
          </p>
          {unconfigured && (
            <Button variant="outline" onClick={() => goTo('researchDataSettings')}>
              <Settings aria-hidden="true" />
              检查 BaoStock 连接
            </Button>
          )}
        </div>
      ) : (
        <>
          <Disclosure title={`查看筛选方法 · 最多 ${MAX_COMPANY_SAMPLES} 家`}>
            <p className="text-pretty">
              {method || '按已取得的行业归属和交易数据选择代表样本；业务龙头身份须有经营证据支持。'}
            </p>
          </Disclosure>
          <div className="grid gap-3 md:grid-cols-2">
            {rows.map(row => (
              <CompanyCard key={row.ts_code} row={row} report={report} microcap={microcap} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
