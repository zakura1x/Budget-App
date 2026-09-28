/**
 * TXN-25 - "Deleted · Undo", for a few seconds after anything is deleted.
 *
 * A delete was already a soft one (TXN-14); this is the way back while the
 * thumb is still there. Undo is the same restore Recently deleted (More) uses,
 * so it brings back whatever went with the entry - a transfer's other leg, a
 * purchase's cashback - and it answers with an Outcome like any write.
 *
 * Nothing is remembered anywhere but this store (SEC-29): miss the toast and
 * the entry is still under More → Recently deleted for 30 days.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { formatPHP } from '../lib/money';
import { restoreTransaction, type Transaction } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';

const SHOWN_MS = 6000;

/** Called by every Delete once the server has answered: "Deleted ₱150.00 · Jollibee · Undo". */
export function offerUndo(row: Transaction): void {
  useUiStore.getState().offerUndo(row.id, [formatPHP(row.amount), row.merchant].filter(Boolean).join(' · '));
}

export function UndoToast() {
  const undo = useUiStore((s) => s.undo);
  const clear = useUiStore((s) => s.clearUndo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBusy(false);
    setError(null);
    if (!undo) return;
    const timer = window.setTimeout(clear, SHOWN_MS);
    return () => window.clearTimeout(timer);
  }, [undo, clear]);

  if (!undo) return null;

  const restore = async () => {
    setBusy(true);
    try {
      useLedgerStore.getState().applyOutcome(await restoreTransaction(undo.id));
      clear();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That could not be undone.');
      setBusy(false);
    }
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-0 z-50 mx-auto max-w-app px-4 bottom-[calc(theme(spacing.tabbar)+env(safe-area-inset-bottom)+1rem)]"
    >
      <div className="flex items-center gap-3 rounded-card border-2 border-stroke bg-ink px-4 py-2.5 text-surface shadow-card">
        <p className="min-w-0 flex-1 truncate text-footnote">{error ?? `Deleted ${undo.label}`}</p>
        {!error && (
          <button
            type="button"
            onClick={() => void restore()}
            disabled={busy}
            className="press shrink-0 rounded-xl bg-surface px-3 py-1.5 text-footnote font-bold text-ink"
          >
            Undo
          </button>
        )}
      </div>
    </div>
  );
}
