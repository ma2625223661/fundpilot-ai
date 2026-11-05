// Same contract as the old frontend's request(): JSON in and out, no caching,
// a timeout, and the server's own error message surfaced to the user.
// Signed-in pages also send the CSRF token on POST and go back to the login page
// when the session ends (what the old cloud-session.js did by patching fetch).
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

let csrfToken = '';
let onSessionEnded: (() => void) | null = null;

export function bindSession(token: string, ended: () => void) {
  csrfToken = token;
  onSessionEnded = ended;
}

export async function request<T = unknown>(path: string, body?: unknown, timeout = 20000): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  }
  let response: Response;
  try {
    response = await fetch(path, {
      ...(body !== undefined ? { method: 'POST', body: JSON.stringify(body) } : {}),
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: AbortSignal.timeout(timeout),
    });
  } catch {
    throw new ApiError('请求未完成，请检查网络后重试', 0);
  }
  let data: { error?: string } & Record<string, unknown> = {};
  try {
    data = await response.json();
  } catch {
    // Non-JSON reply (for example a proxy error page); fall through to the status message.
  }
  if (response.status === 401 && onSessionEnded && !path.startsWith('/api/auth/')) onSessionEnded();
  if (!response.ok) throw new ApiError(data.error || `请求失败（${response.status}）`, response.status);
  return data as T;
}
