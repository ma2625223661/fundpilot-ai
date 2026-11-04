'use strict';
(() => {
  const context = window.FundPilotCloud;
  if (!context) return;
  const original = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    const same = url.origin === location.origin;
    const method = (init.method || (input instanceof Request && input.method) || 'GET').toUpperCase();
    if (same && url.pathname.startsWith('/api/')) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (method === 'POST') headers.set('X-CSRF-Token', context.csrf_token);
      init = {...init, headers, credentials:'same-origin'};
    }
    const response = await original(input, init);
    if (same && response.status === 401 && !url.pathname.startsWith('/api/auth/')) location.replace('/login.html');
    return response;
  };
  // Revalidate restored tabs, including back/forward cache and account switches.
  async function validate() {
    document.documentElement.style.visibility = 'hidden';
    try {
      const response = await original('/api/auth/me', {cache:'no-store'});
      if (!response.ok) return location.replace('/login.html');
      const current = await response.json();
      if (current.id !== context.id) return location.reload();
      document.documentElement.style.visibility = '';
    } catch { location.replace('/login.html'); }
  }
  window.addEventListener('pageshow', validate);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) validate(); });
})();
