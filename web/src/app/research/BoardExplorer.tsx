// Port of renderBoards: category filter, search, sort, scarcity filter and the
// grouped sector list. Grouping, ordering and colours come from the old logic.
// The table, phone cards, guide, export and filter state live in ./board/.
import { Diamond, Download, Search, SearchX } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toggle } from '@/components/ui/toggle';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useResearch } from '@/app/research/ResearchContext';
import { sectorResearch, sectorScarcity } from '@/lib/research';
import { GROUP_LABELS } from '@/lib/format';
import { ScoreGuide } from '@/app/research/board/ScoreGuide';
import { SectorRow } from '@/app/research/board/SectorRow';
import { SectorTable } from '@/app/research/board/SectorTable';
import { SORT_LABELS, type BoardView, type SortMode } from '@/app/research/board/board-view';
import { exportSectors } from '@/app/research/board/export-sectors';
// Kept on this path for existing callers (dashboard, comparison page).
export { useBoardView, type BoardView } from '@/app/research/board/board-view';
export { leadSample } from '@/app/research/board/lead-sample';

const LEGEND: [string, string][] = [
  ['text-tier-optimistic', '≥65 乐观'],
  ['text-tier-neutral', '50～<65 中性'],
  ['text-tier-cautious', '30～<50 谨慎'],
  ['text-tier-avoid', '<30 规避'],
];

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
        {/* Actions in the title row rather than CardAction: on a phone they wrap below
            the title instead of squeezing the summary into a narrow column. */}
        <CardTitle className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h2 className="text-lg font-semibold text-balance">板块机会总览</h2>
          <span className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={!visible.length} onClick={() => exportSectors(report, visible)}>
              <Download aria-hidden="true" />
              导出 CSV
            </Button>
            <ScoreGuide report={report} sort={sort} families={families} scarcity={scarcityAllowed} />
          </span>
        </CardTitle>
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
