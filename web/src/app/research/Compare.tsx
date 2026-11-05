// "加入对比" toggles and the tray that collects the picked sectors at the bottom
// of the page, with a link to the comparison once at least two are picked.
import { Columns3, Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button, buttonVariants } from '@/components/ui/button';
import { COMPARE_LIMIT, compareHref } from '@/app/navigation';
import { compareStore, useCompareList } from '@/app/research/compare-store';
import { useResearch } from '@/app/research/ResearchContext';
import type { Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

export function CompareButton({ id, className }: { id: string; className?: string }) {
  const picked = useCompareList();
  const added = picked.includes(id);
  return (
    <Button
      variant="outline"
      size="sm"
      aria-pressed={added}
      className={className}
      onClick={() => {
        if (added) compareStore.remove(id);
        else if (!compareStore.add(id)) toast.error(`最多同时对比 ${COMPARE_LIMIT} 个板块，请先在底部移除一个。`);
      }}
    >
      {added ? <X aria-hidden="true" /> : <Plus aria-hidden="true" />}
      {added ? '移出对比' : '加入对比'}
    </Button>
  );
}

/** Fixed at the bottom while sectors are picked; hidden on the comparison page itself. */
export function CompareTray() {
  const picked = useCompareList();
  const { report } = useResearch();
  if (!picked.length) return null;
  const names = new Map<string, string>((report?.sector_analysis ?? []).map((s: Sector) => [s.id, s.title]));
  return (
    <section
      aria-label="待对比的板块"
      className="mx-auto mb-2 flex w-full max-w-3xl flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 shadow-sm md:mb-4"
    >
      <span className="mr-auto text-sm font-medium tabular-nums sm:mr-0">
        对比 {picked.length}/{COMPARE_LIMIT}
      </span>
      {/* On a phone the chips get their own full row below the actions, so they wrap side by side. */}
      <ul className="order-last flex min-w-0 basis-full flex-wrap gap-1 sm:order-none sm:flex-1 sm:basis-auto">
        {picked.map(id => (
          <li key={id} className="flex items-center gap-0.5 rounded-md bg-muted py-0.5 pr-0.5 pl-2 text-xs">
            {names.get(id) ?? id}
            <Button variant="ghost" size="icon-xs" aria-label={`从对比中移除${names.get(id) ?? id}`} onClick={() => compareStore.remove(id)}>
              <X aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      <Button variant="ghost" size="sm" onClick={() => compareStore.clear()}>
        清空
      </Button>
      {picked.length >= 2 ? (
        <a href={compareHref(picked)} className={cn(buttonVariants({ size: 'sm' }))}>
          <Columns3 aria-hidden="true" />
          开始对比
        </a>
      ) : (
        <span className="text-xs text-muted-foreground">再选 1 个即可对比</span>
      )}
    </section>
  );
}
