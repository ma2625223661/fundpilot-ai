// Follow / unfollow a sector from wherever it is shown (sector page, detail
// drawer, comparison table). Account edition only; the list itself is shared
// through WatchlistContext, so every button and the sidebar stay in step.
import { Star, StarOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useWatchlist } from '@/app/research/WatchlistContext';

export function WatchButton({ id, title, compact = false }: { id: string; title?: string; compact?: boolean }) {
  const watch = useWatchlist();
  if (!watch.available || !watch.loaded) return null;
  const followed = watch.items.includes(id);
  const label = (followed ? '取消关注' : '加入关注') + (title ? title : '');
  const toggle = () => void watch.change(id, followed ? 'remove' : 'add');
  const icon = followed ? <StarOff aria-hidden="true" /> : <Star aria-hidden="true" />;
  return compact ? (
    <Button variant="ghost" size="icon-xs" aria-label={label} aria-pressed={followed} disabled={watch.busy} onClick={toggle}>
      {icon}
    </Button>
  ) : (
    <Button variant="outline" size="sm" aria-pressed={followed} disabled={watch.busy} onClick={toggle}>
      {icon}
      {followed ? '取消关注' : '加入关注'}
    </Button>
  );
}
