// AI support contact (QR code) and mobile access addresses (port of device-access.js).
import { useRef, useState } from 'react';
import { Copy, Download, MessageCircle, Smartphone } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Disclosure } from '@/components/research/common';
import { ServiceLink } from '@/app/research/SectorAccess';
import { useResearch } from '@/app/research/ResearchContext';

export function SupportCard() {
  return (
    <Card id="aiSupport" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <MessageCircle className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">AI 订阅与 QQ 客服</h2>
          <Badge variant="outline">扫码咨询</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-4 sm:flex-row">
          <a
            href="qq-support.png"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="查看 QQ 客服二维码大图"
            className="shrink-0 self-start rounded-lg focus-visible:outline-2 focus-visible:outline-ring"
          >
            <img src="qq-support.png" alt="QQ 客服加好友二维码" width={1200} height={1174} loading="lazy" className="size-40 rounded-lg border border-border bg-card object-contain" />
          </a>
          <div className="flex flex-col gap-2">
            <h3 className="font-semibold text-balance">让研究按计划自动进行</h3>
            <p className="text-sm text-pretty">中度推理每份 1 点，极高推理每份 1.5 点。咨询服务开通、额度与使用方式，了解板块解读、事件分析和风险梳理。</p>
            <ServiceLink>了解作用 / 联系客服</ServiceLink>
            <a
              href="qq-support.png"
              download="QQ客服二维码.png"
              className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
            >
              <Download className="size-3.5" aria-hidden="true" />
              保存二维码，使用 QQ 添加
            </a>
          </div>
        </div>
        <p className="text-xs text-muted-foreground text-pretty">手机可保存二维码，在 QQ 扫一扫中从相册选择。具体服务范围、使用额度与有效期，请先向客服确认。</p>
      </CardContent>
    </Card>
  );
}

// The server only ever offers private IPv4 links on this port; anything else is ignored.
function lanUrl(value: string) {
  try {
    const url = new URL(value);
    const octets = url.hostname.split('.').map(Number);
    return (
      octets.length === 4 &&
      octets.every(n => Number.isInteger(n) && n >= 0 && n <= 255) &&
      (octets[0] === 10 || (octets[0] === 192 && octets[1] === 168) || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)) &&
      url.protocol === 'http:' &&
      url.port === location.port &&
      url.pathname === '/index.html' &&
      !url.search &&
      !url.hash &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

export function MobileAccessCard() {
  const { session } = useResearch();
  const access = session.access;
  const field = useRef<HTMLInputElement>(null);
  const cloud = access.scope === 'cloud';
  let urls: string[] = [];
  let siteError = false;
  if (cloud) {
    try {
      const url = new URL(access.site_url || '');
      if (url.origin !== location.origin || url.pathname !== '/index.html' || url.search || url.hash || url.username || url.password) throw new Error();
      urls = [url.href];
    } catch {
      siteError = true;
    }
  } else urls = (Array.isArray(access.lan_urls) ? access.lan_urls : []).filter(lanUrl);
  const [chosen, setChosen] = useState('');
  const current = urls.includes(chosen) ? chosen : urls.find(url => new URL(url).hostname === location.hostname) || urls[0] || '';
  const preview = cloud && access.preview === true;
  const defaultStatus = cloud
    ? preview
      ? '本机预览网址不能直接分享给手机或外网用户。'
      : '云端访问网址；手机可使用 Wi-Fi 或移动网络。'
    : urls.length
      ? access.can_manage_settings
        ? '切换 Wi-Fi 后，请刷新页面获取新的手机访问网址。'
        : '已连接同一局域网，可用此网址继续访问。'
      : '请先将电脑连接到 Wi-Fi 或有线网络，再刷新页面。';
  const [status, setStatus] = useState('');
  const tips = cloud
    ? preview
      ? ['当前网址只用于这台电脑的本地预览。', '手机访问需先配置局域网入口或完成云端上线。']
      : ['复制上方网址，在手机浏览器中打开。', '使用自己的账号登录，关注与研究记录独立保存。', '网站由云端运行，个人电脑可以关机。']
    : [
        '手机与电脑连接同一 Wi-Fi，在手机浏览器打开上方网址。',
        access.scope === 'account_local' ? '登录自己的账号查看研究；使用期间电脑和网站后台需保持运行。' : '使用期间电脑和网站后台需保持运行。',
        '不要使用 127.0.0.1，它只代表打开网页的设备本身。',
      ];

  async function copy() {
    if (!current) return;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(current);
      else throw new Error('manual copy');
      setStatus('网址已复制，请在手机浏览器的地址栏中粘贴打开。');
    } catch {
      field.current?.focus();
      field.current?.select();
      setStatus('地址已选中，请长按或使用复制快捷键。');
    }
  }

  return (
    <Card id="mobileAccess" className="scroll-mt-16">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Smartphone className="size-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">手机访问网址</h2>
          <Badge variant="outline">{cloud ? (preview ? '仅本机预览' : '无需同一 Wi-Fi') : '同一 Wi-Fi'}</Badge>
        </CardTitle>
        <CardDescription className="text-pretty">
          {cloud
            ? preview
              ? '当前为本机账号版预览，正式托管后可跨网络访问。'
              : '在手机或电脑浏览器打开同一网址，登录自己的账号即可使用。'
            : '手机与运行网站的电脑连接同一网络后，用下方局域网地址访问。'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field>
          <FieldLabel htmlFor="mobileAccessUrl">{cloud ? (preview ? '当前电脑预览网址' : '手机与电脑通用网址') : '手机访问网址（局域网）'}</FieldLabel>
          <div className="flex gap-2">
            <Input
              id="mobileAccessUrl"
              ref={field}
              readOnly
              value={siteError ? '访问地址无效' : current || '未检测到可用的局域网地址'}
              className="tabular-nums"
            />
            <Button variant="outline" disabled={!current} onClick={() => void copy()}>
              <Copy aria-hidden="true" />
              复制网址
            </Button>
          </div>
          {urls.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {urls.map(url => (
                <Button key={url} size="sm" variant={url === current ? 'secondary' : 'outline'} onClick={() => setChosen(url)}>
                  {new URL(url).hostname}
                </Button>
              ))}
            </div>
          )}
          <FieldDescription role="status">{status || defaultStatus}</FieldDescription>
        </Field>
        <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
          {tips.map(tip => (
            <li key={tip} className="text-pretty">
              {tip}
            </li>
          ))}
        </ol>
        <Disclosure title="为什么手机打不开？">
          <p className="text-pretty">
            {cloud
              ? preview
                ? '请先由管理员配置手机可访问的入口；127.0.0.1 只代表打开网页的设备本身。'
                : '先检查手机网络和网址；若提示备案限制，请联系管理员完成备案。'
              : '请确认手机与电脑在同一网络、网站后台仍在运行，并检查电脑防火墙是否允许该端口。手机需使用电脑的局域网 IP，不能使用 127.0.0.1。'}
          </p>
        </Disclosure>
      </CardContent>
    </Card>
  );
}
