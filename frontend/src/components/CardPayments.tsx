/**
 * A credit card's monthly payments, on the card's own page (ACC-34, 2026-09-15).
 *
 * Built for a card that arrived by import (DAT-21) with a balance and no plans:
 *
 *  - PLANS ON THIS CARD - every installment on it, what each still has to go,
 *    and the other charges that repeat here. Add or edit in place.
 *
 *  - DOES IT BALANCE? - owed on the card now plus what the plans have not yet
 *    billed is everything still to pay. Type the total your card's own app
 *    shows and the difference appears. A card imported with its whole debt
 *    in the balance counts a new plan twice; "Make it match" sets today's
 *    owed to that total less the plans, through the opening balance - ACC-28's
 *    "fix the opening balance", which writes no entry.
 *
 *  - YOU PAY IT EACH MONTH - the recurring transfer into the card, and when
 *    the card reaches zero at that pace. The month-by-month owed is summed
 *    from GET /projection's items; every DATE comes from the server's one
 *    occurrences() engine, never worked out here.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { updateAccount, type Account, type Credit } from '../lib/accounts';
import { centavos, formatPHP, fromCentavos, toDecimalString } from '../lib/money';
import { getProjection, listRules, scheduleLabel, type Projection, type Rule } from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { CardBills } from './CardBills';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const short = (iso: string) => format(parseISO(iso), 'd MMM');

function centsOf(typed: string): number | null {
  try {
    return typed.trim() ? centavos(toDecimalString(typed.trim())) : null;
  } catch {
    return null;
  }
}

/** One leading minus, one point, two places. */
function clean(input: string): string {
  const [whole = '', ...rest] = input.replace(/[^\d.]/g, '').split('.');
  return rest.length ? `${whole}.${rest.join('').slice(0, 2)}` : whole;
}

