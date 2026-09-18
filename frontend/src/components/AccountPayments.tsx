/**
 * What you pay an account you OWE on, each month - and when it reaches zero at
 * that pace (ACC-34, extended 2026-09-16 to loans and borrowed accounts, after
 * the user: "if I put the installment in borrowed/loans I can't pay the
 * installment in any way").
 *
 * The payment is a recurring TRANSFER from the account you pay out of into
 * this one: money really moves, and the plan's own charges stay what they are.
 * A card and a loan work the same way here - the card's version simply sits
 * inside CardPayments beside its bills.
 *
 * The month-by-month figure is summed from GET /projection's items, so every
 * DATE comes from the server's one occurrences() engine and none is worked out
 * here (REC-22).
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { type Account } from '../lib/accounts';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { getProjection, listRules, scheduleLabel, type Projection, type Rule } from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const short = (iso: string) => format(parseISO(iso), 'd MMM');

export interface AccountPaymentsProps {
  account: Account;
  /** What the parent already fetched; left out, this fetches its own. */
  rules?: Rule[] | null;
  projection?: Projection | null;
  /** The day a new payment should start - a card's due date, or today. */
  startOn?: string;
}

export function AccountPayments({ account, rules: givenRules, projection: givenProjection, startOn }: AccountPaymentsProps) {
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const [fetchedRules, setFetchedRules] = useState<Rule[] | null>(null);
  const [fetchedProjection, setFetchedProjection] = useState<Projection | null>(null);
  const rules = givenRules ?? fetchedRules;
  const projection = givenProjection ?? fetchedProjection;

  useEffect(() => {
    if (givenRules !== undefined && givenProjection !== undefined) return;
    const controller = new AbortController();
    Promise.all([listRules(undefined, controller.signal), getProjection(12, controller.signal)])
      .then(([found, ahead]) => {
        setFetchedRules(found);
        setFetchedProjection(ahead);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [givenRules, givenProjection, account.id, version]);

  const payments = (rules ?? []).filter((r) => r.type === 'transfer' && r.counter_account_id === account.id && !r.closed_on);
  // Signed: an account in credit must still add up, which credit.owed - it stops at zero - could not.
  const owed = -centavos(account.balance);

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
    // Paid off from the first month after which it never owes again - an account in
    // credit before its plans start billing is not paid off.
    let from = -1;
    for (let i = all.length - 1; i >= 0 && (all[i]?.owed ?? 1) <= 0; i--) from = i;
    const settled = from >= 0 ? all[from] : undefined;
    return { months: settled ? all.slice(0, from + 1) : all, paidOff: settled ? format(parseISO(settled.end), 'MMMM yyyy') : null };
  }, [projection, payments.length, owed, account.id]);

  const addPayment = () => {
    const payer = lookups.accounts.find(
      (a) => !a.archived && a.id !== account.id && !['credit', 'borrowed', 'lent'].includes(a.type),
    );
    const start = startOn && startOn >= localToday() ? startOn : localToday();
    openRuleSheet({
      kind: 'standard',
      rule: null,
      prefill: {
        kind: 'standard', type: 'transfer', name: `${account.name} payment`, account_id: payer?.id,
        counter_account_id: account.id, frequency: 'monthly', start,
      },
    });
  };

  const what = account.credit ? 'this card' : 'this account';
  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-headline">You pay it each month</h3>
        {payments.length > 0 && (
          <button type="button" onClick={addPayment}
            className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent-ink active:bg-accent-soft">
            + Add
          </button>
        )}
      </div>
      {payments.length === 0 ? (
        <>
          <p className="text-footnote text-ink-3">
            Set what you pay {what} each month — a transfer from your bank that records itself — and see when it is paid
            off. {!account.credit && 'A plan’s own charges post by themselves; this is the money you send to cover them.'}
          </p>
          <Button block variant="secondary" onClick={addPayment}>Set a monthly payment</Button>
        </>
      ) : (
        <>
          <div className="-mx-4 divide-y divide-stroke/80">
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
            <div className="space-y-1.5 border-t border-stroke/40 pt-2">
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
                      {month.owed <= 0
                        ? (month.owed === 0 ? 'Paid off' : `${formatPHP(fromCentavos(-month.owed))} in credit`)
                        : formatPHP(fromCentavos(month.owed))}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="text-caption text-ink-3">
                Counts the plans and repeating charges on {what} — not new purchases you have yet to make.
              </p>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
