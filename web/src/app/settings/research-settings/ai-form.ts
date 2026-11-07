// State and text helpers of the AI settings form: the saved configuration fills
// the form until the person starts editing, the status lines, and the budget
// checks done before saving.
import { useState } from 'react';
import { txt } from '@/lib/format';
import { DEFAULT_COST, MODEL, reasoningLabel, type Row } from '@/app/settings/research-settings/shared';

export interface AiForm {
  reasoning: string;
  enabled: boolean;
  key: string;
  baseUrl: string;
  reuse: boolean;
  requests: number | null;
  tokens: number | null;
}

export type EditAiForm = (patch: Partial<AiForm>) => void;

const EMPTY: AiForm = {
  reasoning: 'xhigh',
  enabled: false,
  key: '',
  baseUrl: '',
  reuse: DEFAULT_COST.reuse_enabled,
  requests: DEFAULT_COST.daily_request_limit,
  tokens: DEFAULT_COST.daily_token_limit,
};

/** The form values: saved ones until the first edit, then the person's own. */
export function useAiForm(config: Row | null) {
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState<AiForm>(EMPTY);
  // Saved values fill the form until the person starts editing it.
  const shown: AiForm =
    dirty || !config
      ? form
      : {
          ...form,
          reasoning: config.reasoning_effort === 'medium' ? 'medium' : 'xhigh',
          enabled: config.enabled === true,
          baseUrl: txt(config.responses_base_url),
          reuse: { ...DEFAULT_COST, ...config.cost_controls }.reuse_enabled,
          requests: { ...DEFAULT_COST, ...config.cost_controls }.daily_request_limit,
          tokens: { ...DEFAULT_COST, ...config.cost_controls }.daily_token_limit,
        };
  const edit: EditAiForm = patch => {
    setForm({ ...shown, ...patch });
    setDirty(true);
  };
  /** After a successful save: back to the saved values, with the key field cleared. */
  const reset = () => {
    setDirty(false);
    setForm({ ...shown, key: '' });
  };
  return { shown, edit, reset };
}

/** The line under the card title: what is saved and whether it checked out. */
export function savedSummary(config: Row | null, configError: string) {
  return configError
    ? configError
    : !config
      ? '正在读取后台配置…'
      : config.configured
        ? '已保存 ' +
          txt(config.key_hint, '密钥') +
          ' · ' +
          (config.verification === 'verified' ? '校验通过' : txt(config.error, '等待校验')) +
          (config.model === MODEL ? ' · ' + MODEL + ' / ' + reasoningLabel(config.reasoning_effort) : '')
        : '尚未配置 API Key，量化板块分析可独立运行。';
}

/** Whether the trading calendar behind the schedule has been verified. */
export function calendarSummary(calendar: Row | null | undefined) {
  return calendar
    ? calendar.status === 'verified'
      ? '交易日历已核验' + (calendar.year ? '（' + calendar.year + ' 年）' : '') + (calendar.source ? ' · ' + calendar.source : '') + '。'
      : txt(calendar.reason, '交易日历尚未核验，暂停自动研究。')
    : '';
}

/** The budget to send, or the message explaining which limit is out of range. */
export function budgetLimits(shown: AiForm): { limits: Row } | { error: string } {
  const limits = { reuse_enabled: shown.reuse, daily_request_limit: Number(shown.requests), daily_token_limit: Number(shown.tokens) };
  if (!Number.isInteger(limits.daily_request_limit) || limits.daily_request_limit < 1 || limits.daily_request_limit > 10000) {
    return { error: '请输入1至10000的每日请求上限。' };
  }
  if (!Number.isInteger(limits.daily_token_limit) || limits.daily_token_limit < 1000 || limits.daily_token_limit > 1000000000) {
    return { error: '请输入1000至1000000000的每日Token预算。' };
  }
  return { limits };
}
