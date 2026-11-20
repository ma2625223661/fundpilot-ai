// Port of dist/ai-service.html: the public page explaining the AI research
// service and how to reach customer service. Opens without logging in.
import { ArrowLeft, Download, ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Brand } from '@/components/brand';
import { ThemeToggle } from '@/components/theme-toggle';

const FEATURES: [string, string][] = [
  ['板块证据解读', '结合已取得的行情、公司样本、财务与历史走势，解释支持理由和反对证据，减少手动逐项整理。'],
  ['重要事件分析', '研究已采集的公司公告与官方政策，梳理影响方向、催化强度及相关板块，保留来源与时间。'],
  ['明确建议与风险条件', '在“我的关注”中查看重点跟踪、持续观察或降低关注的研究建议，结合证据解释原因，列出后续核验重点、主要风险与判断失效条件。'],
  ['按计划自动研究', '支持 A 股交易日 09:20 / 14:50，持续更新可用证据的解读。'],
  ['看见研究依据', '在板块详情中查看走势、业绩、事件、大盘风险与综合研究依据，配合 AI 解读开展复盘。'],
  ['实际用量透明', '工作台展示本轮模型、请求次数、研究覆盖与实际 Token 用量，便于了解服务使用情况。'],
  ['康波周期机会观察', '订阅附带的长期研究工作区：对照宏观景气、短端资金与六组产业主题，查看公司证据、机会成立条件与风险，不按固定年份预测周期拐点。本页不扣研究点数。'],
];
const STEPS: [string, string][] = [
  ['添加 QQ 客服', '提供您的网站注册用户名。'],
  ['确认订阅内容', '先核对研究额度（点）、有效期与服务范围。'],
  ['管理员开通，即可使用', '在“我的 AI 订阅”查看余额与有效期，解锁板块 AI 解读。'],
];

const linkClass =
  'inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring';

export function AiServiceApp() {
  return (
    <div className="safe-bottom mx-auto flex min-h-dvh max-w-6xl flex-col gap-8 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <Brand subtitle="有依据的板块研究" />
        <div className="flex items-center gap-2">
          <a href="index.html#settings" className={linkClass}>
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            返回工作台
          </a>
          <ThemeToggle />
        </div>
      </header>
      <main className="grid items-start gap-6 lg:grid-cols-3">
        <section aria-labelledby="serviceTitle" className="flex flex-col gap-5 lg:col-span-2">
          <h1 id="serviceTitle" className="text-3xl font-semibold text-balance">
            AI 研究订阅说明
          </h1>
          <p className="text-muted-foreground text-pretty">
            订阅后由管理员为账号开通 AI 研究服务与额度，无需自行填写 API Key。自动整理板块走势、业绩证据与重要事件，查看支持理由、风险和需要继续观察的变化。
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">AI 日常研究 · 常规证据更新</Badge>
            <Badge variant="secondary">AI 深度研究 · 深入分析与复核</Badge>
          </div>
          <div className="grid gap-3 sm:grid-cols-2" aria-label="AI 自动化研究作用">
            {FEATURES.map(([title, copy], index) => (
              <Card key={title} size="sm">
                <CardContent className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground tabular-nums">{String(index + 1).padStart(2, '0')}</span>
                  <h2 className="font-semibold text-balance">{title}</h2>
                  <p className="text-sm text-muted-foreground text-pretty">{copy}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card aria-labelledby="keyNoteTitle">
            <CardHeader>
              <CardTitle>
                <h2 id="keyNoteTitle" className="text-lg font-semibold">
                  API Key 如何发挥作用？
                </h2>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm text-pretty">
              <p>API Key 是调用 AI 模型的访问凭证。配置有效密钥、检查模型权限并启用计划后，后台才会调用模型开展研究。网站登录密码与 API Key 分别管理。</p>
              <p>多人网站共用研究报告，服务密钥由管理员统一配置；个人账号无需重复填写公共密钥。后台需保持运行，实际研究取决于数据可用性、模型权限与剩余额度。</p>
              <p className="text-muted-foreground">
                AI 解读基于已采集证据，不能补造缺失行情；研究评分由既有规则计算。研究结果用于证据比较与复盘，不代表收益保证，不构成投资建议。
              </p>
            </CardContent>
          </Card>
        </section>
        <Card aria-labelledby="contactTitle" id="contact">
          <CardHeader>
            <span className="text-xs text-muted-foreground">QQ 客服</span>
            <CardTitle>
              <h2 id="contactTitle" className="text-lg font-semibold">
                咨询 AI 订阅与开通
              </h2>
            </CardTitle>
            <CardDescription className="text-pretty">使用 QQ 扫一扫添加客服，了解研究服务、可用模型、使用额度与配置方式。</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <a
              href="qq-support.png"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="打开完整 QQ 客服二维码"
              className="self-center rounded-lg focus-visible:outline-2 focus-visible:outline-ring"
            >
              <img
                src="qq-support.png"
                width={1200}
                height={1174}
                alt="QQ 客服加好友二维码，使用 QQ 扫一扫添加好友"
                className="h-auto w-full max-w-64 rounded-lg border border-border bg-card"
              />
            </a>
            <a href="qq-support.png" download="QQ客服二维码.png" className={linkClass}>
              <Download className="size-3.5" aria-hidden="true" />
              保存二维码，使用 QQ 添加
            </a>
            <a href="qq-support.png" target="_blank" rel="noopener noreferrer" className={linkClass}>
              查看大图
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
            <p className="text-xs text-muted-foreground text-pretty">手机访问可先保存图片，再在 QQ 扫一扫中从相册选择。</p>
            <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm">
              {STEPS.map(([title, copy]) => (
                <li key={title}>
                  <b className="font-medium">{title}</b>
                  <span className="block text-muted-foreground text-pretty">{copy}</span>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted-foreground text-pretty">
              套餐与价格请向客服确认。研究额度统一按“点”计算：中度推理每份 1 点，极高推理每份 1.5 点；1 份指 1 个板块的 1 期 AI 解读，按报告生成时的强度扣点。未记录强度的旧报告按 1 点；同份重复查看、未生成有效解读均不扣点。普通用户无需提供 API Key 或登录密码。
            </p>
          </CardContent>
        </Card>
      </main>
      <footer className="text-xs text-muted-foreground">FundPilot AI · 让每项研究都能找到依据。</footer>
    </div>
  );
}
