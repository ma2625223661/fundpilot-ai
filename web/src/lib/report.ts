// Shapes produced by the old normalizers (normalizeReport and friends). They are
// plain JavaScript objects; these aliases document intent without retyping every
// field, and the normalizers stay the single source of truth.
import { sectorResearch } from '@/lib/research';

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Report = Record<string, any>;
export type Sector = Record<string, any>;
export type ResearchEvent = Record<string, any>;
export type Source = { id: string; name: string; url: string | null; status: string; as_of: string; fetched_at: string; error: string };
export type AutoState = Record<string, any>;
export type AiConfig = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export type Tone = 'optimistic' | 'neutral' | 'cautious' | 'avoid' | 'unknown';

// The old colour function decides the tier band; map its answer to theme tokens
// instead of re-deriving bands from the score here.
const BANDS: [Tone, string][] = [
  ['optimistic', sectorResearch.colorForScore(65).color],
  ['neutral', sectorResearch.colorForScore(50).color],
  ['cautious', sectorResearch.colorForScore(30).color],
  ['avoid', sectorResearch.colorForScore(0).color],
];

export function sectorTone(sector: Sector, historical = false): Tone {
  const color = sectorResearch.colorForSector(sector, historical).color;
  return BANDS.find(([, value]) => value === color)?.[0] ?? 'unknown';
}

export const TONE_TEXT: Record<Tone, string> = {
  optimistic: 'text-tier-optimistic',
  neutral: 'text-tier-neutral',
  cautious: 'text-tier-cautious',
  avoid: 'text-tier-avoid',
  unknown: 'text-muted-foreground',
};

/** Tinted label for a tier band (text and a faint background of the same token). */
export const TONE_BADGE: Record<Tone, string> = {
  optimistic: 'bg-tier-optimistic/10 text-tier-optimistic',
  neutral: 'bg-tier-neutral/10 text-tier-neutral',
  cautious: 'bg-tier-cautious/10 text-tier-cautious',
  avoid: 'bg-tier-avoid/10 text-tier-avoid',
  unknown: 'bg-muted text-muted-foreground',
};

export const TONE_FILL: Record<Tone, string> = {
  optimistic: 'bg-tier-optimistic',
  neutral: 'bg-tier-neutral',
  cautious: 'bg-tier-cautious',
  avoid: 'bg-tier-avoid',
  unknown: 'bg-muted-foreground',
};

export const TONE_BORDER: Record<Tone, string> = {
  optimistic: 'border-l-tier-optimistic',
  neutral: 'border-l-tier-neutral',
  cautious: 'border-l-tier-cautious',
  avoid: 'border-l-tier-avoid',
  unknown: 'border-l-border',
};

/** Every source the report knows about, for resolving evidence ids to links. */
export function sourceMap(report: Report | null): Map<string, Source> {
  if (!report) return new Map();
  return new Map<string, Source>(
    [...(report.snapshot?.sources ?? []), ...(report.company_evidence?.sources ?? [])].map((row: Source) => [row.id, row]),
  );
}

export function sectorEvents(report: Report, sectorId: string): ResearchEvent[] {
  return report.event_analysis.events.filter((event: ResearchEvent) => event.sector_ids.includes(sectorId));
}

/**
 * The last `days` points of a sector's own sample index (daily closes, plus the
 * intraday estimate when there is one), for small trend lines. Sectors without
 * an independent sample index have no history in the report and get null.
 */
export function sectorTrend(sector: Sector, days = 60) {
  const index = sector.custom_index;
  const history: { date: string; value: number }[] = index?.history ?? [];
  if (!history.length) return null;
  const live = index.live_point as { date: string; value: number } | null;
  const points = (live ? [...history.filter(point => point.date !== live.date), live] : history).slice(-days);
  if (points.length < 2) return null;
  return { points, from: points[0].date, to: points[points.length - 1].date, intraday: Boolean(live) };
}

/**
 * Daily closes the backend attaches to a market index row (snapshot.market[].history).
 * Malformed points become gaps; fewer than two valid closes means no line.
 */
export function indexTrend(row: Record<string, unknown>) {
  const raw = Array.isArray(row.history) ? (row.history as Record<string, unknown>[]) : [];
  const points = raw
    .filter(point => point && typeof point.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(point.date))
    .map(point => ({
      date: point.date as string,
      value: typeof point.close === 'number' && Number.isFinite(point.close) && point.close > 0 ? point.close : null,
    }));
  if (points.filter(point => point.value !== null).length < 2) return null;
  return { points, from: points[0].date, to: points[points.length - 1].date };
}
