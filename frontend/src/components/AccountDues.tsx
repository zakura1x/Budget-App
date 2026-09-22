/**
 * A loan's bills, month by month (ACC-40, 2026-09-21 - user: "make the rules
 * in borrowed and loans the same as in credit cards, because in credit cards
 * it deducts the monthly dues in cash on hand, and it shows the bills per
 * month").
 *
 * A card's bills are TYPED from its own app, because the statement is the
 * bank's (ACC-35). A loan's are DERIVED and nothing is typed: the installment
 * plan on it already carries the schedule, so each payment still uncovered is
 * a bill on its own day. Every figure here comes from the server's `dues` -
 * none is worked out in the browser.
 *
 * What is DUE NOW follows the card's rule exactly: everything overdue plus the
 * next one. That is the figure cash on hand holds back (ACC-17) once the
 * account's switch is on, and the card says so where the switch is off.
 */
import { useMemo } from 'react';
import { format, parseISO } from 'date-fns';
import { type Account } from '../lib/accounts';
import { formatPHP } from '../lib/money';
import { Card } from './ui/Card';

const day = (iso: string) => format(parseISO(iso), 'd MMM yyyy');
const month = (iso: string) => format(parseISO(iso), 'MMM yyyy');

/** How many to show: a 37-payment plan would otherwise bury the page. */
const SHOWN = 6;

export function AccountDues({ account }: { account: Account }) {
  const dues = account.dues;
  // One row per payment, but a plan's name only where more than one plan bills
  // this account - otherwise every line would repeat the loan's own name.
  const plans = useMemo(
    () => new Set((dues?.dues ?? []).map((d) => d.rule_id)).size,
    [dues],
  );
  if (!dues || dues.dues.length === 0) return null;

  const shown = dues.dues.slice(0, SHOWN);
  const rest = dues.dues.length - shown.length;

  return (
    <Card className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-headline">Bills</h3>
        <span className="text-footnote text-ink-3">
          {dues.dues.length} payment{dues.dues.length === 1 ? '' : 's'} left
        </span>
      </div>

      <div className="flex items-baseline justify-between gap-2 rounded-card border-2 border-stroke bg-surface-2 px-3 py-2">
        <span className="min-w-0">
          <span className="block text-footnote font-semibold text-ink-2">Due now</span>
          <span className="block text-caption text-ink-3">
            {dues.overdue !== '0.00'
              ? `${formatPHP(dues.overdue)} overdue${dues.next_on ? ` · next ${day(dues.next_on)}` : ''}`
              : dues.next_on
                ? `Due ${day(dues.next_on)}`
                : 'Nothing due'}
          </span>
        </span>
        <span className={`num shrink-0 text-headline ${dues.overdue !== '0.00' ? 'text-danger' : ''}`}>
          {formatPHP(dues.due_now)}
        </span>
      </div>

      <div className="-mx-4 divide-y divide-stroke/80">
        {shown.map((due) => (
          <div key={`${due.rule_id}-${due.on}`} className="flex min-h-12 items-center gap-3 px-4 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body">{month(due.on)}</span>
              <span className="block truncate text-footnote text-ink-3">
                {due.overdue ? 'Overdue · ' : ''}
                {day(due.on)}
                {plans > 1 && due.name ? ` · ${due.name}` : ''}
              </span>
            </span>
            <span className={`num shrink-0 text-body font-semibold ${due.overdue ? 'text-danger' : ''}`}>
              {formatPHP(due.amount)}
            </span>
          </div>
        ))}
      </div>

      <p className="text-footnote text-ink-3">
        {rest > 0 && `${rest} more, ending ${month(dues.dues[dues.dues.length - 1]!.on)}. `}
        {formatPHP(dues.left_to_pay)} left on the schedule.
        {!account.counts_in_cash_on_hand &&
          ' Turn on “Count in cash on hand” for this account to hold back what is due now.'}
      </p>
    </Card>
  );
}
