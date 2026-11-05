// The account's followed sectors, shared by the dashboard watchlist and the
// sidebar shortcut list (state from the old cloud-account.js loadWatch/change).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, request } from '@/lib/api';
import { useResearch } from '@/app/research/ResearchContext';

async function api<T>(path: string, body?: unknown) {
  try {
    return await request<T>(path, body);
  } catch (error) {
    if (error instanceof ApiError && error.status === 0) throw new Error('无法连接账号服务，请检查连接后重试');
    throw error;
  }
}

interface WatchlistValue {
  available: boolean;
  items: string[];
  loaded: boolean;
  busy: boolean;
  loading: boolean;
  status: string;
  failed: boolean;
  load: () => Promise<void>;
  change: (id: string, action: 'add' | 'remove') => Promise<boolean>;
}

const WatchlistContext = createContext<WatchlistValue | null>(null);

export function useWatchlist() {
  const value = useContext(WatchlistContext);
  if (!value) throw new Error('useWatchlist must be used inside WatchlistProvider');
  return value;
}

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const { accountMode } = useResearch();
  const [items, setItems] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [failed, setFailed] = useState(false);
  const flags = useRef({ busy: false, loading: false });

  const load = useCallback(async () => {
    if (!accountMode || flags.current.loading || flags.current.busy) return;
    flags.current.loading = true;
    setLoading(true);
    setFailed(false);
    try {
      const data = await api<{ items: string[] }>('/api/me/watchlist');
      setItems(data.items);
      setLoaded(true);
      setStatus(current => (current.includes('失败') || current.includes('未确认') ? '关注列表已重新加载。' : current));
    } catch (error) {
      setStatus('关注列表读取失败：' + (error as Error).message);
      setFailed(true);
    } finally {
      flags.current.loading = false;
      setLoading(false);
    }
  }, [accountMode]);

  useEffect(() => {
    void load();
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [load]);

  const change = useCallback(
    async (id: string, action: 'add' | 'remove') => {
      if (flags.current.busy || flags.current.loading || !loaded || !id) return false;
      flags.current.busy = true;
      setBusy(true);
      setFailed(false);
      setStatus('正在保存关注列表…');
      try {
        setItems((await api<{ items: string[] }>('/api/me/watchlist', { board_id: id, action })).items);
        setStatus(action === 'add' ? '已保存关注，刷新或重新登录后保留。' : '已取消关注');
        return true;
      } catch (error) {
        setStatus('保存失败或状态未确认：' + (error as Error).message);
        setFailed(true);
        return false;
      } finally {
        flags.current.busy = false;
        setBusy(false);
      }
    },
    [loaded],
  );

  return (
    <WatchlistContext.Provider value={{ available: accountMode, items, loaded, busy, loading, status, failed, load, change }}>
      {children}
    </WatchlistContext.Provider>
  );
}
