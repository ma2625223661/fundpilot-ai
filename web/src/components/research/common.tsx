// Small pieces shared by the research views: outbound source links, the
// critical-risk / strong-trend markers, collapsible evidence sections and
// signed changes. Unicode symbols from the old logic are mapped to lucide icons.
import { useState, type ReactNode } from 'react';
import { ChevronDown, ExternalLink, Star, TriangleAlert } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { DIRECTION_CLASS, direction, pct } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Only https sources become links; anything else is shown as plain text. */
export function SourceLink({ url, children, className }: { url?: string | null; children: ReactNode; className?: string }) {
  let href: string | null = null;
  try {
    const parsed = new URL(String(url));
    href = parsed.protocol === 'https:' && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    href = null;
  }
  if (!href) return <span className={cn('text-sm text-muted-foreground', className)}>{children}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring',
        className,
      )}
    >
      <span className="text-pretty">{children}</span>
      <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
    </a>
  );
}

export interface Indicator {
  symbol: string;
  className: 'risk-critical' | 'trend-strong';
  label: string;
  reason?: string;
}

/** The old sectorIndicator / eventIndicator symbols ('!' and the star) as icons. */
export function IndicatorIcon({ indicator, withLabel = false }: { indicator: Indicator; withLabel?: boolean }) {
  const critical = indicator.className === 'risk-critical';
  const Icon = critical ? TriangleAlert : Star;
  const description = indicator.label + (indicator.reason ? '：' + indicator.reason : '');
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          // Not focusable: a focusable hint inside a dialog would open its own popup and
          // break the dialog's focus trap. The reason is also written out as text
          // where it matters (sector detail), and screen readers get it here.
          <span
            role="img"
            aria-label={description}
            className={cn('inline-flex items-center gap-1 text-xs font-medium', critical ? 'text-destructive' : 'text-tier-optimistic')}
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {withLabel && indicator.label}
          </span>
        }
      />
      <TooltipContent className="max-w-xs text-pretty">{description}</TooltipContent>
    </Tooltip>
  );
}

/** A labelled, collapsed-by-default evidence block (replaces the old <details>). */
export function Disclosure({
  title,
  children,
  defaultOpen = false,
  className,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className={cn('rounded-lg border border-border', className)}>
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
        <span className="text-pretty">{title}</span>
        <ChevronDown className={cn('size-4 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-2 px-3 pb-3 text-sm text-muted-foreground">{children}</CollapsibleContent>
    </Collapsible>
  );
}

/** A percentage change: the sign is always in the text, colour follows A-share red-up. */
export function Change({ value, historical = false, className }: { value: unknown; historical?: boolean; className?: string }) {
  const tone = historical ? 'unknown' : direction(value);
  return <span className={cn('tabular-nums', DIRECTION_CLASS[tone], className)}>{pct(value)}</span>;
}

/** A labelled figure in a metric grid. */
export function Stat({ label, value, note, className }: { label: ReactNode; value: ReactNode; note?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-0.5', className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
      {note && <span className="text-xs text-muted-foreground text-pretty">{note}</span>}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <span className="text-xs font-medium text-muted-foreground">{children}</span>;
}

export function BulletList({ items, fallback }: { items: string[]; fallback?: string }) {
  const rows = items.length ? items : fallback ? [fallback] : [];
  if (!rows.length) return null;
  return (
    <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-pretty">
      {rows.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}
