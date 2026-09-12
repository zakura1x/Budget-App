/**
 * Accounts (ACC-01..ACC-18).
 *
 * The screen opens on CASH ON HAND, because that is the number this app is
 * about (ACC-17) — "what is in my pockets", not net worth. It is stated once,
 * large, with the accounts it is the sum of directly beneath it, so the total
 * and its parts can never appear to disagree.
 *
 * Only credit cards carry a meter. A bar under every account would be
 * decoration; under a card it is the one thing you cannot work out by
 * reading the balance — how much of the limit is left, and when it is due.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AccountSheet } from '../components/AccountSheet';
import { GlyphTile } from '../components/StylePicker';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { TYPE_LABEL, listAccounts, type Account, type AccountList } from '../lib/accounts';
import { centavos, formatPHP } from '../lib/money';

function Balance({ value, muted = false }: { value: string; muted?: boolean }) {
  const negative = value.startsWith('-');
  return (
    <span className={`num text-body font-semibold ${muted ? 'text-ink-3' : negative ? 'text-danger' : 'text-ink'}`}>
      {formatPHP(value)}
    </span>
  );
}

/** The one place a bar earns its space: how much of the limit is gone. */
function CreditMeter({ account }: { account: Account }) {
  const credit = account.credit;
  if (!credit) return null;
  const limit = credit.limit;
  const ceiling = limit ? centavos(limit) : 0;
  const used = ceiling > 0 ? Math.min(100, Math.max(0, (centavos(credit.owed) / ceiling) * 100)) : null;

  return (
    <div className="mt-2 space-y-1.5">
      {used !== null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full transition-[width] duration-500 ease-ios"
            style={{ width: `${used}%`, backgroundColor: account.colour }}
          />
        </div>
      )}
      <p className="text-footnote text-ink-2">
        {credit.available !== null ? (
          <>
            <span className="num">{formatPHP(credit.available)}</span> left to spend
          </>
        ) : (
          <>
            <span className="num">{formatPHP(credit.owed)}</span> on the card
          </>
        )}
        {' · '}
        <span className={credit.due_soon ? 'font-semibold text-warn' : undefined}>
          {credit.due_in_days === 0
            ? 'due today'
            : credit.due_in_days > 0
              ? `due in ${credit.due_in_days} days`
              : 'payment overdue'}
        </span>
      </p>
    </div>
  );
}

function AccountRow({ account, onEdit }: { account: Account; onEdit: (a: Account) => void }) {
  return (
    <button
      type="button"
      onClick={() => onEdit(account)}
      className="flex w-full items-start gap-3 px-4 py-3 text-left transition active:bg-surface-2"
    >
      <GlyphTile icon={account.icon} colour={account.colour} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className="truncate text-body">{account.name}</span>
          <Balance value={account.balance} muted={account.archived} />
        </span>
        <span className="mt-0.5 block text-footnote text-ink-3">
          {TYPE_LABEL[account.type]}
          {!account.counts_in_cash_on_hand && !account.archived && ' · not counted'}
        </span>
        {account.credit && !account.archived && <CreditMeter account={account} />}
      </span>
    </button>
  );
}

export function Accounts() {
  const navigate = useNavigate();
  const [data, setData] = useState<AccountList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
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
            <AccountRow key={account.id} account={account} onEdit={open} />
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
                <AccountRow key={account.id} account={account} onEdit={open} />
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
    </>
  );
}
