// Works out which edition is running and who is signed in, without the old
// server-side script injection:
//   /api/auth/me  200 -> account edition (cloud or local with accounts)
//                 401 -> not signed in, go to the login page
//                 404 -> local edition without accounts (create_server(require_login=False))
//   /api/access   scope: 'cloud' | 'account_local' | 'same_network'
import { ApiError, bindSession, request } from '@/lib/api';

export type Role = 'admin' | 'member';
export type Scope = 'cloud' | 'account_local' | 'same_network';

export interface User {
  id: number;
  username: string;
  role: Role;
  csrf_token: string;
}

export interface Access {
  scope: Scope;
  can_manage_settings: boolean;
  can_trigger_research?: boolean;
  lan_urls: string[];
  site_url?: string;
  preview?: boolean;
  /** The site only accepts this computer (the default since issue #5); phones need --allow-lan. */
  local_only?: boolean;
}

export interface Session {
  user: User | null;
  access: Access;
  /** Cloud edition: shared research, personal records saved to the account. */
  cloud: boolean;
  isAdmin: boolean;
}

export function toLogin() {
  location.replace('/login.html');
}

export async function loadSession(): Promise<Session> {
  let user: User | null = null;
  try {
    user = await request<User>('/api/auth/me');
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      toLogin();
      throw error;
    }
    if (!(error instanceof ApiError && error.status === 404)) throw error;
  }
  if (user) bindSession(user.csrf_token, toLogin);
  const access = await request<Access>('/api/access');
  if (user) installLegacyBridge(user, access);
  return {
    user,
    access,
    cloud: access.scope === 'cloud',
    // Without accounts the settings rights come from being on this computer.
    isAdmin: user ? user.role === 'admin' : access.can_manage_settings,
  };
}

declare global {
  interface Window {
    FundPilotCloud?: User & { mode: 'cloud' | 'local'; preview: boolean };
  }
}

// The verbatim legacy modules (for example the account history store in
// sector-history.js) detect the account edition through window.FundPilotCloud
// and call fetch directly. The old cloud-session.js added the CSRF token to those
// calls by wrapping fetch; this does the same for same-origin /api/ POSTs only.
let bridged = false;
function installLegacyBridge(user: User, access: Access) {
  window.FundPilotCloud = { ...user, mode: access.scope === 'cloud' ? 'cloud' : 'local', preview: access.preview === true };
  if (bridged) return;
  bridged = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin === location.origin && url.pathname.startsWith('/api/') && method === 'POST') {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (!headers.has('X-CSRF-Token') && window.FundPilotCloud) headers.set('X-CSRF-Token', window.FundPilotCloud.csrf_token);
      init = { ...init, headers, credentials: 'same-origin' };
    }
    return original(input, init);
  };
}

/** Restored tabs (back/forward cache, another account signed in) are checked again. */
export function watchSession(user: User | null) {
  if (!user) return () => {};
  const validate = async () => {
    try {
      const current = await request<User>('/api/auth/me');
      if (current.id !== user.id) location.reload();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) toLogin();
    }
  };
  const onVisible = () => {
    if (!document.hidden) void validate();
  };
  window.addEventListener('pageshow', validate);
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    window.removeEventListener('pageshow', validate);
    document.removeEventListener('visibilitychange', onVisible);
  };
}

export async function logout() {
  await request('/api/auth/logout', {});
  toLogin();
}
