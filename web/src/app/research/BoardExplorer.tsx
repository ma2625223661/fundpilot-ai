// Port of renderBoards: category filter, search, sort, scarcity filter and the
// grouped sector list. Grouping, ordering and colours come from the old logic.
import { Fragment, useState } from 'react';
import { ArrowDown, ArrowUpDown, Diamond, Download, Info, Search, SearchX } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toggle } from '@/components/ui/toggle';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { IndicatorIcon } from '@/components/research/common';
import { ScarcityBadge } from '@/app/research/Scarcity';
import { useResearch } from '@/app/research/ResearchContext';
import { sectorResearch, sectorScarcity } from '@/lib/research';
import { DIRECTION_CLASS, GROUP_LABELS, direction, finite, num, pct, stamp, txt } from '@/lib/format';
import { TONE_BADGE, TONE_BORDER, TONE_TEXT, sectorEvents, sectorTone, type Report, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';
import { downloadCsv, toCsv } from '@/lib/csv';

type SortMode = 'score' | 'change' | 'name';
const SORT_LABELS: Record<SortMode, string> = { score: '同类研究分优先', change: '当日涨幅优先', name: '板块名称' };

const LEGEND: [string, string][] = [
  ['text-tier-optimistic', '≥65 乐观'],
  ['text-tier-neutral', '50～<65 中性'],
  ['text-tier-cautious', '30～<50 谨慎'],
  ['text-tier-avoid', '<30 规避'],
];

/** Sub-score as a short bar: points of its maximum; a missing part stays empty. */
function Part({ label, value, max, signed = false }: { label: string; value: number | null; max: number; signed?: boolean }) {
  const measured = finite(value);
  const width = measured ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <b
          className={cn(
            'font-medium tabular-nums',
            signed && measured && value > 0 && 'text-rise',
            signed && measured && value < 0 && 'text-fall',
            !measured && 'text-muted-foreground',
          )}
        >
          {measured ? (signed && value > 0 ? '+' : '') + num(value) : '待评估'}
          <span className="text-muted-foreground">{signed ? ' / ±' + max : ' / ' + max}</span>
        </b>
      </span>
      <span className="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <span
          className={cn('block h-full rounded-full', signed && measured && value < 0 ? 'bg-fall' : signed ? 'bg-rise' : 'bg-primary')}
          style={{ width: width + '%' }}
        />
      </span>
    </span>
  );
}

/**
 * The company sample with the largest change today, and how many samples rose or
 * fell (as quote centres show a sector's leading stock). Only picks and counts
 * the quotes the report already holds; nothing is recalculated.
 */
function leadSample(report: Report, sector: Sector) {
  const rows: Sector[] = report.company_evidence.sector_leaders[sector.id] || [];
  const quoted = rows.filter(row => finite(row.quote?.pct_chg));
  if (!quoted.length) return null;
  const top = quoted.reduce((best, row) => (row.quote.pct_chg > best.quote.pct_chg ? row : best));
  return {
    name: top.name as string,
    change: top.quote.pct_chg as number,
    date: String(top.quote.trade_date || top.as_of || '').slice(5, 10),
    up: quoted.filter(row => row.quote.pct_chg > 0).length,
    down: quoted.filter(row => row.quote.pct_chg < 0).length,
    total: rows.length,
  };
}

function LeadSample({ report, sector, className }: { report: Report; sector: Sector; className?: string }) {
  const lead = leadSample(report, sector);
  if (!lead) return <span className={cn('text-xs text-muted-foreground', className)}>—</span>;
  const tone = report.report_stale ? 'unknown' : direction(lead.change);
  return (
    <span className={cn('flex flex-col', className)}>
      <span className="flex items-baseline gap-1.5 whitespace-nowrap">
        <span className="max-w-24 truncate text-sm">{lead.name}</span>
        <span className={cn('text-sm font-medium tabular-nums', DIRECTION_CLASS[tone])}>{pct(lead.change)}</span>
      </span>
      <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
        {lead.up} 涨 · {lead.down} 跌 / {lead.total} 家{lead.date && ' · ' + lead.date}
      </span>
    </span>
  );
}

