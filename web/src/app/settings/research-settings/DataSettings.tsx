// Data connections: the BaoStock and multi-source data checks.
import { useEffect, useRef, useState } from 'react';
import { Database, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Disclosure, SourceLink } from '@/components/research/common';
import { useResearch } from '@/app/research/ResearchContext';
import { request } from '@/lib/api';
import { sectorResearch } from '@/lib/research';
import { arr, finite, stamp, txt } from '@/lib/format';
import { CAPABILITY, type Row } from '@/app/settings/research-settings/shared';

function Capability({ row, extra }: { row: Row; extra?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-md bg-muted p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b className="text-sm font-medium">{txt(row.label)}</b>
        <Badge variant={['available', 'verified', 'ok'].includes(row.status) ? 'secondary' : 'outline'}>
          {CAPABILITY[row.status] || '尚未核验'}
        </Badge>
      </div>
      {extra && <small className="text-xs text-muted-foreground tabular-nums">{extra}</small>}
      {(row.error || row.note || row.message) && <small className="text-xs text-muted-foreground text-pretty">{txt(row.error || row.note || row.message)}</small>}
      {row.checked_at && <small className="text-xs text-muted-foreground tabular-nums">检查时间：{stamp(row.checked_at)}</small>}
    </div>
  );
}

export function DataSettings({ canManage }: { canManage: boolean }) {
  const { dataConfig, publicData, dataError, reloadData, applyDataConfig } = useResearch();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [publicBusy, setPublicBusy] = useState(false);
  const [publicMessage, setPublicMessage] = useState('');
  const delay = useRef(1500);
  const presentation = sectorResearch.dataStatusPresentation(dataConfig);
  const checking = dataConfig?.verification === 'checking';
  const publicChecking = publicData?.verification === 'checking';

  // While a check runs on the server, re-read its status with a growing delay.
  useEffect(() => {
    if (!checking && !publicChecking) {
      delay.current = 1500;
      return;
    }
    const timer = setTimeout(() => {
      delay.current = Math.min(6000, delay.current * 2);
      void reloadData();
    }, publicChecking ? 2500 : delay.current);
    return () => clearTimeout(timer);
  }, [checking, publicChecking, dataConfig, publicData, reloadData]);

  async function dataAction(path: string, text: string) {
    if (busy || checking) return;
    setBusy(true);
    setMessage(text);
    try {
      const data = await request<Row>(path, {}, 90000);
      delay.current = 1500;
      const next = sectorResearch.normalizeDataConfig(data.config || data);
      applyDataConfig(data.config || data);
      setMessage(sectorResearch.dataStatusPresentation(next).message);
      toast.success(next.verification === 'checking' ? '已开始检查数据连接' : '数据源状态已更新');
    } catch (error) {
      const text = (error as Error).name === 'TimeoutError' ? '连接检查请求超时，请稍后重新检查。' : (error as Error).message;
      setMessage(text);
      toast.error(text);
    } finally {
      setBusy(false);
    }
  }

  async function testPublic() {
    if (publicBusy) return;
    setPublicBusy(true);
    setPublicMessage('正在请求真实官方成分、公司行情和已披露财务样本…');
    try {
      const data = await request<Row>('/api/data/public/test', {});
      applyDataConfig(null, data.supplemental);
      setPublicMessage('');
    } catch (error) {
      setPublicMessage('多源连接检查失败：' + (error as Error).message);
    } finally {
      setPublicBusy(false);
      void reloadData();
    }
  }

  const publicBadge: Record<string, string> = {
    checking: '正在取数',
    verified: '样本取数通过',
    partial: '部分取得',
    failed: '取数未通过',
    unverified: '自动研究已接入',
  };
  return (
    <>
      <Card id="researchDataSettings" className="scroll-mt-16">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <Database className="size-4 text-muted-foreground" aria-hidden="true" />
            <h2 className="text-lg font-semibold">多源数据连接</h2>
            <Badge variant="outline">{publicData ? publicBadge[publicData.verification] || '等待检查' : '等待检查'}</Badge>
          </CardTitle>
          <CardDescription className="text-pretty">中证官方成分名单 + 腾讯公司行情 + 东方财富财务，共同提供板块研究依据。</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <ol className="flex flex-wrap gap-2 text-sm">
            {['官方成分', '行情与财务', '板块研究'].map((label, index) => (
              <li key={label} className="rounded-md bg-muted px-2 py-1">
                <small className="mr-1 text-xs text-muted-foreground tabular-nums">0{index + 1}</small>
                {label}
              </li>
            ))}
          </ol>
          <p role="status" className="text-sm text-pretty">
            {publicMessage ||
              (publicData
                ? (publicData.error || publicData.scope || '真实样本检查，不代表全板块覆盖') +
                  (publicData.last_checked_at ? ' · 检查于 ' + stamp(publicData.last_checked_at) : '')
                : '连接检查使用真实样本；部分成功不代表全板块完成。')}
          </p>
          <Button variant="outline" className="self-start" disabled={!canManage || publicBusy || publicChecking} onClick={() => void testPublic()}>
            <RefreshCw aria-hidden="true" />
            检查多源连接
          </Button>
          <div className="grid gap-2 sm:grid-cols-2">
            {arr<Row>(publicData?.capabilities).map((row, index) => (
              <Capability
                key={index}
                row={{ ...row, status: row.status === 'available' ? 'available' : row.status, error: '', message: row.note }}
                extra={'记录 / 配置数量：' + (finite(row.count) ? row.count : 0)}
              />
            ))}
          </div>
          <Disclosure title="连接通过后，为什么仍可能未评分？">
            <p className="text-pretty">
              评分须同时满足有效数据、明确指标映射及对应评分模型。股票样本、债券与可转债分别使用对应模型；样本检查通过不代表每个板块均已完成覆盖。
            </p>
          </Disclosure>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <Database className="size-4 text-muted-foreground" aria-hidden="true" />
            <h2 className="text-lg font-semibold">BaoStock 数据连接</h2>
            <Badge variant="outline">{dataError ? '状态读取失败' : dataConfig ? presentation.badge : '正在检测'}</Badge>
          </CardTitle>
          <CardDescription>备用数据源 · 行业标签、公司行情与财务</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-pretty">
            {dataError ||
              (dataConfig
                ? presentation.description + (dataConfig.last_verified_at ? ' 检查于 ' + stamp(dataConfig.last_verified_at) : '')
                : '检测本机是否安装 BaoStock，数据状态以实际取数结果为准。')}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!canManage || busy || checking}
              onClick={() => void dataAction('/api/data/config', '正在检查 BaoStock 数据连接…')}
            >
              检查数据连接
            </Button>
            <Button
              variant="outline"
              disabled={!canManage || busy || checking}
              onClick={() => void dataAction('/api/data/test', '正在检查行业成分、行情和财务数据…')}
            >
              <RefreshCw aria-hidden="true" />
              重新检查
            </Button>
          </div>
          <p role="status" aria-live="polite" className="text-sm text-pretty">
            {message || (dataConfig && !checking ? presentation.message : '')}
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {arr<Row>(dataConfig?.capabilities).map(row => (
              <Capability key={row.id} row={row} extra={finite(row.count) ? '有效记录：' + row.count : undefined} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4">
            <SourceLink url="https://github.com/baostock/baostock">BaoStock 安装说明</SourceLink>
            <SourceLink url="https://akshare.akfamily.xyz/">AKShare 数据源</SourceLink>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
