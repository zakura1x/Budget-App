/**
 * GOA-12 - "Your ₱25,000 arrived. Set some aside?"
 *
 * When income of at least the amount set in Settings lands (default ₱5,000,
 * the user's choice 2026-09-28), Home offers a split worked out by the server
 * from each goal's part of this month - the emergency fund first, then sinking
 * funds, then the rest - never more than came in, never more than an account
 * has available. Every amount can be changed.
 *
 * It SUGGESTS: nothing moves until "Set aside" (one commit on the server, which
 * also marks the income answered), and "Not now" is kept on the income itself,
 * on the server - so it is never asked again, on any device.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { afterWrite } from '../lib/invalidate';
import { centavos, formatPHP, fromCentavos, sanitizeAmount, toDecimalString } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { dismissPayday, getPayday, setAsidePayday } from '../lib/security';
import { KIND_LABEL } from './GoalSheets';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const typed = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);
const cents = (value: string) => {
  try {
    return centavos(toDecimalString(value || '0'));
  } catch {
    return 0;
  }
};

export function PaydayCard() {
  const { data: offer } = useQuery({
    queryKey: keys.payday(),
    queryFn: ({ signal }) => getPayday(signal),
    staleTime: STALE.derived,
  });
  const [amounts, setAmounts] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAmounts(Object.fromEntries((offer?.suggestions ?? []).map((s) => [s.goal_id, typed(s.amount)])));
    setError(null);
  }, [offer]);

  if (!offer) return null;
  const total = Object.values(amounts).reduce((sum, v) => sum + cents(v), 0);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      afterWrite('goals', 'accounts'); // money set aside comes off what accounts have available
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
    }
    setBusy(false);
  };

  return (
    <Card className="mb-3 space-y-3">
      <div>
        <p className="text-headline">{formatPHP(offer.amount)} arrived</p>
        <p className="text-footnote text-ink-2">From {offer.name}. Set some aside for your goals before it gets spent?</p>
      </div>
      <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2">
        {offer.suggestions.map((s) => (
          <li key={s.goal_id} className="flex items-center gap-3 px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body">{s.name}</span>
              <span className="block text-caption text-ink-3">{KIND_LABEL[s.kind as keyof typeof KIND_LABEL] ?? 'Goal'} · this month's part</span>
            </span>
            <input
              value={amounts[s.goal_id] ?? ''}
              onChange={(e) => setAmounts((a) => ({ ...a, [s.goal_id]: sanitizeAmount(e.target.value) }))}
              inputMode="decimal"
              aria-label={`Set aside for ${s.name}`}
              className="num min-h-11 w-28 rounded-xl border-2 border-stroke bg-surface px-3 text-right text-body"
            />
          </li>
        ))}
      </ul>
      {error && <p className="text-footnote text-danger">{error}</p>}
      <div className="grid grid-cols-2 gap-2">
        <Button disabled={busy || total <= 0} onClick={() => void run(() => setAsidePayday(
          offer.transaction_id,
          Object.fromEntries(Object.entries(amounts).filter(([, v]) => cents(v) > 0).map(([id, v]) => [id, toDecimalString(v)])),
        ))}>
          Set aside {formatPHP(fromCentavos(total))}
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => void run(() => dismissPayday(offer.transaction_id))}>
          Not now
        </Button>
      </div>
      <p className="text-caption text-ink-3">Nothing moves: it is set aside inside each goal's account, and your balances stay the same.</p>
    </Card>
  );
}
