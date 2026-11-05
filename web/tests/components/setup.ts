// jsdom lacks a few browser APIs the components touch.
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());

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
Element.prototype.scrollIntoView = () => {};

// Charts draw with ECharts, which needs real layout; the tests check text instead.
vi.mock('@/components/charts', () => ({
  ScoreGauge: () => null,
  DatedLine: ({ label }: { label: string }) => label,
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