function SectorRow({ sector, report, active, onSelect }: { sector: Sector; report: Report; active: boolean; onSelect: () => void }) {
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, {
    historical,
    companyCount: (report.company_evidence.sector_leaders[sector.id] || []).length,
    eventCount: sectorEvents(report, sector.id).length,
  });
  const tone = sectorTone(sector, historical);
  const view = sectorResearch.companyScoreView(sector);
  const indicator = historical ? null : sectorResearch.sectorIndicator(sector);
  const risk = sector.market_risk || {};
  const changeTone = data.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
  const parts = sector.score_breakdown || {};
  return (
    <Button
      variant="ghost"
      aria-haspopup="dialog"
      aria-pressed={active}
      onClick={onSelect}
      className={cn(
        'h-auto w-full flex-col items-stretch gap-3 rounded-lg border border-l-4 border-border bg-card p-4 text-left whitespace-normal hover:bg-muted aria-pressed:bg-muted',
        TONE_BORDER[tone],
      )}
    >
      <span className="grid w-full grid-cols-2 items-center gap-x-4 gap-y-2 md:grid-cols-12">
        <span className="col-span-2 flex min-w-0 flex-col gap-1 md:col-span-5">
          <span className="flex flex-wrap items-center gap-2">
            <b className="text-base font-semibold">{sector.title}</b>
            <ScarcityBadge value={sector.scarcity} />
          </span>
          <small className="line-clamp-2 text-xs font-normal text-muted-foreground" title={data.subtitle}>
            {data.subtitle}
          </small>
        </span>
        <span className="flex flex-col md:col-span-2 md:items-end">
          <span className="text-xs font-normal text-muted-foreground">{data.changeLabel}</span>
          <span className={cn('text-lg font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>{data.changeText}</span>
        </span>
        <span className="flex flex-col items-end md:col-span-2">
          <span className="flex items-baseline gap-1">
            <b className={cn('text-2xl font-semibold tabular-nums', TONE_TEXT[tone])}>{data.scoreText}</b>
            <small className="text-xs font-normal text-muted-foreground">{data.scoreUnit}</small>
          </span>
          {view && <span className={cn('rounded-sm px-1.5 py-0.5 text-xs font-medium', TONE_BADGE[tone])}>{view.label}</span>}
        </span>
        <span className="col-span-2 flex flex-col gap-0.5 text-xs font-normal md:col-span-3 md:items-end" title={txt(risk.scope)}>
          <span className="flex items-center gap-1 text-foreground">
            {indicator && <IndicatorIcon indicator={indicator} />}
            行情 {data.riskText}
            {indicator ? ' · ' + indicator.label : ''}
          </span>
          {finite(risk.score) && (
            <span className="text-muted-foreground tabular-nums">
              环境 {txt(risk.level)} {num(risk.score, 0)}/100{risk.status !== 'complete' ? '（部分）' : ''}
            </span>
          )}
        </span>
      </span>
      {view && (
        <span className="grid w-full gap-x-6 gap-y-2 font-normal sm:grid-cols-3">
          <Part label="基本面" value={parts.fundamentals?.points ?? null} max={40} />
          <Part label="走势" value={parts.trend?.points ?? null} max={30} />
          <Part label="事件催化" value={parts.catalysts?.observed_adjustment ?? null} max={30} signed />
        </span>
      )}
      {leadSample(report, sector) && (
        <span className="flex items-center gap-2 text-xs font-normal">
          <span className="text-muted-foreground">领涨样本</span>
          <LeadSample report={report} sector={sector} className="flex-row items-baseline gap-2" />
        </span>
      )}
      {view?.gates && <span className="text-xs font-normal text-muted-foreground">{view.gates}</span>}
    </Button>
  );
}

/**
 * Everything needed to read the table, behind one button instead of lines of
 * text above it: what each score means, the columns, the grouping of this list
 * and the event status. The short disclaimer stays visible next to the table.
 */
function ScoreGuide({ report, sort, families, scarcity }: { report: Report; sort: SortMode; families: { id: string; label: string; note: string }[]; scarcity: boolean }) {
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" />}>
        <Info aria-hidden="true" />
        口径说明
      </PopoverTrigger>
      <PopoverContent align="end" className="max-h-(--available-height) w-80 gap-3 overflow-y-auto sm:w-96">
        <PopoverHeader>
          <PopoverTitle className="font-semibold">这些分数怎么看</PopoverTitle>
          <PopoverDescription className="text-pretty">研究分不代表收益概率，不构成投资建议。</PopoverDescription>
        </PopoverHeader>
        <dl className="flex flex-col gap-2 text-sm">
          {GUIDE.map(([term, text]) => (
            <div key={term}>
              <dt className="font-medium">{term}</dt>
              <dd className="text-muted-foreground text-pretty">{text}</dd>
            </div>
          ))}
          {scarcity && (
            <div>
              <dt className="font-medium">稀缺性标注</dt>
              <dd className="text-muted-foreground text-pretty">依据近期公告标注具体环节；点开查看原文、AI推理与疑点。稀缺标签不加分。</dd>
            </div>
          )}
        </dl>
        {families.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-border pt-2 text-sm">
            <b className="font-medium">分组口径</b>
            {families.map(family => (
              <p key={family.id} className="text-muted-foreground text-pretty">
                <span className="text-foreground">{family.label}：</span>
                {family.note}
              </p>
            ))}
          </div>
        )}
        <p className="border-t border-border pt-2 text-xs text-muted-foreground text-pretty">{sectorResearch.boardResearchNotice(report, sort)}</p>
      </PopoverContent>
    </Popover>
  );
}

