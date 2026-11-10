import { Suspense, lazy, useEffect, useState, type ComponentType } from 'react';
import { RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBoundary } from '@/components/error-boundary';
import { AppShell } from '@/app/AppShell';
import { useView, type ViewId } from '@/app/navigation';
import { DashView } from '@/app/views/DashView';
import { ResearchProvider } from '@/app/research/ResearchContext';
import { SubscriptionProvider } from '@/app/research/SubscriptionContext';
import { WatchlistProvider } from '@/app/research/WatchlistContext';
import { ApiError } from '@/lib/api';
import { loadSession, watchSession, type Session } from '@/lib/session';

// The home page loads with the app; the other pages are fetched the first time
// they are opened, so the first visit downloads only what the home page needs.
const PAGES: Record<ViewId, ComponentType> = {
  dash: DashView,
  data: lazy(() => import('@/app/views/DataView').then(module => ({ default: module.DataView }))),
  history: lazy(() => import('@/app/views/HistoryView').then(module => ({ default: module.HistoryView }))),
  cycle: lazy(() => import('@/app/views/CycleView').then(module => ({ default: module.CycleView }))),
  settings: lazy(() => import('@/app/views/SettingsView').then(module => ({ default: module.SettingsView }))),
  sector: lazy(() => import('@/app/views/SectorView').then(module => ({ default: module.SectorView }))),
  compare: lazy(() => import('@/app/views/CompareView').then(module => ({ default: module.CompareView }))),
};

function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="正在载入页面">
      <Skeleton className="h-16" />
      <Skeleton className="h-72" />
    </div>
  );
}

function CurrentView({ view }: { view: ViewId }) {
  const Page = PAGES[view];
  // A failing page (or a page file replaced by a newer build) shows a reload
  // notice instead of blanking the site; opening another page clears it.
  return (
    <ErrorBoundary resetKey={view}>
      <Suspense fallback={<PageSkeleton />}>
        <Page />
      </Suspense>
    </ErrorBoundary>
  );
}

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const view = useView();

  useEffect(() => {
    let cancelled = false;
    loadSession()
      .then(value => {
        if (!cancelled) setSession(value);
      })
      .catch((reason: unknown) => {
        // A 401 is already on its way to the login page.
        if (!cancelled && !(reason instanceof ApiError && reason.status === 401)) setError((reason as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  useEffect(() => watchSession(session?.user ?? null), [session]);

  if (error)
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-4">
        <Alert variant="destructive">
          <AlertTitle>无法连接研究服务</AlertTitle>
          <AlertDescription className="text-pretty">{error}。请确认网站后台仍在运行，然后重试。</AlertDescription>
        </Alert>
        <Button
          onClick={() => {
            setError('');
            setAttempt(attempt + 1);
          }}
        >
          <RefreshCw aria-hidden="true" />
          重新连接
        </Button>
      </main>
    );

  if (!session)
    return (
      <main className="flex min-h-dvh gap-4 p-4" aria-busy="true" aria-label="正在载入">
        <Skeleton className="hidden w-60 md:block" />
        <div className="flex flex-1 flex-col gap-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-40" />
          <Skeleton className="h-72" />
        </div>
      </main>
    );

  return (
    <ResearchProvider session={session}>
      <SubscriptionProvider>
        <WatchlistProvider>
          <AppShell session={session} view={view}>
            <CurrentView view={view} />
          </AppShell>
        </WatchlistProvider>
      </SubscriptionProvider>
    </ResearchProvider>
  );
}
