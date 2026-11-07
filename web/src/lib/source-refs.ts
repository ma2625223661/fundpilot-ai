// The server sends a sector's source records as ids when snapshot.sources holds
// the identical record (research_auto.compact_sector_sources), which saves about
// 1.7 MB per report. Expand them before the old normalizer reads the report.
// Full records (historical reports, the legacy format) pass through unchanged;
// an id with no matching record is dropped rather than turned into an empty source.
import type { Report } from '@/lib/report';

type Row = Record<string, unknown>;

export function expandSourceRefs<T extends Report | null | undefined>(report: T): T {
  if (!report || !Array.isArray(report.sector_analysis)) return report;
  const sectors = report.sector_analysis as Row[];
  if (!sectors.some(sector => Array.isArray(sector?.sources) && (sector.sources as unknown[]).some(item => typeof item === 'string'))) {
    return report;
  }
  const shared = new Map<string, Row>();
  for (const row of (report.snapshot?.sources ?? []) as Row[]) {
    if (row && typeof row.id === 'string') shared.set(row.id, row);
  }
  return {
    ...report,
    sector_analysis: sectors.map(sector =>
      Array.isArray(sector?.sources)
        ? {
            ...sector,
            sources: (sector.sources as unknown[])
              .map(item => (typeof item === 'string' ? shared.get(item) : item))
              .filter(Boolean),
          }
        : sector,
    ),
  };
}