const GUIDE: [string, string][] = [
  ['研究分：看证据强弱', '完整公司研究满分 100；基本面与走势合计满分 70，事件未评估时保留基础分。'],
  ['基本面 / 40、走势 / 30', '基本面看样本公司营收、净利增长与盈利状态；走势看 20 日、60 日收益与 20 日均线差。'],
  ['事件 ±30', '本批官方证据里最强利好与最强利空的调整，重复报道不叠加；"待评估"不按 0 分处理。'],
  ['行情风险、环境风险', '越高越需留意。环境风险按大盘、流动性与宏观独立计算，不扣减研究分。'],
  ['涨跌幅', '样本当日表现，红色为涨、绿色为跌；灰色或"—"表示没有可用行情，不能当作 0。'],
  ['领涨样本', '本板块公司样本中当日涨幅最大的一家，以及样本里上涨、下跌的家数和行情日期；没有报价的样本不计入涨跌家数。样本不代表全板块。'],
];

function SortHead({
  label,
  mode,
  sort,
  setSort,
  className,
}: {
  label: string;
  mode: SortMode;
  sort: SortMode;
  setSort: (mode: SortMode) => void;
  className?: string;
}) {
  const active = sort === mode;
  return (
    <TableHead aria-sort={active ? (mode === 'name' ? 'ascending' : 'descending') : 'none'} className={className}>
      <Button variant="ghost" size="xs" className={cn('-mx-2', active ? 'text-primary' : 'text-muted-foreground')} onClick={() => setSort(mode)}>
        {label}
        {active ? <ArrowDown aria-hidden="true" /> : <ArrowUpDown aria-hidden="true" />}
      </Button>
    </TableHead>
  );
}

