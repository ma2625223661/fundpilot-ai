// Daily and monthly personal AI call limits from the backend (subscription
// summary's call_quota). Counts are read, never worked out here.
export interface CallQuota {
  unlimited: boolean;
  configured: boolean;
  dailyLimit: number | null;
  monthlyLimit: number | null;
  dailyUsed: number;
  monthlyUsed: number;
  dailyRemaining: number | null;
  monthlyRemaining: number | null;
  canCall: boolean;
  day: string;
  month: string;
}

const count = (value: unknown) => (typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null);

export function readQuota(value: unknown): CallQuota | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return {
    unlimited: row.unlimited === true,
    configured: row.configured === true,
    dailyLimit: count(row.daily_limit),
    monthlyLimit: count(row.monthly_limit),
    dailyUsed: count(row.daily_used) ?? 0,
    monthlyUsed: count(row.monthly_used) ?? 0,
    dailyRemaining: count(row.daily_remaining),
    monthlyRemaining: count(row.monthly_remaining),
    canCall: row.can_call === true,
    day: typeof row.day === 'string' ? row.day : '',
    month: typeof row.month === 'string' ? row.month : '',
  };
}

/** "今日剩余 2 次，本月剩余 18 次", or why there are no calls. */
export function quotaText(quota: CallQuota | null) {
  if (!quota) return 'AI 调用次数读取中';
  if (quota.unlimited) return '管理员调用不限次数';
  if (!quota.configured) return '管理员尚未设置你的每日和每月 AI 调用次数';
  return `今日剩余 ${quota.dailyRemaining ?? 0} 次，本月剩余 ${quota.monthlyRemaining ?? 0} 次`;
}

/** Why a personal AI call cannot start right now; '' when it can. */
export function quotaBlock(quota: CallQuota | null) {
  if (!quota || quota.unlimited || quota.canCall) return '';
  if (!quota.configured) return '管理员尚未设置你的 AI 调用次数，暂不能发起';
  if ((quota.monthlyRemaining ?? 0) <= 0) return `本月调用次数已用完（${quotaText(quota)}）`;
  return `今日调用次数已用完（${quotaText(quota)}），北京时间次日 0 点恢复`;
}
