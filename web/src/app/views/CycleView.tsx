// Port of dist/research-cycle.js: the subscriber long-wave (Kondratieff) research
// framework. Evidence coverage measures data completeness, not opportunity odds.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Circle, CircleDashed, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { BulletList, Disclosure, SourceLink } from '@/components/research/common';
import { goTo } from '@/app/navigation';
import { PageHeader } from '@/components/page-header';
import { useResearch } from '@/app/research/ResearchContext';
import { ScarcityBadge, ScarcityDetail } from '@/app/research/Scarcity';
import { ServiceLink } from '@/app/research/SectorAccess';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { request } from '@/lib/api';
import { cycle, sectorScarcity } from '@/lib/research';
import { cn } from '@/lib/utils';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

const format: (value: unknown) => string = cycle.format;
const TONE: Record<string, string> = { positive: 'text-tier-optimistic', caution: 'text-warning', neutral: 'text-foreground', pending: 'text-muted-foreground' };

function Message({ title, copy, children }: { title: string; copy: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-border p-4">
      <h3 className="font-medium">{title}</h3>
      <p className="text-sm text-muted-foreground text-pretty">{copy}</p>
      {children}
    </div>
  );
}

function Signals({ data }: { data: Row }) {
  const later: Row[] = data.signals.slice(2);
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">结论来自哪些数据</h2>
        <span className="text-xs text-muted-foreground">月度需求 + 短端资金 · 来源可追溯</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {data.signals.slice(0, 2).map((signal: Row) => {
          const reading = cycle.signalReading(signal);
          return (
            <Card key={signal.id} size="sm">
              <CardContent className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-medium">{signal.title}</h3>
                  <Badge variant="outline">{signal.status === 'ready' ? '可核验' : '待补齐'}</Badge>
                </div>
                <p className="text-2xl font-semibold tabular-nums">
                  {format(signal.value)}
                  <span className="ml-1 text-sm font-normal text-muted-foreground">{signal.unit || ''}</span>
                </p>
                <div>
                  <b className={cn('text-sm font-medium', TONE[reading.tone])}>{reading.label}</b>
                  <p className="text-sm text-muted-foreground text-pretty">{reading.copy}</p>
                </div>
                <p className="text-sm text-pretty">{signal.detail}</p>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground tabular-nums">
                  <span>数据日期 {signal.as_of ? signal.as_of.replace('T', ' ').slice(0, 16) : '尚无有效日期'}</span>
                  {signal.url && <SourceLink url={signal.url}>来源</SourceLink>}
                </div>
                <small className="text-xs text-muted-foreground text-pretty">{signal.scope}</small>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Disclosure title={`还有 ${later.filter(s => s.status !== 'ready').length} 组长期数据待补齐 · 查看缺口`}>
        {later.map(s => (
          <div key={s.id}>
            <b className="font-medium text-foreground">{s.title}</b>
            <p className="text-pretty">{s.detail}</p>
          </div>
        ))}
      </Disclosure>
    </section>
  );
}

function Scenarios({ data }: { data: Row }) {
  const [chosen, setChosen] = useState('');
  const scenario = chosen && data.scenarios.some((s: Row) => s.id === chosen) ? chosen : data.scenarios.find((s: Row) => s.active)?.id || 'repair';
  const current: Row | undefined = data.scenarios.find((s: Row) => s.id === scenario);
  return (
    <Disclosure title="如果需求或资金改变，如何观察？展开四种情景">
      <p className="text-pretty">点击情景查看对应条件与研究重点。情景用于交叉验证，不表示周期按此顺序轮转。</p>
      <ToggleGroup
        variant="outline"
        className="grid w-full grid-cols-1 sm:grid-cols-2"
        value={[scenario]}
        onValueChange={value => value[0] && setChosen(value[0])}
      >
        {data.scenarios.map((s: Row) => (
          <ToggleGroupItem key={s.id} value={s.id} className="h-auto flex-col items-start py-2 text-left whitespace-normal">
            <span className="text-xs text-muted-foreground">{s.active ? '当前观测' : '条件情景'}</span>
            <b className="font-medium">{s.title}</b>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {current && (
        <p className="rounded-md bg-muted p-2 text-pretty">
          <b className="font-medium text-foreground">{current.active ? '当前情景核验' : '情景演练'}</b> {current.condition}。{current.implication}
        </p>
      )}
    </Disclosure>
  );
}

function ScarcityClues({ data, onOpen }: { data: Row; onOpen: (id: string) => boolean }) {
  const items: Row[] = Array.isArray(data.scarcity_sectors) ? data.scarcity_sectors : [];
  const summary = data.scarcity_summary || {};
  const progress: [string, number, string][] = [
    ['本批候选', summary.candidate_count || 0, '有效公告条数'],
    ['已完成研判', summary.assessed_count || 0, '完成证据分析'],
    ['有效稀缺线索', items.filter(s => sectorScarcity.isMarked(s)).length, '获得来源支持'],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">稀缺性线索</h2>
          <Badge variant="outline">依据新闻与公告</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">看清“什么供给受限、证据是否可靠”，再判断是否值得持续研究。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <dl className="grid grid-cols-3 gap-2">
          {progress.map(([label, value, copy]) => (
            <div key={label} className="rounded-md bg-muted p-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-xl font-semibold tabular-nums">{value}</dd>
              <small className="text-xs text-muted-foreground">{copy}</small>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">
          {summary.schedule || 'A股交易日 09:20 / 14:50（北京时间）'} · 随定时研究更新
        </p>
        {!items.length && (
          <Message
            title={summary.status === 'no_supported_clues' ? '本批尚无充分稀缺证据' : '等待定时证据研判'}
            copy={
              summary.status === 'no_supported_clues'
                ? '已评估内容暂不足以形成稀缺线索，保持待核验；未标注不等于不稀缺。'
                : '将随下一次定时研究分析已采集公告，辨析支持与相反证据。证据不足时不沿用固定分数、不提前标为稀缺。'
            }
          />
        )}
        <div className="grid gap-3 md:grid-cols-2">
          {items.map(item => {
            const p = sectorScarcity.normalize(item.scarcity);
            if (!p) return null;
            return (
              <article key={item.id} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button variant="link" className="h-auto p-0 font-semibold" onClick={() => onOpen(item.id)}>
                    {item.title}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                  <ScarcityBadge value={p} />
                </div>
                <p className="text-sm text-pretty">{p.scope}</p>
                <small className="text-xs text-muted-foreground tabular-nums">
                  {p.verification.label} · {p.sources[0].published_at.slice(0, 10)}
                </small>
                <ScarcityDetail value={p} />
              </article>
            );
          })}
        </div>
        <Disclosure title="查看判断方式与数据口径">
          {data.scarcity_note && <p className="text-pretty">{data.scarcity_note}</p>}
          {summary.note && <p className="text-pretty">{summary.note}</p>}
          {summary.cost_note && <p className="text-pretty">{summary.cost_note}</p>}
        </Disclosure>
      </CardContent>
    </Card>
  );
}

function Themes({ data, onOpen }: { data: Row; onOpen: (id: string) => boolean }) {
  const [chosen, setChosen] = useState('digital');
  const [onlyWatched, setOnlyWatched] = useState(false);
  const [missing, setMissing] = useState('');
  const theme: Row = data.themes.find((t: Row) => t.id === chosen) || data.themes[0];
  if (!theme) return null;
  const items: Row[] = cycle.visibleSectors(theme, onlyWatched);
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">选择一个长期方向</h2>
        <span className="text-xs text-muted-foreground">点击主题查看板块与验证条件</span>
      </div>
      <p className="text-sm text-muted-foreground text-pretty">主题提供研究线索，是否值得关注仍需公司数据支持。以下顺序不代表投资排名。</p>
      <ToggleGroup
        variant="outline"
        className="grid w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
        value={[theme.id]}
        onValueChange={value => value[0] && setChosen(value[0])}
      >
        {data.themes.map((t: Row) => (
          <ToggleGroupItem key={t.id} value={t.id} className="h-auto flex-col items-start gap-1 p-3 text-left whitespace-normal">
            <span className="flex items-baseline gap-2">
              <small className="text-xs text-muted-foreground tabular-nums">{t.serial}</small>
              <b className="font-medium">{t.title}</b>
            </span>
            <span className="text-xs text-muted-foreground text-pretty">{t.subtitle}</span>
            <small className="text-xs text-muted-foreground tabular-nums">
              {t.evidence_count}/{t.sectors.length} 个方向有当前样本证据{t.watch_count ? ' · 已关注 ' + t.watch_count + ' 个' : ''}
            </small>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-3 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{theme.title} · 板块证据</h3>
            <div className="flex items-center gap-2">
              <Switch id="cycleOnlyWatched" checked={onlyWatched} onCheckedChange={setOnlyWatched} />
              <Label htmlFor="cycleOnlyWatched">只看我的关注</Label>
            </div>
          </div>
          <p className="text-sm text-pretty">{theme.thesis}</p>
          <p className="text-xs text-muted-foreground">研究分越高，当前证据越强；环境风险越高，外部压力越大。研究分不代表收益概率，不构成投资建议。</p>
          {!items.length && (
            <Message
              title={onlyWatched ? '此主题暂无关注板块' : '等待板块数据'}
              copy={onlyWatched ? '关闭筛选查看相关方向，再打开板块研究添加关注。' : '研究报告更新后会展示对应公司样本证据。'}
            />
          )}
          {items.map(item => {
            const reading = cycle.scoreReading(item);
            return (
              <article key={item.id} className="flex flex-col gap-2 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button
                    variant="link"
                    className="h-auto p-0 font-semibold"
                    onClick={() => setMissing(onOpen(item.id) ? '' : item.id)}
                  >
                    {item.title}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                  <Badge variant={item.watched ? 'default' : 'outline'}>{item.watched ? '已关注' : '公司样本'}</Badge>
                </div>
                {missing === item.id && <p className="text-xs text-warning">当前报告暂未包含此方向，请等待报告更新后重试。</p>}
                <div className="flex flex-wrap items-baseline gap-2">
                  <small className="text-xs text-muted-foreground">{reading.label}</small>
                  <b className="text-xl font-semibold tabular-nums">{reading.value}</b>
                  <span className="text-xs text-muted-foreground">{reading.maximum}</span>
                  <span className="text-sm text-muted-foreground">{item.status !== 'ready' ? '数据待更新' : reading.copy}</span>
                </div>
                <ScarcityDetail value={item.scarcity} />
                <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {(
                    [
                      ['基本面', item.fundamentals, 40],
                      ['走势', item.trend, 30],
                      ['事件', item.catalysts, 30],
                      ['环境风险', item.risk_score, 100],
                    ] as [string, number | null, number][]
                  ).map(([label, value, max]) => (
                    <div key={label} className="rounded-md bg-muted p-2">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className="font-medium tabular-nums">
                        {value === null ? '待评估' : (label === '事件' && value > 0 ? '+' : '') + format(value) + ' / ' + max}
                      </dd>
                    </div>
                  ))}
                </dl>
                <div className="flex flex-wrap gap-1">
                  {item.checks.map((check: Row, index: number) => (
                    <Badge key={index} variant={check.state === 'met' ? 'secondary' : 'outline'}>
                      {/* Met / not met / not yet assessed; the state is also written out for screen readers. */}
                      {check.state === 'met' ? (
                        <Check aria-hidden="true" />
                      ) : check.state === 'unmet' ? (
                        <Circle aria-hidden="true" />
                      ) : (
                        <CircleDashed aria-hidden="true" />
                      )}
                      {check.label}
                      <span className="sr-only">
                        {check.state === 'met' ? '（已满足）' : check.state === 'unmet' ? '（未满足）' : '（待评估）'}
                      </span>
                    </Badge>
                  ))}
                </div>
                <small className="text-xs text-muted-foreground tabular-nums">
                  {item.as_of ? '行情截至 ' + item.as_of.slice(0, 10) : '等待新鲜行情'}
                  {item.risk_status && item.risk_status !== 'complete' ? ' · 环境风险仅部分数据' : ''}
                </small>
              </article>
            );
          })}
        </div>
        <aside className="flex flex-col gap-2 rounded-lg bg-muted p-3">
          <span className="text-xs text-muted-foreground">研究核验清单</span>
          <h3 className="font-semibold text-balance">机会成立，需要哪些证据？</h3>
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
            {theme.next_checks.map((text: string, index: number) => (
              <li key={index} className="text-pretty">
                {text}
              </li>
            ))}
          </ol>
          <h4 className="text-sm font-medium">哪些变化会削弱判断？</h4>
          <BulletList items={theme.risks} />
          <p className="text-sm text-pretty">先核验证据，再提高关注优先级。研究条件满足不代表价格便宜，也不保证收益。</p>
          <Button variant="outline" onClick={() => goTo('history')}>
            查看五日复盘
            <ArrowRight aria-hidden="true" />
          </Button>
        </aside>
      </div>
    </section>
  );
}

export function CycleView() {
  const { accountMode, report } = useResearch();
  const sub = useSubscription();
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const last = useRef(0);

  const load = useCallback(async (force = false) => {
    if (!force && Date.now() - last.current < 20000) return;
    setBusy(true);
    try {
      setData(await request<Row>('/api/me/cycle'));
      setError('');
      last.current = Date.now();
    } catch (reason) {
      setError((reason as Error).message || '请稍后重试。');
    } finally {
      setBusy(false);
    }
  }, []);

  const reportId = report?.as_of;
  useEffect(() => {
    if (accountMode) void load(true);
  }, [accountMode, load, reportId]);

  const open = (id: string) => {
    if (!report?.sector_analysis.some((s: Row) => s.id === id)) return false;
    goTo('dash');
    sub.openSector(id);
    return true;
  };

  const status = !accountMode ? '请登录账号后查看' : busy ? '正在读取最新证据…' : error ? '读取未完成，可重新刷新' : data?.access ? '订阅附带 · 刷新不扣点' : '订阅专属研究功能';
  const active: Row | undefined = data?.scenarios?.find((s: Row) => s.active);

  return (
    <>
      <PageHeader
        title="康波周期"
        description="长期机会观察：把宏观环境、产业方向与公司证据放在一起，了解机会成立的条件，也看清风险与数据缺口。"
        actions={
          <div className="flex items-center gap-2">
            <span role="status" className="text-xs text-muted-foreground">
              {status}
            </span>
            {accountMode && (
              <Button variant="outline" disabled={busy} onClick={() => void load(true)}>
                <RefreshCw aria-hidden="true" />
                刷新周期研究
              </Button>
            )}
          </div>
        }
      />
      {!accountMode ? (
        <Message title="订阅专属研究功能" copy="康波周期观察随账号订阅提供，请登录账号后查看。" />
      ) : error ? (
        <Message title="周期研究暂未读取" copy={error} />
      ) : !data ? (
        <Skeleton className="h-96" />
      ) : !data.access ? (
        <Message
          title="为订阅者建立长期机会观察框架"
          copy="把宏观环境、产业方向与公司证据放在一起，了解机会成立的条件，也看清风险与数据缺口。订阅有效期内附带提供，本页不扣研究点数。"
        >
          <ServiceLink>了解订阅 · 联系客服</ServiceLink>
        </Message>
      ) : (
        <>
          <Card>
            <CardContent className="grid gap-4 md:grid-cols-3">
              <div className="flex flex-col gap-2 md:col-span-2">
                <span className="text-xs text-muted-foreground">当前环境 · 先看结论</span>
                <h2 className="text-2xl font-semibold text-balance">{cycle.scenarioLabel(data)}</h2>
                <p className="text-sm text-pretty">
                  {active?.implication ||
                    (data.current_scenario === 'mixed'
                      ? '资金变化暂不指向明显宽松或紧张，继续跟踪需求与公司兑现。'
                      : '宏观数据仍待补齐，暂不判断当前情景。')}
                </p>
                <Badge variant="outline">长期周期阶段仍待验证</Badge>
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-xs text-muted-foreground">宏观证据覆盖</span>
                <strong className="text-2xl font-semibold tabular-nums">
                  {data.coverage} / {data.coverage_total}
                  <span className="ml-1 text-sm font-normal text-muted-foreground">组数据可核验</span>
                </strong>
                <div className="flex gap-1" role="img" aria-label={`已有 ${data.coverage} 组宏观证据，共 ${data.coverage_total} 组`}>
                  {data.signals.map((s: Row) => (
                    <span
                      key={s.id}
                      title={s.title + (s.status === 'ready' ? ' · 可核验' : ' · 待补齐')}
                      className={cn('h-2 flex-1 rounded-full', s.status === 'ready' ? 'bg-primary' : 'bg-muted')}
                    />
                  ))}
                </div>
                <small className="text-xs text-muted-foreground">证据覆盖表示数据完整程度，不代表机会概率。</small>
              </div>
              <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums md:col-span-3">
                <span>先看环境，再选择主题，最后核验公司</span>
                <span>{data.as_of ? '报告更新 ' + data.as_of.replace('T', ' ').slice(0, 16) : '等待报告更新'}</span>
                <b className="font-medium">订阅附带 · 刷新不扣点</b>
              </p>
            </CardContent>
          </Card>
          {data.status === 'awaiting_report' && (
            <Message title="等待新鲜研究报告" copy="后台正在核验报告，或报告缺失、过期、时间无法核验。旧数据不参与当前情景与板块判断。" />
          )}
          <Signals data={data} />
          <Scenarios data={data} />
          <ScarcityClues data={data} onOpen={open} />
          <Themes data={data} onOpen={open} />
          <Disclosure title="了解康波周期、证据口径与使用边界">
            <p className="text-pretty">
              “康博周期”通常指“康波周期”（Kondratieff long wave）。本页将长波作为长期研究框架，不按固定年份预测拐点，不预设当前处于某一轮底部或起飞阶段。
            </p>
            <p className="text-pretty">{data.method}</p>
            <p className="text-pretty">
              情景规则：以新订单 PMI 的 50 分界与隔夜 Shibor 近 20 个有效发布日变化交叉观察；−5 至 +5 基点之间（不含边界）保持中间情景。阈值为本站初始研究设计，未经策略回测。两项短期数据不足以验证几十年的周期。
            </p>
            <p className="text-pretty">
              板块沿用基本面0–40、走势0–30、事件催化−30至+30的既有评分。只有完整评分进入研究档位；阶段分不能直接解释为“乐观看待”。环境风险独立显示，分数越高风险越大。公司样本不代表整个行业；估值、杠杆、现金流与主题收入需要额外核验。
            </p>
            <p className="text-pretty">本页复用已有公开数据，不生成新的付费 AI 解读。板块 AI 解读沿用原订阅规则，解锁前显示实际所需点数。</p>
            {data.references.map((ref: Row, index: number) => (
              <p key={index} className="text-pretty">
                {ref.url ? <SourceLink url={ref.url}>{ref.title}</SourceLink> : <b className="font-medium text-foreground">{ref.title}</b>}
                <span> · {ref.scope}</span>
              </p>
            ))}
          </Disclosure>
        </>
      )}
    </>
  );
}
