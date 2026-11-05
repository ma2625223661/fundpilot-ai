// The sector research home page (the old #dash view).
import { useEffect, useRef, useState } from 'react';
import { CircleAlert, CircleCheck, History, LoaderCircle, Radio, RefreshCw, Sparkles } from 'lucide-react';
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Disclosure } from '@/components/research/common';
import { AiPanel } from '@/app/research/AiPanel';
import { BoardExplorer, useBoardView } from '@/app/research/BoardExplorer';
import { ImportantEvents } from '@/app/research/Events';
import { MarketOverview, MarketQuotes } from '@/app/research/MarketOverview';
import { SectorRankings } from '@/app/research/SectorRankings';
import { useResearch } from '@/app/research/ResearchContext';
import { SectorDetail } from '@/app/research/SectorDetail';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { SubscriptionProfile } from '@/app/research/SubscriptionProfile';
import { Watchlist } from '@/app/research/Watchlist';
import type { Sector } from '@/lib/report';
import { stamp, txt } from '@/lib/format';
import { cn } from '@/lib/utils';

const STATUS_TITLE: Record<string, string> = {
  idle: '板块研究准备中',
  running: '正在更新板块行情与分析',
  ready: '本轮板块研究已完成',
  error: '本轮板块研究暂未完成',
};

