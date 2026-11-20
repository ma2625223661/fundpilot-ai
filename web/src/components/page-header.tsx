import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/**
 * The heading block every page starts with: title, one line of purpose, actions.
 * The title is the page's name in the sidebar, so a page never has two names.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-2xl flex-col gap-2">
        {eyebrow && <span className="text-sm font-medium text-primary">{eyebrow}</span>}
        <h1 className="text-3xl font-semibold text-balance">{title}</h1>
        <p className="text-muted-foreground text-pretty">{description}</p>
      </div>
      {actions && <div className="flex flex-col items-end gap-2">{actions}</div>}
    </header>
  );
}

/** A large figure with its label, for summary rows at the top of a section. */
export function StatTile({ value, label, tone, note }: { value: ReactNode; label: string; tone?: string; note?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-muted p-3">
      <dd className={cn('text-2xl font-semibold tabular-nums', tone)}>{value}</dd>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      {note && <span className="text-xs text-muted-foreground text-pretty">{note}</span>}
    </div>
  );
}
