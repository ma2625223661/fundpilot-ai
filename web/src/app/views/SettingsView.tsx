// The control centre (the old #settings view), split into tabs. Public settings
// are editable only by an administrator on the machine that runs the site (or
// the cloud admin). Old deep links such as #mobileAccess open the right tab.
import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PageHeader } from '@/components/page-header';
import { useResearch } from '@/app/research/ResearchContext';
import { AiSettings, DataSettings } from '@/app/settings/ResearchSettings';
import { AdminSubscriptionsCard, MobileAccessCard, PasswordCard, PhoneCard, SupportCard } from '@/app/settings/AccountSettings';

type SettingsTab = 'ai' | 'data' | 'account' | 'help' | 'users';

// Which tab each old section anchor lives in.
const ANCHOR_TAB: Record<string, SettingsTab> = {
  researchSettings: 'ai',
  researchDataSettings: 'data',
  cloudAccount: 'account',
  aiSupport: 'help',
  mobileAccess: 'help',
  aiSubscriptionAdmin: 'users',
};

export function SettingsView() {
  const { session, accountMode, reloadData } = useResearch();
  const canManage = session.access.can_manage_settings === true;
  const anchor = location.hash.slice(1);

  // A deep link picks the tab; afterwards the person's own choice stands until
  // the link changes again (derived during render, not in an effect).
  const [state, setState] = useState(() => ({ anchor, tab: ANCHOR_TAB[anchor] ?? ('ai' as SettingsTab) }));
  if (state.anchor !== anchor) setState({ anchor, tab: ANCHOR_TAB[anchor] ?? state.tab });

  const tabs: [SettingsTab, string, boolean][] = [
    ['ai', 'AI 研究', true],
    ['data', '数据连接', true],
    ['account', '账号与安全', accountMode],
    ['help', '订阅帮助与手机访问', true],
    ['users', '用户管理', accountMode && session.isAdmin],
  ];
  const tab = tabs.some(([id, , shown]) => id === state.tab && shown) ? state.tab : 'ai';

  // Entering the page refreshes the data connection state; a deep link scrolls to its card.
  useEffect(() => {
    void reloadData();
  }, [reloadData]);
  useEffect(() => {
    if (anchor in ANCHOR_TAB) requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: 'start' }));
  }, [anchor]);

  const remoteNote =
    session.access.scope === 'cloud'
      ? '公共研究报告与模型设置由管理员维护。您可管理自己的关注、记录和密码。'
      : session.access.scope === 'account_local'
        ? '公共设置仅限管理员在运行后台的电脑上修改。您可以管理自己的关注、研究记录和密码。'
        : '当前为局域网访问，可查看报告与连接状态。公共设置由管理员维护。';

  return (
    <>
      <PageHeader
        title="设置"
        description={canManage ? '选择研究深度与执行计划，管理数据连接和个人账号。' : '查看研究计划与数据连接状态，管理个人账号。公共设置只能由管理员在运行网站的电脑上修改。'}
      />
      {!canManage && (
        <Alert>
          <Info aria-hidden="true" />
          <AlertDescription className="text-pretty">{remoteNote}</AlertDescription>
        </Alert>
      )}
      <Tabs value={tab} onValueChange={value => setState({ anchor, tab: value as SettingsTab })} className="gap-4">
        <div className="overflow-x-auto overflow-y-hidden border-b border-border">
          <TabsList variant="line" aria-label="设置分类">
            {tabs
              .filter(([, , shown]) => shown)
              .map(([id, label]) => (
                <TabsTrigger key={id} value={id} className="px-3 text-sm">
                  {label}
                </TabsTrigger>
              ))}
          </TabsList>
        </div>
        <TabsContent value="ai" keepMounted>
          <AiSettings canManage={canManage} />
        </TabsContent>
        <TabsContent value="data" keepMounted className="flex flex-col gap-4">
          <DataSettings canManage={canManage} />
        </TabsContent>
        {accountMode && (
          <TabsContent value="account" keepMounted className="grid items-start gap-4 lg:grid-cols-2">
            <PasswordCard />
            <PhoneCard />
          </TabsContent>
        )}
        <TabsContent value="help" keepMounted className="grid items-start gap-4 lg:grid-cols-2">
          <SupportCard />
          <MobileAccessCard />
        </TabsContent>
        {accountMode && session.isAdmin && (
          <TabsContent value="users" keepMounted>
            <AdminSubscriptionsCard />
          </TabsContent>
        )}
      </Tabs>
      <footer className="text-xs text-muted-foreground text-pretty">
        FundPilot AI · 板块研究，可查证、可解释、可复盘。未评分方向可查看具体数据缺口。
      </footer>
    </>
  );
}
