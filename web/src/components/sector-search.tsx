// Command palette for jumping to any sector (Ctrl/Cmd+K), the quick-search
// pattern used by dashboards such as Linear and Vercel. Filtering and keyboard
// navigation come from the shadcn Command component (cmdk).
import { useEffect } from 'react';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, Command } from '@/components/ui/command';
import { goTo } from '@/app/navigation';
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
  const { report } = useResearch();
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

  const groups = Object.entries(GROUP_LABELS)
    .map(([id, label]) => [label, sectors.filter(s => s.group === id)] as const)
    .filter(([, rows]) => rows.length);

  return (
    <>
      <CommandDialog open={open} onOpenChange={setOpen} title="搜索板块" description="输入板块名称，回车打开研究详情">
        {/* Plain substring match: names are Chinese, and fuzzy matching surfaces unrelated sectors. */}
        <Command filter={(value, search) => (value.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0)}>
          <CommandInput placeholder="输入板块名称，如半导体、白酒…" />
          <CommandList>
            <CommandEmpty>{report ? '没有找到这个板块。' : '研究报告加载后可搜索。'}</CommandEmpty>
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
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}
