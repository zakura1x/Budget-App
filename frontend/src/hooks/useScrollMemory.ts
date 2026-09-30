/**
 * Where you were on each screen (misc/archive/UX_RESPONSIVENESS_PLAN.md §2.5, step 6).
 *
 * Half of "it reloaded everything" was never the data: every return to a tab
 * started at the top. It used to do that by accident - the screen came back
 * empty, the page had no height, and the browser clamped the scroll to zero.
 * Now that a warm screen paints its figures immediately, the old position is
 * both restorable AND, left alone, would carry over to the next screen. So
 * this does both jobs: restore where there is a memory, and start at the top
 * where there is not.
 *
 * Positions live in module memory and are cleared with everything else on lock
 * (SEC-29) - a scroll offset is not a figure, but it is a trace of one.
 */
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

const positions = new Map<string, number>();

/** A second attempt, for a screen whose content lands a frame or two late. */
const SETTLE_MS = 150;

export function useScrollMemory(): void {
  const { pathname } = useLocation();

  useEffect(() => {
    const saved = positions.get(pathname) ?? 0;
    const restore = () => window.scrollTo(0, saved);
    const frame = requestAnimationFrame(restore);
    // If the page was still short on that frame, the browser clamped us. Try
    // once more - but only if the user has not started scrolling themselves.
    const settle = window.setTimeout(() => {
      if (window.scrollY !== saved && window.scrollY === 0) restore();
    }, SETTLE_MS);

    const remember = () => positions.set(pathname, window.scrollY);
    window.addEventListener('scroll', remember, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(settle);
      remember();
      window.removeEventListener('scroll', remember);
    };
  }, [pathname]);
}

export function clearScrollMemory(): void {
  positions.clear();
}
