/**
 * The only sign that a screen is refreshing behind its own figures
 * (misc/UX_RESPONSIVENESS_PLAN.md D7, step 6).
 *
 * Silent for the first 400 ms, which covers nearly every refresh; past that, a
 * 2px accent line under the safe area, so a slow one is visible rather than
 * mysterious. It never dims or blanks what is on screen - that was the
 * blinking this whole plan exists to remove.
 */
import { useIsFetching } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';

const QUIET_MS = 400;

export function RefreshLine() {
  const queries = useIsFetching();
  // The two stores are not queries (plan D9), so they report for themselves.
  const ledgerLoading = useLedgerStore((s) => s.loading);
  const budgetLoading = useBudgetStore((s) => s.loading);
  const busy = queries > 0 || ledgerLoading || budgetLoading;
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!busy) {
      setShown(false);
      return;
    }
    const timer = window.setTimeout(() => setShown(true), QUIET_MS);
    return () => window.clearTimeout(timer);
  }, [busy]);

  if (!shown) return null;
  return <div aria-hidden="true" className="fixed inset-x-0 top-safe-t z-50 h-0.5 bg-accent" />;
}
