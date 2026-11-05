// Filter, search, sort and selection state of the sector list; the dashboard
// shares it with the detail panel.
import { useState } from 'react';
import { sectorResearch, sectorScarcity } from '@/lib/research';
import { GROUP_LABELS, finite, txt } from '@/lib/format';
import { type Report, type Sector } from '@/lib/report';

export type SortMode = 'score' | 'change' | 'name';

export const SORT_LABELS: Record<SortMode, string> = { score: '同类研究分优先', change: '当日涨幅优先', name: '板块名称' };

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
