// React versions of the DOM helpers in dist/sector-scarcity.js (badge, metrics,
// verificationDetail, detail). Normalisation stays in the legacy module.
import { Diamond } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { BulletList, Disclosure, SourceLink } from '@/components/research/common';
import { sectorScarcity } from '@/lib/research';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Raw = any;
/* eslint-enable @typescript-eslint/no-explicit-any */

const CLAIM: Record<string, string> = { fact: '事实陈述', forecast: '预测', opinion: '观点' };

export function ScarcityBadge({ value }: { value: Raw }) {
  const p = sectorScarcity.normalize(value);
  if (!p) return null;
  const text =
    p.status === 'easing' ? '稀缺约束缓解' : sectorScarcity.isMarked({ scarcity: p }) ? '稀缺线索 · ' + p.label : '稀缺性待核验';
  return (
    <Badge variant="outline" title={`${p.scope}；${p.verification.label}。${p.boundary}`}>
      <Diamond aria-hidden="true" />
      {text}
    </Badge>
  );
}

function Metrics({ p }: { p: Raw }) {
  const st = p.strength;
  const a = p.attention;
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <div className="rounded-md bg-muted p-2">
        <p className="text-xs">稀缺强度 · 公告证据</p>
        <p className="font-medium text-foreground tabular-nums">
          {st.score !== null ? st.score + ' / 100' : st.confirmed_score !== null ? '已支持 ' + st.confirmed_score + ' 分' : '待核验'}
        </p>
        <p className="text-xs text-pretty">
          {st.score !== null
            ? '4/4项有原文依据 · ' + p.verification.label
            : st.confirmed_score !== null
              ? st.coverage + '/4项有依据 · 缺项不补分'
              : '预测、争议及缺证据不定分'}
        </p>
      </div>
      <div className="rounded-md bg-muted p-2">
        <p className="text-xs">推荐关注值 · 研究分</p>
        <p className="font-medium text-foreground tabular-nums">{a.score !== null ? a.score.toFixed(2) + ' / 100' : '待完成评估'}</p>
        <p className="text-xs text-pretty">
          {a.score !== null
            ? a.label
            : a.known_score !== null
              ? '基础/阶段 ' + a.known_score.toFixed(2) + ' / ' + a.known_maximum
              : '基本面、走势与事件证据待齐'}
        </p>
      </div>
    </div>
  );
}

export function VerificationDetail({ value }: { value: Raw }) {
  const v = sectorScarcity.verification(value);
  return (
    <section className="flex flex-col gap-2 text-sm">
      <b className="font-medium text-foreground">证据研判 · {v.label}</b>
      <p className="text-pretty">{v.reason}</p>
      {v.claim_excerpt && (
        <>
          <small>发布方原文 · {CLAIM[v.claim_type] || '待辨'}</small>
          <blockquote className="border-l-2 border-border pl-3 text-pretty">{v.claim_excerpt}</blockquote>
        </>
      )}
      {v.inference && (
        <>
          <small>AI 推断</small>
          <p className="text-pretty">{v.inference}</p>
        </>
      )}
      {v.uncertainties.length > 0 && (
        <>
          <small>疑点与局限</small>
          <BulletList items={v.uncertainties} />
        </>
      )}
      {v.links.map((l: Raw, index: number) => (
        <div key={index} className="flex flex-col gap-1 rounded-md bg-muted p-2">
          <SourceLink url={l.url}>
            {(l.relation === 'contradicts' ? '相反证据' : '支持证据') + ' · ' + l.title}
          </SourceLink>
          <small>
            {l.independent ? '不同发布主体' : '同一发布主体'} · {l.published_at}
          </small>
          <blockquote className="border-l-2 border-border pl-3 text-pretty">{l.fact_excerpt}</blockquote>
          <p className="text-pretty">{l.reason}</p>
        </div>
      ))}
      {v.note && <p className="text-xs text-pretty">{v.note}</p>}
    </section>
  );
}

export function ScarcityDetail({ value, showMetrics = true }: { value: Raw; showMetrics?: boolean }) {
  const p = sectorScarcity.normalize(value);
  if (!p) return null;
  return (
    <Disclosure
      title={
        <span className="flex flex-wrap items-center gap-2">
          <ScarcityBadge value={p} />
          <span>查看原文、推理与疑点</span>
        </span>
      }
    >
      {showMetrics && <Metrics p={p} />}
      <p className="text-pretty">{p.scope}</p>
      <small>
        {p.scope_level === 'company' ? '公司及具体环节陈述' : '具体产业环节'} · {p.direction_label}
      </small>
      <p className="text-pretty">{p.basis}</p>
      <VerificationDetail value={p.verification} />
      {p.strength.dimensions.length > 0 && (
        <div className="flex flex-col gap-2">
          {p.strength.dimensions.map((d: Raw, index: number) => (
            <div key={index} className="rounded-md bg-muted p-2">
              <p className="flex justify-between gap-2 text-foreground">
                <span>{d.title}</span>
                <b className="font-medium tabular-nums">{d.points === null ? '待核验' : d.points + ' / 25'}</b>
              </p>
              <small className="text-pretty">{d.reason}</small>
              {d.fact_excerpt && (
                <Disclosure title="查看对应原文 [1]" className="mt-2">
                  <blockquote className="border-l-2 border-border pl-3 text-pretty">{d.fact_excerpt}</blockquote>
                </Disclosure>
              )}
            </div>
          ))}
          <p className="text-xs text-pretty">{p.strength.method}</p>
        </div>
      )}
      {p.attention.note && (
        <p className="text-xs text-pretty">
          {p.attention.note} ≥65且原附加条件满足为乐观看待；50～&lt;65中性；30～&lt;50谨慎；&lt;30规避。
        </p>
      )}
      <p className="text-pretty">{p.boundary}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {(
          [
            ['继续核验', p.checks],
            ['判断失效条件', p.invalidation],
          ] as [string, string[]][]
        ).map(([label, items]) => (
          <div key={label}>
            <b className="font-medium text-foreground">{label}</b>
            <BulletList items={items} />
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        {p.sources.map((s: Raw, index: number) => (
          <div key={index}>
            <SourceLink url={s.url}>{`[${index + 1}] ${s.title}`}</SourceLink>
            <small className="block">
              {s.kind} · {s.published_at}
            </small>
          </div>
        ))}
      </div>
      <small>
        AI 分析 {p.reviewed_at || '时间待核验'} · 原文有效期至 {p.review_due_at}
      </small>
      <small>订阅附带 · 稀缺标签不加分；查看不调用 AI、不另扣点。</small>
    </Disclosure>
  );
}
