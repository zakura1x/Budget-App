/**
 * What a credit card carries beyond its balance, shown on the card's own page
 * (AccountDetail) now that every account on the Accounts tab is a small tile:
 *
 *  - THE BILL (ACC-19/20) - what the last statement came to, what is left of
 *    it, and when it is due; "Paid" once it is, even with new purchases on
 *    the card.
 *  - YOUR OWN LIMIT (ACC-21) - how much of this cycle's allowance is gone, in
 *    money-state colour.
 *  - THE STATEMENT CHECK (ACC-24) - one tap to compare the bill with the
 *    bank's figure.
 */
import { format, parseISO } from 'date-fns';
import type { Account, Credit } from '../lib/accounts';
import { centavos, formatPHP } from '../lib/money';
import { Card } from './ui/Card';
import { toneFor, type Tone } from './ui/Ring';

export const isZero = (value: string) => /^-?0+(\.0+)?$/.test(value);
const day = (iso: string) => format(parseISO(iso), 'd MMM');

const BAR: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger' };
const TEXT: Record<Tone, string> = { ok: 'text-ink-2', warn: 'text-warn', danger: 'text-danger' };

function Bar({ percent, className, colour }: { percent: number; className?: string; colour?: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ease-ios ${className ?? ''}`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%`, ...(colour ? { backgroundColor: colour } : {}) }}
      />
    </div>
  );
}

/** ACC-19/20. The last statement, in one line. */
export function BillLine({ credit }: { credit: Credit }) {
  const bill = credit.bill;
  if (isZero(bill.amount)) {
    return <p className="text-footnote text-ink-3">Nothing billed on the {day(bill.closes)} statement</p>;
  }
  if (isZero(bill.left_to_pay)) {
    return (
      <p className="text-footnote text-ok">
        ✓ Paid · <span className="num">{formatPHP(bill.amount)}</span> statement
      </p>
    );
  }
  const tone = bill.overdue ? 'font-semibold text-danger' : credit.due_soon ? 'font-semibold text-warn' : 'text-ink-2';
  return (
    <p className={`text-footnote ${tone}`}>
      <span className="num">{formatPHP(bill.left_to_pay)}</span>
      {bill.left_to_pay !== bill.amount && (
        <>
          {' '}left of <span className="num">{formatPHP(bill.amount)}</span>
        </>
      )}
      {' · '}
      {bill.overdue ? `was due ${day(bill.due)}` : `due ${day(bill.due)}`}
    </p>
  );
}

/** One short status for a card's tile: overdue / due soon / differs / nothing. */
export function cardStatus(credit: Credit): { text: string; className: string } | null {
  const bill = credit.bill;
  if (!isZero(bill.left_to_pay)) {
    if (bill.overdue) return { text: `Was due ${day(bill.due)}`, className: 'text-danger' };
    if (credit.due_soon) return { text: `Due ${day(bill.due)}`, className: 'text-warn' };
  }
  if (bill.difference !== null && !isZero(bill.difference)) return { text: 'Statement differs', className: 'text-warn' };
  return null;
}

/** ACC-21. Your own limit for this cycle - the only bar in money-state colour. */
function OwnLimit({ credit }: { credit: Credit }) {
  if (!credit.spending_limit || credit.limit_left === null) return null;
  const ceiling = centavos(credit.spending_limit);
  const used = ceiling > 0 ? centavos(credit.limit_spent) / ceiling : 0;
  const tone = toneFor(used);
  const over = credit.limit_left.startsWith('-');
  // The words sit ABOVE their own bar, so a figure never reads as the label of the bar under it.
  return (
    <div className="space-y-1 pt-1">
      <p className={`text-footnote ${TEXT[tone]}`}>
        <span className="num">{formatPHP(credit.limit_spent)}</span> of your{' '}
        <span className="num">{formatPHP(credit.spending_limit)}</span> limit this cycle
        {over && (
          <>
            {' · '}
            <span className="num">{formatPHP(credit.limit_left.slice(1))}</span> over
          </>
        )}
      </p>
      <Bar percent={used * 100} className={BAR[tone]} />
    </div>
  );
}

function statementAction(credit: Credit): { label: string; className: string } {
  const difference = credit.bill.difference;
  if (difference === null) return { label: 'Check statement', className: 'bg-accent-soft text-accent' };
  if (isZero(difference)) return { label: '✓ Statement matches the bank', className: 'bg-ok/10 text-ok' };
  return { label: `Statement differs by ${formatPHP(difference.replace(/^-/, ''))}`, className: 'bg-warn/10 text-warn' };
}

export function CreditDetails({ account, onCheck }: { account: Account; onCheck: () => void }) {
  const credit = account.credit as Credit;
  const ceiling = credit.limit ? centavos(credit.limit) : 0;
  const action = statementAction(credit);
  return (
    <Card className="space-y-2">
      {/* Typed bills (ACC-35) say what is due; the statement-derived line would contradict them. */}
      {credit.bills.length === 0 && <BillLine credit={credit} />}
      <OwnLimit credit={credit} />
      <div className="space-y-1 pt-1">
        {credit.available !== null ? (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-footnote text-ink-2">Left to spend</span>
              <span className={`num text-body font-semibold ${credit.available.startsWith('-') ? 'text-danger' : ''}`}>
                {formatPHP(credit.available)}
              </span>
            </div>
            <p className="text-caption text-ink-3">
              of <span className="num">{formatPHP(credit.limit as string)}</span> limit
              {/* ACC-14: the bank blocks the whole unpaid remainder from the limit on day one. */}
              {credit.unpaid_installments !== '0.00' && (
                <>
                  {' · '}
                  <span className="num">{formatPHP(credit.unpaid_installments)}</span> of plans still to bill is held back
                </>
              )}
            </p>
          </>
        ) : (
          <p className="text-footnote text-ink-3">Set the card’s credit limit to see what is left to spend.</p>
        )}
        {ceiling > 0 && <Bar percent={(centavos(credit.owed) / ceiling) * 100} colour={account.colour} />}
      </div>
      <button
        type="button"
        onClick={onCheck}
        className={`min-h-tap rounded-full px-4 text-footnote font-semibold transition active:scale-[0.98] ${action.className}`}
      >
        {action.label}
      </button>
    </Card>
  );
}
