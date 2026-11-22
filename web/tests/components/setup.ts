// jsdom lacks a few browser APIs the components touch.
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());

// Newer Node versions ship their own localStorage global, which hides jsdom's and
// is undefined or throws without --localstorage-file (issue #10). Give every test
// run the same in-memory storage, whatever the Node version.
class MemoryStorage implements Storage {
  private items = new Map<string, string>();
  get length() {
    return this.items.size;
  }
  clear() {
    this.items.clear();
  }
  getItem(key: string) {
    return this.items.has(String(key)) ? (this.items.get(String(key)) as string) : null;
  }
  key(index: number) {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.items.delete(String(key));
  }
  setItem(key: string, value: string) {
    this.items.set(String(key), String(value));
  }
}
for (const name of ['localStorage', 'sessionStorage'] as const) {
  const storage = new MemoryStorage();
  for (const target of new Set<object>([globalThis, window])) {
    Object.defineProperty(target, name, { configurable: true, get: () => storage });
  }
}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }),
});
window.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
window.scrollTo = () => {};
// Base UI's Switch and other pressables dispatch PointerEvent, which jsdom lacks.
if (!('PointerEvent' in window)) {
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent = class extends MouseEvent {} as typeof MouseEvent;
}
Element.prototype.scrollIntoView = () => {};

// Charts draw with ECharts, which needs real layout; the tests check text instead.
vi.mock('@/components/charts', () => ({
  DatedLine: ({ label }: { label: string }) => label,
  DatedLines: ({ label }: { label: string }) => label,
  cssColor: () => '',
}));

// A fake API: tests fill globalThis.__replies by path (see harness.tsx).
const fake = globalThis as unknown as { __replies: Record<string, unknown>; __requests: { path: string; body?: unknown }[] };
fake.__replies = {};
fake.__requests = [];
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    bindSession: () => {},
    request: async (path: string, body?: unknown) => {
      fake.__requests.push({ path, body });
      const key = Object.keys(fake.__replies).find(candidate => path === candidate || path.startsWith(candidate + '?'));
      if (!key) throw new ApiError('接口不存在', 404);
      const value = fake.__replies[key];
      return typeof value === 'function' ? (value as (body: unknown) => unknown)(body) : structuredClone(value);
    },
  };
});
