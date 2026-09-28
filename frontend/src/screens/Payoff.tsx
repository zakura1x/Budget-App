/**
 * Pay off debts (REC-35) - every card and loan side by side, with an extra
 * amount a month you could put towards them: when each is cleared, in which
 * order, and what the interest comes to.
 *
 *   Smallest first     (snowball) the smallest balance is cleared first - quick wins
 *   Dearest first      (avalanche) the highest interest first - least interest;
 *                      only offered when some debt has a rate typed on it
 *
 * Each debt's payment is what already goes to it each month - its repeating
 * card or loan payment, else its installments' next payment - and can be typed
 * here for a try; nothing typed is stored. A cleared debt's payment rolls on to
 * the next. Extra money on an installment plan finishes it sooner (the user's
 * decision, 2026-09-28). Interest comes from the rate typed on the account, as
 * the bank shows it: an ESTIMATE - the app never calculates a card's real
 * interest (ACC-19). Writes nothing.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { TextField } from '../components/ui/TextField';
import { formatPHP, sanitizeAmount, toDecimalString } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { getPayoff, type PayoffDebt, type PayoffPlan } from '../lib/recurring';

const month = (iso: string | null) => (iso ? format(parseISO(iso), 'MMM yyyy') : null);
const SOURCE: Record<PayoffDebt['payment_source'], string> = {
  rule: 'your repeating payment',
  plan: 'its installments',
  yours: 'typed here',
  none: 'nothing scheduled',
};

/** "₱3,000 a month for ..." typed in pesos, sent as a decimal string - or "0.00" while empty or half typed. */
function decimal(typed: string): string {
  try {
    return toDecimalString(typed.trim() || '0');
  } catch {
    return '0.00';
  }
}

function rateLabel(debt: PayoffDebt): string {
  if (!debt.rate) return 'no rate typed';
  const shown = debt.rate.replace(/0+$/, '').replace(/\.$/, '');
  return `${shown}% a ${debt.rate_per}`;
}

