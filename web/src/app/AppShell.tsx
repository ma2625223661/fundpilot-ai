// Application frame, modelled on the shadcn "dashboard-01" block: an inset
// sidebar that shares the page canvas, a primary action at the top (sector
// search, Ctrl+K), grouped navigation with count badges, secondary links and the
// account card pinned to the bottom. A quote-centre style watchlist fills the
// middle with each followed sector's score and change.
import { useState, type CSSProperties, type ReactNode } from 'react';
import { Clock, ExternalLink, LifeBuoy } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';
import { Separator } from '@/components/ui/separator';
import { AccountMenu } from '@/components/account-menu';
import { BeijingClock } from '@/components/beijing-clock';
import { Brand } from '@/components/brand';
import { SectorSearchDialog, SectorSearchTrigger } from '@/components/sector-search';
import { ThemeToggle } from '@/components/theme-toggle';
import { VIEWS, goTo, type ViewId } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { researchStatus } from '@/app/research/research-status';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { useWatchlist } from '@/app/research/WatchlistContext';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, finite, stamp } from '@/lib/format';
import { TONE_TEXT, sectorTone, type Sector } from '@/lib/report';
import type { Session } from '@/lib/session';
import { cn } from '@/lib/utils';

const MAIN: ViewId[] = ['dash', 'data', 'history', 'cycle'];

function useSidebarMode() {
  const { isMobile, setOpenMobile, state } = useSidebar();
  return {
    collapsed: state === 'collapsed' && !isMobile,
    close: () => {
      if (isMobile) setOpenMobile(false);
    },
  };
}

function NavItem({ id, current, badge }: { id: ViewId; current: ViewId; badge?: { text: string; alert?: boolean } }) {
  const { close } = useSidebarMode();
  const view = VIEWS.find(entry => entry.id === id)!;
  // A sector page belongs to the research section.
  const active = current === id || (current === 'sector' && id === 'dash');
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        size="lg"
        isActive={active}
        aria-current={active ? 'page' : undefined}
        tooltip={view.label}
        className="h-10 gap-3 text-sm data-active:font-semibold"
        onClick={() => {
          goTo(id);
          close();
        }}
      >
        <view.icon className={cn('size-5', active ? 'text-primary' : 'text-muted-foreground')} aria-hidden="true" />
        <span>{view.label}</span>
      </SidebarMenuButton>
      {badge && (
        <SidebarMenuBadge className={cn('top-2.5 tabular-nums', badge.alert && 'text-warning')}>{badge.text}</SidebarMenuBadge>
      )}
    </SidebarMenuItem>
  );
}

