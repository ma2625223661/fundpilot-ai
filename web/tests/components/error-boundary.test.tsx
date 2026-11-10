// A failing page shows a reload notice instead of blanking the site, a page
// file replaced by a newer build says so, and opening another page recovers.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ErrorBoundary, isStaleBuild } from '@/components/error-boundary';

function Broken({ message }: { message: string }): never {
  throw new Error(message);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ErrorBoundary', () => {
  it('shows a reload notice in place of a page that fails to render', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <div>
        <nav>侧边栏</nav>
        <ErrorBoundary resetKey="data">
          <Broken message="boom" />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByRole('alert').textContent).toContain('这个页面暂时无法显示');
    expect(screen.getByRole('button', { name: /重新加载页面/ })).toBeTruthy();
    // Everything outside the boundary stays on screen.
    expect(screen.getByText('侧边栏')).toBeTruthy();
  });

  it('explains a page file replaced by a newer build', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary resetKey="settings">
        <Broken message="Failed to fetch dynamically imported module: http://127.0.0.1:8765/SettingsView-old.js" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert').textContent).toContain('网站已更新');
  });

  it('recovers when another page is opened', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary resetKey="data">
        <Broken message="boom" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    rerender(
      <ErrorBoundary resetKey="history">
        <p>研究记录</p>
      </ErrorBoundary>,
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('研究记录')).toBeTruthy();
  });

  it('recognises the browsers’ wording for a missing page file', () => {
    expect(isStaleBuild(new TypeError('Importing a module script failed.'))).toBe(true);
    expect(isStaleBuild(new Error('error loading dynamically imported module'))).toBe(true);
    expect(isStaleBuild(new Error('Cannot read properties of undefined'))).toBe(false);
  });
});
