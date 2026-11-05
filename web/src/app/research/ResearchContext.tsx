// Port of the state and polling half of dist/sector-research.js: the latest
// report, the background job status, the personal history records and the AI /
// data configuration that several views read. Rendering lives in the views.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { request } from '@/lib/api';
import { sectorHistory, sectorResearch } from '@/lib/research';
import { arr, stamp } from '@/lib/format';
import type { AiConfig, AutoState, Report, Sector } from '@/lib/report';
import type { Session } from '@/lib/session';
import { normalizeChanges } from '@/lib/changes';

/**
 * normalizeReport() keeps only the fields it knows, so the backend's change block
 * is validated and re-attached. A report that was already normalized keeps its block.
 */
function withChanges(source: Report | null | undefined, input: Report): Report | null {
  const next = sectorResearch.normalizeReport(input);
  if (!next) return next;
  const block = source?.sector_changes;
  return { ...next, sector_changes: block && typeof block === 'object' && 'baselineAsOf' in block ? block : normalizeChanges(block) };
}

const HISTORY_KEY = 'fundpilot_sector_history_v1';
const RETIRED_KEYS = ['fundpilot_history_v3', 'fundpilot_history_v2', 'fundpilot_codes_v3', 'fundpilot_constraints_v3', 'fundpilot_prefs', 'fundpilot_ds'];

/* eslint-disable @typescript-eslint/no-explicit-any */
export type HistoryEntry = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

interface ResearchValue {
  session: Session;
  /** Account edition: records live on the server, not in this browser. */
  accountMode: boolean;
  report: Report | null;
  state: AutoState;
  config: AiConfig | null;
  configError: string;
  dataConfig: AiConfig | null;
  publicData: AiConfig | null;
  dataError: string;
  notice: string;
  viewingHistory: boolean;
  histories: HistoryEntry[];
  historyStatus: string;
  aiEnabled: boolean;
  selected: string | null;
  select: (id: string | null) => void;
  refresh: () => Promise<void>;
  openHistory: (entry: HistoryEntry) => Promise<void>;
  returnLatest: () => void;
  clearHistory: () => Promise<boolean>;
  reloadConfig: () => Promise<void>;
  applyConfig: (value: AiConfig) => void;
  reloadData: () => Promise<void>;
  applyDataConfig: (value: AiConfig | null, supplemental?: AiConfig | null) => void;
  applyUnlockedSector: (raw: Sector, reportId: string) => boolean;
  poll: () => Promise<void>;
}

const ResearchContext = createContext<ResearchValue | null>(null);

export function useResearch() {
  const value = useContext(ResearchContext);
  if (!value) throw new Error('useResearch must be used inside ResearchProvider');
  return value;
}

