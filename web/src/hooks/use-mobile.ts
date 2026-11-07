import { useSyncExternalStore } from 'react';

const MOBILE_BREAKPOINT = 768;
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`;

// Read the media query on every render instead of caching it in state after
// mount, so a narrow first paint and later resizes are both reflected.
function subscribe(listener: () => void) {
  const mql = window.matchMedia(QUERY);
  mql.addEventListener('change', listener);
  window.addEventListener('resize', listener);
  return () => {
    mql.removeEventListener('change', listener);
    window.removeEventListener('resize', listener);
  };
}

export function useIsMobile() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false);
}
