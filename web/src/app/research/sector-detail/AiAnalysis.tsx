// AI interpretation of a sector and its detailed advice.
import { BulletList, SourceLink } from '@/components/research/common';
import { sectorResearch } from '@/lib/research';
import { arr, txt } from '@/lib/format';
import { sourceMap, type Report, type Sector } from '@/lib/report';
import { Section, type Row } from '@/app/research/sector-detail/parts';

function DetailedAdvice({ sector, advice, report }: { sector: Sector; advice: Row; report: Report }) {
  const sources = sourceMap(report);
  const group = (title: string, rows: Row[], fields: [string, string][]) =>
    rows.length > 0 && (
      <Section title={title}>
        <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm">
          {rows.map((row, index) => (
            <li key={index} className="flex flex-col gap-1">
              {fields.map(([key, label]) => (
                <p key={key} className="text-pretty">
                  {label}：{txt(row[key])}
                </p>
              ))}
              <div className="flex flex-wrap gap-x-3">
                {arr<string>(row.evidence_ids).map((id, i) => {
                  const source: Row | undefined = sources.get(id);
                  const name = txt(source?.name || source?.title || source?.label, '来源 ' + (i + 1));
                  return source ? (
                    <SourceLink key={id} url={source.url}>
                      {name}
                    </SourceLink>
                  ) : (
                    <span key={id} className="text-sm text-muted-foreground">
                      {name}
                    </span>
                  );
                })}
              </div>
            </li>
          ))}
        </ol>
      </Section>
    );
  const scope = advice.historical
    ? '范围：生成时保存的' + (advice.scope === 'reference' ? '参考指标研究' : '公司研究') + '，请结合当时证据复盘。'
    : advice.scope === 'reference'
      ? '范围：参考指标研究，观察其走势及覆盖市场。'
      : sector.score_status !== 'complete'
        ? '范围：公司基础/阶段研究，保留 ' + sector.score_maximum + ' 分口径，先核验尚缺证据。'
        : '范围：公司研究，按当前完整研究分及其证据形成条件判断。';
  return (
    <section aria-label={advice.historical ? advice.label : '详细研究建议与核验计划'} className="flex flex-col gap-3">
      <h4 className="font-semibold text-balance">{advice.historical ? advice.label : '详细研究建议与核验计划'}</h4>
      {advice.historical && <p className="text-sm text-warning text-pretty">{advice.notice}</p>}
      <p className="text-xs text-muted-foreground text-pretty">{scope}</p>
      {group('判断依据：事实与解释', advice.evidenceChain, [
        ['fact', '证据事实'],
        ['interpretation', '研究解释'],
      ])}
      {group('下一步怎么核验', advice.actionPlan, [
        ['trigger', '触发条件'],
        ['step', '核验步骤'],
      ])}
      {group('不同情况如何调整关注', advice.scenarios, [
        ['condition', '观察到的变化'],
        ['response', '研究应对'],
      ])}
      {advice.reviewConditions.length > 0 && (
        <Section title="暂停原结论并重新复核的条件">
          <BulletList items={advice.reviewConditions} />
        </Section>
      )}
    </section>
  );
}

export function AiAnalysis({ sector, report }: { sector: Sector; report: Report }) {
  if (!(sector.ai_analysis && sector.ai_research_status === 'completed' && (report.report_stale || report.ai_research.status !== 'stale')))
    return null;
  const advice = sectorResearch.researchAdvicePresentation(sector, report);
  const historicalAdvice = sectorResearch.researchHistoricalAdvicePresentation(sector, report);
  const saved = sectorResearch.researchSavedPresentation(sector, report);
  return (
    <section className="flex flex-col gap-3 rounded-lg bg-muted p-3">
      <h4 className="font-semibold text-balance">{report.report_stale ? '历史 AI 板块解读' : 'AI 板块解读'}</h4>
      {saved.saved && (
        <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
          {saved.generatedAt ? <time dateTime={saved.generatedAt}>{saved.label}</time> : <span>{saved.label}</span>}
          <small>{saved.note}</small>
          <small>{saved.dataLabel}</small>
        </div>
      )}
      {!report.report_stale ? (
        <>
          <b className="font-medium">{advice.label}</b>
          {advice.summary && <p className="text-sm text-pretty">{advice.summary}</p>}
          {advice.watchPoints.length > 0 && (
            <Section title="后续核验重点">
              <BulletList items={advice.watchPoints} />
            </Section>
          )}
          {advice.detailed && <DetailedAdvice sector={sector} advice={advice} report={report} />}
        </>
      ) : (
        historicalAdvice && <DetailedAdvice sector={sector} advice={historicalAdvice} report={report} />
      )}
      <p className="text-sm text-pretty">{sector.ai_analysis}</p>
      {sector.ai_risks.length > 0 && (
        <Section title="AI 补充风险">
          <BulletList items={sector.ai_risks} />
        </Section>
      )}
      {sector.ai_invalidation && <p className="text-sm text-pretty">失效条件：{sector.ai_invalidation}</p>}
      <p className="text-xs text-muted-foreground">AI 解读用于整理证据，不代表收益概率，不构成投资建议。</p>
    </section>
  );
}
