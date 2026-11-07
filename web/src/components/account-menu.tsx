import { useState } from 'react';
import { ChevronDown, KeyRound, LogOut, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { goTo } from '@/app/navigation';
import { logout, type User } from '@/lib/session';
import { cn } from '@/lib/utils';

export function AccountMenu({ user, className, hideIcon = false }: { user: User; className?: string; hideIcon?: boolean }) {
  const [leaving, setLeaving] = useState(false);
  async function signOut() {
    setLeaving(true);
    try {
      await logout();
    } catch (error) {
      setLeaving(false);
      toast.error('退出登录失败', { description: (error as Error).message + '，请稍后重试。' });
    }
  }
  const role = user.role === 'admin' ? '管理员' : '成员';
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" className={cn('max-w-48', className)} aria-label={`账号 ${user.username}（${role}）`}>
            {!hideIcon && <UserRound aria-hidden="true" />}
            <span className="flex min-w-0 flex-1 flex-col items-start text-left">
              <span className="w-full truncate">{user.username}</span>
              <span className="text-xs font-normal text-muted-foreground">{role}</span>
            </span>
            <ChevronDown aria-hidden="true" />
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center justify-between gap-2">
            <span className="truncate">{user.username}</span>
            <Badge variant="secondary">{role}</Badge>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => goTo('settings')}>
          <KeyRound aria-hidden="true" />
          修改密码与手机号
        </DropdownMenuItem>
        <DropdownMenuItem disabled={leaving} onClick={() => void signOut()}>
          <LogOut aria-hidden="true" />
          {leaving ? '正在退出…' : '退出登录'}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
