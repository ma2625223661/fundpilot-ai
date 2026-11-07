// Port of renderAi / renderAiCost / nextAiText: model, request count, coverage,
// actual token usage and the cost-protection strip. Unknown counts stay unknown.
import { ExternalLink, Settings, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Disclosure, Stat } from '@/components/research/common';
import { goTo } from '@/app/navigation';
import { useResearch } from '@/app/research/ResearchContext';
import { sectorResearch } from '@/lib/research';
import { UNKNOWN, finite, stamp, txt } from '@/lib/format';

export function useNextAiText() {
  const { state, config, report, aiEnabled } = useResearch();
  const calendar = state.ai_calendar || config?.ai_calendar;
  if (aiEnabled && config?.schedule?.mode === 'market_sessions' && calendar && calendar.status !== 'verified')
    return txt(calendar.reason, '交易日历尚未核验，暂停自动 AI 研究。');
  if (!aiEnabled) return '自动 AI 当前关闭';
  const nextRun = state.ai_next_run_at || config?.ai_next_run_at;
  const next = nextRun ? '下次实际 AI 调用：' + stamp(nextRun) : '下次实际 AI 调用：等待后台计划';
  return (sectorResearch.aiActivityPresentation(config, state, report?.ai_research || {}).reinforcing ? '正在强化分析 · 整理已有证据；' : '') + next;
}

export function AiPanel() {
  const { report, state, config, aiEnabled, session } = useResearch();
  const nextText = useNextAiText();
  const ai = report?.ai_research || state.ai_research || {};
  const usage = ai.usage || {};
  const activity = sectorResearch.aiActivityPresentation(config, state, ai);
  const cost = sectorResearch.costPresentation(state.ai_cost, ai);
  const badge = !config
    ? '配置读取中'
    : !config.configured
      ? '未配置 API Key'
      : aiEnabled
        ? '已验证 · 自动 AI 已启用'
        : config.verification === 'failed'
          ? '密钥校验失败'
          : '自动 AI 当前关闭';
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-balance">
            <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
            {activity.title}
          </h2>
        </CardTitle>
        <CardDescription className="text-pretty">
          {activity.detail ||
            txt(
              ai.summary || ai.error,
              aiEnabled
                ? '后台将按已保存的时间计划研究板块证据，并显示实际用量。'
                : '启用 AI 后自动研究板块行情、市场新闻与风险理由；量化分析继续独立运行。',
            )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Badge variant="outline">{badge}</Badge>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label="本轮模型"
            value={ai.model || config?.model ? sectorResearch.modelLabel(ai.model || config?.model, ai.reasoning_effort || config?.reasoning_effort) : UNKNOWN}
          />
          <Stat label="API 请求" value={finite(ai.request_count) ? String(ai.request_count) : finite(ai.calls) ? String(ai.calls) : UNKNOWN} />
          <Stat
            label="AI 已研究 / 计划板块"
            value={finite(ai.analyzed_count) && finite(ai.target_count) ? ai.analyzed_count + ' / ' + ai.target_count : UNKNOWN}
          />
          <Stat
            label="实际 Token 用量"
            value={finite(usage.total_tokens) ? String(usage.total_tokens) : finite(ai.total_tokens) ? String(ai.total_tokens) : UNKNOWN}
          />
        </div>
        <section aria-labelledby="aiCostTitle" className="flex flex-col gap-3 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="aiCostTitle" className="font-semibold">
              费用保护
            </h3>
            <Badge variant={cost.status === 'blocked' ? 'destructive' : 'secondary'}>{cost.label}</Badge>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="今日实际请求 / 计费次数" value={cost.requests} />
            <Stat label="计费折算 Token / 上限" value={cost.tokens} />
            <Stat label="本轮复用有效解读" value={cost.reused} />
          </div>
          {cost.unknown && <p className="text-sm text-warning text-pretty">{cost.unknown}</p>}
          <Disclosure title="查看板块与事件用量">
            {cost.kinds.length ? (
              cost.kinds.map((row: Record<string, string>) => (
                <div key={row.label} className="flex flex-wrap justify-between gap-2 rounded-md bg-muted p-2 tabular-nums">
                  <b className="font-medium text-foreground">{row.label}</b>
                  <span>{row.requests} 次请求</span>
                  <small>
                    实际输入 {row.prompt} · 输出 {row.completion} Token
                  </small>
                </div>
              ))
            ) : (
              <p>今日尚无可展示的分类用量记录。</p>
            )}
            <p className="text-pretty">
              {cost.note} 当前推理倍率：{cost.multiplier}×；实际 Token 与计费折算分别展示。
            </p>
          </Disclosure>
        </section>
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-muted-foreground tabular-nums text-pretty">{nextText}</p>
          <div className="ml-auto flex flex-wrap gap-2">
            <a
              href="ai-service.html"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
            >
              AI 自动化作用 · QQ 订阅咨询
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
            {session.isAdmin && (
              <Button variant="outline" onClick={() => goTo('researchSettings')}>
                <Settings aria-hidden="true" />
                管理 AI 与时间计划
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
