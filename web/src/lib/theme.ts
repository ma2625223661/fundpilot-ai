// Dark first, light on request. The choice lives in localStorage and is shared
// with any component through useTheme().
import { useSyncExternalStore } from 'react';

export type Theme = 'dark' | 'light';
const KEY = 'fundpilot_theme_v1';
const listeners = new Set<() => void>();

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

function currentTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  document.documentElement.style.colorScheme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for this page only.
  }
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => 'dark' as Theme);
  return { theme, setTheme: applyTheme };
}
