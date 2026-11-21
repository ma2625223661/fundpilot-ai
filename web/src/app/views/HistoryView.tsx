// The research journal (the old #history view): five-day review plus the saved
// reports. Clearing records is confirmed in an alert dialog.
import { useState } from 'react';
import { FileClock, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { goTo } from '@/app/navigation';
import { PageHeader } from '@/components/page-header';
import { FiveDayReview } from '@/app/research/FiveDayReview';
import { useResearch, type HistoryEntry } from '@/app/research/ResearchContext';
import { stamp } from '@/lib/format';

/** Saved reports grouped by Beijing date, newest day first, keeping their order. */
function groupByDay(entries: HistoryEntry[]): [string, HistoryEntry[]][] {
  const days = new Map<string, HistoryEntry[]>();
  for (const entry of entries) {
    const day = stamp(entry.as_of).split(' ')[0] || '日期未知';
    days.set(day, [...(days.get(day) ?? []), entry]);
  }
  return [...days];
}

export function HistoryView() {
  const { histories, historyStatus, openHistory, clearHistory, accountMode, session } = useResearch();
  const [opening, setOpening] = useState('');
  const [confirming, setConfirming] = useState(false);
  const defaultStatus = accountMode
    ? '个人记录保存到当前账号，最多保留20份。'
    : '报告保存在当前浏览器，最多保留20份。';

  async function open(entry: HistoryEntry) {
    setOpening(entry.as_of);
    try {
      await openHistory(entry);
      goTo('dash');
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setOpening('');
    }
  }

  return (
    <>
      <PageHeader
        title="研究记录"
        description="回看研究证据，复核五日表现，积累下一轮判断依据。"
        actions={
        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogTrigger
            render={
              <Button variant="destructive" disabled={!histories.length}>
                <Trash2 aria-hidden="true" />
                清空板块记录
              </Button>
            }
          />
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>清空全部研究记录？</AlertDialogTitle>
              <AlertDialogDescription className="text-pretty">
                将删除{accountMode ? '当前账号保存的' : '本浏览器保存的'} {histories.length} 份历史报告，删除后无法恢复。五日复盘的原始核验记录独立保存，不受影响。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>保留记录</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={() => {
                  setConfirming(false);
                  void clearHistory();
                }}
              >
                清空记录
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        }
      />
      {accountMode && <FiveDayReview />}
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">历史研究报告</h2>
            <Badge variant="secondary" className="tabular-nums">
              {histories.length} 份
            </Badge>
          </CardTitle>
          <CardDescription role="status" className="text-pretty">
            {historyStatus || defaultStatus}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* Grouped by day: several reports a day otherwise repeat the same date row after row. */}
          {groupByDay(histories).map(([day, entries]) => (
            <section key={day} aria-label={day + ' 的研究报告'} className="flex flex-col gap-1.5">
              <h3 className="text-sm font-semibold tabular-nums">
                {day}
                <span className="ml-2 font-normal text-muted-foreground">{entries.length} 份</span>
              </h3>
              {entries.map(entry => (
                <Button
                  key={entry.as_of}
                  variant="outline"
                  disabled={opening === entry.as_of}
                  className="h-auto justify-start gap-4 px-3 py-2 text-left whitespace-normal"
                  onClick={() => void open(entry)}
                >
                  <span className="w-16 shrink-0 text-sm font-semibold tabular-nums">{stamp(entry.as_of).split(' ')[1] || '—'}</span>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium tabular-nums">
                      {entry.cloud_record ? entry.sector_count : entry.sector_analysis.length} 个板块
                      {entry === histories[0] && <Badge variant="secondary">最近一份</Badge>}
                    </span>
                    {entry.summary && (
                      <span className="line-clamp-2 text-xs font-normal text-muted-foreground text-pretty">{entry.summary}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs font-normal text-primary">回看</span>
                </Button>
              ))}
            </section>
          ))}
          {!histories.length && (
            <div className="flex flex-col items-start gap-2 py-4">
              <FileClock className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground text-pretty">生成成功后自动保存至研究记录；刷新后可恢复进行中的任务。</p>
              {(!accountMode || session.isAdmin) && (
                <Button variant="outline" onClick={() => goTo('dash')}>
                  去板块研究首页
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}
