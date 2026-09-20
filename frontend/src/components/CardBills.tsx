/**
 * A card's bills, typed from its own app (ACC-35, 2026-09-15).
 *
 * For a card like SPayLater whose app already lists "Sep ₱7,754.49 due 15 Oct,
 * Oct ₱4,120.80 due 15 Nov…": type those instead of every purchase behind
 * them. Cash on hand then subtracts only what is due now - overdue bills and
 * the next one - while net worth keeps the whole debt.
 *
 * What is paid is never ticked here: payments into the card from the day the
 * list was saved settle bills oldest first. Editing starts from what is still
 * unpaid, because saving replaces the list and restarts that count - just as
 * a paid bill leaves the card app's Unpaid tab.
 *
 * Tap a bill for what it is made of (BillSheet). Below the bills, the section adds up to what the
 * card owes - the tile's figure - with "Not on a bill yet" for the part no typed bill lists
 * (2026-09-19, user: the bills and what the card owes did not match, and nothing said why).
 */
import { addMonths, format, parseISO } from 'date-fns';
import { useState } from 'react';
import { ApiError } from '../lib/api';
import { setBills, type Account, type Bill, type Credit } from '../lib/accounts';
import { afterWrite } from '../lib/invalidate';
import { formatPHP, sanitizeAmount, toDecimalString } from '../lib/money';
import { localToday } from '../lib/transactions';
import { BillSheet } from './BillSheet';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

interface Row {
  key: number;
  due: string;
  amount: string;
}

const typedFrom = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);