function PlanCard({ plan, asIs, debts }: { plan: PayoffPlan; asIs: PayoffPlan; debts: PayoffDebt[] }) {
  const byId = new Map(debts.map((d) => [d.account_id, d]));
  const sooner = plan.months !== null && asIs.months !== null ? asIs.months - plan.months : null;
  return (
    <Card className="space-y-3">
      <div>
        <p className="text-footnote text-ink-2">Debt-free</p>
        <p className="num text-title">{month(plan.debt_free) ?? 'Not at these payments'}</p>
        <p className="text-footnote text-ink-2">
          {asIs.months === null && plan.months !== null
            ? 'Without the extra, some of it never clears.'
            : sooner !== null && sooner > 0
              ? `${sooner} month${sooner === 1 ? '' : 's'} sooner than paying as you do now (${month(asIs.debt_free)}).`
              : plan.months === null
                ? 'A debt whose interest grows faster than what is paid never clears — pay more on it.'
                : `The same as paying as you do now.`}
        </p>
      </div>
      {plan.interest !== '0.00' && (
        <p className="text-footnote text-ink-2">
          About <span className="num font-semibold text-ink">{formatPHP(plan.interest)}</span> in interest
          {asIs.interest !== plan.interest && (
            <> · <span className="num">{formatPHP(asIs.interest)}</span> as you pay now</>
          )}
        </p>
      )}
      <ol className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2">
        {plan.outcomes.map((o) => (
          <li key={o.id} className="flex items-center gap-3 px-3 py-2.5">
            <span className="num flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface text-footnote font-bold shadow-edge">
              {o.position}
            </span>
            <span className="min-w-0 flex-1 truncate text-body">{byId.get(o.id)?.name ?? 'Debt'}</span>
            <span className="num shrink-0 text-footnote text-ink-2">{month(o.paid_off) ?? 'not cleared'}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function Payoff() {
  const navigate = useNavigate();
  const [extraTyped, setExtraTyped] = useState('');
  const [typedPayments, setTypedPayments] = useState<Record<number, string>>({});
  const [strategy, setStrategy] = useState<'snowball' | 'avalanche'>('snowball');

  // Asked for once typing pauses - every key would otherwise be a request.
  const [asked, setAsked] = useState({ extra: '0.00', payments: {} as Record<number, string> });
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const payments = Object.fromEntries(
        Object.entries(typedPayments).filter(([, v]) => v.trim()).map(([id, v]) => [id, decimal(v)]),
      );
      setAsked({ extra: decimal(extraTyped), payments });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [extraTyped, typedPayments]);

  const { data, error, isFetching } = useQuery({
    queryKey: keys.payoff(asked.extra, JSON.stringify(asked.payments)),
    queryFn: ({ signal }) => getPayoff(asked.extra, asked.payments, signal),
    staleTime: STALE.derived,
    placeholderData: (previous) => previous,
  });

  const plan = data ? (strategy === 'avalanche' && data.avalanche ? data.avalanche : data.snowball) : null;

  return (
    <>
      <ScreenHeader
        title="Pay off debts"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />

      {error && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {(error as Error).message}
        </p>
      )}
      {!data && !error && <div className="skeleton h-64 rounded-card" aria-hidden="true" />}

      {data && data.debts.length === 0 && (
        <Card className="text-center">
          <p className="text-body">Nothing owed on a card or a loan.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            When a card or a borrowed account carries a balance, it shows here with when it clears.
          </p>
        </Card>
      )}

      {data && data.debts.length > 0 && (
        <div className={`space-y-4 transition-opacity ${isFetching ? 'opacity-70' : ''}`}>
          <Card>
            <TextField
              label="Extra you could pay a month"
              value={extraTyped}
              onChange={(e) => setExtraTyped(sanitizeAmount(e.target.value))}
              inputMode="decimal"
              placeholder="0"
              leading={<span className="pl-3.5 text-body text-ink-3">₱</span>}
              hint="On top of what already goes to each debt. When one is cleared, its payment moves on to the next."
            />
          </Card>

          {plan && (
            <>
              {data.avalanche && (
                <Segmented<'snowball' | 'avalanche'>
                  label="Order"
                  value={strategy}
                  onChange={setStrategy}
                  options={[
                    { value: 'snowball', label: 'Smallest first' },
                    { value: 'avalanche', label: 'Dearest first' },
                  ]}
                />
              )}
              <p className="px-1 text-footnote text-ink-2">
                {strategy === 'avalanche' && data.avalanche
                  ? 'The highest interest is cleared first — the least interest overall.'
                  : 'The smallest balance is cleared first — each one gone frees its payment for the next.'}
              </p>
              <PlanCard plan={plan} asIs={data.as_is} debts={data.debts} />
            </>
          )}

          <SectionTitle>What you owe</SectionTitle>
          <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {data.debts.map((debt) => (
              <div key={debt.account_id} className="space-y-2 px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 truncate text-body">{debt.name}</span>
                  <span className="num shrink-0 text-body font-semibold">{formatPHP(debt.owed)}</span>
                </div>
                <div className="flex items-end gap-3">
                  <TextField
                    className="w-36"
                    label="A month"
                    value={typedPayments[debt.account_id] ?? ''}
                    onChange={(e) => setTypedPayments((p) => ({ ...p, [debt.account_id]: sanitizeAmount(e.target.value) }))}
                    inputMode="decimal"
                    placeholder={debt.payment_source === 'yours' ? '' : debt.payment.replace(/\.00$/, '')}
                    aria-label={`${debt.name} payment a month`}
                  />
                  <p className="min-w-0 flex-1 pb-3 text-caption text-ink-3">
                    {typedPayments[debt.account_id]?.trim() ? 'typed here, for this try' : SOURCE[debt.payment_source]}
                    {' · '}
                    {rateLabel(debt)}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <p className="px-1 text-footnote text-ink-3">
            Interest is an estimate from the rate typed on each card or loan (edit the account to add one). Extra
            money on an installment plan finishes it sooner — the monthly payment stays the same. Nothing here is
            saved or paid.
          </p>
        </div>
      )}
    </>
  );
}
