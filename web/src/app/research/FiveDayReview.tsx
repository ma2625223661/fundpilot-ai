// Port of dist/research-review.js: the subscriber five-day review of followed
// sectors. Scores describe what already happened; they are not return forecasts.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Circle, CircleHelp, RefreshCw, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { DatedLine } from '@/components/charts-lazy';
import { BulletList, Disclosure, SourceLink, Stat } from '@/components/research/common';
import { goTo } from '@/app/navigation';
import { StatTile } from '@/components/page-header';
import { useResearch } from '@/app/research/ResearchContext';
import { ServiceLink } from '@/app/research/SectorAccess';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { request } from '@/lib/api';
import { review } from '@/lib/research';
import { DIRECTION_CLASS, direction } from '@/lib/format';
import { cn } from '@/lib/utils';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

const number: (value: unknown) => string = review.number;
const percent: (value: unknown) => string = review.percent;
const ACTIONS: Record<string, string> = review.actions;

function Empty({ title, description, children }: { title: string; description: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-border p-4">
      <strong className="font-medium">{title}</strong>
      <p className="text-sm text-muted-foreground text-pretty">{description}</p>
      {children}
    </div>
  );
}

function Guidance({ value }: { value: Row | undefined }) {
  const g = value || {};
  return (
    <section className="flex flex-col gap-2 rounded-lg bg-muted p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b className="font-medium">{g.name || '推荐关注指数'}</b>
        <span className="text-xs text-muted-foreground">规则计算 · 不调用 AI</span>
      </div>
      <div className="flex items-baseline gap-2">
        <strong className="text-2xl font-semibold tabular-nums">{number(g.recommendation_index)}</strong>
        <small className="text-xs text-muted-foreground">/ 100</small>
        <Badge variant="secondary">{g.label || '待评估'}</Badge>
      </div>
      <h3 className="font-medium text-balance">{g.headline || '等待完整复盘证据'}</h3>
      <p className="text-sm text-pretty">{g.reason || '推荐指数等待服务更新；缺失数据不记零分。'}</p>
      {Number.isFinite(g.effective_cap) && (
        <p className="text-xs text-muted-foreground tabular-nums">规则上限 {number(g.effective_cap)} · 与五日复盘分取较低值</p>
      )}
      {(g.before_participation || g.if_holding) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ['尚未参与', g.before_participation],
              ['已经持有时', g.if_holding],
            ] as [string, string][]
          )
            .filter(([, text]) => text)
            .map(([title, text]) => (
              <div key={title}>
                <h4 className="text-sm font-medium">{title}</h4>
                <p className="text-sm text-pretty">{text}</p>
              </div>
            ))}
        </div>
      )}
      {g.upgrade_condition && (
        <Disclosure title="何时升级 / 何时警惕 · 查看核验清单">
          <h4 className="font-medium text-foreground">升级或维持条件</h4>
          <p className="text-pretty">{g.upgrade_condition}</p>
          <h4 className="font-medium text-foreground">降级与风险条件</h4>
          <p className="text-pretty">{g.risk_condition}</p>
          <div className="flex flex-col gap-2">
            {(g.checks || []).map((check: Row, index: number) => (
              <div key={index} className="rounded-md bg-background p-2">
                <div className="flex items-center justify-between gap-2">
                  <b className="font-medium text-foreground">{check.label}</b>
                  <span className="flex items-center gap-1 text-xs">
                    {check.met === true ? (
                      <Check className="size-3" aria-hidden="true" />
                    ) : check.met === false ? (
                      <Circle className="size-3" aria-hidden="true" />
                    ) : (
                      <CircleHelp className="size-3" aria-hidden="true" />
                    )}
                    {check.met === true ? '已满足' : check.met === false ? '未满足' : '待补证据'}
                  </span>
                </div>
                <p className="text-pretty">{check.condition}</p>
                <small className="tabular-nums">当前：{check.value}</small>
              </div>
            ))}
          </div>
          {g.caps?.length > 0 && (
            <>
              <h4 className="font-medium text-foreground">当前规则上限依据</h4>
              <BulletList items={g.caps.map((limit: Row) => limit.reason + ' · 上限 ' + number(limit.maximum))} />
            </>
          )}
          {g.basis?.length > 0 && <p className="text-pretty">{g.basis.join('；')}</p>}
          <small className="tabular-nums">
            走势截至 {g.period_end || '待确认'} · 研究快照 {String(g.research_as_of || '待确认').replace('T', ' ').slice(0, 16)}
          </small>
          {g.note && <small>{g.note}</small>}
        </Disclosure>
      )}
      <p className="text-xs text-muted-foreground">推荐关注指数用于排列研究优先级，不代表收益概率，不构成投资建议。</p>
    </section>
  );
}

