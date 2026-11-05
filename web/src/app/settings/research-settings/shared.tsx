// Constants and small pieces shared by the AI and data settings forms.

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export const MODEL = 'gpt-6.1-sol';

export const DEFAULT_COST = { reuse_enabled: true, daily_request_limit: 28, daily_token_limit: 8000000 };

// Only the A-share session plan is offered, as in the old form.
export const SCHEDULE = { mode: 'market_sessions', interval_minutes: 30, daily_time: '09:20', end_time: null, timezone: 'Asia/Shanghai' };

// Same wording as capabilityStatusLabels in the old sector-research.js (not exported there).
export const CAPABILITY: Record<string, string> = {
  available: '已取得',
  verified: '已取得',
  ok: '已取得',
  unverified: '尚未核验',
  checking: '检查中',
  empty: '未返回有效数据',
  timeout: '请求超时',
  error: '获取失败',
  failed: '获取失败',
  partial: '部分取得',
  not_installed: '未安装',
  unavailable: '未取得',
};

export const REASONING: Record<string, string> = { medium: '中度推理（1 点 / 份）', xhigh: '极高推理（1.5 点 / 份）' };

export const reasoningLabel = (value: unknown) => (value === 'medium' ? '中度推理' : value === 'xhigh' ? '极高推理' : '未配置');

export function SectionTitle({ index, title, children }: { index: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-t border-border pt-4">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary tabular-nums">
        {index}
      </span>
      <h3 className="text-base font-semibold">{title}</h3>
      {children}
    </div>
  );
}
