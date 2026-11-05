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