/** Research job, quote refresh and AI schedule in one strip, each with its own time. */
function StatusStrip() {
  const { state } = useResearch();
  const live = state.public_refresh;
  const problem = Boolean(state.connection_error || state.status === 'error');
  const running = state.status === 'running';
  const title = state.connection_error ? '暂时无法连接板块研究服务' : STATUS_TITLE[state.status] || '正在连接板块研究服务';
  const detail = state.connection_error
    ? state.connection_message
    : state.error
      ? '研究异常：' + txt(state.error)
      : state.status === 'ready' && state.ai_research?.public_refresh
        ? '行情、量化评分与市场指标已更新；本轮未发起新的 AI 研究。'
        : txt(state.stage, '后台自动采集板块行情、市场新闻并生成分析。');
  const Icon = problem ? CircleAlert : running ? LoaderCircle : CircleCheck;
  return (
    <Card size="sm" aria-label="研究状态与更新计划">
      <CardContent className="grid gap-4 md:grid-cols-3 md:divide-x md:divide-border">
        <div className="flex items-start gap-3" role="status">
          <Icon className={cn('mt-0.5 size-5 shrink-0', problem ? 'text-destructive' : 'text-primary')} aria-hidden="true" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <strong className="font-semibold">{title}</strong>
            <span className="text-sm text-muted-foreground text-pretty">{detail}</span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {[state.completed_at ? '最近完成 ' + stamp(state.completed_at) : '', state.next_run_at ? '下次更新 ' + stamp(state.next_run_at) : '']
                .filter(Boolean)
                .join(' · ')}
            </span>
          </div>
        </div>
        <div className="flex items-start gap-3 md:pl-4">
          <Radio className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="flex flex-col gap-0.5">
            <strong className="font-semibold">{live?.running ? '正在更新行情与量化评分' : txt(live?.label, '行情动态更新')}</strong>
            <span className="text-xs text-muted-foreground">行情与量化评分盘中每 5 分钟 · 不调用 AI，0 Token</span>
            <span className="text-sm text-muted-foreground tabular-nums">
              {live ? (live.completed_at ? '最近刷新 ' + stamp(live.completed_at) : '等待首次有效采集') : '正在读取更新计划'}
            </span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {live ? (live.next_run_at ? '下次采集 ' + stamp(live.next_run_at) : '交易日历核验后恢复') : '午间、休市暂停；收盘补采'}
            </span>
          </div>
        </div>
        <div className="flex items-start gap-3 md:pl-4">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="flex flex-col gap-0.5">
            <strong className="font-semibold">AI 深度研究独立运行</strong>
            <span className="text-sm text-muted-foreground tabular-nums">A 股交易日 09:20 / 14:50</span>
            <span className="text-xs text-muted-foreground">复用解读不重复调用</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ReportNotice() {
  const { notice, viewingHistory, returnLatest } = useResearch();
  if (!notice) return null;
  return (
    <Alert>
      <History aria-hidden="true" />
      <AlertDescription className="text-pretty" role="status">
        {notice}
      </AlertDescription>
      {viewingHistory && (
        <AlertAction>
          <Button size="sm" variant="outline" onClick={returnLatest}>
            返回最新报告
          </Button>
        </AlertAction>
      )}
    </Alert>
  );
}

function ReadingGuide() {
  return (
    <Disclosure title="这些分数怎么看？研究分、风险分和行情涨跌各自代表什么">
      <div className="grid gap-3 md:grid-cols-3">
        <div>
          <b className="font-medium text-foreground">研究分：看证据强弱</b>
          <p className="text-pretty">完整公司研究满分 100；基本面与走势合计满分 70，事件未评估时保留基础分。研究分不代表收益概率，不构成投资建议。</p>
        </div>
        <div>
          <b className="font-medium text-foreground">风险分：越高越需留意</b>
          <p className="text-pretty">市场压力与环境风险独立计算。情绪高代表活跃，过热还需关注拥挤；流动性高代表资金偏宽。</p>
        </div>
        <div>
          <b className="font-medium text-foreground">涨跌幅：看样本当日表现</b>
          <p className="text-pretty">涨跌幅与研究分不同，红色为涨、绿色为跌。灰色或“待评估”表示证据不够，不能当作 0 分或没有风险。</p>
        </div>
      </div>
    </Disclosure>
  );
}

const TAB_KEY = 'fundpilot_dash_tab_v1';

/** The last homepage tab this viewer used (a per-browser convenience only). */
function readTab() {
  try {
    return localStorage.getItem(TAB_KEY) || 'overview';
  } catch {
    return 'overview';
  }
}

export function DashView() {
  const research = useResearch();
  const { report, state, session, refresh, select } = research;
  const board = useBoardView(report, research.selected);
  const subscription = useSubscription();
  const [detailOpen, setDetailOpen] = useState(false);
  // Focus the panel heading on open, so the drawer starts at its top.
  const detailHead = useRef<HTMLDivElement>(null);
  const detailSector: Sector | undefined = report?.sector_analysis.find((s: Sector) => s.id === board.current);

  // Watchlist shortcuts and finished personal research open a sector directly.
  useEffect(() =>
    subscription.onOpenSector(id => {
      board.reset();
      select(id);
      setDetailOpen(true);
    }),
  );

  const canRefresh = !research.accountMode || session.isAdmin;
  const [tab, setTab] = useState(readTab);
  const chooseTab = (value: string) => {
    setTab(value);
    try {
      localStorage.setItem(TAB_KEY, value);
    } catch {
      // Storage unavailable: the choice lasts for this page only.
    }
  };
  const openSector = (id: string) => {
    board.reset();
    select(id);
    setDetailOpen(true);
  };
  const tabs: [string, string, boolean][] = [
    ['overview', '市场概览', true],
    ['boards', '板块总览', true],
    ['events', '重要事件', true],
    ['mine', '我的关注与订阅', research.accountMode],
    ['ai', 'AI 研究', true],
  ];
  const activeTab = tabs.some(([id, , shown]) => id === tab && shown) ? tab : 'overview';

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <h1 className="text-2xl font-semibold text-balance">板块研究</h1>
          <p className="hidden text-sm text-muted-foreground text-pretty sm:block">
            以龙头股和经营数据为主，结合公开公告与官方政策判断板块机会与风险。
          </p>
        </div>
        {canRefresh && (
          <Button onClick={() => void refresh()} disabled={state.status === 'running'}>
            <RefreshCw aria-hidden="true" />
            {state.status === 'running' ? '正在更新…' : '更新行情与评分'}
          </Button>
        )}
      </header>
      {report && <MarketQuotes report={report} />}
      <StatusStrip />
      <ReportNotice />
      <Tabs value={activeTab} onValueChange={value => chooseTab(String(value))} className="gap-4">
        <div className="overflow-x-auto overflow-y-hidden border-b border-border">
          <TabsList variant="line" aria-label="板块研究分区">
            {tabs
              .filter(([, , shown]) => shown)
              .map(([id, label]) => (
                <TabsTrigger key={id} value={id} className="px-3 text-sm">
                  {label}
                </TabsTrigger>
              ))}
          </TabsList>
        </div>
        <TabsContent value="overview" keepMounted className="flex flex-col gap-6">
          {!report ? (
            <div className="flex flex-col gap-4" aria-busy="true" aria-label="正在载入板块报告">
              <Skeleton className="h-40" />
              <Skeleton className="h-72" />
            </div>
          ) : (
            <>
              <MarketOverview report={report} />
              <SectorRankings report={report} onOpen={openSector} />
            </>
          )}
        </TabsContent>
        <TabsContent value="boards" keepMounted className="flex flex-col gap-4">
          <ReadingGuide />
          {report ? <BoardExplorer board={board} onOpenDetail={() => setDetailOpen(true)} /> : <Skeleton className="h-96" />}
        </TabsContent>
        <TabsContent value="events" keepMounted>
          {report ? <ImportantEvents /> : <Skeleton className="h-72" />}
        </TabsContent>
        {research.accountMode && (
          <TabsContent value="mine" keepMounted className="flex flex-col gap-4">
            <Watchlist />
            <SubscriptionProfile />
          </TabsContent>
        )}
        <TabsContent value="ai" keepMounted>
          <AiPanel />
        </TabsContent>
      </Tabs>
      {report && (
        <Sheet open={detailOpen && Boolean(detailSector)} onOpenChange={setDetailOpen}>
          <SheetContent side="right" size="wide" className="gap-0 p-0" initialFocus={detailHead}>
            <SheetHeader ref={detailHead} tabIndex={-1} className="border-b border-border pr-12 outline-none">
              <SheetTitle className="text-sm font-medium text-muted-foreground">板块详情</SheetTitle>
              <SheetDescription className="sr-only">{(detailSector?.title ?? '') + '：研究依据、数据缺口与公司证据'}</SheetDescription>
            </SheetHeader>
            <ScrollArea key={board.current} className="min-h-0 flex-1">
              <div className="p-4">
                <SectorDetail report={report} sectorId={board.current} framed={false} />
              </div>
            </ScrollArea>
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}
