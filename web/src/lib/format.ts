// Display helpers with the same output as the old frontend's private helpers
// (stamp, compactDate, num, pct, txt, arr). They only format values; scores,
// tiers and changes come from @/lib/research or the API.
import { sectorResearch } from '@/lib/research';

export const UNKNOWN: string = sectorResearch.UNKNOWN;
export const MAX_COMPANY_SAMPLES = 8;
export const GROUP_LABELS: Record<string, string> = {
  industry: '行业主题',
  broad: '宽基指数',
  overseas: '海外市场',
  style: '风格策略',
  defensive: '防守资产',
  commodity: '商品资产',
  other: '其他方向',
};

export const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
export const txt = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback);
export const arr = <T = any>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
export const num = (value: unknown, digits = 2) => (finite(value) ? value.toFixed(digits) : UNKNOWN);
export const pct: (value: unknown) => string = sectorResearch.pct;

/** Beijing time for timestamps; plain dates (YYYY-MM-DD) are shown as they are. */
export function stamp(value: unknown): string {
  if (!value || typeof value !== 'string') return UNKNOWN;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return UNKNOWN;
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
}

export function compactDate(value: unknown): string {
  if (typeof value === 'string' && /^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
  return value ? stamp(value) : UNKNOWN;
}

/** Only http(s) links leave the site, always in a new tab without referrer. */
export function safeUrl(value: unknown): string | null {
  try {
    const url = new URL(String(value));
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export const CURRENCY: Record<string, string> = { CNY: '元', HKD: '港元', USD: '美元' };

/** Direction of a change for colouring: the sign itself always stays in the text. */
export function direction(value: unknown): 'rise' | 'fall' | 'flat' | 'unknown' {
  if (!finite(value)) return 'unknown';
  return value > 0 ? 'rise' : value < 0 ? 'fall' : 'flat';
}

export const DIRECTION_CLASS = {
  rise: 'text-rise',
  fall: 'text-fall',
  flat: 'text-flat',
  unknown: 'text-muted-foreground',
} as const;
