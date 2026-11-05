import { cn } from '@/lib/utils';

/** The product mark: a solid tile with the initials, no image needed. */
export function Brand({ subtitle, compact, className }: { subtitle?: string; compact?: boolean; className?: string }) {
  return (
    <a
      href="/index.html"
      className={cn(
        'flex items-center gap-2 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-semibold text-primary-foreground"
      >
        FP
      </span>
      {compact ? (
        <span className="sr-only">FundPilot AI</span>
      ) : (
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="font-semibold">FundPilot AI</span>
          {subtitle && <span className="truncate text-xs text-muted-foreground">{subtitle}</span>}
        </span>
      )}
    </a>
  );
}
