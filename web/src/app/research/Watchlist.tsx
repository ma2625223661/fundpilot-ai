// Port of the watchlist half of dist/cloud-account.js: the account's followed
// sectors with their score, change, risk, AI research state and shortcuts.
import { useState } from 'react';
import { ArrowRight, Plus, RefreshCw, Sparkles, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { BulletList, Disclosure, SourceLink } from '@/components/research/common';
import { ResearchControl, openSubscriptionChoices } from '@/app/research/ResearchControl';
import { useResearch } from '@/app/research/ResearchContext';
import { ScarcityBadge } from '@/app/research/Scarcity';
import { ServiceLink } from '@/app/research/SectorAccess';
import { useSubscription } from '@/app/research/SubscriptionContext';
import { useWatchlist } from '@/app/research/WatchlistContext';
import { goTo } from '@/app/navigation';
import { sectorResearch } from '@/lib/research';
import { DIRECTION_CLASS, direction, stamp } from '@/lib/format';
import { TONE_BORDER, TONE_TEXT, sectorTone, sectorTrend, sourceMap, type Report, type Sector } from '@/lib/report';
import { Sparkline } from '@/components/sparkline';
import { ChangeLine } from '@/app/research/Changes';
import { cn } from '@/lib/utils';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */


function Breakdown({ sector, historical }: { sector: Sector; historical: boolean }) {
  const parts = sector.score_breakdown || {};
  return (
    <section aria-label={(historical ? '历史' : '') + '研究分项'} className="flex flex-col gap-1.5">
      {(
        [
          ['fundamentals', '基本面', 40],
          ['trend', '走势', 30],
          ['catalysts', '事件催化', 30],
        ] as [string, string, number][]
      ).map(([key, label, max]) => {
        const part = parts[key] || {};
        const value = key === 'catalysts' ? part.observed_adjustment : part.points;
        const measured = Number.isFinite(value);
        let display = measured
          ? (key === 'catalysts' && value > 0 ? '+' : '') + value.toFixed(2) + (key === 'catalysts' ? ' / ±30' : ' / ' + max)
          : '待评估';
        if (key === 'catalysts' && measured && !Number.isFinite(part.points)) display += ' · 部分';
        const width = measured ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
        return (
          <div key={key} className="flex flex-col gap-0.5">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">{label}</span>
              <b className="font-medium tabular-nums">{display}</b>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <div
                className={cn('h-full rounded-full', measured && value < 0 ? 'bg-fall' : 'bg-primary')}
                style={{ width: width + '%' }}
              />
            </div>
          </div>
        );
      })}
      {historical && <small className="text-xs text-muted-foreground">历史分项仅供复盘，最新研究待更新。</small>}
    </section>
  );
}

function AiSection({ sector, report, title, onOpen }: { sector: Sector; report: Report; title: string; onOpen: () => void }) {
  const research = useResearch();
  const sub = useSubscription();
  const advice = sectorResearch.researchAdvicePresentation(sector, report);
  const runtime = { subscription: sub.subscription, config: research.config, state: research.state };
  const config = research.config;
  const canConnect = config?.configured && config.enabled !== false;
  const needsConnection = canConnect && (config.verification !== 'verified' || config.effective_enabled === false);
  let service: Row = sectorResearch.aiServicePresentation(sector, report, runtime);
  // The research control is always shown on an account page, as in the old code.
  if (canConnect && !service.completed && !service.unlockable && !service.subscribe && service.status !== 'locked')
    service = {
      ...service,
      status: 'manual',
      tag: needsConnection ? '订阅专属 · 点击连接' : '订阅专属 · 点击生成',
      title: needsConnection ? '连接后开始本板块研究' : '由您决定何时开始研究',
      detail: needsConnection
        ? '点击下方“连接并生成研究”，系统会先核验服务，再梳理本板块证据与详细建议；连接或研究失败不扣点。'
        : '关注板块和查看行情不会启动个人 AI 研究。选择推理深度后，点击下方按钮开始；完成后展示研究建议、风险与核验条件。',
    };
  const saved = service.completed ? sectorResearch.researchSavedPresentation(sector, report) : null;
  const detailed = sector.ai_advice || {};
  const sources = sourceMap(report);
  const [unlockStatus, setUnlockStatus] = useState('');
  return (
    <section className="flex flex-col gap-2 rounded-lg bg-muted p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
        <h3 className="font-semibold">AI 板块研究</h3>
        <Badge variant="outline">{service.tag}</Badge>
      </div>
      <strong className="text-sm font-medium text-pretty">{service.title}</strong>
      <p className="text-sm text-muted-foreground text-pretty">{service.detail}</p>
      {saved?.saved && (
        <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
          {saved.generatedAt ? <time dateTime={saved.generatedAt}>{saved.label}</time> : <span>{saved.label}</span>}
          <small>{saved.note}</small>
          <small>{saved.dataLabel}</small>
        </div>
      )}
      {service.completed && service.status !== 'completed' && (
        <>
          <strong className="text-sm font-medium">{advice.label}</strong>
          {advice.summary && <p className="text-sm text-pretty">{advice.summary}</p>}
        </>
      )}
      {service.eventNotice && !service.subscribe && <small className="text-xs text-muted-foreground text-pretty">{service.eventNotice}</small>}
      {service.completed && (
        <Disclosure title="展开 AI 分析、风险与复核条件">
          <p className="text-pretty">{sector.ai_analysis}</p>
          {advice.watchPoints.length > 0 && (
            <>
              <b className="font-medium text-foreground">接下来关注</b>
              <BulletList items={advice.watchPoints} />
            </>
          )}
          {(
            [
              ['evidence_chain', '建议依据与推理', ['fact', 'interpretation']],
              ['action_plan', '可执行的研究步骤', ['trigger', 'step']],
              ['scenarios', '不同情景如何应对', ['condition', 'response']],
            ] as [string, string, [string, string]][]
          ).map(([key, heading, fields]) => {
            const rows: Row[] = Array.isArray(detailed[key]) ? detailed[key].slice(0, 3) : [];
            if (!rows.length) return null;
            return (
              <div key={key}>
                <b className="font-medium text-foreground">{heading}</b>
                <ol className="flex list-decimal flex-col gap-1 pl-5">
                  {rows.map((row, index) => {
                    const ids: string[] = Array.isArray(row?.evidence_ids) ? row.evidence_ids.filter((id: unknown) => typeof id === 'string').slice(0, 4) : [];
                    return (
                      <li key={index}>
                        {typeof row?.[fields[0]] === 'string' && <strong className="font-medium text-foreground">{row[fields[0]]}</strong>}
                        {typeof row?.[fields[1]] === 'string' && <p className="text-pretty">{row[fields[1]]}</p>}
                        {ids.length > 0 && (
                          <div className="flex flex-wrap gap-x-2">
                            <small>依据：</small>
                            {ids.map((id, i) => {
                              const source: Row | undefined = sources.get(id);
                              const name = [source?.name, source?.title, source?.label].find(v => typeof v === 'string' && v.trim());
                              return (
                                <SourceLink key={id} url={source?.url || source?.source_url}>
                                  {name ? name.trim().slice(0, 80) : '来源 ' + (i + 1)}
                                </SourceLink>
                              );
                            })}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </div>
            );
          })}
          {Array.isArray(detailed.review_conditions) && detailed.review_conditions.length > 0 && (
            <>
              <b className="font-medium text-foreground">何时重新评估</b>
              <BulletList items={detailed.review_conditions.filter((v: unknown) => typeof v === 'string').slice(0, 3)} />
            </>
          )}
          {sector.ai_risks.length > 0 && (
            <>
              <b className="font-medium text-foreground">主要风险</b>
              <BulletList items={sector.ai_risks} />
            </>
          )}
          {sector.ai_invalidation && <p className="text-pretty">判断失效条件：{sector.ai_invalidation}</p>}
        </Disclosure>
      )}
      {service.unlockable ? (
        <div className="flex flex-wrap items-center gap-2">
          <small className="text-xs text-muted-foreground">解锁后可反复查看</small>
          <Button size="sm" onClick={async () => setUnlockStatus(await sub.unlock(sector, report))}>
            {report.report_stale ? '解锁历史' : '解锁本期'}
          </Button>
          <small role="status" className="text-xs">
            {unlockStatus}
          </small>
        </div>
      ) : service.subscribe && !research.session.isAdmin && !['active', 'exhausted'].includes(sub.subscription?.status) ? (
        <div className="flex flex-wrap items-center gap-2" aria-label={title + '：了解 AI 板块研究，咨询 QQ 客服'}>
          <small className="text-xs text-muted-foreground">了解服务 · QQ 客服咨询</small>
          <ServiceLink>订阅查看</ServiceLink>
        </div>
      ) : null}
      <ResearchControl sector={sector} report={report} onOpen={onOpen} />
    </section>
  );
}

function WatchCard({ id, report, busy, onOpen, onRemove }: { id: string; report: Report | null; busy: boolean; onOpen: () => void; onRemove: () => void }) {
  const sector: Sector | undefined = report?.sector_analysis.find((s: Sector) => s.id === id);
  const title = sector?.title || id;
  if (!sector || !report)
    return (
      <article className="flex flex-col gap-2 rounded-lg border border-border p-3">
        <div className="flex items-center justify-between gap-2">
          <b className="font-medium">{title}</b>
          <Button variant="ghost" size="icon-sm" aria-label={'取消关注' + title} disabled={busy} onClick={onRemove}>
            <X aria-hidden="true" />
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">当前报告暂未包含此板块，已保留关注。</p>
      </article>
    );
  const historical = report.report_stale;
  const data = sectorResearch.sectorDataPresentation(sector, { historical });
  const tone = sectorTone(sector, historical);
  const state = historical
    ? '历史快照'
    : !data.hasScore
      ? '待补数据'
      : sector.score_model === 'company_research_v2' && sector.score_status !== 'complete'
        ? '阶段研究'
        : '研究已更新';
  const changeTone = !historical && data.hasQuote ? direction(sector.change_pct) : 'unknown';
  const view = sectorResearch.companyScoreView(sector);
  const trend = sectorTrend(sector);
  return (
    <article className={cn('flex flex-col gap-3 rounded-lg border border-l-4 border-border p-3', TONE_BORDER[tone])}>
      <div className="flex items-center justify-between gap-2">
        <Button variant="link" className="h-auto p-0 text-base font-semibold" onClick={onOpen}>
          {title}
        </Button>
        <div className="flex items-center gap-1">
          <Badge variant="secondary">{state}</Badge>
          <Button variant="ghost" size="icon-sm" aria-label={'取消关注' + title} disabled={busy} onClick={onRemove}>
            <X aria-hidden="true" />
          </Button>
        </div>
      </div>
      <ScarcityBadge value={sector.scarcity} />
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col">
          <span className="text-xs text-muted-foreground">{historical ? '历史研究分' : '研究分'}</span>
          <strong className={cn('text-2xl font-semibold tabular-nums', TONE_TEXT[tone])}>
            {data.hasScore ? data.scoreText : '—'}
            <small className="ml-1 text-xs font-normal text-muted-foreground">{data.hasScore ? data.scoreUnit : historical ? '待更新' : '待评估'}</small>
          </strong>
        </div>
        <div className="flex flex-col" title={data.recoveryNote || undefined}>
          <span className="text-xs text-muted-foreground">
            {historical ? '历史' : ''}
            {data.changeLabel}
          </span>
          <strong className={cn('text-lg font-semibold tabular-nums', DIRECTION_CLASS[changeTone])}>{data.changeText}</strong>
          {data.dataTimeText && <small className="text-xs text-muted-foreground tabular-nums">{data.dataTimeText}</small>}
        </div>
      </div>
      <ChangeLine sectorId={sector.id} />
      {trend && (
        <div className="flex flex-col gap-1">
          <Sparkline
            points={trend.points}
            label={`${title}样本指标近 ${trend.points.length} 个交易日走势，${trend.from} 至 ${trend.to}${trend.intraday ? '，末点为盘中估值' : ''}；非官方指数`}
          />
          <small className="text-xs text-muted-foreground tabular-nums">
            样本指标近 {trend.points.length} 个交易日 · 截至 {trend.to}
            {trend.intraday ? '（末点为盘中估值）' : ''}
          </small>
        </div>
      )}
      {view && <Breakdown sector={sector} historical={historical} />}
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge variant={/高|特大/.test(data.riskText) ? 'destructive' : 'outline'}>
          {historical ? '历史行情风险 ' : '行情风险 '}
          {data.riskText}
        </Badge>
        {Number.isFinite(sector.market_risk?.score) && (
          <Badge variant={sector.market_risk.score >= 65 ? 'destructive' : 'outline'} title={sector.market_risk.level || '待核验'}>
            环境风险 {sector.market_risk.score.toFixed(0)}/100
          </Badge>
        )}
      </div>
      <AiSection sector={sector} report={report} title={title} onOpen={onOpen} />
      <Disclosure title="数据时间与研究摘要">
        <small className="tabular-nums">行情时间：{stamp(sector.as_of)}</small>
        <p className="text-pretty">{sector.summary || data.subtitle}</p>
      </Disclosure>
      <Button variant="outline" onClick={onOpen}>
        查看研究依据
        <ArrowRight aria-hidden="true" />
      </Button>
    </article>
  );
}

export function Watchlist() {
  const { report } = useResearch();
  const sub = useSubscription();
  const { items, loaded, busy, loading, status, failed, load, change: save } = useWatchlist();
  const [choice, setChoice] = useState('');
  const [note, setNote] = useState('');
  async function change(id: string, action: 'add' | 'remove') {
    setNote('');
    if ((await save(id, action)) && action === 'add') setChoice('');
  }

  const boards: Sector[] = report?.sector_analysis ?? [];
  const options = boards.filter(s => !items.includes(s.id)).sort((a, b) => a.title.localeCompare(b.title, 'zh-CN'));
  const selectedOption = options.some(s => s.id === choice) ? choice : options[0]?.id || '';
  const open = (id: string) => {
    if (!boards.some(s => s.id === id)) {
      setNote('当前报告尚未包含该板块，请等待报告更新后重试。');
      return;
    }
    goTo('dash');
    sub.openSector(id);
  };

  return (
    <Card id="cloudWatchlist" aria-busy={busy || loading}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">我的关注</h2>
          <Badge variant="secondary" className="tabular-nums">
            {loaded ? items.length + ' 个板块' : '加载中'}
          </Badge>
        </CardTitle>
        <CardDescription className="text-pretty">
          关注重点，一眼看清研究分、走势与风险。名单随账号保存，数据随报告更新。
          <span className="block tabular-nums">
            {report
              ? (report.report_stale ? '历史快照 · ' : '当前报告 · ') + stamp(report.as_of) + '；历史或阶段分保留原有口径。'
              : '研究报告加载后展示分数与依据。'}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Select
            value={selectedOption}
            onValueChange={value => setChoice(String(value))}
            disabled={busy || loading || !loaded || !selectedOption}
          >
            <SelectTrigger className="min-w-48" aria-label="选择关注板块">
              <SelectValue>
                {(value: string) =>
                  options.find(s => s.id === value)?.title || (boards.length ? '当前报告的板块均已关注' : '等待板块报告加载')
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {options.map(s => (
                <SelectItem key={s.id} value={s.id}>
                  {s.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button disabled={busy || loading || !loaded || !selectedOption} onClick={() => void change(selectedOption, 'add')}>
            <Plus aria-hidden="true" />
            {busy ? '正在保存…' : '添加关注'}
          </Button>
          <Button variant="ghost" onClick={openSubscriptionChoices}>
            选择推理深度
          </Button>
        </div>
        <p role="status" aria-live="polite" className="text-sm text-pretty">
          {note || status}
        </p>
        {failed && (
          <Button variant="outline" className="self-start" onClick={() => void load()}>
            <RefreshCw aria-hidden="true" />
            重新加载关注
          </Button>
        )}
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map(id => (
            <WatchCard key={id} id={id} report={report} busy={busy || loading} onOpen={() => open(id)} onRemove={() => void change(id, 'remove')} />
          ))}
        </div>
        {!items.length && (
          <p className="text-sm text-muted-foreground text-pretty">
            {loaded ? '尚未关注板块。选择上方板块并点击“添加关注”，即可在这里查看研究概览。' : '正在读取您的关注列表…'}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