function Evidence({ item }: { item: Row }) {
  const e = item.evidence || {};
  const https = (s: Row) => /^https:\/\//i.test(s.url || '');
  const references = [...new Map((e.reference_sources || []).filter(https).map((s: Row) => [s.url, s])).values()] as Row[];
  return (
    <Disclosure
      title={
        '复盘依据 · ' +
        (item.review_kind === 'company' ? (e.members?.length || 0) + ' 家公司' : item.review_kind === 'rate' ? '隔夜Shibor' : '明确映射的价格指数')
      }
    >
      <p>{item.calendar_label || '交易日期待核验'}</p>
      {item.adjustment_note && <p className="text-pretty">{item.adjustment_note}</p>}
      {item.observation_only && <p className="text-pretty">按来源最近五个已发布收盘观测计算；未核验当地完整休市日历，不宣称日期连续。</p>}
      {e.members?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {e.members.map((m: Row) => (
            <Badge key={m.code} variant="outline" className="tabular-nums">
              {m.name} · {m.code}
            </Badge>
          ))}
        </div>
      )}
      {references.length > 0 && (
        <>
          <p>同日期参照 · {e.reference_label}</p>
          {references.map(source => (
            <div key={source.url} className="flex flex-wrap gap-2">
              <SourceLink url={source.url}>{source.name || '查看参照来源'}</SourceLink>
              <small className="tabular-nums">{source.as_of || '日期未提供'}</small>
            </div>
          ))}
        </>
      )}
      {(e.sources || [])
        .filter(https)
        .slice(0, 10)
        .map((source: Row, index: number) => (
          <div key={index} className="flex flex-wrap gap-2">
            <SourceLink url={source.url}>{source.name || '查看来源'}</SourceLink>
            <small className="tabular-nums">
              {source.as_of || '日期未提供'} · {source.status === 'ok' ? '已取得' : '待核验'}
            </small>
          </div>
        ))}
      {item.scope && <p className="text-pretty">{item.scope}</p>}
    </Disclosure>
  );
}

function Validation({ value = {} }: { value?: Row }) {
  const original = value.original;
  return (
    <Disclosure
      title={
        <span className="flex flex-wrap gap-2">
          <span>原始研究结论验证</span>
          <b className="font-medium tabular-nums">
            {value.status === 'completed' ? '已完成五日核验' : (value.completed_sessions || 0) + '/5 交易日'}
          </b>
        </span>
      }
    >
      <p className="text-pretty">{value.reason || '等待原始研究记录。'}</p>
      {original && (
        <>
          <p className="tabular-nums">
            记录于 {original.observed_at.replace('T', ' ').slice(0, 16)} · 当时结论：{ACTIONS[original.action] || '等待证据'} · {original.tier || '待评估'}
          </p>
          <p className="tabular-nums text-pretty">
            当时完整研究分：{number(original.score)}；已知分：{number(original.confirmed_score)}。仅完整评分才能用于对照完整研究档位。
          </p>
          <small>冻结样本：{original.sample_names.join('、')}</small>
          {value.expected_end && <p className="tabular-nums">五日核验收盘日：{value.expected_end}</p>}
        </>
      )}
      {value.status === 'completed' && (
        <>
          <p className="tabular-nums">
            {Number.isFinite(value.rate_change_bp)
              ? '原始同期限利率后续五次发布变化 ' + number(value.rate_change_bp) + ' 基点'
              : '原始样本五日涨跌 ' + percent(value.return_pct) + ' · 最大回撤 ' + number(value.drawdown_pct) + '%'}
          </p>
          {Number.isFinite(value.market_risk_change) && (
            <p className="tabular-nums">
              环境风险较记录时变化 {(value.market_risk_change > 0 ? '+' : '') + number(value.market_risk_change)} 分（当前时点对照，非期末风险回测）
            </p>
          )}
        </>
      )}
    </Disclosure>
  );
}