function readLocalHistory(): HistoryEntry[] {
  try {
    return arr<HistoryEntry>(JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'))
      .map((row): HistoryEntry | null => sectorResearch.normalizeReport(row))
      .filter((row): row is HistoryEntry => row !== null)
      .slice(0, 20);
  } catch {
    return [];
  }
}

export function ResearchProvider({ session, children }: { session: Session; children: ReactNode }) {
  const accountMode = Boolean(session.user);
  const [report, setReport] = useState<Report | null>(null);
  const [state, setState] = useState<AutoState>({});
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [configError, setConfigError] = useState('');
  const [dataConfig, setDataConfig] = useState<AiConfig | null>(null);
  const [publicData, setPublicData] = useState<AiConfig | null>(null);
  const [dataError, setDataError] = useState('');
  const [notice, setNotice] = useState('');
  const [viewingHistory, setViewingHistory] = useState(false);
  const [histories, setHistories] = useState<HistoryEntry[]>(() => (accountMode ? [] : readLocalHistory()));
  const [historyStatus, setHistoryStatus] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const live = useRef({ report: null as Report | null, version: '', needsRefresh: false, viewingHistory: false, polling: false, timer: 0, status: '' });
  const historyStore = useMemo(() => sectorHistory.createHistoryStore(), []);
  // Kept in step synchronously, so a save issued while records are still loading
  // writes the merged list (the old code read its module variable the same way).
  const historyRef = useRef(histories);
  const commitHistories = useCallback((rows: HistoryEntry[]) => {
    historyRef.current = rows;
    setHistories(rows);
  }, []);
  const historyRevision = useRef(0);
  const historyLoaded = useRef<Promise<void> | null>(null);
  const historyReady = useRef(!accountMode);

  // The sector workspace never restores the former fund product records.
  useEffect(() => {
    RETIRED_KEYS.forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch {
        // Storage unavailable: nothing to remove.
      }
    });
  }, []);

  useEffect(() => {
    const historyItem = (value: HistoryEntry) => (accountMode && value?.cloud_record ? value : sectorResearch.normalizeReport(value));
    historyLoaded.current = historyStore
      .load()
      .then((value: { items: HistoryEntry[] }) => {
        historyReady.current = true;
        const seen = new Set<string>();
        commitHistories(
          [...historyRef.current, ...value.items.map(historyItem).filter(Boolean)]
            .filter(row => !seen.has(row.as_of) && (seen.add(row.as_of), true))
            .sort((a, b) => b.as_of.localeCompare(a.as_of))
            .slice(0, 20),
        );
        if (accountMode)
          setHistoryStatus(session.access.scope === 'cloud' ? '个人记录已从云端加载，仅当前账号可见。' : '个人记录已从后台加载，仅当前账号可见。');
      })
      .catch(() => {
        if (accountMode) setHistoryStatus('个人记录加载失败，请刷新页面重试。');
      });
  }, [accountMode, commitHistories, historyStore, session.access.scope]);

  const saveHistory = useCallback(
    async () => {
      const revision = ++historyRevision.current;
      try {
        await historyLoaded.current;
        if (!historyReady.current) throw new Error('个人记录尚未从后台加载，请刷新页面后重试。');
        const result = await historyStore.save(historyRef.current);
        if (revision !== historyRevision.current) return true;
        setHistoryStatus(
          ['cloud', 'account'].includes(result.backend)
            ? `最近 ${result.saved_count} 份记录已保存到您的${result.backend === 'cloud' ? '云端' : '网站'}账号。`
            : result.backend === 'memory'
              ? '本机存储不可用，记录仅在本次打开期间保留。'
              : result.limited
                ? `本机存储空间不足：重开网页后可恢复最近 ${result.saved_count} 份；其余仅在本次打开期间保留。`
                : `最近 ${result.saved_count} 份报告已保存到本机，最多保留 20 份。`,
        );
        return true;
      } catch (error) {
        setHistoryStatus('记录保存失败：' + (error as Error).message);
        return false;
      }
    },
    [historyStore],
  );

  const showReport = useCallback((next: Report | null) => {
    live.current.report = next;
    setReport(next);
  }, []);

  const acceptReport = useCallback(
    (raw: Report, stale = false) => {
      const next = withChanges(raw, { ...raw, report_stale: stale || raw?.report_stale === true });
      if (!next) return false;
      live.current.viewingHistory = false;
      setViewingHistory(false);
      showReport(next);
      if (!next.report_stale && !historyRef.current.some(h => h.as_of === next.as_of)) {
        commitHistories([next, ...historyRef.current].slice(0, 20));
        void saveHistory();
      }
      return true;
    },
    [commitHistories, saveHistory, showReport],
  );

  const poll = useCallback(async () => {
    const current = live.current;
    if (current.polling) return;
    current.polling = true;
    clearTimeout(current.timer);
    try {
      const s = await request<AutoState>('/api/auto/status?summary=1');
      current.status = s.status;
      setState(s);
      if (s.ai_config) setConfig(s.ai_config);
      if (!current.viewingHistory && s.has_report && (s.report_version !== current.version || !current.report || current.needsRefresh)) {
        const data = await request<{ report: Report; report_stale?: boolean; report_version?: string }>('/api/auto/report', undefined, 60000);
        if (!current.viewingHistory && acceptReport(data.report, Boolean(data.report_stale))) {
          current.needsRefresh = false;
          current.version = data.report_version || s.report_version;
          setNotice(data.report_stale ? '当前为历史快照，最新市场状态待更新；推荐指数暂不作为当前判断。' : '');
        } else if (!current.viewingHistory) setNotice('系统正在切换到板块专用研究，新报告完成后自动显示。');
      }
    } catch (error) {
      current.needsRefresh = true;
      const message = (error as Error).name === 'TimeoutError' ? '请求超时，将自动重试。' : (error as Error).message;
      setState(previous => ({ ...previous, connection_error: true, connection_message: message }));
      if (current.report && !current.viewingHistory) {
        showReport(withChanges(current.report, { ...current.report, report_stale: true }));
        setNotice('当前为上次成功报告，最新行情状态尚未确认。');
      }
    } finally {
      current.polling = false;
      current.timer = window.setTimeout(() => void poll(), ['running', 'idle'].includes(current.status) ? 5000 : 30000);
    }
  }, [acceptReport, showReport]);

  const reloadConfig = useCallback(async () => {
    try {
      const data = await request<{ config?: AiConfig }>('/api/ai/config');
      setConfigError('');
      setConfig(data.config || data);
    } catch (error) {
      setConfigError('AI 配置读取失败：' + (error as Error).message);
    }
  }, []);

  const applyDataConfig = useCallback((value: AiConfig | null, supplemental?: AiConfig | null) => {
    if (value) setDataConfig(sectorResearch.normalizeDataConfig(value));
    if (supplemental) setPublicData(supplemental);
  }, []);

  const reloadData = useCallback(async () => {
    try {
      const data = await request<{ config?: AiConfig; supplemental?: AiConfig }>('/api/data/config');
      setDataError('');
      applyDataConfig(data.config || data, data.supplemental);
    } catch (error) {
      setDataError(
        (error as Error).name === 'TimeoutError' ? '数据连接状态读取超时，请稍后重试。' : '数据连接状态读取失败：' + (error as Error).message,
      );
    }
  }, [applyDataConfig]);

  useEffect(() => {
    void reloadConfig();
    void reloadData();
    void poll();
    const current = live.current;
    return () => clearTimeout(current.timer);
  }, [poll, reloadConfig, reloadData]);

  const refresh = useCallback(async () => {
    if (accountMode && !session.isAdmin) {
      toast.info('公共研究由后台自动更新');
      return;
    }
    try {
      const s = await request<AutoState>('/api/auto/refresh', {});
      setState(s);
      live.current.viewingHistory = false;
      live.current.needsRefresh = true;
      live.current.version = '';
      setViewingHistory(false);
      toast.success('板块研究已启动，将自动更新结果');
      void poll();
    } catch (error) {
      toast.error((error as Error).message);
    }
  }, [accountMode, poll, session.isAdmin]);

  const openHistory = useCallback(
    async (entry: HistoryEntry) => {
      const raw = entry.cloud_record
        ? (await request<{ report: Report }>('/api/me/history/report?as_of=' + encodeURIComponent(entry.as_of))).report
        : entry;
      const next = withChanges(raw, { ...raw, report_stale: true });
      if (!next) throw new Error('历史记录格式无效');
      live.current.viewingHistory = true;
      setViewingHistory(true);
      showReport(next);
      setNotice(`正在回看历史报告（${stamp(entry.as_of)}），历史指数仅供复盘。`);
    },
    [showReport],
  );

  const returnLatest = useCallback(() => {
    live.current.viewingHistory = false;
    live.current.needsRefresh = true;
    setViewingHistory(false);
    setNotice('正在读取最新报告…');
    void poll();
  }, [poll]);

  const clearHistory = useCallback(async () => {
    commitHistories([]);
    const saved = await saveHistory();
    if (saved) toast.success('板块研究记录已清空');
    return saved;
  }, [commitHistories, saveHistory]);

  const applyUnlockedSector = useCallback(
    (raw: Sector, reportId: string) => {
      const current = live.current.report;
      if (current?.as_of !== reportId) return false;
      const value = sectorResearch.normalizeSector(raw);
      const index = current.sector_analysis.findIndex((s: Sector) => s.id === value?.id);
      if (index < 0) return false;
      const sectors = [...current.sector_analysis];
      sectors[index] = value;
      showReport({ ...current, sector_analysis: sectors });
      return true;
    },
    [showReport],
  );

  const aiEnabled = config?.effective_enabled === true || Boolean(config?.configured && config?.enabled && config?.verification === 'verified');

  const value: ResearchValue = {
    session,
    accountMode,
    report,
    state,
    config,
    configError,
    dataConfig,
    publicData,
    dataError,
    notice,
    viewingHistory,
    histories,
    historyStatus,
    aiEnabled,
    selected,
    select: setSelected,
    refresh,
    openHistory,
    returnLatest,
    clearHistory,
    reloadConfig,
    applyConfig: setConfig,
    reloadData,
    applyDataConfig,
    applyUnlockedSector,
    poll,
  };
  return <ResearchContext.Provider value={value}>{children}</ResearchContext.Provider>;
}
