/**
 * REC-32 - pay money on an installment plan (2026-09-16, user: "every time the
 * user pays, the system will ask if this would reduce the monthly payment, or
 * keep the same monthly payment and take it off the later payments").
 *
 * The amount starts at the next payment. Paying it - or anything up to what is
 * due - just records the payment. Paying MORE asks what the extra should do,
 * with the server's own numbers for both answers:
 *
 *   Lower the monthly payment     ₱4,722.22 × 36 · done Sep 2029
 *   Keep ₱5,000, finish sooner    34 payments · done Jul 2029
 *
 * Nothing is saved until one is picked; the question comes from the server
 * (PREPAYMENT_CHOICE), which works out both outcomes from the one schedule, so
 * the sheet never does plan arithmetic of its own.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { type Account } from '../lib/accounts';
import { formatPHP, toDecimalString } from '../lib/money';
import {
  payPlan,
  prepaymentQuestion,
  type PrepaymentMode,
  type PrepaymentQuestion,
  type Rule,
} from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { Button } from './ui/Button';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

/** Digits and one point, two places - typed as text, sent as text. */
function clean(input: string): string {
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  return rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
}

const month = (iso: string | null) => (iso ? format(parseISO(iso), 'MMM yyyy') : '—');

export interface PlanPaymentSheetProps {
  rule: Rule | null;
  /** Accounts that can pay - the plan's own account is left out here. */
  accounts: Account[];
  onClose: () => void;
}

export function PlanPaymentSheet({ rule, accounts, onClose }: PlanPaymentSheetProps) {
  const plan = rule?.installment ?? null;
  const payers = accounts.filter(
    (a) => !a.archived && a.id !== rule?.account_id && !['credit', 'borrowed', 'lent', 'investment'].includes(a.type),
  );
  const [amount, setAmount] = useState('');
  const [fromId, setFromId] = useState<number | null>(null);
  const [on, setOn] = useState(localToday());
  const [question, setQuestion] = useState<PrepaymentQuestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!rule) return;
    setAmount(plan && plan.current_payment !== '0.00' ? plan.current_payment : '');
    setFromId(payers[0]?.id ?? null);
    setOn(localToday());
    setQuestion(null);
    setError(null);
    setBusy(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rule?.id]);

  const send = async (mode?: PrepaymentMode) => {
    if (!rule || fromId === null || !amount.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await payPlan(rule.id, { amount: toDecimalString(amount.trim()), from_account_id: fromId, on, mode });
      useLedgerStore.setState((s) => ({ version: s.version + 1 }));
      onClose();
    } catch (e) {
      const asked = prepaymentQuestion(e);
      if (asked) setQuestion(asked);
      else setError(e instanceof ApiError ? e.message : 'That payment did not save. Try again.');
    }
    setBusy(false);
  };

  return (
    <Sheet open={rule !== null} onClose={onClose} title={rule ? `Pay ${rule.name}` : 'Pay'}>
      {rule && plan && (
        <div className="space-y-4 px-5 pb-6">
          <p className="text-footnote text-ink-2">
            <span className="num font-semibold text-ink">{formatPHP(plan.money_paid)}</span> paid ·{' '}
            <span className="num font-semibold text-ink">{formatPHP(plan.left_to_pay)}</span> left ·{' '}
            {plan.payments_left} payment{plan.payments_left === 1 ? '' : 's'} to go
          </p>

          {question ? (
            <div className="space-y-3">
              <p className="text-body">
                <span className="num font-semibold">{formatPHP(question.due)}</span> covers what is due. What should the
                extra <span className="num font-semibold">{formatPHP(question.extra)}</span> do?
              </p>
              <button type="button" disabled={busy} onClick={() => void send('lower')}
                className="block w-full rounded-2xl bg-surface-2 p-4 text-left transition active:scale-[0.99] disabled:opacity-50">
                <span className="block text-body font-semibold">Lower the monthly payment</span>
                <span className="num mt-0.5 block text-footnote text-ink-2">
                  {formatPHP(question.lower.payment)} × {question.lower.payments} · done {month(question.lower.payoff_on)}
                </span>
              </button>
              <button type="button" disabled={busy} onClick={() => void send('shorten')}
                className="block w-full rounded-2xl bg-surface-2 p-4 text-left transition active:scale-[0.99] disabled:opacity-50">
                <span className="block text-body font-semibold">
                  Keep {formatPHP(question.shorten.payment)} a month, finish sooner
                </span>
                <span className="num mt-0.5 block text-footnote text-ink-2">
                  {question.shorten.payments} payments · done {month(question.shorten.payoff_on)}
                </span>
              </button>
              <Button variant="ghost" block onClick={() => setQuestion(null)} disabled={busy}>Change the amount</Button>
            </div>
          ) : (
            <>
              <TextField
                label="Amount"
                value={amount}
                onChange={(e) => setAmount(clean(e.target.value))}
                inputMode="decimal"
                placeholder={plan.current_payment}
                hint={`The next payment is ${formatPHP(plan.current_payment)}. Pay more and you choose what the extra does.`}
              />
              <div>
                <p className="mb-1.5 text-footnote font-semibold text-ink-2">Paid from</p>
                <div className="flex flex-wrap gap-2">
                  {payers.map((a) => (
                    <button key={a.id} type="button" onClick={() => setFromId(a.id)} aria-pressed={fromId === a.id}
                      className={`min-h-tap rounded-full px-4 text-footnote font-semibold transition ${
                        fromId === a.id ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2'
                      }`}>
                      {a.name}
                    </button>
                  ))}
                </div>
              </div>
              <TextField label="Paid on" type="date" value={on} max={localToday()}
                onChange={(e) => e.target.value && setOn(e.target.value)} />
              {error && <p className="text-footnote text-danger">{error}</p>}
              <Button block size="lg" onClick={() => void send()} disabled={busy || fromId === null || !amount.trim()}>
                Record payment
              </Button>
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}
