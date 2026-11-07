// Command palette for jumping to any sector, page or settings section
// (Ctrl/Cmd+K), the quick-search pattern used by dashboards such as Linear and Vercel. Filtering and keyboard
// navigation come from the shadcn Command component (cmdk).
import { useEffect } from 'react';
import { Search, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, Command } from '@/components/ui/command';
import { VIEWS, goTo } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, GROUP_LABELS, direction } from '@/lib/format';
import { TONE_TEXT, sectorTone, type Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

/** Button that opens the palette; the sidebar shows the wide form, the phone header the icon. */
export function SectorSearchTrigger({ onOpen, compact = false }: { onOpen: () => void; compact?: boolean }) {
  return compact ? (
    <Button variant="ghost" size="icon" aria-label="搜索板块（Ctrl+K）" onClick={onOpen}>
      <Search aria-hidden="true" />
    </Button>
  ) : (
    <Button variant="outline" className="w-full justify-start gap-2 text-muted-foreground" onClick={onOpen}>
      <Search aria-hidden="true" />
      <span className="flex-1 text-left">搜索板块</span>
      <kbd className="rounded-sm border border-border px-1.5 text-xs font-normal text-muted-foreground">Ctrl K</kbd>
    </Button>
  );
}

/** The single palette for the whole app; it owns the Ctrl/Cmd+K shortcut. */
export function SectorSearchDialog({ open, setOpen, onNavigate }: { open: boolean; setOpen: (open: boolean) => void; onNavigate?: () => void }) {
  const { report, session, accountMode } = useResearch();
  const sub = useSubscription();
  const historical = report?.report_stale === true;
  const sectors: Sector[] = report?.sector_analysis ?? [];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, setOpen]);

  function choose(id: string) {
    setOpen(false);
    goTo('dash');
    sub.openSector(id);
    onNavigate?.();
  }

  function jump(target: string) {
    setOpen(false);
    goTo(target);
    onNavigate?.();
  }

  // Settings sections that old links (#researchSettings …) already open; the
  // account and user entries only exist where the settings page shows them.
  const settings: [string, string, boolean][] = [
    ['researchSettings', 'AI 研究设置', true],
    ['researchDataSettings', '数据连接', true],
    ['cloudAccount', '账号与安全', accountMode],
    ['aiSupport', '订阅帮助', true],
    ['mobileAccess', '手机访问', true],
    ['aiSubscriptionAdmin', '用户管理', accountMode && session.isAdmin],
  ];

  const groups = Object.entries(GROUP_LABELS)
    .map(([id, label]) => [label, sectors.filter(s => s.group === id)] as const)
    .filter(([, rows]) => rows.length);

  return (
    <>
      <CommandDialog open={open} onOpenChange={setOpen} title="搜索板块与页面" description="输入板块、页面或设置名称，回车打开">
        {/* Plain substring match: names are Chinese, and fuzzy matching surfaces unrelated sectors. */}
        <Command filter={(value, search) => (value.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0)}>
          <CommandInput placeholder="输入板块、页面或设置，如半导体、数据连接…" />
          <CommandList>
            <CommandEmpty>{report ? '没有找到匹配的板块、页面或设置。' : '研究报告加载后可搜索板块；页面和设置可直接输入名称。'}</CommandEmpty>
            {groups.map(([label, rows]) => (
              <CommandGroup key={label} heading={label}>
                {rows.map(sector => {
                  const data = sectorResearch.sectorDataPresentation(sector, { historical });
                  const changeTone = data.hasQuote && !historical ? direction(sector.change_pct) : 'unknown';
                  return (
                    <CommandItem key={sector.id} value={sector.title + ' ' + sector.id} onSelect={() => choose(sector.id)}>
                      <span className="flex-1 truncate">{sector.title}</span>
                      <span className={cn('text-xs tabular-nums', TONE_TEXT[sectorTone(sector, historical)])}>
                        {data.hasScore ? data.scoreText : '待评估'}
                      </span>
                      <span className={cn('w-16 text-right text-xs font-medium tabular-nums', DIRECTION_CLASS[changeTone])}>
                        {data.hasQuote ? data.changeText : '—'}
                      </span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ))}
            <CommandGroup heading="页面">
              {VIEWS.map(view => (
                <CommandItem key={view.id} value={'页面 ' + view.label} onSelect={() => jump(view.id)}>
                  <view.icon aria-hidden="true" />
                  <span className="flex-1">{view.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandGroup heading="设置">
              {settings
                .filter(([, , shown]) => shown)
                .map(([anchor, label]) => (
                  <CommandItem key={anchor} value={'设置 ' + label} onSelect={() => jump(anchor)}>
                    <Settings2 aria-hidden="true" />
                    <span className="flex-1">{label}</span>
                  </CommandItem>
                ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}
