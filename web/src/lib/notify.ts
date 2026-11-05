// Browser system notifications for change alerts. Opt-in only: permission is
// requested from the switch in the alert panel, never on page load. They work
// while the page is open (for example in a background tab); there is no
// service worker, so nothing arrives after the page is closed.
import type { SectorChange } from '@/lib/changes';

const ENABLED_KEY = 'fundpilot_notify_v1';
const SENT_KEY = 'fundpilot_notify_sent_v1';

export type NotifySupport = 'ok' | 'unsupported' | 'insecure';

/** Notifications need the API and a secure page (https or this computer). */
export function notifySupport(): NotifySupport {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  if (!window.isSecureContext) return 'insecure';
  return 'ok';
}

export function notifyPermission(): NotificationPermission | 'unsupported' {
  return notifySupport() === 'ok' ? Notification.permission : 'unsupported';
}

export function readEnabled() {
  try {
    return localStorage.getItem(ENABLED_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeEnabled(on: boolean) {
  try {
    localStorage.setItem(ENABLED_KEY, on ? '1' : '0');
  } catch {
    // Storage unavailable: the choice lasts for this page only.
  }
}

/**
 * What makes a change worth a new notification: its markers, tier, risk level
 * and whether the score moved notably. The exact delta is left out on purpose,
 * so a score drifting between 5-minute refreshes does not notify again.
 */
export function changeSignature(id: string, change: SectorChange) {
  return [id, change.flags.join('+'), change.tier?.now ?? '', change.risk?.now ?? '', change.notable && change.scoreDelta !== null ? 'score' : ''].join('|');
}

/** Signatures already notified for this baseline day; a new day starts a new list. */
export function readSent(day: string): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(SENT_KEY) || '{}');
    return new Set(value?.day === day && Array.isArray(value.keys) ? value.keys : []);
  } catch {
    return new Set();
  }
}

export function writeSent(day: string, keys: Set<string>) {
  try {
    localStorage.setItem(SENT_KEY, JSON.stringify({ day, keys: [...keys].slice(-500) }));
  } catch {
    // Storage unavailable: at worst a change is notified again after a reload.
  }
}