function RatePanel({ item }: { item: Row }) {
  const m = item.rate_metrics || {};
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-medium">隔夜资金利率 · 五次发布对照</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="最新年化利率" value={number(m.annual_rate_pct) + '%'} note="不是产品收益率" />
        <Stat label="五次发布变化" value={number(m.rate_change_5d_bp) + ' 基点'} note="正值表示利率上升" />
        <Stat label="20次发布变化" value={number(m.rate_change_20d_bp) + ' 基点'} note="同一隔夜期限" />
        <Stat label="20次发布波动" value={number(m.rate_std_20d_bp) + ' 基点'} note="利率标准差" />
      </div>
      <p className="text-xs text-muted-foreground tabular-nums">
        {item.period_start} — {item.period_end}
      </p>
      <Disclosure title="查看专用流动性模型">
        <p className="text-pretty">{item.model_method}</p>
      </Disclosure>
    </div>
  );
}

function ReviewCard({ item, onOpen }: { item: Row; onOpen: (id: string) => void }) {
  const head = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="link" className="h-auto p-0 text-base font-semibold" onClick={() => onOpen(item.id)}>
        {item.title}
        <ArrowRight aria-hidden="true" />
      </Button>
      <Badge variant="secondary">{item.score_label || (item.status === 'unsupported' ? '暂不支持' : '等待数据')}</Badge>
    </div>
  );
  if (item.status === 'pending' || item.status === 'unsupported')
    return (
      <article className="flex flex-col gap-3 rounded-lg border border-border p-3">
        {head}
        <Guidance value={item.guidance} />
        <Evidence item={item} />
        <Empty title="暂未形成复盘分" description={item.reason} />
        <Validation value={item.validation} />
      </article>
    );
  if (item.review_kind === 'rate')
    return (
      <article className="flex flex-col gap-3 rounded-lg border border-border p-3">
        {head}
        <Guidance value={item.guidance} />
        <Evidence item={item} />
        <RatePanel item={item} />
        <Validation value={item.validation} />
      </article>
    );
  const points = (item.series || []).map((s: Row, index: number) => ({
    date: String(s.date || s.trade_date || index + 1),
    value: Number.isFinite(s.value) ? s.value : null,
  }));
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-border p-3">
      {head}
      <Guidance value={item.guidance} />
      <Evidence item={item} />
      <div className="grid items-center gap-3 sm:grid-cols-3">
        <div className="flex flex-col">
          <span className="text-xs text-muted-foreground">{item.score_name || '五日走势复盘分'}</span>
          <strong className="text-3xl font-semibold tabular-nums">
            {number(item.score)}
            <small className="ml-1 text-sm font-normal text-muted-foreground">/ 100</small>
          </strong>
        </div>
        <div className="sm:col-span-2">
          {points.length > 1 && <DatedLine points={points} unit="归一化" label={item.title + '五个交易日归一化样本走势'} className="h-28" />}
          <small className="text-xs text-muted-foreground tabular-nums">
            {item.period_start} — {item.period_end} · {item.sample_count ? item.sample_count + ' 家公司样本' : '来源价格指数'}
          </small>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">衡量已发生的走势；分数越高表示本轮样本表现越强，不代表未来收益。</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="五次收盘涨跌"
          value={<span className={DIRECTION_CLASS[direction(item.return_pct)]}>{percent(item.return_pct)}</span>}
          note={item.review_kind === 'reference' ? '来源价格口径' : '本轮公司样本'}
        />
        {item.review_kind !== 'reference' && (
          <Stat
            label="相对参照"
            value={
              <span className={DIRECTION_CLASS[direction(item.excess_pct)]}>
                {Number.isFinite(item.excess_pct) ? (item.excess_pct > 0 ? '+' : '') + number(item.excess_pct) + ' 百分点' : '—'}
              </span>
            }
            note={item.reference_label || '正值表示跑赢参考'}
          />
        )}
        <Stat label="最大回撤" value={Number.isFinite(item.drawdown_pct) ? number(item.drawdown_pct) + '%' : '—'} note="期间从高点最大跌幅" />
        <Stat label="上涨次数" value={Number.isFinite(item.up_days) ? item.up_days + ' / 5 次' : '—'} note="五个收盘区间" />
      </div>
      <Disclosure title={'查看评分分项 · ' + (item.review_kind === 'reference' ? '价格模型 40 / 35 / 25' : '每项满分 25')}>
        {(item.components || []).map((component: Row, index: number) => {
          const max = component.maximum || 25;
          const measured = Number.isFinite(component.points);
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="flex justify-between">
                <span>{component.label}</span>
                <b className="font-medium tabular-nums">{measured ? number(component.points) + ' / ' + max : '待补数据'}</b>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <div className="h-full rounded-full bg-primary" style={{ width: (measured ? (component.points / max) * 100 : 0) + '%' }} />
              </div>
            </div>
          );
        })}
        {item.model_method && <p className="text-pretty">{item.model_method}</p>}
        <p className="text-pretty">参照：{item.reference_label || '沪深300公司样本'}。观察分与当前完整公司研究分分别计算。</p>
      </Disclosure>
      {item.reason && <p className="text-sm text-muted-foreground text-pretty">{item.reason}</p>}
      <Validation value={item.validation} />
      <section className="flex flex-col gap-2 rounded-lg bg-muted p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b className="flex items-center gap-1 font-medium">
            <Sparkles className="size-4" aria-hidden="true" />
            AI 复盘解读
          </b>
          <span className="text-xs text-muted-foreground">{item.ai?.status === 'completed' ? '已生成' : '正在强化分析'}</span>
        </div>
        {item.ai?.status === 'completed' ? (
          <>
            {item.ai.plan_reason && <p className="text-xs text-muted-foreground text-pretty">{item.ai.plan_reason}</p>}
            <p className="text-sm text-pretty">{item.ai.summary}</p>
            {item.ai.action_plan && (
              <div className="flex flex-col gap-2">
                <h4 className="font-medium">AI 条件式操作思路</h4>
                {(
                  [
                    ['尚未参与', item.ai.action_plan.before_participation],
                    ['已经持有时', item.ai.action_plan.if_holding],
                  ] as [string, string][]
                ).map(([title, text]) => (
                  <div key={title}>
                    <b className="text-sm font-medium">{title}</b>
                    <p className="text-sm text-pretty">{text}</p>
                  </div>
                ))}
                <h4 className="text-sm font-medium">提高关注的信号</h4>
                <BulletList items={item.ai.action_plan.upgrade_signals || []} />
                <h4 className="text-sm font-medium">需要重新评估的信号</h4>
                <BulletList items={item.ai.action_plan.risk_signals || []} />
                <small className="text-xs text-muted-foreground">依据本期五日证据给出的条件式思路，受上方最新推荐档位与风险限制约束，不构成投资建议。</small>
              </div>
            )}
            {item.ai.next_checks?.length > 0 && (
              <>
                <h4 className="text-sm font-medium">接下来核验什么</h4>
                <BulletList items={item.ai.next_checks} />
              </>
            )}
            {item.ai.lessons?.length > 0 && (
              <Disclosure title="展开本轮反思">
                <BulletList items={item.ai.lessons} />
              </Disclosure>
            )}
            <small className="text-xs text-muted-foreground tabular-nums">
              {item.ai.reasoning_effort === 'xhigh' ? '极高推理' : '中度推理'} · {String(item.ai.generated_at || '').replace('T', ' ').slice(0, 16)} · 依据{' '}
              {(item.ai.evidence_ids || []).join('、')}
            </small>
          </>
        ) : (
          <>
            <p className="text-sm text-pretty">{item.ai?.reason || '等待数据补齐后定时生成解读。'}</p>
            <small className="text-xs text-muted-foreground">解读在研究时段按计划生成；刷新页面不触发 AI 调用，本功能不扣研究点数。</small>
          </>
        )}
      </section>
    </article>
  );
}