export function CardBills({ account }: { account: Account }) {
  const credit = account.credit as Credit;
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<Bill | null>(null);
  const [why, setWhy] = useState(false);

  const start = () => {
    // Everything still unpaid, as the card's app shows it: a saved list replaces the plans and
    // purchases recorded before it (the server adds only what is recorded later), so saving
    // without a change keeps every total (2026-09-17).
    const unpaid = credit.bills.filter((b) => b.left !== '0.00');
    setRows(unpaid.length
      ? unpaid.map((b, i) => ({ key: i, due: b.due, amount: typedFrom(b.left) }))
      : [{ key: 0, due: credit.payment_due >= localToday() ? credit.payment_due : localToday(), amount: '' }]);
    setError(null);
    setEditing(true);
  };

  const addRow = () =>
    setRows((current) => {
      const last = current[current.length - 1];
      const due = last ? format(addMonths(parseISO(last.due), 1), 'yyyy-MM-dd') : localToday();
      return [...current, { key: Date.now(), due, amount: '' }];
    });

  const save = async (list: Row[]) => {
    setBusy(true);
    setError(null);
    try {
      await setBills(account.id, list.filter((r) => r.amount.trim()).map((r) => ({ due: r.due, amount: toDecimalString(r.amount) })));
      setEditing(false);
      // ACC-35 - a typed bill list changes cash on hand (the card adds -due_now) and
      // the card-due alert, which is a budget figure and the tab bar's dot.
      afterWrite('accounts', 'budget', 'projection');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setBusy(false);
  };

  if (editing) {
    return (
      <Card className="space-y-3">
        <h3 className="text-headline">Bills from the card’s app</h3>
        <p className="text-footnote text-ink-3">Type the unpaid bills exactly as the app lists them — due date and amount.</p>
        <div className="space-y-2">
          {rows.map((row) => (
            <div key={row.key} className="flex items-center gap-2">
              <input type="date" value={row.due} aria-label="Due date"
                onChange={(e) => e.target.value && setRows((rs) => rs.map((r) => (r.key === row.key ? { ...r, due: e.target.value } : r)))}
                className="min-h-tap min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-2.5 text-footnote" />
              <input value={row.amount} inputMode="decimal" placeholder="0.00" aria-label="Amount"
                onChange={(e) => setRows((rs) => rs.map((r) => (r.key === row.key ? { ...r, amount: sanitizeAmount(e.target.value) } : r)))}
                className="num min-h-tap w-28 rounded-xl border-2 border-stroke bg-surface px-2.5 text-right text-body" />
              <button type="button" aria-label="Remove bill" onClick={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}
                className="flex h-tap w-8 items-center justify-center text-ink-3">×</button>
            </div>
          ))}
        </div>
        <button type="button" onClick={addRow} className="min-h-tap text-footnote font-semibold text-accent-ink">+ Add next month’s bill</button>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <div className="grid grid-cols-2 gap-2">
          <Button variant="ghost" onClick={() => setEditing(false)} disabled={busy}>Cancel</Button>
          <Button onClick={() => void save(rows)} disabled={busy}>Save bills</Button>
        </div>
        {credit.bills.length > 0 && (
          <Button variant="ghost" block className="text-danger" onClick={() => void save([])} disabled={busy}>
            Remove the bills
          </Button>
        )}
      </Card>
    );
  }

  if (credit.bills.length === 0) {
    return (
      <Card className="space-y-2">
        <h3 className="text-headline">Bills from the card’s app</h3>
        <p className="text-footnote text-ink-3">
          Does the card’s app already list what you pay each month? Type those bills — no need to add every purchase — and cash on
          hand counts only this month’s bill. Net worth still counts the whole debt.
        </p>
        <Button block variant="secondary" onClick={start}>Type the bills</Button>
      </Card>
    );
  }

  // What the card owes = bills left + not on a bill yet - charges on the bills not made yet.
  const unbilled = credit.not_on_bill ?? '0.00';
  const over = unbilled.startsWith('-');
  const missing = unbilled !== '0.00';
  const notCharged = (credit.bills_not_charged ?? '0.00') !== '0.00';
  const reconciles = missing || notCharged;

  return (
    <Card padded={false}>
      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <h3 className="text-headline">Bills</h3>
        <button type="button" onClick={start} className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent-ink active:bg-accent-soft">
          Edit
        </button>
      </div>
      <div className="divide-y divide-stroke/80">
        {credit.bills.map((bill) => {
          const paid = bill.left === '0.00';
          const part = !paid && bill.paid !== '0.00';
          return (
            <button type="button" key={bill.due} onClick={() => setOpened(bill)}
              className={`flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left active:bg-surface-2 ${paid ? 'opacity-60' : ''}`}>
              <span className="min-w-0 flex-1">
                <span className="block text-body">Due {format(parseISO(bill.due), 'd MMM yyyy')}</span>
                <span className={`block text-footnote ${bill.overdue ? 'font-semibold text-danger' : 'text-ink-3'}`}>
                  {paid ? '✓ Paid' : bill.overdue ? 'Overdue' : part ? `${formatPHP(bill.paid)} paid` : 'Unpaid'}
                  {(bill.from_purchases ?? '0.00') !== '0.00' && (
                    <span className="text-accent-ink">
                      {' · '}
                      {bill.typed === '0.00' && bill.from_plans === '0.00'
                        ? 'new purchases'
                        : `incl. ${formatPHP(bill.from_purchases)} new purchases`}
                    </span>
                  )}
                  {bill.from_plans !== '0.00' && (
                    <span className="text-accent-ink">
                      {' · '}
                      {bill.typed === '0.00' && (bill.from_purchases ?? '0.00') === '0.00'
                        ? 'from plans'
                        : `incl. ${formatPHP(bill.from_plans)} from plans`}
                    </span>
                  )}
                </span>
              </span>
              <span className="num shrink-0 text-right">
                <span className="block text-body font-semibold">{formatPHP(paid ? bill.amount : bill.left)}</span>
                {part && <span className="block text-caption text-ink-3">of {formatPHP(bill.amount)}</span>}
              </span>
              <span aria-hidden="true" className="shrink-0 text-ink-3">›</span>
            </button>
          );
        })}
      </div>
      <div className="space-y-1 border-t border-stroke/40 px-4 py-3">
        <div className="flex justify-between text-footnote">
          <span className="text-ink-2">Due now — counted in cash on hand</span>
          <span className="num font-semibold">{formatPHP(credit.due_now ?? '0.00')}</span>
        </div>
        <div className="flex justify-between text-footnote">
          <span className="text-ink-2">All bills left</span>
          <span className="num">{formatPHP(credit.bills_left)}</span>
        </div>
        {reconciles && (
          <>
            {notCharged && (
              <div className="flex justify-between text-footnote">
                <span className="text-ink-2">Charges on the bills not made yet</span>
                <span className="num">−{formatPHP(credit.bills_not_charged)}</span>
              </div>
            )}
            {missing && (
              <button type="button" onClick={() => setWhy((w) => !w)} aria-expanded={why}
                className="flex min-h-tap w-full items-center justify-between text-left text-footnote">
                <span className="font-semibold text-accent-ink">
                  {over ? 'The bills hold more than the card owes' : 'Not on a bill yet'} {why ? '▴' : '▾'}
                </span>
                <span className="num font-semibold">{formatPHP(over ? unbilled.slice(1) : unbilled)}</span>
              </button>
            )}
            {missing && why && (
              <p className="text-caption text-ink-3">
                {over
                  ? 'The typed bills add up to more than this card’s balance. Check the balance, or the bills in the card’s app.'
                  : 'The card’s balance includes this, but no bill you typed lists it — usually payments the card’s app shows only in a later month. It is not in cash on hand. When the app lists it, add it with Edit.'}
              </p>
            )}
            <div className="flex justify-between border-t border-stroke/40 pt-1 text-footnote font-semibold">
              <span>Card owes</span>
              <span className="num">{formatPHP(credit.owed_with_plans)}</span>
            </div>
          </>
        )}
        <p className="pt-1 text-caption text-ink-3">
          Payments into the card mark bills paid by themselves, oldest first. Installments and repeating charges on this card are
          added to the bill they land on.
        </p>
      </div>
      <BillSheet bill={opened} onClose={() => setOpened(null)} />
    </Card>
  );
}
