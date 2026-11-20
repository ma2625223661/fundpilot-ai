// The "data and evidence" page (the old #data view): source health, every
// source record with its data date, collection limits and verified events.
import { useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { BulletList, Disclosure, SourceLink } from '@/components/research/common';
import { PageHeader, StatTile } from '@/components/page-header';
import { EventList } from '@/app/research/Events';
import { useResearch } from '@/app/research/ResearchContext';
import { sectorResearch } from '@/lib/research';
import { finite, stamp } from '@/lib/format';
import type { Source } from '@/lib/report';
import { cn } from '@/lib/utils';

const FILTERS: Record<string, string> = {
  all: '全部状态',
  attention: '未取得或过时',
  partial: '部分获取',
  ok: '已获取',
  unknown: '待确认',
};
const SUMMARY: [string, string][] = [
  ['total', '来源记录'],
  ['ok', '已获取'],
  ['partial', '部分获取'],
  ['attention', '未取得或过时'],
  ['unknown', '待确认'],
];
const STATUS: Record<string, string> = {
  ok: '已获取',
  partial: '部分获取',
  error: '未取得',
  missing: '未取得',
  unavailable: '未取得',
  stale: '已过时',
  unknown: '待确认',
};
const ISSUES: Record<string, string> = {
  timeout: '采集超时',
  http: '接口请求失败',
  connection: '连接或返回格式异常',
  coverage: '数据日期或历史覆盖不足',
  other: '其他不完整记录',
};
const PAGE = 12;
const SUMMARY_TONE: Record<string, string | undefined> = {
  ok: 'text-tier-optimistic',
  partial: 'text-warning',
  attention: 'text-destructive',
  unknown: 'text-muted-foreground',
};
const STATE_BORDER: Record<string, string> = {
  ok: 'border-l-tier-optimistic',
  partial: 'border-l-warning',
  attention: 'border-l-destructive',
  unknown: 'border-l-border',
};

export function DataView() {
  const { report, refresh, accountMode, session, state } = useResearch();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE);
  const canRefresh = !accountMode || session.isAdmin;

  const header = (
    <PageHeader
      title="数据依据"
      description="先看采集状态，再核对数据日期，最后追溯原始来源。"
      actions={
        canRefresh && (
          <Button variant="outline" disabled={state.status === 'running'} onClick={() => void refresh()}>
            <RefreshCw aria-hidden="true" />
            更新板块数据
          </Button>
        )
      }
    />
  );
  if (!report)
    return (
      <>
        {header}
        <Skeleton className="h-96" />
      </>
    );

  const sources: Source[] = report.snapshot.sources;
  const stats = sectorResearch.sourceOverview(sources);
  const total = report.sector_analysis.length;
  const scored = report.sector_analysis.filter((s: { score: unknown }) => finite(s.score)).length;
  const issues = (Object.entries(sectorResearch.sourceIssueOverview(sources)) as [string, number][]).filter(([, count]) => count > 0);
  const records: Source[] = sectorResearch.selectSourceRecords(sources, query, filter);
  const events = report.event_analysis.events;
  const warnings: string[] = report.snapshot.warnings;

  return (
    <>
      {header}
      <Card aria-labelledby="dataSourcesHeading">
        <CardHeader>
          <CardTitle>
            <h2 id="dataSourcesHeading" className="text-lg font-semibold">
              数据来源状态
            </h2>
          </CardTitle>
          <CardDescription className="tabular-nums">快照时间 {stamp(report.snapshot.as_of || report.as_of)}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label="来源记录采集概览">
            {SUMMARY.map(([key, label]) => (
              <StatTile key={key} value={stats[key]} label={label} tone={SUMMARY_TONE[key]} />
            ))}
          </dl>
          <p className="text-sm text-pretty tabular-nums">
            本快照覆盖 {total} 个板块，其中 {scored} 个已有评分、{total - scored} 个暂未评分。来源记录数包含同一板块的多次请求与备用接口，不等于板块数量。
          </p>
          <p className="text-sm text-pretty tabular-nums">
            {issues.length
              ? '异常与不完整记录：' + issues.map(([key, count]) => ISSUES[key] + ' ' + count + ' 条').join('；') + '。下方展开“查看说明”可核对原始原因。'
              : '本次来源记录没有未取得、过时或部分获取的记录。'}
          </p>
          <p className="text-xs text-muted-foreground text-pretty">
            “已获取”表示取数成功。是否适合当前研究，还需核对每条记录的数据日期；获取时间不等于数据日期。下方按来源记录计数。
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
              <Input
                type="search"
                aria-label="搜索数据来源"
                placeholder="搜索来源、指标或异常说明…"
                maxLength={100}
                className="pl-8"
                value={query}
                onChange={event => {
                  setQuery(event.target.value);
                  setPageSize(PAGE);
                }}
              />
            </div>
            <Select
              value={filter}
              onValueChange={value => {
                setFilter(String(value));
                setPageSize(PAGE);
              }}
            >
              <SelectTrigger className="sm:w-44" aria-label="筛选来源状态">
                <SelectValue>{(value: string) => FILTERS[value]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {Object.entries(FILTERS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p role="status" className="text-sm text-muted-foreground tabular-nums">
            符合条件 {records.length} 条 · 已展示 {Math.min(pageSize, records.length)} 条
          </p>
          <div className="flex flex-col gap-2">
            {records.slice(0, pageSize).map((s, index) => (
              <article
                key={s.id + index}
                className={cn('flex flex-col gap-1 rounded-lg border border-l-4 border-border bg-card px-3 py-2', STATE_BORDER[sectorResearch.sourceRecordState(s)])}
              >
                <div className="grid items-center gap-x-4 gap-y-1 sm:grid-cols-12">
                  <div className="min-w-0 sm:col-span-7">
                    <SourceLink url={s.url} className="font-medium">
                      {s.name || s.id || '数据源'}
                    </SourceLink>
                  </div>
                  {/* Data date and fetch time are different things, so each keeps its own label. */}
                  <span className="flex flex-col text-xs text-muted-foreground tabular-nums sm:col-span-3">
                    <span>数据日期 {s.as_of ? stamp(s.as_of) : '未提供'}</span>
                    {s.fetched_at && <span>获取时间 {stamp(s.fetched_at)}</span>}
                  </span>
                  <span className="sm:col-span-2 sm:text-right">
                    <Badge variant={sectorResearch.sourceRecordState(s) === 'attention' ? 'destructive' : 'outline'}>{STATUS[s.status] || '待确认'}</Badge>
                  </span>
                </div>
                {/* Only records with an explanation to read keep a collapsible. */}
                {s.error && (
                  <Disclosure title="查看说明">
                    <p className="text-pretty">{s.error}</p>
                  </Disclosure>
                )}
              </article>
            ))}
            {!records.length && (
              <div className="flex flex-col items-start gap-2">
                <p className="text-sm text-muted-foreground">没有符合条件的来源记录，可更换搜索词或状态。</p>
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery('');
                    setFilter('all');
                  }}
                >
                  清除筛选条件
                </Button>
              </div>
            )}
          </div>
          {pageSize < records.length && (
            <Button variant="outline" className="self-start" onClick={() => setPageSize(pageSize + PAGE)}>
              再显示 {Math.min(PAGE, records.length - pageSize)} 条来源
            </Button>
          )}
          {warnings.length > 0 && (
            <Disclosure title={`数据限制与采集说明 · ${warnings.length} 项`}>
              <BulletList items={warnings} />
            </Disclosure>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">重要公告与政策事件</h2>
            <Badge variant="secondary" className="tabular-nums">
              {events.length} 项
            </Badge>
          </CardTitle>
          <CardDescription className="text-pretty">
            这里展示已评估的中等及以上影响事件。没有展示事件时，请结合首页的评估状态判断，不能理解为市场没有风险。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EventList events={events} emptyText="当前没有完成评估的中等及以上重要事件。" />
        </CardContent>
      </Card>
    </>
  );
}
