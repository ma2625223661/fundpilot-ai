// The control centre (the old #settings view). Public settings are editable only
// by an administrator on the machine that runs the site (or the cloud admin).
import { useEffect } from 'react';
import { Info, Smartphone } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { SETTINGS_ANCHORS } from '@/app/navigation';
import { PageHeader } from '@/components/page-header';
import { useResearch } from '@/app/research/ResearchContext';
import { AiSettings, DataSettings } from '@/app/settings/ResearchSettings';
import { AdminSubscriptionsCard, MobileAccessCard, PasswordCard, PhoneCard, SupportCard } from '@/app/settings/AccountSettings';

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ block: 'start' });
  history.replaceState(null, '', '#' + id);
}

export function SettingsView() {
  const { session, accountMode, reloadData } = useResearch();
  const canManage = session.access.can_manage_settings === true;

  // Entering the page refreshes the data connection state; old deep links
  // (#mobileAccess and friends) scroll to their section.
  useEffect(() => {
    void reloadData();
    const anchor = location.hash.slice(1);
    if (SETTINGS_ANCHORS.includes(anchor)) requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: 'start' }));
  }, [reloadData]);

  const remoteNote =
    session.access.scope === 'cloud'
      ? '公共研究报告与模型设置由管理员维护。您可管理自己的关注、记录和密码。'
      : session.access.scope === 'account_local'
        ? '公共设置仅限管理员在运行后台的电脑上修改。您可以管理自己的关注、研究记录和密码。'
        : '当前为局域网访问，可查看报告与连接状态。公共设置由管理员维护。';

  return (
    <>
      <PageHeader
        eyebrow="控制中心"
        title="模型与数据设置"
        description="选择研究深度与执行计划，管理数据连接和个人账号。"
        actions={
          <Button variant="outline" onClick={() => jump('mobileAccess')}>
            <Smartphone aria-hidden="true" />
            手机访问
          </Button>
        }
      />
      <nav aria-label="设置页快捷导航" className="flex flex-wrap gap-2">
        {(
          [
            ['researchSettings', 'AI 研究'],
            ['researchDataSettings', '数据连接'],
            ['aiSupport', '订阅与帮助'],
            ...(accountMode ? [['cloudAccount', '账号与密码']] : []),
          ] as [string, string][]
        ).map(([id, label]) => (
          <Button key={id} size="sm" variant="outline" onClick={() => jump(id)}>
            {label}
          </Button>
        ))}
      </nav>
      {!canManage && (
        <Alert>
          <Info aria-hidden="true" />
          <AlertDescription className="text-pretty">{remoteNote}</AlertDescription>
        </Alert>
      )}
      <AiSettings canManage={canManage} />
      <DataSettings canManage={canManage} />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <SupportCard />
        <MobileAccessCard />
      </div>
      {accountMode && (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <PasswordCard />
          <PhoneCard />
        </div>
      )}
      {accountMode && session.isAdmin && <AdminSubscriptionsCard />}
      <footer className="text-xs text-muted-foreground text-pretty">
        FundPilot AI · 板块研究，可查证、可解释、可复盘。未评分方向可查看具体数据缺口。
      </footer>
    </>
  );
}