export function FiveDayReview() {
  const { accountMode, report } = useResearch();
  const sub = useSubscription();
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('');
  const last = useRef(0);

  const load = useCallback(
    async (force = false) => {
      if (!accountMode) {
        setError('请登录账号后查看订阅复盘。');
        return;
      }
      if (!force && Date.now() - last.current < 20000) return;
      setBusy(true);
      try {
        setData(await request<Row>('/api/me/reviews'));
        setError('');
        last.current = Date.now();
      } catch (reason) {
        setError((reason as Error).message || '请稍后重新读取。');
      } finally {
        setBusy(false);
      }
    },
    [accountMode],
  );

  // Re-read when the report changes, as the old page did on every re-render.
  const reportId = report?.as_of;
  useEffect(() => {
    void load(true);
  }, [load, reportId]);

  const items: Row[] = data?.items || [];
  const active = items.length > 1 && items.some(item => item.id === filter) ? filter : '';
  const stats = data?.access && data.status !== 'empty' ? review.summary(items) : null;
  const open = (id: string) => {
    goTo('dash');
    sub.openSector(id);
  };

  return (
    <Card id="fiveDayReview" aria-labelledby="reviewHeading">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h2 id="reviewHeading" className="text-lg font-semibold">
            AI 自动化复盘
          </h2>
          <Badge variant="outline">订阅专属</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">用五个交易日的真实表现，复核研究证据与判断。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3" aria-live="polite">
        <Button variant="outline" className="self-start" disabled={busy} onClick={() => void load(true)}>
          <RefreshCw aria-hidden="true" />
          {busy ? '读取中…' : '刷新复盘'}
        </Button>
        {error ? (
          <Empty title="复盘暂未读取" description={error} />
        ) : !data ? (
          <Skeleton className="h-40" />
        ) : !data.access ? (
          <Empty title="订阅后，获得持续的研究复核" description="跟踪关注板块近五个交易日，查看量化复盘、原始结论对照与 AI 改进建议。订阅有效期内附带提供，不额外扣研究点数。">
            <ServiceLink>了解订阅服务</ServiceLink>
          </Empty>
        ) : data.status === 'empty' ? (
          <Empty title="先添加关注，建立自己的复盘清单" description="复盘围绕你的关注板块展开，与账号同步保存。">
            <Button variant="outline" onClick={() => goTo('dash')}>
              去选择关注板块
            </Button>
          </Empty>
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
                <strong className="font-semibold tabular-nums">{data.period_end ? '数据核对至 ' + data.period_end : '等待收盘数据'}</strong>
                <span className="text-xs text-muted-foreground">最近五个收盘观测 · 按各市场口径 · 订阅附带，本功能不扣研究点数</span>
              </p>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatTile value={stats!.total + ' 个'} label="关注板块" />
                <StatTile value={stats!.scored + ' 个'} label="已形成复盘分" />
                <StatTile value={stats!.verified + ' 个'} label="原始结论已核验" />
                <StatTile value={stats!.ai + ' 份'} label="AI 解读已生成" />
              </dl>
            </div>
            <p className="text-sm text-pretty">
              <b className="font-medium">怎么看复盘？</b>
              先看推荐关注档位与操作参考，再核对五日表现和原始结论。规则指数即时计算，AI 解读按时段生成。
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                定时解读 {data.schedule} · {data.reasoning_effort === 'xhigh' ? '极高推理' : '中度推理'}
              </p>
              {items.length > 1 && (
                <Select value={active} onValueChange={value => setFilter(String(value ?? ''))}>
                  <SelectTrigger className="w-48" aria-label="筛选复盘板块">
                    <SelectValue>{(value: string) => items.find(item => item.id === value)?.title || '全部关注板块'}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">全部关注板块</SelectItem>
                    {items.map(item => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className={cn('grid gap-3', 'lg:grid-cols-2')}>
              {items
                .filter(item => !active || item.id === active)
                .map(item => (
                  <ReviewCard key={item.id} item={item} onOpen={open} />
                ))}
            </div>
            <Disclosure title="两种分数如何计算？查看口径与边界">
              <h4 className="font-medium text-foreground">五日复盘与观察分 · 看已经发生的表现</h4>
              <p className="text-pretty">{data.method}</p>
              <h4 className="font-medium text-foreground">推荐关注指数 · 看接下来的研究优先级</h4>
              <p className="text-pretty">{data.guidance_method || '推荐指数等待服务更新，不把缺失数据当作零分。'}</p>
              <p className="text-pretty">
                A股公司以沪深300公司样本作参照（非官方指数）；港股、美股公司分别匹配恒生、标普500价格指数。参考指数与利率使用各自的观察模型，依据可在板块卡片中展开。公司样本回溯存在选样偏差；原始研究验证使用记录时冻结的全部样本。缺少数据不记零分。
              </p>
              {data.note && <p className="text-pretty">{data.note}</p>}
              <p className="text-pretty">
                原始复核记录独立保存180天；清空个人历史报告不影响复核证据。为控制调用费用，每次定时研究最多生成一批8个复盘解读，其余排队等待。
              </p>
            </Disclosure>
          </>
        )}
      </CardContent>
    </Card>
  );
}
