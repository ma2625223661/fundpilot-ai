import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { AppShell } from '@/app/AppShell';
import { useView, type ViewId } from '@/app/navigation';
import { CycleView } from '@/app/views/CycleView';
import { DashView } from '@/app/views/DashView';
import { DataView } from '@/app/views/DataView';
import { HistoryView } from '@/app/views/HistoryView';
import { SettingsView } from '@/app/views/SettingsView';
import { ResearchProvider } from '@/app/research/ResearchContext';
import { SubscriptionProvider } from '@/app/research/SubscriptionContext';
import { WatchlistProvider } from '@/app/research/WatchlistContext';
import { ApiError } from '@/lib/api';
import { loadSession, watchSession, type Session } from '@/lib/session';

const PAGES: Record<ViewId, () => React.ReactNode> = {
  dash: DashView,
  data: DataView,
  history: HistoryView,
  cycle: CycleView,
  settings: SettingsView,
};

function CurrentView({ view }: { view: ViewId }) {
  const Page = PAGES[view];
  return <Page />;
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
