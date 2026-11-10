// Standalone page for one sector (#sector/<id>): the same detail as the drawer,
// with room to read and an address to bookmark or share. Previous / next follow
// the default order of the sector table (old sortSectors by score group).
import { useEffect } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { goTo, sectorHref, useHashSector } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { WatchButton } from '@/app/research/WatchButton';
import { SectorDetail } from '@/app/research/SectorDetail';
import { CompareButton } from '@/app/research/Compare';
import { sectorResearch } from '@/lib/research';
import { finite } from '@/lib/format';
import type { Sector } from '@/lib/report';
import { cn } from '@/lib/utils';

async function copyLink() {
  try {
    await navigator.clipboard.writeText(location.href);
    toast.success('已复制本板块链接');
  } catch {
    toast.error('无法写入剪贴板，请直接复制浏览器地址栏中的链接');
  }
}

export function SectorView() {
  const id = useHashSector();
  const { report, select } = useResearch();
  const sector: Sector | undefined = report?.sector_analysis.find((s: Sector) => s.id === id);

  // Keep the dashboard selection in step, so going back shows the same sector.
  useEffect(() => {
    if (sector) select(sector.id);
  }, [sector, select]);
  useEffect(() => {
    if (!sector) return;
    const previous = document.title;
    document.title = `${sector.title} · FundPilot AI`;
    window.scrollTo({ top: 0 });
    return () => {
      document.title = previous;
    };
  }, [sector]);

  const back = (
    <Button variant="ghost" size="sm" className="-ml-2 self-start" onClick={() => goTo('dash')}>
      <ArrowLeft aria-hidden="true" />
      返回板块研究
    </Button>
  );

  if (!report)
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="正在载入板块">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-96" />
      </div>
    );

  if (!sector)
    return (
      <div className="flex flex-col items-start gap-3">
        {back}
        <h1 className="text-xl font-semibold text-balance">没有找到这个板块</h1>
        <p className="text-sm text-muted-foreground text-pretty">本期报告中没有该方向，可能链接有误或板块已调整。可回到板块研究重新选择，或按 Ctrl K 搜索。</p>
      </div>
    );

  const order: Sector[] = sectorResearch.sortSectors(
    report.sector_analysis.filter((s: Sector) => finite(s.score)),
    'score',
  );
  const index = order.findIndex(s => s.id === sector.id);
  const prev = index > 0 ? order[index - 1] : null;
  const next = index >= 0 && index < order.length - 1 ? order[index + 1] : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <nav aria-label="板块页面" className="flex flex-wrap items-center justify-between gap-2">
        {back}
        <div className="flex flex-wrap items-center gap-2">
          <WatchButton id={sector.id} />
          <CompareButton id={sector.id} />
          <Button variant="outline" size="sm" onClick={() => void copyLink()}>
            <Link2 aria-hidden="true" />
            复制链接
          </Button>
          {index >= 0 && (
            <span className="flex items-center gap-1">
              <a
                href={prev ? sectorHref(prev.id) : undefined}
                aria-label={prev ? `上一个：${prev.title}` : '已是第一个'}
                aria-disabled={!prev}
                className={cn(buttonVariants({ variant: 'outline', size: 'icon-sm' }), !prev && 'pointer-events-none opacity-50')}
              >
                <ChevronLeft aria-hidden="true" />
              </a>
              <span className="px-1 text-xs text-muted-foreground tabular-nums">
                {index + 1} / {order.length}
              </span>
              <a
                href={next ? sectorHref(next.id) : undefined}
                aria-label={next ? `下一个：${next.title}` : '已是最后一个'}
                aria-disabled={!next}
                className={cn(buttonVariants({ variant: 'outline', size: 'icon-sm' }), !next && 'pointer-events-none opacity-50')}
              >
                <ChevronRight aria-hidden="true" />
              </a>
            </span>
          )}
        </div>
      </nav>
      {/* A new sector remounts the detail, so its tabs start again at the overview. */}
      <SectorDetail key={sector.id} report={report} sectorId={sector.id} />
    </div>
  );
}
