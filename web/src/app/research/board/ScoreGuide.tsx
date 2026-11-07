// The "口径说明" popover: what the scores and columns mean.
import { Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { sectorResearch } from '@/lib/research';
import { type Report } from '@/lib/report';
import { type SortMode } from '@/app/research/board/board-view';

/**
 * Everything needed to read the table, behind one button instead of lines of
 * text above it: what each score means, the columns, the grouping of this list
 * and the event status. The short disclaimer stays visible next to the table.
 */
export function ScoreGuide({ report, sort, families, scarcity }: { report: Report; sort: SortMode; families: { id: string; label: string; note: string }[]; scarcity: boolean }) {
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" />}>
        <Info aria-hidden="true" />
        口径说明
      </PopoverTrigger>
      <PopoverContent align="end" className="max-h-(--available-height) w-80 gap-3 overflow-y-auto sm:w-96">
        <PopoverHeader>
          <PopoverTitle className="font-semibold">这些分数怎么看</PopoverTitle>
          <PopoverDescription className="text-pretty">研究分不代表收益概率，不构成投资建议。</PopoverDescription>
        </PopoverHeader>
        <dl className="flex flex-col gap-2 text-sm">
          {GUIDE.map(([term, text]) => (
            <div key={term}>
              <dt className="font-medium">{term}</dt>
              <dd className="text-muted-foreground text-pretty">{text}</dd>
            </div>
          ))}
          {scarcity && (
            <div>
              <dt className="font-medium">稀缺性标注</dt>
              <dd className="text-muted-foreground text-pretty">依据近期公告标注具体环节；点开查看原文、AI推理与疑点。稀缺标签不加分。</dd>
            </div>
          )}
        </dl>
        {families.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-border pt-2 text-sm">
            <b className="font-medium">分组口径</b>
            {families.map(family => (
              <p key={family.id} className="text-muted-foreground text-pretty">
                <span className="text-foreground">{family.label}：</span>
                {family.note}
              </p>
            ))}
          </div>
        )}
        <p className="border-t border-border pt-2 text-xs text-muted-foreground text-pretty">{sectorResearch.boardResearchNotice(report, sort)}</p>
      </PopoverContent>
    </Popover>
  );
}

const GUIDE: [string, string][] = [
  ['研究分：看证据强弱', '完整公司研究满分 100；基本面与走势合计满分 70，事件未评估时保留基础分。'],
  ['基本面 / 40、走势 / 30', '基本面看样本公司营收、净利增长与盈利状态；走势看 20 日、60 日收益与 20 日均线差。'],
  ['事件 ±30', '本批官方证据里最强利好与最强利空的调整，重复报道不叠加；"待评估"不按 0 分处理。'],
  ['行情风险、环境风险', '越高越需留意。环境风险按大盘、流动性与宏观独立计算，不扣减研究分。'],
  ['涨跌幅', '样本当日表现，红色为涨、绿色为跌；灰色或"—"表示没有可用行情，不能当作 0。'],
  ['领涨样本', '本板块公司样本中当日涨幅最大的一家，以及样本里上涨、下跌的家数和行情日期；没有报价的样本不计入涨跌家数。样本不代表全板块。'],
];