function Line({ label, value, strong = false, tone = '' }: { label: string; value: string; strong?: boolean; tone?: string }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? 'border-t border-line pt-2' : ''}`}>
      <span className={`text-footnote ${strong ? 'font-semibold text-ink' : 'text-ink-2'}`}>{label}</span>
      <span className={`num text-body ${strong ? 'font-semibold' : ''} ${tone}`}>{value}</span>
    </div>
  );
}

export function CardPayments({ account }: { account: Account }) {
  const credit = account.credit as Credit;
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [total, setTotal] = useState(credit.bills.length > 0 ? credit.bills_left : '');
  // ACC-35: with bills typed, the card app's total is their sum - the check starts from it.
  useEffect(() => {
    if (credit.bills.length > 0) setTotal(credit.bills_left);
  }, [credit.bills.length, credit.bills_left]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listRules(undefined, controller.signal), getProjection(12, controller.signal)])
      .then(([found, ahead]) => {
        setRules(found);
        setProjection(ahead);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, [account.id, version]);

  const plans = (rules ?? []).filter((r) => r.kind === 'installment' && r.account_id === account.id);
  const openPlans = plans.filter((r) => r.installment && !r.installment.closed);
  const charges = (rules ?? []).filter((r) => r.kind !== 'installment' && r.type === 'expense' && r.account_id === account.id && !r.closed_on);
  const payments = (rules ?? []).filter((r) => r.type === 'transfer' && r.counter_account_id === account.id && !r.closed_on);

  // Signed, not credit.owed: owed stops at zero, and a card in credit must still add up.
  const owed = -centavos(account.balance);
  const unbilled = centavos(credit.unpaid_installments);
  const everything = owed + unbilled;
  const typed = centsOf(total);
  const difference = typed === null ? null : typed - everything;
  const target = typed === null ? null : typed - unbilled;

  // The card's owed at the end of each month ahead, from the projection's items - dates are the server's.
  const path = useMemo(() => {
    if (!projection || payments.length === 0) return null;
    let running = owed;
    const all: { label: string; end: string; owed: number }[] = [];
    for (const month of projection.months) {
      for (const item of month.items) {
        if (item.paused) continue;
        const amount = centavos(item.amount);
        if (item.account_id === account.id) running += item.type === 'income' ? -amount : amount;
        else if (item.type === 'transfer' && item.counter_account_id === account.id) running -= amount;
      }
      all.push({ label: format(parseISO(month.start), 'MMM yyyy'), end: month.end, owed: running });
    }
    // Paid off from the first month after which it never owes again - a card in credit before its
    // plans start billing is not paid off.
    let from = -1;
    for (let i = all.length - 1; i >= 0 && (all[i]?.owed ?? 1) <= 0; i--) from = i;
    const settled = from >= 0 ? all[from] : undefined;
    const paidOff = settled ? format(parseISO(settled.end), 'MMMM yyyy') : null;
    return { months: settled ? all.slice(0, from + 1) : all, paidOff };
  }, [projection, payments.length, owed, account.id]);

  const addPlan = () =>
    openRuleSheet({ kind: 'installment', rule: null, prefill: { kind: 'installment', type: 'expense', account_id: account.id } });

  const addPayment = () => {
    const payer = lookups.accounts.find((a) => !a.archived && a.id !== account.id && !['credit', 'borrowed', 'lent'].includes(a.type));
    const due = credit.payment_due >= localToday() ? credit.payment_due : localToday();
    openRuleSheet({ kind: 'standard', rule: null, prefill: {
      kind: 'standard', type: 'transfer', name: `${account.name} payment`, account_id: payer?.id,
      counter_account_id: account.id, frequency: 'monthly', start: due,
    } });
  };

  const makeItMatch = async () => {
    if (target === null) return;
    setBusy(true);
    setError(null);
    try {
      await updateAccount(account.id, {
        name: account.name, type: account.type, subtype: account.subtype, colour: account.colour, icon: account.icon,
        counts_in_cash_on_hand: account.counts_in_cash_on_hand, note: account.note,
        statement_closing_day: credit.statement_closing_day, payment_due_day: credit.payment_due_day,
        credit_limit: credit.limit, spending_limit: credit.spending_limit, posting_lag_days: credit.posting_lag_days,
        // A card's balance is minus what it owes (ACC-27).
        balance: fromCentavos(-target), balance_action: 'fix_opening',
        balance_note: 'Owed matched to the card app, less installment plans',
      });
      setTotal('');
      setConfirming(false);
      useLedgerStore.setState((s) => ({ version: s.version + 1 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setBusy(false);
  };

  if (rules === null && !error) return <div className="skeleton mt-3 h-40 rounded-card" aria-hidden="true" />;

  return (
    <div className="mt-3 space-y-3">
      {error && <p className="rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      <CardBills account={account} />

      <Card padded={false}>
        <div className="flex items-center justify-between px-4 pb-1 pt-3">
          <h3 className="text-headline">Plans on this card</h3>
          <button type="button" onClick={addPlan} className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent active:bg-accent-soft">
            + Add
          </button>
        </div>
        {openPlans.length === 0 && charges.length === 0 ? (
          <p className="px-4 pb-4 text-footnote text-ink-3">
            No installments yet. Add each one still running — price, number of payments, first payment — and the check below
            shows whether they explain what you owe.
          </p>
        ) : (
          <div className="divide-y divide-line">
            {openPlans.map((rule) => {
              const plan = rule.installment!;
              const left = plan.payments - plan.payments_posted;
              return (
                <button key={rule.id} type="button" onClick={() => openRuleSheet({ kind: 'installment', rule, prefill: null })}
                  className="flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-surface-2">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body">{rule.name}</span>
                    <span className="block truncate text-footnote text-ink-3">
                      {formatPHP(plan.per_payment)} × {plan.payments} · {left} left{rule.next_on ? ` · next ${short(rule.next_on)}` : ''}
                    </span>
                  </span>
                  <span className="num shrink-0 text-body font-semibold">{formatPHP(plan.remaining)}</span>
                </button>
              );
            })}
            {charges.map((rule) => (
              <button key={rule.id} type="button" onClick={() => openRuleSheet({ kind: rule.kind, rule, prefill: null })}
                className="flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-surface-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">{rule.name}</span>
                  <span className="block truncate text-footnote text-ink-3">{scheduleLabel(rule)}{rule.next_on ? ` · next ${short(rule.next_on)}` : ''}</span>
                </span>
                <span className="num shrink-0 text-body">{formatPHP(rule.next_amount ?? rule.amount)}</span>
              </button>
            ))}
          </div>
        )}
        {plans.length > openPlans.length && (
          <p className="px-4 pb-3 text-caption text-ink-3">{plans.length - openPlans.length} paid-off plan{plans.length - openPlans.length === 1 ? '' : 's'} not shown</p>
        )}
      </Card>

      <Card className="space-y-2">
        <h3 className="text-headline">Does it balance?</h3>
        <Line label={owed < 0 ? 'In credit on the card now' : 'Owed on the card now'} value={formatPHP(fromCentavos(Math.abs(owed)))} />
        <Line label="Plans not billed yet" value={formatPHP(credit.unpaid_installments)} />
        <Line label="Everything still to pay" value={formatPHP(fromCentavos(everything))} strong />
        <label className="block pt-2">
          <span className="text-footnote font-semibold text-ink-2">What your card’s app says you owe in total</span>
          <input value={total} onChange={(e) => { setTotal(clean(e.target.value)); setConfirming(false); }} inputMode="decimal" placeholder="0.00"
            className="num mt-1.5 block min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-right text-body" />
        </label>
        {difference !== null && (
          difference === 0 ? (
            <p className="rounded-xl bg-ok/10 px-3 py-2 text-footnote font-semibold text-ok">✓ It balances — the plans explain what you owe.</p>
          ) : (
            <div className="space-y-2 rounded-xl bg-warn/10 px-3 py-2">
              <p className="text-footnote font-semibold text-warn">
                {difference > 0
                  ? `${formatPHP(fromCentavos(difference))} more in the card’s app — a plan or a purchase is missing here.`
                  : `${formatPHP(fromCentavos(-difference))} less in the card’s app — today’s owed may already count these plans.`}
              </p>
              {target !== null && (confirming ? (
                <div className="space-y-2">
                  <p className="text-footnote text-ink-2">
                    Set owed now to <span className="num font-semibold text-ink">{formatPHP(fromCentavos(target))}</span>, so that with the
                    plans it comes to {formatPHP(fromCentavos(typed ?? 0))}? The starting balance changes; no entry is added.
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>Cancel</Button>
                    <Button onClick={() => void makeItMatch()} disabled={busy}>Make it match</Button>
                  </div>
                </div>
              ) : (
                <Button block variant="secondary" onClick={() => setConfirming(true)}>Make it match</Button>
              ))}
            </div>
          )
        )}
      </Card>

      <Card className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-headline">You pay it each month</h3>
          {payments.length > 0 && (
            <button type="button" onClick={addPayment} className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent active:bg-accent-soft">
              + Add
            </button>
          )}
        </div>
        {payments.length === 0 ? (
          <>
            <p className="text-footnote text-ink-3">
              Set what you pay this card each month — a transfer from your bank that records itself — and see when it is paid off.
            </p>
            <Button block variant="secondary" onClick={addPayment}>Set a monthly payment</Button>
          </>
        ) : (
          <>
            <div className="-mx-4 divide-y divide-line">
              {payments.map((rule) => (
                <button key={rule.id} type="button" onClick={() => openRuleSheet({ kind: rule.kind, rule, prefill: null })}
                  className={`flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-surface-2 ${rule.paused ? 'opacity-60' : ''}`}>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body">
                      From {lookups.accountById.get(rule.account_id)?.name ?? 'an account'}
                    </span>
                    <span className="block truncate text-footnote text-ink-3">
                      {rule.paused ? 'Paused' : scheduleLabel(rule)}{rule.next_on ? ` · next ${short(rule.next_on)}` : ''}
                    </span>
                  </span>
                  <span className="num shrink-0 text-body font-semibold">{formatPHP(rule.next_amount ?? rule.amount)}</span>
                </button>
              ))}
            </div>
            {path && (
              <div className="space-y-1.5 border-t border-line pt-2">
                <p className={`text-footnote font-semibold ${path.paidOff ? 'text-ok' : 'text-warn'}`}>
                  {path.paidOff
                    ? `✓ Paid off by ${path.paidOff} at this pace`
                    : `Still ${formatPHP(fromCentavos(Math.max(path.months[path.months.length - 1]?.owed ?? owed, 0)))} owed after ${path.months.length} months — pay more, or check the plans`}
                </p>
                <ul className="space-y-0.5">
                  {path.months.map((month) => (
                    <li key={month.label} className="num flex justify-between text-footnote text-ink-2">
                      <span>{month.label}</span>
                      <span className={month.owed <= 0 ? 'text-ok' : ''}>
                        {month.owed <= 0 ? (month.owed === 0 ? 'Paid off' : `${formatPHP(fromCentavos(-month.owed))} in credit`) : formatPHP(fromCentavos(month.owed))}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="text-caption text-ink-3">Counts the plans and repeating charges on the card — not new purchases you have yet to make.</p>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
