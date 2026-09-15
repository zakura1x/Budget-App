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
 */
import { addMonths, format, parseISO } from 'date-fns';
import { useState } from 'react';
import { ApiError } from '../lib/api';
import { setBills, type Account, type Credit } from '../lib/accounts';
import { formatPHP, sanitizeAmount, toDecimalString } from '../lib/money';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
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

  const start = () => {
    // Only the typed part: plan payments are added by the server on every read, and typing them in
    // here as well would count them twice.
    const unpaid = credit.bills.filter((b) => b.typed_left !== '0.00');
    setRows(unpaid.length
      ? unpaid.map((b, i) => ({ key: i, due: b.due, amount: typedFrom(b.typed_left) }))
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
      useLedgerStore.setState((s) => ({ version: s.version + 1 }));
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
                className="min-h-tap min-w-0 flex-1 rounded-xl border border-line bg-surface px-2.5 text-footnote" />
              <input value={row.amount} inputMode="decimal" placeholder="0.00" aria-label="Amount"
                onChange={(e) => setRows((rs) => rs.map((r) => (r.key === row.key ? { ...r, amount: sanitizeAmount(e.target.value) } : r)))}
                className="num min-h-tap w-28 rounded-xl border border-line bg-surface px-2.5 text-right text-body" />
              <button type="button" aria-label="Remove bill" onClick={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}
                className="flex h-tap w-8 items-center justify-center text-ink-3">×</button>
            </div>
          ))}
        </div>
        <button type="button" onClick={addRow} className="min-h-tap text-footnote font-semibold text-accent">+ Add next month’s bill</button>
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

  return (
    <Card padded={false}>
      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <h3 className="text-headline">Bills</h3>
        <button type="button" onClick={start} className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent active:bg-accent-soft">
          Edit
        </button>
      </div>
      <div className="divide-y divide-line">
        {credit.bills.map((bill) => {
          const paid = bill.left === '0.00';
          const part = !paid && bill.paid !== '0.00';
          return (
            <div key={bill.due} className={`flex min-h-14 items-center gap-3 px-4 py-2 ${paid ? 'opacity-60' : ''}`}>
              <span className="min-w-0 flex-1">
                <span className="block text-body">Due {format(parseISO(bill.due), 'd MMM yyyy')}</span>
                <span className={`block text-footnote ${bill.overdue ? 'font-semibold text-danger' : 'text-ink-3'}`}>
                  {paid ? '✓ Paid' : bill.overdue ? 'Overdue' : part ? `${formatPHP(bill.paid)} paid` : 'Unpaid'}
                  {bill.from_plans !== '0.00' && (
                    <span className="text-accent">
                      {' · '}
                      {bill.typed === '0.00' ? 'from plans' : `incl. ${formatPHP(bill.from_plans)} from plans`}
                    </span>
                  )}
                </span>
              </span>
              <span className="num shrink-0 text-right">
                <span className="block text-body font-semibold">{formatPHP(paid ? bill.amount : bill.left)}</span>
                {part && <span className="block text-caption text-ink-3">of {formatPHP(bill.amount)}</span>}
              </span>
            </div>
          );
        })}
      </div>
      <div className="space-y-1 border-t border-line px-4 py-3">
        <div className="flex justify-between text-footnote">
          <span className="text-ink-2">Due now — counted in cash on hand</span>
          <span className="num font-semibold">{formatPHP(credit.due_now ?? '0.00')}</span>
        </div>
        <div className="flex justify-between text-footnote">
          <span className="text-ink-2">All bills left</span>
          <span className="num">{formatPHP(credit.bills_left)}</span>
        </div>
        <p className="pt-1 text-caption text-ink-3">
          Payments into the card mark bills paid by themselves, oldest first. Installments and repeating charges on this card are
          added to the bill they land on.
        </p>
      </div>
    </Card>
  );
}
