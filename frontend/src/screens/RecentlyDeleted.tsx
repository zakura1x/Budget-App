/**
 * Recently deleted (TXN-25) - what you deleted in the last 30 days, newest
 * first, each with Restore.
 *
 * One line per thing deleted, the way the ledger shows it: a transfer as one
 * row, a purchase that took its cashback with it as the purchase alone - and
 * Restore brings back everything that went with it.
 *
 * Some entries cannot come back, and the server says why: its account was
 * archived, a category it was filed under was deleted, it was a payment on a
 * plan (pay it again from the plan), or the charge has been recorded again
 * since. The button is shown disabled with that reason under it, rather than
 * offered and refused.
 *
 * Only what Delete removed is here: a purchase that became an installment
 * plan (REC-34) is hidden, not deleted, and comes back with Convert back.
 */
import { useQuery } from '@tanstack/react-query';
import { formatDistanceToNowStrict, parseISO } from 'date-fns';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { keys, STALE } from '../lib/queryKeys';
import { listDeleted, restoreTransaction, type Deleted } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';

/** `deleted_at` is UTC without a zone, as every server timestamp is. */
const ago = (stamp: string) => formatDistanceToNowStrict(parseISO(`${stamp}Z`), { addSuffix: true });

export function RecentlyDeleted() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: entries, error: loadError, refetch } = useQuery({
    queryKey: keys.deleted(),
    queryFn: ({ signal }) => listDeleted(signal),
    staleTime: STALE.derived,
  });

  const restore = async (entry: Deleted) => {
    setBusy(entry.transaction.id);
    setError(null);
    try {
      // An Outcome like any write: the ledger takes the rows back, and every
      // figure that moved - this list included, it is keyed under transactions - is asked for again.
      useLedgerStore.getState().applyOutcome(await restoreTransaction(entry.transaction.id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not restore. Try again.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <ScreenHeader
        title="Recently deleted"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />

      {(loadError || error) && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error ?? loadError?.message}{' '}
          {loadError && (
            <button type="button" className="font-semibold underline" onClick={() => void refetch()}>
              Try again
            </button>
          )}
        </p>
      )}

      {!entries && !loadError && <div className="skeleton h-40 rounded-card" aria-hidden="true" />}

      {entries && entries.length === 0 && (
        <Card className="text-center">
          <p className="text-body">Nothing deleted in the last 30 days.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            Anything you delete waits here for 30 days, so a slip of the thumb is never final.
          </p>
        </Card>
      )}

      {entries && entries.length > 0 && (
        <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
          {entries.map((entry) => (
            <div key={entry.transaction.id} className="pb-3">
              <TransactionRow row={entry.transaction} lookups={lookups} />
              <div className="flex items-center gap-3 px-4">
                <p className="min-w-0 flex-1 text-footnote text-ink-3">
                  {entry.restorable ? `Deleted ${ago(entry.deleted_at)}` : entry.reason}
                </p>
                <Button
                  variant="secondary"
                  className="shrink-0"
                  disabled={!entry.restorable || busy !== null}
                  onClick={() => void restore(entry)}
                >
                  {busy === entry.transaction.id ? 'Restoring…' : 'Restore'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
      {entries && entries.length > 0 && (
        <p className="px-1 pt-3 text-footnote text-ink-3">
          Entries stay here for 30 days. A purchase you turned into an installment plan isn’t deleted — open the plan
          and convert it back instead.
        </p>
      )}
    </>
  );
}
