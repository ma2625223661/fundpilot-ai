// ECharts is large and only a few panels draw a chart, so the chart module is
// fetched the first time one of them is shown. A skeleton of the same height
// holds the space meanwhile.
import { Suspense, lazy, type ComponentProps } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const LazyDatedLine = lazy(() => import('@/components/charts').then(module => ({ default: module.DatedLine })));

export function DatedLine(props: ComponentProps<typeof LazyDatedLine>) {
  return (
    <Suspense fallback={<Skeleton className={cn('h-40 w-full', props.className)} aria-label="正在载入走势图" />}>
      <LazyDatedLine {...props} />
    </Suspense>
  );
}