/** Dense, sortable table for tablets and desktops; the sort keys are the old ones. */
function SectorTable({
  sectors,
  report,
  sort,
  setSort,
  counts,
  current,
  onOpen,
}: {
  sectors: Sector[];
  report: Report;
  sort: SortMode;
  setSort: (mode: SortMode) => void;
  counts: Map<string, number>;
  current: string | null;
  onOpen: (id: string) => void;
}) {
  const historical = report.report_stale;
  let previous: string | null = null;
  return (
    <div className="hidden md:block">
      <Table containerClassName="max-h-dvh overflow-y-auto rounded-lg border border-border">
        <TableHeader className="sticky top-0 z-20 bg-card shadow-xs">
          <TableRow>
            <SortHead label="板块" mode="name" sort={sort} setSort={setSort} />
            <SortHead label="涨跌幅" mode="change" sort={sort} setSort={setSort} className="text-right" />
            <TableHead className="hidden text-xs xl:table-cell">领涨样本</TableHead>
            <SortHead label="研究分" mode="score" sort={sort} setSort={setSort} className="text-right" />
            <TableHead className="text-right text-xs">基本面 / 40</TableHead>
            <TableHead className="text-right text-xs">走势 / 30</TableHead>
            <TableHead className="text-right text-xs">事件 ±30</TableHead>
            <TableHead className="text-xs">行情风险</TableHead>
            <TableHead className="hidden text-right text-xs xl:table-cell">环境风险</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sectors.map(sector => {
            const data = sectorResearch.sectorDataPresentation(sector, {
              historical,
              companyCount: (report.company_evidence.sector_leaders[sector.id] || []).length,
              eventCount: sectorEvents(report, sector.id).length,
            });
            const tone = sectorTone(sector, historical);
            const view = sectorResearch.companyScoreView(sector);
            const indicator = historical ? null : sectorResearch.sectorIndicator(sector);
            const parts = sector.score_breakdown || {};
            const risk = sector.market_risk || {};
            const changeTone = data.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
            const family = sectorResearch.boardScoreGroup(sector);
            const heading =
              sort === 'score' && family.id !== previous ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="bg-muted/50 py-1.5">
                    <span className="text-xs font-semibold tabular-nums">
                      {family.label} · {counts.get(family.id)} 个
                    </span>
                  </TableCell>
                </TableRow>
              ) : null;
            previous = family.id;
            const part = (value: unknown, signed = false) =>
              finite(value) ? (
                <span className={cn(signed && value > 0 && 'text-rise', signed && value < 0 && 'text-fall')}>
                  {(signed && value > 0 ? '+' : '') + num(value)}
                </span>
              ) : (
                <span className="text-muted-foreground">待评估</span>
              );
            return (
              <Fragment key={sector.id}>
                {heading}
                <TableRow data-state={sector.id === current ? 'selected' : undefined} className="relative cursor-pointer">
                  <TableCell className={cn('border-l-4 py-2', TONE_BORDER[tone])}>
                    {/* The name button stretches over the whole row, so any click on the row
                        opens the detail while keyboard users still reach one real button. */}
                    <Button
                      variant="link"
                      aria-haspopup="dialog"
                      className="h-auto p-0 text-sm font-semibold text-foreground after:absolute after:inset-0"
                      onClick={() => onOpen(sector.id)}
                    >
                      {sector.title}
                    </Button>
                    <span className="block max-w-28 truncate text-xs text-muted-foreground 2xl:max-w-52" title={data.subtitle}>
                      {data.subtitle}
                    </span>
                  </TableCell>
                  <TableCell className={cn('text-right font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>{data.changeText}</TableCell>
                  <TableCell className="hidden xl:table-cell">
                    <LeadSample report={report} sector={sector} />
                  </TableCell>
                  {/* Below 1536px the tier label drops under the score instead of widening the table. */}
                  <TableCell className="text-right whitespace-normal 2xl:whitespace-nowrap">
                    <span className={cn('text-base font-semibold tabular-nums', TONE_TEXT[tone])}>{data.scoreText}</span>
                    {view && <span className={cn('ml-1 inline-block rounded-sm px-1 py-0.5 text-xs whitespace-nowrap', TONE_BADGE[tone])}>{view.label}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.fundamentals?.points) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.trend?.points) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{view ? part(parts.catalysts?.observed_adjustment, true) : '—'}</TableCell>
                  <TableCell className="text-xs whitespace-normal">
                    <span className="relative z-10 flex items-center gap-1">
                      {indicator && <IndicatorIcon indicator={indicator} />}
                      {data.riskText}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-right text-xs tabular-nums xl:table-cell" title={txt(risk.scope)}>
                    {finite(risk.score) ? num(risk.score, 0) + '/100' : '—'}
                  </TableCell>
                </TableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** Filter state and the derived list; the dashboard shares it with the detail panel. */
export function useBoardView(report: Report | null, selected: string | null) {
  const [group, setGroup] = useState('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortMode>('score');
  const [onlyScarcity, setOnlyScarcity] = useState(false);
  const all: Sector[] = report?.sector_analysis ?? [];
  const sectors = all.filter(s => finite(s.score));
  const activeGroup = group !== 'all' && !sectors.some(s => s.group === group) ? 'all' : group;
  const scarcityAllowed = report?.scarcity_access?.allowed === true && !report?.report_stale;
  const scarcityOnly = scarcityAllowed && onlyScarcity;
  const needle = query.trim().toLowerCase();
  const visible: Sector[] = sectorResearch.sortSectors(
    sectors.filter(
      s =>
        (!scarcityOnly || sectorScarcity.isMarked(s)) &&
        (activeGroup === 'all' || s.group === activeGroup) &&
        (!needle ||
          (s.title + ' ' + (GROUP_LABELS[s.group] || '') + ' ' + txt(s.scarcity?.scope) + ' ' + txt(s.scarcity?.label))
            .toLowerCase()
            .includes(needle)),
    ),
    sort,
  );
  // Unscored directions stay selectable through personal watchlist shortcuts.
  const current: string | null =
    visible.some(s => s.id === selected) || all.some(s => s.id === selected && !finite(s.score)) ? selected : visible[0]?.id || null;
  function reset() {
    setQuery('');
    setGroup('all');
    setOnlyScarcity(false);
  }
  return { group: activeGroup, setGroup, query, setQuery, sort, setSort, scarcityAllowed, scarcityOnly, setOnlyScarcity, sectors, visible, current, reset };
}

export type BoardView = ReturnType<typeof useBoardView>;

/**
 * The listed rows (current filter and order) as a spreadsheet, using the same
 * texts as the table. The first line carries the report time and the score note.
 */
function exportSectors(report: Report, sectors: Sector[]) {
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

export function BoardExplorer({ board, onOpenDetail }: { board: BoardView; onOpenDetail: () => void }) {
  const { report, select } = useResearch();
  if (!report) return null;
  const { group: activeGroup, setGroup, query, setQuery, sort, setSort, scarcityAllowed, scarcityOnly, setOnlyScarcity, sectors, visible, current } = board;
  const marked = sectors.filter(s => sectorScarcity.isMarked(s));
  const company = sectors.filter(s => s.score_model === 'company_research_v2');
  const groupsPresent = Object.entries(GROUP_LABELS).filter(([id]) => sectors.some(s => s.group === id));

  const counts = new Map<string, number>();
  visible.forEach(s => {
    const id = sectorResearch.boardScoreGroup(s).id;
    counts.set(id, (counts.get(id) || 0) + 1);
  });
  const families = [
    ...new Map(
      visible.map(s => {
        const family = sectorResearch.boardScoreGroup(s);
        return [family.id, { id: family.id, label: family.label, note: family.note }] as const;
      }),
    ).values(),
  ];
  let previous: string | null = null;

  return (
    <Card id="boardExplorer">
      <CardHeader>
        <CardTitle>
          <h2 className="text-lg font-semibold text-balance">板块机会总览</h2>
        </CardTitle>
        <CardAction>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" size="sm" disabled={!visible.length} onClick={() => exportSectors(report, visible)}>
              <Download aria-hidden="true" />
              导出 CSV
            </Button>
            <ScoreGuide report={report} sort={sort} families={families} scarcity={scarcityAllowed} />
          </div>
        </CardAction>
        <CardDescription className="tabular-nums text-pretty">
          共 {sectors.length} 个方向 · 公司完整分 {company.filter(s => s.score_status === 'complete').length} 个 · 公司基础/阶段分{' '}
          {company.filter(s => s.score_status !== 'complete').length} 个 · 其他指标{' '}
          {sectors.filter(s => s.score_model !== 'company_research_v2').length} 个
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            aria-label="搜索板块"
            placeholder="搜索板块，如半导体、白酒…"
            maxLength={60}
            className="pl-8"
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </div>
        {scarcityAllowed && (
          <div className="flex flex-wrap items-center gap-2">
            <Toggle variant="outline" pressed={scarcityOnly} onPressedChange={setOnlyScarcity}>
              <Diamond aria-hidden="true" />
              只看稀缺性标注 · {marked.length}
            </Toggle>
          </div>
        )}
        <Tabs value={activeGroup} onValueChange={value => setGroup(String(value))}>
          <div className="overflow-x-auto overflow-y-hidden border-b border-border">
            <TabsList variant="line" aria-label="板块分类筛选">
              <TabsTrigger value="all" className="tabular-nums">
                全部 {sectors.length}
              </TabsTrigger>
              {groupsPresent.map(([id, name]) => (
                <TabsTrigger key={id} value={id} className="tabular-nums">
                  {name} {sectors.filter(s => s.group === id).length}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </Tabs>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-sm">
            排序
            <Select value={sort} onValueChange={value => setSort(value as SortMode)}>
              <SelectTrigger className="w-40">
                <SelectValue>{(value: SortMode) => SORT_LABELS[value]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(SORT_LABELS) as SortMode[]).map(mode => (
                  <SelectItem key={mode} value={mode}>
                    {SORT_LABELS[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <p className="flex flex-wrap gap-x-3 text-xs" aria-label="研究档位颜色">
            {LEGEND.map(([className, label]) => (
              <span key={label} className={className}>
                {label}
              </span>
            ))}
            <span className="text-muted-foreground">研究分不代表收益概率，不构成投资建议</span>
          </p>
        </div>
        {report.report_stale && (
          <p role="status" className="text-sm text-warning text-pretty">
            {sectorResearch.boardResearchNotice(report, sort)}
          </p>
        )}
        <div className="flex flex-col gap-1 md:hidden">
          {visible.map(sector => {
            const family = sectorResearch.boardScoreGroup(sector);
            const heading =
              sort === 'score' && family.id !== previous ? (
                <div role="heading" aria-level={3} className="mt-2 flex flex-col px-1">
                  <b className="text-sm font-medium tabular-nums">
                    {family.label} · {counts.get(family.id)} 个
                  </b>
                </div>
              ) : null;
            previous = family.id;
            return (
              <div key={sector.id} className="flex flex-col gap-1">
                {heading}
                <SectorRow
                  sector={sector}
                  report={report}
                  active={sector.id === current}
                  onSelect={() => {
                    select(sector.id);
                    onOpenDetail();
                  }}
                />
              </div>
            );
          })}
        </div>
        <SectorTable
          sectors={visible}
          report={report}
          sort={sort}
          setSort={setSort}
          counts={counts}
          current={current}
          onOpen={id => {
            select(id);
            onOpenDetail();
          }}
        />
        {!visible.length && (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <SearchX className="size-6 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">没有符合条件的板块。</p>
            <Button variant="outline" onClick={board.reset}>
              清除筛选条件
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
