/**
 * Accounts (ACC-01..ACC-30).
 *
 * The screen opens on CASH ON HAND, because that is the number this app is
 * about (ACC-17) — "what is in my pockets", not net worth. It is stated once,
 * large, with the accounts it is the sum of directly beneath it, so the total
 * and its parts can never appear to disagree.
 *
 * Only credit cards carry more than a balance, because a card is the one
 * account whose balance does not answer the questions you have about it:
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
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AccountSheet } from '../components/AccountSheet';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { StatementSheet } from '../components/StatementSheet';
import { GlyphTile } from '../components/StylePicker';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { toneFor, type Tone } from '../components/ui/Ring';
import { TYPE_LABEL, listAccounts, type Account, type AccountList, type Credit } from '../lib/accounts';
import { centavos, formatPHP } from '../lib/money';

const isZero = (value: string) => /^-?0+(\.0+)?$/.test(value);
const day = (iso: string) => format(parseISO(iso), 'd MMM');

const BAR: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger' };
const TEXT: Record<Tone, string> = { ok: 'text-ink-2', warn: 'text-warn', danger: 'text-danger' };

function Balance({ value, muted = false }: { value: string; muted?: boolean }) {
  const negative = value.startsWith('-');
  return (
    <span className={`num text-body font-semibold ${muted ? 'text-ink-3' : negative ? 'text-danger' : 'text-ink'}`}>
      {formatPHP(value)}
    </span>
  );
}

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
function BillLine({ credit }: { credit: Credit }) {
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
  if (difference === null) return { label: 'Check statement', className: 'text-accent' };
  if (isZero(difference)) return { label: '✓ Statement matches the bank', className: 'text-ok' };
  return { label: `Statement differs by ${formatPHP(difference.replace(/^-/, ''))}`, className: 'text-warn' };
}

function CreditDetails({ account, onCheck }: { account: Account; onCheck: (a: Account) => void }) {
  const credit = account.credit as Credit;
  const ceiling = credit.limit ? centavos(credit.limit) : 0;
  const action = statementAction(credit);
  return (
    <div className="mt-2 space-y-1.5">
      <BillLine credit={credit} />
      <OwnLimit credit={credit} />
      <div className="space-y-1 pt-1">
        <p className="text-footnote text-ink-3">
          {credit.available !== null ? (
            <>
              <span className="num">{formatPHP(credit.available)}</span> of the bank’s limit left
            </>
          ) : (
            <>
              <span className="num">{formatPHP(credit.owed)}</span> on the card
            </>
          )}
        </p>
        {ceiling > 0 && <Bar percent={(centavos(credit.owed) / ceiling) * 100} colour={account.colour} />}
      </div>
      <button
        type="button"
        onClick={() => onCheck(account)}
        className={`-ml-1 min-h-tap rounded-xl px-1 text-footnote font-semibold active:bg-surface-2 ${action.className}`}
      >
        {action.label}
      </button>
    </div>
  );
}

function AccountRow({
  account,
  onEdit,
  onCheck,
}: {
  account: Account;
  onEdit: (a: Account) => void;
  onCheck: (a: Account) => void;
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <button type="button" onClick={() => onEdit(account)} aria-label={`Edit ${account.name}`} className="shrink-0">
        <GlyphTile icon={account.icon} colour={account.colour} />
      </button>
      <div className="min-w-0 flex-1">
        <button type="button" onClick={() => onEdit(account)} className="block w-full text-left transition active:opacity-70">
          <span className="flex items-baseline justify-between gap-3">
            <span className="truncate text-body">{account.name}</span>
            <Balance value={account.balance} muted={account.archived} />
          </span>
          <span className="mt-0.5 block text-footnote text-ink-3">
            {TYPE_LABEL[account.type]}
            {!account.counts_in_cash_on_hand && !account.archived && ' · not counted'}
          </span>
        </button>
        {account.credit && !account.archived && <CreditDetails account={account} onCheck={onCheck} />}
      </div>
    </div>
  );
}

export function Accounts() {
  const navigate = useNavigate();
  const [data, setData] = useState<AccountList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [checking, setChecking] = useState<Account | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    return listAccounts(signal)
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const open = (account: Account | null) => {
    setEditing(account);
    setSheetOpen(true);
  };

  const active = data?.accounts.filter((a) => !a.archived) ?? [];
  const archived = data?.accounts.filter((a) => a.archived) ?? [];
  const excluded = data ? data.cash_on_hand.excluded_ids.filter((id) => !archived.some((a) => a.id === id)) : [];

  return (
    <>
      <ScreenHeader
        title="Accounts"
        subtitle={<button type="button" className="text-accent" onClick={() => navigate('/more')}>‹ More</button>}
        action={
          <Button size="md" onClick={() => open(null)} aria-label="Add account">
            <PlusIcon size={20} />
            Add
          </Button>
        }
      />

      {data && (
        <Card className="py-6 text-center">
          <p className="text-footnote font-medium text-ink-2">Cash on hand</p>
          <p className="num mt-1 text-display">{formatPHP(data.cash_on_hand.total)}</p>
          <p className="mt-1.5 text-footnote text-ink-3">
            {active.length === 0
              ? 'Nothing tracked yet'
              : `Across ${data.cash_on_hand.account_ids.length} of ${active.length} account${active.length === 1 ? '' : 's'}`}
            {excluded.length > 0 && ` · ${excluded.length} not counted`}
          </p>
        </Card>
      )}

      {error && (
        <p className="mt-4 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error} <button type="button" className="font-semibold underline" onClick={() => void load()}>Try again</button>
        </p>
      )}

      {data && active.length === 0 && !error && (
        <Card className="mt-4 text-center">
          <p className="text-body">Add the accounts you actually spend from.</p>
          <p className="mt-1 text-footnote text-ink-2">
            Your wallet, your bank, your card. Everything else is built on top of them.
          </p>
          <Button className="mt-4" onClick={() => open(null)}>
            Add your first account
          </Button>
        </Card>
      )}

      {active.length > 0 && (
        <div className="mt-4 divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
          {active.map((account) => (
            <AccountRow key={account.id} account={account} onEdit={open} onCheck={setChecking} />
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <div className="mt-5">
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            className="min-h-tap w-full px-1 text-left text-footnote font-semibold uppercase tracking-wide text-ink-3"
          >
            Archived · {archived.length} {showArchived ? '▴' : '▾'}
          </button>
          {showArchived && (
            <div className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
              {archived.map((account) => (
                <AccountRow key={account.id} account={account} onEdit={open} onCheck={setChecking} />
              ))}
            </div>
          )}
        </div>
      )}

      <AccountSheet
        open={sheetOpen}
        account={editing}
        onClose={() => setSheetOpen(false)}
        onSaved={() => void load()}
      />
      <StatementSheet
        open={checking !== null}
        account={checking}
        onClose={() => setChecking(null)}
        onChanged={() => void load()}
      />
    </>
  );
}