function Navigation({ current }: { current: ViewId }) {
  const { report, histories } = useResearch();
  // Count badges: scored sectors, sources needing attention, saved reports.
  // Unknown counts show no badge rather than 0.
  const badges: Partial<Record<ViewId, { text: string; alert?: boolean }>> = {};
  if (report) {
    badges.dash = { text: String(report.sector_analysis.filter((s: Sector) => finite(s.score)).length) };
    const attention = sectorResearch.sourceOverview(report.snapshot.sources).attention;
    if (attention > 0) badges.data = { text: String(attention), alert: true };
  }
  if (histories.length) badges.history = { text: String(histories.length) };
  return (
    <SidebarGroup>
      <SidebarGroupLabel>研究</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu className="gap-1">
          {MAIN.map(id => (
            <NavItem key={id} id={id} current={current} badge={badges[id]} />
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

/** Followed sectors with score and change; hidden when the sidebar is an icon rail. */
function SideWatchlist() {
  const { collapsed, close } = useSidebarMode();
  const { report } = useResearch();
  const watch = useWatchlist();
  const sub = useSubscription();
  if (!watch.available || collapsed) return null;
  const historical = report?.report_stale === true;
  const sectors = new Map<string, Sector>((report?.sector_analysis ?? []).map((s: Sector) => [s.id, s]));
  return (
    <SidebarGroup>
      <SidebarGroupLabel className="justify-between">
        <span>我的关注</span>
        {watch.loaded && <span className="tabular-nums">{watch.items.length}</span>}
      </SidebarGroupLabel>
      <SidebarGroupContent>
        {!watch.loaded ? (
          <p className="px-2 py-1 text-xs text-muted-foreground">正在读取…</p>
        ) : !watch.items.length ? (
          <div className="mx-2 flex flex-col gap-1 rounded-lg border border-dashed border-sidebar-border p-3 text-xs text-muted-foreground">
            <span className="font-medium text-sidebar-foreground">还没有关注的板块</span>
            <span className="text-pretty">在板块研究的“我的关注与订阅”分区添加关注，这里会显示研究分与涨跌。</span>
          </div>
        ) : (
          <SidebarMenu className="gap-0.5">
            {watch.items.slice(0, 12).map(id => {
              const sector = sectors.get(id);
              const data = sector ? sectorResearch.sectorDataPresentation(sector, { historical }) : null;
              const changeTone = sector && data?.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
              return (
                <SidebarMenuItem key={id}>
                  <SidebarMenuButton
                    size="lg"
                    className="h-auto gap-3 py-2"
                    disabled={!sector}
                    onClick={() => {
                      goTo('dash');
                      sub.openSector(id);
                      close();
                    }}
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="truncate text-sm font-medium">{sector?.title ?? id}</span>
                      <span className={cn('text-xs tabular-nums', sector ? TONE_TEXT[sectorTone(sector, historical)] : 'text-muted-foreground')}>
                        {data ? (data.hasScore ? '研究分 ' + data.scoreText : '待评估') : '报告未包含'}
                      </span>
                    </span>
                    <span className={cn('shrink-0 text-sm font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>
                      {data && data.hasQuote ? data.changeText : '—'}
                    </span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        )}
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

function SideHeader({ onSearch }: { onSearch: () => void }) {
  const { collapsed } = useSidebarMode();
  return (
    <SidebarHeader className="gap-3 p-3">
      <Brand subtitle={collapsed ? undefined : '自动板块研究工作台'} compact={collapsed} />
      {!collapsed && <SectorSearchTrigger onOpen={onSearch} />}
    </SidebarHeader>
  );
}

/** Closes the phone drawer after a search result is opened. */
function SearchPalette({ open, setOpen }: { open: boolean; setOpen: (open: boolean) => void }) {
  const { close } = useSidebarMode();
  return <SectorSearchDialog open={open} setOpen={setOpen} onNavigate={close} />;
}

function SideFooter({ session, current }: { session: Session; current: ViewId }) {
  const { collapsed } = useSidebarMode();
  const research = useResearch();
  const status = researchStatus(research.state, Boolean(research.report?.report_stale));
  const user = session.user;
  return (
    <SidebarFooter className="gap-2 p-3">
      <SidebarMenu className="gap-1">
        <NavItem id="settings" current={current} />
        <SidebarMenuItem>
          <SidebarMenuButton
            size="lg"
            tooltip="订阅与帮助"
            className="h-10 gap-3 text-sm"
            render={<a href="ai-service.html" target="_blank" rel="noopener noreferrer" />}
          >
            <LifeBuoy className="size-5 text-muted-foreground" aria-hidden="true" />
            <span className="flex-1">订阅与帮助</span>
            <ExternalLink className="size-3.5 text-muted-foreground" aria-hidden="true" />
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      {!collapsed && (
        <div className="flex flex-col gap-1 rounded-lg bg-sidebar-accent p-3 text-xs">
          <span className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 font-medium text-sidebar-foreground">
              <span className={cn('size-2 rounded-full', status.dot)} aria-hidden="true" />
              {status.label}
            </span>
            {research.accountMode && <Badge variant="outline">{session.access.scope === 'cloud' ? '云端版' : '本地版'}</Badge>}
          </span>
          {research.state.next_run_at && (
            <span className="flex items-center gap-1 text-muted-foreground tabular-nums">
              <Clock className="size-3" aria-hidden="true" />
              下次更新 {stamp(research.state.next_run_at)}
            </span>
          )}
          <span className="text-muted-foreground text-pretty">研究指数用于比较证据强弱，不代表收益概率，不构成投资建议。</span>
        </div>
      )}
      {user &&
        (collapsed ? (
          <Avatar className="mx-auto size-8">
            <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">{user.username.slice(0, 1).toUpperCase()}</AvatarFallback>
          </Avatar>
        ) : (
          <div className="flex items-center gap-2 rounded-lg p-1">
            <Avatar className="size-9">
              <AvatarFallback className="bg-primary/15 text-sm font-semibold text-primary">{user.username.slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <AccountMenu user={user} hideIcon className="h-auto min-w-0 flex-1 max-w-none justify-start px-1 py-1" />
          </div>
        ))}
    </SidebarFooter>
  );
}

// Short names for the phone tab bar; the sidebar keeps the full ones.
const TAB_LABELS: Partial<Record<ViewId, string>> = { dash: '研究', data: '数据', history: '记录', cycle: '周期', settings: '设置' };

/**
 * Phones get the main pages as a bottom tab bar (as in Xueqiu or East Money),
 * one tap from anywhere; the sidebar drawer still holds the watchlist and account.
 */
function MobileTabBar({ current }: { current: ViewId }) {
  return (
    <nav
      aria-label="主要页面"
      className="safe-inset-bottom fixed inset-x-0 bottom-0 z-20 border-t border-border bg-background md:hidden"
    >
      <div className="grid grid-cols-5">
        {VIEWS.map(view => {
          const active = current === view.id || (current === 'sector' && view.id === 'dash');
          return (
            <Button
              key={view.id}
              variant="ghost"
              aria-current={active ? 'page' : undefined}
              aria-label={view.label}
              className={cn(
                'h-14 flex-col gap-1 rounded-none text-xs font-normal',
                active ? 'text-primary' : 'text-muted-foreground',
              )}
              onClick={() => goTo(view.id)}
            >
              <view.icon className="size-5" aria-hidden="true" />
              <span aria-hidden="true">{TAB_LABELS[view.id] ?? view.label}</span>
            </Button>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({ session, view, children }: { session: Session; view: ViewId; children: ReactNode }) {
  const [searchOpen, setSearchOpen] = useState(false);
  return (
    <SidebarProvider style={{ '--sidebar-width': '17rem' } as CSSProperties}>
      {/* First stop for keyboard users: skip the sidebar and header. A button, not
          an in-page link, because the location hash selects the page here. */}
      <Button
        variant="default"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2 focus-visible:z-50"
        onClick={() => document.getElementById('main-content')?.focus()}
      >
        跳到主要内容
      </Button>
      <Sidebar collapsible="icon" variant="inset">
        <SideHeader onSearch={() => setSearchOpen(true)} />
        <SidebarContent className="gap-1">
          <Navigation current={view} />
          <SideWatchlist />
        </SidebarContent>
        <SideFooter session={session} current={view} />
      </Sidebar>
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-2 rounded-t-xl border-b border-border bg-background px-4">
          <SidebarTrigger aria-label="展开或收起导航" />
          <Separator orientation="vertical" className="h-4" />
          <BeijingClock />
          <div className="ml-auto flex items-center gap-1">
            <span className="md:hidden">
              <SectorSearchTrigger compact onOpen={() => setSearchOpen(true)} />
            </span>
            <ThemeToggle />
          </div>
        </header>
        <div id="main-content" tabIndex={-1} className="safe-bottom mx-auto flex w-full max-w-7xl min-w-0 flex-col gap-6 px-4 py-6 outline-none max-md:safe-bottom-tabs">
          {children}
        </div>
        <MobileTabBar current={view} />
      </SidebarInset>
      <SearchPalette open={searchOpen} setOpen={setSearchOpen} />
    </SidebarProvider>
  );
}
