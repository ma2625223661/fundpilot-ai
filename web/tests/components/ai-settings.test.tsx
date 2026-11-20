// The AI settings form: saved values fill it, saving sends the expected body,
// an empty key keeps the saved one, and out-of-range budgets are refused
// before any request is made.
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { AiSettings } from '@/app/settings/research-settings/AiSettings';
import { baseReplies, renderPage, requests } from './harness';

const saved = {
  configured: true,
  enabled: true,
  verification: 'verified',
  key_hint: 'sk-…abcd',
  model: 'gpt-6.1-sol',
  reasoning_effort: 'medium',
  responses_base_url: 'https://api.example.com/v1',
  cost_controls: { reuse_enabled: false, daily_request_limit: 40, daily_token_limit: 2000000 },
};

const openConnection = () => fireEvent.click(screen.getByRole('button', { name: '管理员服务连接设置' }));

function render() {
  return renderPage(<AiSettings canManage />, {
    replies: baseReplies({ '/api/ai/config': (body: unknown) => (body ? { config: { ...saved, ...(body as object) } } : { config: saved }) }),
  });
}

describe('AI settings form', () => {
  it('shows what is saved and fills the form with it', async () => {
    render();
    expect(await screen.findByText(/已保存 sk-…abcd · 校验通过 · gpt-6.1-sol \/ 中度推理/)).toBeTruthy();
    openConnection();
    expect((screen.getByLabelText('服务商接口地址') as HTMLInputElement).value).toBe('https://api.example.com/v1');
    expect((document.getElementById('aiDailyRequestLimit') as HTMLInputElement).value).toBe('40');
  });

  it('saves the saved values plus the edit, and keeps the stored key when the field is empty', async () => {
    render();
    await screen.findByText(/已保存 sk-…abcd/);
    openConnection();
    fireEvent.change(screen.getByLabelText('服务商接口地址'), { target: { value: ' https://api.other.com/v1 ' } });
    fireEvent.click(screen.getByRole('button', { name: /保存研究设置/ }));
    await screen.findAllByText('研究设置已保存，按北京时间计划运行。');
    const post = requests().find(item => item.path === '/api/ai/config' && item.body);
    expect(post?.body).toEqual({
      responses_base_url: 'https://api.other.com/v1',
      model: 'gpt-6.1-sol',
      reasoning_effort: 'medium',
      enabled: true,
      schedule: { mode: 'market_sessions', interval_minutes: 30, daily_time: '09:20', end_time: null, timezone: 'Asia/Shanghai' },
      cost_controls: { reuse_enabled: false, daily_request_limit: 40, daily_token_limit: 2000000 },
    });
    // After saving, the key field is empty again.
    expect((screen.getByLabelText(/服务商 API Key/) as HTMLInputElement).value).toBe('');
  });

  // The number field clamps typed values to 1–10000 on blur, so an emptied field is the invalid case left.
  it('refuses an empty daily request limit without calling the server', async () => {
    render();
    await screen.findByText(/已保存 sk-…abcd/);
    const field = document.getElementById('aiDailyRequestLimit') as HTMLInputElement;
    fireEvent.change(field, { target: { value: '' } });
    fireEvent.blur(field);
    fireEvent.click(screen.getByRole('button', { name: /保存研究设置/ }));
    await waitFor(() => expect(screen.getByText('请输入 1 至 10000 的每日请求上限。')).toBeTruthy());
    expect(requests().some(item => item.path === '/api/ai/config' && item.body)).toBe(false);
  });
});
