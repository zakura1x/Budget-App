/**
 * UX-14 - a short vibration where a phone's own apps give one: a key on the
 * number pads, an entry saved, an entry deleted, a wrong PIN.
 *
 * navigator.vibrate exists on Android. iOS Safari has no vibration for web
 * pages at all, so there it does nothing - silently, never an error. The
 * `haptics` preference (Settings, on by default) turns it off; it lives on
 * the server with every other preference, never in the browser. While the
 * app is locked the preferences are not loaded, so the lock screen's PIN pad
 * follows the default.
 */
import { usePreferencesStore } from '../stores/preferencesStore';

const PATTERNS = {
  tap: 8, // a key - barely there, like a keyboard's
  success: 18, // saved
  warn: [24, 60, 24], // deleted - something went away
  error: [60, 50, 60], // refused - a wrong PIN
} as const;

export type Haptic = keyof typeof PATTERNS;

export function buzz(kind: Haptic): void {
  if (usePreferencesStore.getState().prefs?.haptics === false) return;
  try {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) navigator.vibrate(PATTERNS[kind] as number | number[]);
  } catch {
    /* a browser that refuses (no user gesture yet, or a policy) - nothing to tell anyone */
  }
}
