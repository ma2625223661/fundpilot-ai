// AI research settings (applyConfig, the AI settings form and testAi).
// Saving a schedule never calls the model; it only applies to later runs.
// The form state and texts are in ./ai-form.ts, the form sections in ./AiSections.tsx.
import { useRef, useState, type FormEvent } from 'react';
import { PlugZap, Save, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldGroup } from '@/components/ui/field';
import { useNextAiText } from '@/app/research/AiPanel';
import { useResearch } from '@/app/research/ResearchContext';
import { request } from '@/lib/api';
import { txt } from '@/lib/format';
import { MODEL, SCHEDULE, type Row } from '@/app/settings/research-settings/shared';
import { budgetLimits, calendarSummary, savedSummary, useAiForm } from '@/app/settings/research-settings/ai-form';
import { BudgetSection, DepthSection, ScheduleSection, ServicePitch } from '@/app/settings/research-settings/AiSections';

export function AiSettings({ canManage }: { canManage: boolean }) {
  const { config, configError, applyConfig, poll, state, accountMode, session } = useResearch();
  const nextText = useNextAiText();
  const cloud = session.access.scope === 'cloud';
  const { shown, edit, reset } = useAiForm(config);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('保存计划不会立即调用研究模型。');
  const keyInput = useRef<HTMLInputElement>(null);
  const locked = !canManage || busy;

  const saved = savedSummary(config, configError);
  const calendarText = calendarSummary(state.ai_calendar || config?.ai_calendar);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !canManage) return;
    const budget = budgetLimits(shown);
    if ('error' in budget) {
      setStatus(budget.error);
      return;
    }
    const key = shown.key.trim();
    if ((!accountMode || !cloud) && !key && !config?.configured) {
      toast.error('请输入 AI API Key');
      keyInput.current?.focus();
      return;
    }
    if (/\s/.test(key)) {
      toast.error('API Key 不能包含空白字符');
      return;
    }
    setBusy(true);
    setStatus('正在保存设置并检查配置…');
    try {
      const data = await request<Row>(
        '/api/ai/config',
        {
          ...(key ? { key } : {}),
          responses_base_url: shown.baseUrl.trim(),
          model: MODEL,
          reasoning_effort: shown.reasoning,
          enabled: shown.enabled,
          schedule: SCHEDULE,
          cost_controls: budget.limits,
        },
        60000,
      );
      reset();
      applyConfig(data.config || data);
      const message =
        data.connection?.ok === false && !data.connection?.skipped
          ? '设置已保存，连接校验未通过：' + txt(data.connection.error, '请检查密钥或模型')
          : '研究设置已保存，按北京时间计划运行。';
      setStatus(message);
      toast.success(message);
      void poll();
    } catch (error) {
      setStatus((error as Error).message);
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    if (busy) return;
    setBusy(true);
    setStatus('正在检查连接与模型权限…');
    try {
      const data = await request<Row>('/api/ai/test', {}, 60000);
      applyConfig(data.config || config);
      setStatus(
        data.connection?.ok === true
          ? '连接与模型权限检查通过；实际研究用量见首页。'
          : '连接检查未通过：' + txt(data.connection?.error || data.error, '请检查配置'),
      );
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="researchSettings" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">AI 研究与执行计划</h2>
          <Badge variant="outline">研究控制台</Badge>
        </CardTitle>
        <CardDescription role="status" className="text-pretty">
          {saved}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} noValidate>
          <FieldGroup>
            <ServicePitch />
            <DepthSection
              shown={shown}
              edit={edit}
              locked={locked}
              cloud={cloud}
              accountMode={accountMode}
              configured={Boolean(config?.configured)}
              keyInput={keyInput}
            />
            <ScheduleSection shown={shown} edit={edit} locked={locked} cloud={cloud} calendarText={calendarText} nextText={nextText} />
            <BudgetSection shown={shown} edit={edit} locked={locked} />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">保存后应用于后续研究，不会立即发起模型调用。</p>
              <div className="flex gap-2">
                <Button type="button" variant="outline" disabled={locked || !config?.configured} onClick={() => void test()}>
                  <PlugZap aria-hidden="true" />
                  检查连接
                </Button>
                <Button type="submit" disabled={locked}>
                  <Save aria-hidden="true" />
                  保存研究设置
                </Button>
              </div>
            </div>
            <p role="status" aria-live="polite" className="text-sm text-pretty">
              {status}
            </p>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}
