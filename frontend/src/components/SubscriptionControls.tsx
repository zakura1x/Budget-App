/**
 * SUB-07 - cancelling a subscription, inside its rule sheet.
 *
 *   Cancel     you cancelled it with the service on a day (today unless you
 *              say otherwise): nothing charges after it. It stays listed under
 *              Cancelled with what it would have cost since - replayed through
 *              the one schedule on the server, never estimated here.
 *   Resume     signed up again: it charges from today, never the months it
 *              was cancelled.
 *   Cancel by  a free trial's last day - reminded on Home within the
 *              subscription's reminder days. Only a reminder: nothing is
 *              cancelled for you.
 *
 * A cancelled subscription cannot be restarted by editing its end date; only
 * Resume does it (the server holds to that too).
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { afterWrite, MONEY } from '../lib/invalidate';
import { formatPHP } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { cancelSubscription, getSubscriptions, resumeSubscription, setCancelBy, type Rule } from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { Button } from './ui/Button';

const day = (iso: string) => format(parseISO(iso), 'd MMM yyyy');

export function SubscriptionControls({ rule, onDone }: { rule: Rule; onDone: () => void }) {
  const { data: subs } = useQuery({
    queryKey: keys.subscriptions(),
    queryFn: ({ signal }) => getSubscriptions(signal),
    staleTime: STALE.derived,
  });
  const item = subs?.items.find((i) => i.rule.id === rule.id);
  const [asking, setAsking] = useState(false);
  const [on, setOn] = useState(localToday());
  const [by, setBy] = useState(item?.cancel_by ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The overview may arrive after the sheet opens; the field follows what is saved.
  const saved = item?.cancel_by ?? '';
  useEffect(() => setBy(saved), [saved]);

  const run = async (action: () => Promise<unknown>, close = true) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      // Cancelling and resuming change what charges, so every figure that shows money is asked for again.
      afterWrite(...MONEY);
      if (close) onDone();
      else setBusy(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  if (!item) return null;

  if (item.cancelled_on) {
    return (
      <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
        <p className="text-body">
          Cancelled on {day(item.cancelled_on)}
          {item.saved && item.saved !== '0.00' && (
            <> — <span className="num font-semibold">{formatPHP(item.saved)}</span> not charged since</>
          )}
        </p>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button variant="secondary" block disabled={busy} onClick={() => void run(() => resumeSubscription(rule.id))}>
          I signed up again — resume it
        </Button>
        <p className="text-caption text-ink-3">It charges from today; the months it was cancelled are never charged.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
      {asking ? (
        <>
          <label className="block text-footnote font-semibold text-ink-2">
            Cancelled with the service on
            <input type="date" value={on} max={localToday()} onChange={(e) => e.target.value && setOn(e.target.value)}
              className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
          </label>
          <p className="text-caption text-ink-3">Nothing charges after that day. A charge already recorded after it stays — it was real money.</p>
          {error && <p className="text-footnote text-danger">{error}</p>}
          <div className="grid grid-cols-2 gap-2">
            <Button variant="danger" disabled={busy} onClick={() => void run(() => cancelSubscription(rule.id, on))}>
              Cancel it
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setAsking(false)}>Not now</Button>
          </div>
        </>
      ) : (
        <>
          <Button variant="secondary" block className="text-danger" disabled={busy} onClick={() => setAsking(true)}>
            I cancelled this subscription
          </Button>
          <label className="flex items-center justify-between gap-3 text-footnote">
            <span className="font-semibold text-ink-2">Remind me to cancel by</span>
            <input type="date" value={by} min={localToday()} onChange={(e) => setBy(e.target.value)}
              aria-label="Remind me to cancel by"
              className="min-h-11 rounded-xl border-2 border-stroke bg-surface px-2 text-body" />
          </label>
          {(by || item.cancel_by) && by !== (item.cancel_by ?? '') && (
            <Button variant="secondary" block disabled={busy}
              onClick={() => void run(() => setCancelBy(rule.id, by || null), false)}>
              {by ? `Remind me by ${day(by)}` : 'Clear the reminder'}
            </Button>
          )}
          {item.cancel_by && by === item.cancel_by && (
            <p className="text-caption text-ink-3">
              Home reminds you from {rule.reminder_days ?? 3} days before — a free trial’s last day, say.{' '}
              <button type="button" className="font-semibold text-accent-ink" disabled={busy}
                onClick={() => { setBy(''); void run(() => setCancelBy(rule.id, null), false); }}>
                Clear
              </button>
            </p>
          )}
          {error && <p className="text-footnote text-danger">{error}</p>}
        </>
      )}
    </div>
  );
}
