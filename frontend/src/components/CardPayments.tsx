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
 *  - YOU PAY IT EACH MONTH - AccountPayments, shared with loans and borrowed
 *    accounts since 2026-09-16: the recurring transfer into the card and when
 *    it reaches zero at that pace.
 *
 * The plans list is AccountPlans, shared the same way - every account that
 * carries a plan shows one.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '../lib/api';
import { updateAccount, type Account, type Credit } from '../lib/accounts';
import { centavos, formatPHP, fromCentavos, toDecimalString } from '../lib/money';
import { getProjection, listRules, type Projection, type Rule } from '../lib/recurring';
import { useLedgerStore } from '../stores/ledgerStore';
import { AccountPayments } from './AccountPayments';
import { AccountPlans } from './AccountPlans';
import { CardBills } from './CardBills';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

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
  const version = useLedgerStore((s) => s.version);
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

  // Signed, not credit.owed: owed stops at zero, and a card in credit must still add up.
  const owed = -centavos(account.balance);
  const unbilled = centavos(credit.unpaid_installments);
  // ACC-35. With bills typed from the card's app, the BILLS are what is still
  // to pay: they already hold the purchases the bank has billed and the plan
  // payments that land on them (2026-09-16 - adding the plans a second time
  // was showing a difference that did not exist).
  const typedLeft = credit.bills.reduce((sum, bill) => sum + centavos(bill.typed_left), 0);
  const billed = credit.bills.length > 0;
  const everything = billed ? centavos(credit.bills_left) : owed + unbilled;
  const typed = centsOf(total);
  const difference = typed === null ? null : typed - everything;
  const target = typed === null ? null : typed - unbilled;

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

      <AccountPlans account={account} rules={rules} alwaysShow />

      <Card className="space-y-2">
        <h3 className="text-headline">Does it balance?</h3>
        {billed ? (
          <>
            <Line label="Bills you typed, still unpaid" value={formatPHP(fromCentavos(typedLeft))} />
            <Line label="Plans inside those bills" value={formatPHP(fromCentavos(everything - typedLeft))} />
          </>
        ) : (
          <>
            <Line label={owed < 0 ? 'In credit on the card now' : 'Owed on the card now'} value={formatPHP(fromCentavos(Math.abs(owed)))} />
            <Line label="Plans not billed yet" value={formatPHP(credit.unpaid_installments)} />
          </>
        )}
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
              {target !== null && !billed && (confirming ? (
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

      <AccountPayments account={account} rules={rules} projection={projection} startOn={credit.payment_due} />
    </div>
  );
}
