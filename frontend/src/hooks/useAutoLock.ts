/**
 * Auto-lock (SEC-08) - the browser half. The server enforces the same idle
 * limit on its own (session_keys.py); this makes the screen follow promptly
 * instead of waiting for the next request to be refused.
 *
 *   idle for `minutes`          -> lock
 *   hidden for over a minute    -> lock on return (switched apps, phone
 *                                  locked, tab in the background)
 *
 * A minute's grace on "hidden" rather than locking on every blur: glancing at
 * a message and coming straight back should not cost a PIN entry.
 */
import { useEffect, useRef } from 'react';

const HIDDEN_GRACE_MS = 60_000;
const ACTIVITY = ['pointerdown', 'keydown', 'touchstart', 'wheel'] as const;

export function useAutoLock(enabled: boolean, minutes: number, onLock: () => void) {
  const lastActive = useRef(Date.now());
  const hiddenAt = useRef<number | null>(null);
  const onLockRef = useRef(onLock);
  onLockRef.current = onLock;

  useEffect(() => {
    if (!enabled) return;
    lastActive.current = Date.now();
    const idleMs = Math.max(1, minutes) * 60_000;

    const touch = () => {
      lastActive.current = Date.now();
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        hiddenAt.current = Date.now();
      } else if (hiddenAt.current !== null) {
        const away = Date.now() - hiddenAt.current;
        hiddenAt.current = null;
        if (away > HIDDEN_GRACE_MS || Date.now() - lastActive.current > idleMs) onLockRef.current();
      }
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && Date.now() - lastActive.current > idleMs) onLockRef.current();
    }, 10_000);

    ACTIVITY.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(timer);
      ACTIVITY.forEach((e) => window.removeEventListener(e, touch));
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, minutes]);
}
