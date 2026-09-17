/**
 * REC-05 and ACC-37. Post whatever recurring charges fell due since the last
 * open, and credit the days of savings interest earned since - on unlock and
 * whenever the app comes back into view, on ANY screen (user, 2026-09-17: it
 * used to run only when Home opened).
 *
 * Both calls are idempotent on the server, so running them again changes
 * nothing; the figures refresh only when something actually landed.
 */
import { useEffect } from 'react';
import { accrueInterest } from '../lib/accounts';
import { expandRecurring } from '../lib/recurring';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';

let running: Promise<void> | null = null;

function catchUp(): Promise<void> {
  // Unlock and a visibility change can fire together; one run is enough.
  running ??= Promise.all([expandRecurring(), accrueInterest()])
    .then((results) => {
      if (results.every((result) => result.posted === 0)) return;
      useLedgerStore.setState((s) => ({ version: s.version + 1 }));
      void useLedgerStore.getState().load(); // with whatever filters the screen has
      void useBudgetStore.getState().load();
    })
    .catch(() => {
      /* a failed catch-up retries on the next open; nothing is half-posted */
    })
    .finally(() => {
      running = null;
    });
  return running;
}

export function useCatchUp(active: boolean) {
  useEffect(() => {
    if (!active) return;
    void catchUp();
    const onVisible = () => document.visibilityState === 'visible' && void catchUp();
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [active]);
}
