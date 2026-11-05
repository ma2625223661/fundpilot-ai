// The sectors picked for comparison, shared by every "加入对比" button and the
// tray at the bottom of the page. Kept in this browser as a convenience only:
// storage failures fall back to memory and nothing depends on it surviving.
import { useSyncExternalStore } from 'react';
import { COMPARE_LIMIT } from '@/app/navigation';

const KEY = 'fundpilot_compare_v1';
const listeners = new Set<() => void>();

function read(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === 'string'))].slice(0, COMPARE_LIMIT) : [];
  } catch {
    return [];
  }
}

let picked = read();

function write(next: string[]) {
  picked = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable: the list lasts for this page only.
  }
  listeners.forEach(listener => listener());
}

export const compareStore = {
  get: () => picked,
  has: (id: string) => picked.includes(id),
  /** Adds a sector; returns false when the list is already full. */
  add(id: string) {
    if (picked.includes(id)) return true;
    if (picked.length >= COMPARE_LIMIT) return false;
    write([...picked, id]);
    return true;
  },
  remove(id: string) {
    write(picked.filter(item => item !== id));
  },
  clear() {
    write([]);
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useCompareList() {
  return useSyncExternalStore(compareStore.subscribe, compareStore.get, compareStore.get);
}
