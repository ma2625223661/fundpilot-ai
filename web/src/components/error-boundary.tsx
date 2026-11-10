// Keeps one failing page from blanking the whole site. React only catches render
// errors in a class component and the component library has none, so it lives
// here (not in components/ui). The sidebar sits outside the boundary and stays
// usable; a new resetKey (the next page) clears the error.
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { CircleAlert, RefreshCw } from 'lucide-react';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

/**
 * A page split into its own file (React.lazy) whose file no longer exists:
 * the site was rebuilt while this tab stayed open, so the hashed names changed.
 */
export function isStaleBuild(error: unknown) {
  const text = String((error as Error)?.message ?? error);
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i.test(text);
}

interface Props {
  children: ReactNode;
  /** When this changes (another page is opened) the error is cleared. */
  resetKey?: string;
}

interface State {
  error: unknown;
  key?: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('页面渲染失败', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const stale = isStaleBuild(error);
    return (
      <Alert variant="destructive" role="alert">
        <CircleAlert aria-hidden="true" />
        <AlertTitle>{stale ? '网站已更新，这个页面需要重新加载' : '这个页面暂时无法显示'}</AlertTitle>
        <AlertDescription className="text-pretty">
          {stale
            ? '网站在此标签页打开期间更新过，旧版本的页面文件已被替换。重新加载后即可使用，研究数据不受影响。'
            : '页面在显示时出错。重新加载通常可以恢复；如果反复出现，可以先从左侧打开其他页面，并把出错的页面告诉管理员。'}
        </AlertDescription>
        <AlertAction>
          <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
            <RefreshCw aria-hidden="true" />
            重新加载页面
          </Button>
        </AlertAction>
      </Alert>
    );
  }
}
