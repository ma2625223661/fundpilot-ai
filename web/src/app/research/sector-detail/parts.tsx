// Small layout helpers and the loose row type shared by the sector detail parts.
import type { ReactNode } from 'react';
import { SourceLink } from '@/components/research/common';
import { type Source } from '@/lib/report';

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="font-semibold text-balance">{title}</h4>
      {children}
    </section>
  );
}

export function Sources({ ids, sources }: { ids: string[]; sources: Map<string, Source> }) {
  const rows = [...new Set(ids)].map(id => sources.get(id)).filter(Boolean) as Source[];
  if (!rows.length) return null;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {rows.map(source => (
        <SourceLink key={source.id} url={source.url}>
          {source.name || source.id}
        </SourceLink>
      ))}
    </div>
  );
}
