/**
 * REC-14 - the installment plans and repeating charges running on ONE account,
 * wherever that account is (fixed 2026-09-16, user: a plan on a loan or a
 * borrowed account appeared on the Recurring page and nowhere else).
 *
 * A plan is money you owe from the day you take it out, so the account it sits
 * on has to say so, whether it is a credit card, a loan or a store card. The
 * card's page shows this list inside CardPayments, beside its bills and the
 * monthly payment; every other account shows it on its own.
 *
 * Every figure comes from the server's one engine (`installment` on the rule):
 * what each payment is, how many are left and what the plan still owes are
 * never worked out here.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { formatPHP } from '../lib/money';
import { listRules, scheduleLabel, type Rule } from '../lib/recurring';
import { type Account } from '../lib/accounts';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';
import { PayNowSheet } from './PayNowSheet';
import { PlanPaymentSheet } from './PlanPaymentSheet';
import { Card } from './ui/Card';

const short = (iso: string) => format(parseISO(iso), 'd MMM');

export interface AccountPlansProps {
  account: Account;
  /** The rules the parent already fetched; left out, this fetches its own. */
  rules?: Rule[] | null;
  /** A card always shows the list, with its "add one" hint; other accounts only when there is something. */
  alwaysShow?: boolean;
  /**
   * REC-32. Open the payment sheet for a plan. The account page passes one so
   * its own Pay back button and these rows share a single sheet; left out,
   * the list hosts the sheet itself.
   */
  onPay?: (rule: Rule) => void;
  /** Told which plans are open, so the page can route Pay back to them. */
  onPlans?: (open: Rule[]) => void;
}

export function AccountPlans({ account, rules: given, alwaysShow = false, onPay, onPlans }: AccountPlansProps) {
  const version = useLedgerStore((s) => s.version);
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const lookups = useLookups();
  const [fetched, setFetched] = useState<Rule[] | null>(null);
  const [paying, setPaying] = useState<Rule | null>(null);
  /** REC-33. The repeating charge being paid early. */
  const [payingNow, setPayingNow] = useState<Rule | null>(null);
  const rules = given ?? fetched;

  useEffect(() => {
    if (given !== undefined) return;
    const controller = new AbortController();
    listRules(undefined, controller.signal)
      .then(setFetched)
      .catch(() => undefined);
    return () => controller.abort();
  }, [given, account.id, version]);

  const mine = (rules ?? []).filter((r) => r.account_id === account.id);
  const plans = mine.filter((r) => r.kind === 'installment');
  const openPlans = plans.filter((r) => r.installment && !r.installment.closed);
  const charges = mine.filter((r) => r.kind !== 'installment' && r.type === 'expense' && !r.closed_on);
  const openIds = openPlans.map((r) => r.id).join(',');

  useEffect(() => {
    onPlans?.(openPlans);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openIds, rules]);

  const pay = (rule: Rule) => (onPay ? onPay(rule) : setPaying(rule));

  if (!alwaysShow && openPlans.length === 0 && charges.length === 0) return null;

  const addPlan = () =>
    openRuleSheet({
      kind: 'installment',
      rule: null,
      prefill: { kind: 'installment', type: 'expense', account_id: account.id },
    });

  return (
    <Card padded={false}>
      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <h3 className="text-headline">{account.credit ? 'Plans on this card' : 'Plans on this account'}</h3>
        <button type="button" onClick={addPlan}
          className="min-h-tap rounded-full px-3 text-footnote font-semibold text-accent active:bg-accent-soft">
          + Add
        </button>
      </div>
      {openPlans.length === 0 && charges.length === 0 ? (
        <p className="px-4 pb-4 text-footnote text-ink-3">
          No installments yet. Add each one still running — price, number of payments, first payment — and what the card
          owes counts all of it from today.
        </p>
      ) : (
        <div className="divide-y divide-line">
          {openPlans.map((rule) => {
            const plan = rule.installment!;
            // REC-32. A card's plan is paid through the card's bill, so its figure
            // is what the plan has still to BILL; any other account is paid on the
            // plan itself, so its figure is what is left to PAY.
            const paidHere = !account.credit || plan.money_paid !== '0.00';
            return (
              <div key={rule.id} className="flex min-h-14 items-center gap-2 pr-3">
                <button type="button" onClick={() => openRuleSheet({ kind: 'installment', rule, prefill: null })}
                  className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pl-4 text-left transition active:bg-surface-2">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body">{rule.name}</span>
                    <span className="line-clamp-2 block text-footnote text-ink-3">
                      {formatPHP(plan.current_payment !== '0.00' ? plan.current_payment : plan.per_payment)} a month
                      {' · '}{plan.payments_left} to go
                      {paidHere && plan.money_paid !== '0.00' ? ` · ${formatPHP(plan.money_paid)} paid` : ''}
                      {rule.next_on ? ` · next ${short(rule.next_on)}` : ''}
                    </span>
                  </span>
                  <span className="num shrink-0 text-body font-semibold">
                    {formatPHP(paidHere ? plan.left_to_pay : plan.remaining)}
                  </span>
                </button>
                <button type="button" onClick={() => pay(rule)} aria-label={`Pay ${rule.name}`}
                  className="min-h-tap shrink-0 rounded-full bg-accent-soft px-3 text-footnote font-semibold text-accent active:scale-95">
                  Pay
                </button>
              </div>
            );
          })}
          {charges.map((rule) => (
            <div key={rule.id} className="flex min-h-14 items-center gap-2 pr-3">
              <button type="button" onClick={() => openRuleSheet({ kind: rule.kind, rule, prefill: null })}
                className={`flex min-w-0 flex-1 items-center gap-3 py-2.5 pl-4 text-left transition active:bg-surface-2 ${
                  account.credit ? 'pr-1' : ''
                }`}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">{rule.name}</span>
                  <span className="block truncate text-footnote text-ink-3">
                    {rule.paused ? 'Paused' : scheduleLabel(rule)}{rule.next_on ? ` · next ${short(rule.next_on)}` : ''}
                  </span>
                </span>
                <span className="num shrink-0 text-body">{formatPHP(rule.next_amount ?? rule.amount)}</span>
              </button>
              {/* REC-33. On an account the money leaves itself, a repeating charge can be
                  paid early. A card's charges are paid through the card's bill instead. */}
              {!account.credit && !rule.paused && rule.next_on && (
                <button type="button" onClick={() => setPayingNow(rule)} aria-label={`Pay ${rule.name} now`}
                  className="min-h-tap shrink-0 rounded-full bg-accent-soft px-3 text-footnote font-semibold text-accent active:scale-95">
                  Pay
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {plans.length > openPlans.length && (
        <p className="px-4 pb-3 text-caption text-ink-3">
          {plans.length - openPlans.length} paid-off plan{plans.length - openPlans.length === 1 ? '' : 's'} not shown
        </p>
      )}
      {!onPay && <PlanPaymentSheet rule={paying} accounts={lookups.accounts} onClose={() => setPaying(null)} />}
      <PayNowSheet rule={payingNow} accountName={account.name} onClose={() => setPayingNow(null)} />
      {!account.credit && openPlans.length > 0 && (
        <p className="border-t border-line px-4 py-3 text-footnote text-ink-2">
          Pay a plan here and it counts against it — pay more than is due and you choose whether the extra lowers the
          monthly payment or finishes it sooner. What is left is counted in what you owe, and in net worth.
        </p>
      )}
    </Card>
  );
}
