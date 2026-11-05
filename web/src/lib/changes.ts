// Day-over-day sector changes produced by the backend (research_changes.py).
// The page only validates and displays them; deltas are never computed here.
// The old normalizeReport() builds the report field by field and would drop
// this block, so it is validated separately and attached afterwards.
import type { Report } from '@/lib/report';

export interface SectorChange {
  scoreBefore: number | null;
  scoreNow: number | null;
  scoreDelta: number | null;
  tier: { before: string; now: string } | null;
  flags: string[];
  risk: { before: string; now: string } | null;
  notable: boolean;
}

export interface SectorChanges {
  status: 'ok' | 'no_baseline' | 'unavailable';
  baselineAsOf: string | null;
  baselineDate: string | null;
  reason: string;
  note: string;
  items: Record<string, SectorChange>;
}

const number = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const text = (value: unknown) => (typeof value === 'string' ? value : '');
const pair = (value: unknown) => {
  const row = value as Record<string, unknown> | null;
  return row && typeof row === 'object' && text(row.before) && text(row.now) ? { before: text(row.before), now: text(row.now) } : null;
};

export function normalizeChanges(value: unknown): SectorChanges {
  const input = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  const status = input.status === 'ok' || input.status === 'no_baseline' ? input.status : 'unavailable';
  const items: Record<string, SectorChange> = {};
  const raw = input.items && typeof input.items === 'object' ? (input.items as Record<string, Record<string, unknown>>) : {};
  for (const [id, row] of Object.entries(raw)) {
    if (!row || typeof row !== 'object') continue;
    items[id] = {
      scoreBefore: number(row.score_before),
      scoreNow: number(row.score_now),
      scoreDelta: number(row.score_delta),
      tier: pair(row.tier),
      flags: Array.isArray(row.flags) ? row.flags.filter((flag): flag is string => typeof flag === 'string') : [],
      risk: pair(row.risk),
      notable: row.notable === true,
    };
  }
  return {
    status,
    baselineAsOf: text(input.baseline_as_of) || null,
    baselineDate: text(input.baseline_date) || null,
    reason: text(input.reason) || (status === 'unavailable' ? '本报告没有变动记录。' : ''),
    note: text(input.note) || '变动只描述研究证据的变化，不代表收益方向，不构成投资建议。',
    items,
  };
}

/** The change record for one sector, or null when there is nothing comparable. */
export function sectorChange(report: Report | null, id: string): SectorChange | null {
  return (report?.sector_changes as SectorChanges | undefined)?.items[id] ?? null;
}

/** Whether a change says anything beyond an unchanged score. */
export function hasChange(change: SectorChange | null): change is SectorChange {
  return Boolean(change && ((change.scoreDelta ?? 0) !== 0 || change.tier || change.flags.length || change.risk));
}
