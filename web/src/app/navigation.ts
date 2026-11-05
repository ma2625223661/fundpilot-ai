import { useSyncExternalStore } from 'react';
import { Database, History, LineChart, Settings, Waves, type LucideIcon } from 'lucide-react';

export type ViewId = 'dash' | 'data' | 'history' | 'cycle' | 'settings';

export interface ViewEntry {
  id: ViewId;
  label: string;
  icon: LucideIcon;
}

export const VIEWS: ViewEntry[] = [
  { id: 'dash', label: '板块研究', icon: LineChart },
  { id: 'data', label: '数据依据', icon: Database },
  { id: 'history', label: '研究记录', icon: History },
  { id: 'cycle', label: '康波周期', icon: Waves },
  { id: 'settings', label: '模型与数据设置', icon: Settings },
];

// Old links point at sections inside the settings page (for example #mobileAccess).
export const SETTINGS_ANCHORS = ['mobileAccess', 'researchSettings', 'researchDataSettings', 'aiSupport'];

/** The location hash selects the view, so old bookmarks such as /index.html#cycle keep working. */
export function viewFromHash(hash: string): ViewId {
  const id = hash.replace(/^#/, '');
  if (SETTINGS_ANCHORS.includes(id)) return 'settings';
  return VIEWS.some(view => view.id === id) ? (id as ViewId) : 'dash';
}

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}

export function useView() {
  return useSyncExternalStore(subscribe, () => viewFromHash(location.hash), () => 'dash' as ViewId);
}

export function goTo(view: string) {
  if (location.hash.slice(1) !== view) location.hash = view;
  window.scrollTo({ top: 0 });
}
