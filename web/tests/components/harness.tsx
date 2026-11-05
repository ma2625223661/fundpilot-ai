// Renders a page inside the research providers with a fake API. Each test
// passes the JSON replies by path; unknown paths fail like a missing endpoint.
import type { ReactNode } from 'react';
import { render } from '@testing-library/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ResearchProvider } from '@/app/research/ResearchContext';
import { SubscriptionProvider } from '@/app/research/SubscriptionContext';
import { WatchlistProvider } from '@/app/research/WatchlistContext';
import type { Session } from '@/lib/session';

export type Replies = Record<string, unknown>;

const fake = globalThis as unknown as { __replies: Replies; __requests: { path: string; body?: unknown }[] };

export function requests() {
  return fake.__requests;
}

export function session(overrides: Partial<Session> = {}): Session {
  return {
    user: { id: 1, username: 'owner', role: 'admin', csrf_token: 'test' },
    access: { scope: 'cloud', can_manage_settings: true, lan_urls: [], site_url: 'http://localhost:3000/index.html', preview: true },
    cloud: true,
    isAdmin: true,
    ...overrides,
  };
}

export function sector(overrides: Record<string, unknown> = {}) {
  return {
    id: 'semiconductor',
    title: '半导体',
    group: 'industry',
    status: 'ok',
    score: 52.4,
    change_pct: 1.25,
    trend: '趋势平稳',
    risk: '中风险',
    as_of: '2026-11-04T15:00:00+08:00',
    requirements: [
      { id: 'data', status: 'ok' },
      { id: 'mapping', status: 'ok' },
      { id: 'model', status: 'ok' },
    ],
    quote: { change_pct: 1.25, as_of: '2026-11-04T15:00:00+08:00' },
    sources: [],
    ...overrides,
  };
}

export function report(sectors: Record<string, unknown>[] = [sector()], overrides: Record<string, unknown> = {}) {
  return {
    research_scope: 'sectors',
    as_of: '2026-11-04T15:00:00+08:00',
    sector_analysis: sectors,
    snapshot: { as_of: '2026-11-04T15:00:00+08:00', market: [], sources: [], warnings: [] },
    strategy: { panic: {}, regime: {} },
    event_analysis: { status: 'completed', events: [] },
    company_evidence: { sector_leaders: {} },
    ...overrides,
  };
}

export function baseReplies(extra: Replies = {}, value = report()): Replies {
  return {
    '/api/auto/status': { status: 'ready', has_report: true, report_version: 'v1' },
    '/api/auto/report': { report: value, report_version: 'v1' },
    '/api/ai/config': { config: { configured: false, enabled: false, verification: 'unverified' } },
    '/api/data/config': { config: { verification: 'unverified', capabilities: [] }, supplemental: { verification: 'unverified', capabilities: [] } },
    '/api/me/history': { items: [] },
    '/api/me/ai-subscription': { subscription: { status: 'admin' }, items: [] },
    '/api/me/ai-research': { jobs: [] },
    '/api/me/watchlist': { items: [] },
    '/api/me/reviews': { access: true, status: 'empty', items: [] },
    '/api/me/phone': { available: false, bound: false },
    '/api/admin/users': { items: [] },
    ...extra,
  };
}

export function renderPage(page: ReactNode, options: { replies?: Replies; session?: Session } = {}) {
  fake.__replies = options.replies ?? baseReplies();
  fake.__requests.length = 0;
  return render(
    <TooltipProvider>
      <ResearchProvider session={options.session ?? session()}>
        <SubscriptionProvider>
          <WatchlistProvider>{page}</WatchlistProvider>
        </SubscriptionProvider>
      </ResearchProvider>
    </TooltipProvider>,
  );
}
