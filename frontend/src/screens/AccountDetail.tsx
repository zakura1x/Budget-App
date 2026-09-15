/**
 * One account's own page (/accounts/:id, 2026-09-15, after sample_ui/): its
 * balance on a banner in the account's colour, and the TRAIL - every peso that
 * came in or went out of it, newest first.
 *
 * The trail is GET /transactions?account=, which returns this account's own
 * leg of every transfer, each carrying its direction - so IN and OUT are
 * worked out per row (TransactionRow.moneyIn) and summed in centavos. Day
 * groups a page at a time (200 rows); Month reads the whole history first,
 * so a month's totals are never a partial page.
 *
 * + and ⇄ open the add sheet already on this account. Edit opens the account
 * form. A credit card's bill, own limit and statement check live here too.
 */
import { format, parseISO } from 'date-fns';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AccountSheet } from '../components/AccountSheet';
import { CardPayments } from '../components/CardPayments';
import { CreditDetails } from '../components/CreditDetails';
import { CloseIcon, PlusIcon, TransferIcon } from '../components/Icons';
import { StatementSheet } from '../components/StatementSheet';
import { GlyphTile } from '../components/StylePicker';
import { TransactionRow, moneyIn } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Segmented } from '../components/ui/Segmented';
import { useLookups } from '../hooks/useLookups';
import { isOwed, kindLabelOf, listAccounts, type Account } from '../lib/accounts';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { listTransactions, type Transaction } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';

type View = 'day' | 'month';

const PAGE = 200;

const negateAmount = (value: string) =>
  value.startsWith('-') ? value.slice(1) : /^0+(\.0+)?$/.test(value) ? value : `-${value}`;
/** Month view reads the whole trail; this caps it at 8,000 rows. */
const MAX_PAGES = 40;

function totals(rows: Transaction[]) {
  let inward = 0;
  let outward = 0;
  for (const row of rows) {
    if (moneyIn(row)) inward += centavos(row.amount);
    else outward += centavos(row.amount);
  }
  return { inward, outward };
}

function InOut({ rows }: { rows: Transaction[] }) {
  const { inward, outward } = totals(rows);
  return (
    <span className="num flex gap-2.5 text-footnote">
      {inward > 0 && (
        <span>
          <span className="text-ok">IN</span> <span className="font-semibold">{formatPHP(fromCentavos(inward))}</span>
        </span>
      )}
      {outward > 0 && (
        <span>
          <span className="text-ink-3">OUT</span> <span className="font-semibold">{formatPHP(fromCentavos(outward))}</span>
        </span>
      )}
    </span>
  );
}

function group(rows: Transaction[], key: (row: Transaction) => string) {
  const groups: { key: string; rows: Transaction[] }[] = [];
  for (const row of rows) {
    const k = key(row);
    const last = groups[groups.length - 1];
    if (last && last.key === k) last.rows.push(row);
    else groups.push({ key: k, rows: [row] });
  }
  return groups;
}

export function AccountDetail() {
  const { id } = useParams();
  const accountId = Number(id);
  const navigate = useNavigate();
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const openSheet = useUiStore((s) => s.openAddSheet);

  const [account, setAccount] = useState<Account | null>(null);
  const [missing, setMissing] = useState(false);
  const [rows, setRows] = useState<Transaction[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [view, setView] = useState<View>('day');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);

  const loadAccount = useCallback(
    (signal?: AbortSignal) =>
      listAccounts(signal)
        .then((list) => {
          const found = list.accounts.find((a) => a.id === accountId) ?? null;
          setAccount(found);
          setMissing(found === null);
        })
        .catch((e: Error) => e.name !== 'AbortError' && setError(e.message)),
    [accountId],
  );

  /** The first page, or - for Month - every page. */
  const loadTrail = useCallback(
    async (all: boolean, signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        let page = await listTransactions({ account: accountId }, null, signal, PAGE);
        const items = [...page.items];
        for (let n = 1; all && page.next_cursor && n < MAX_PAGES; n++) {
          page = await listTransactions({ account: accountId }, page.next_cursor, signal, PAGE);
          items.push(...page.items);
        }
        setRows(items);
        setCursor(page.next_cursor);
      } catch (e) {
        if ((e as Error).name !== 'AbortError') setError((e as Error).message);
      }
      setLoading(false);
    },
    [accountId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadAccount(controller.signal);
    void loadTrail(view === 'month', controller.signal);
    return () => controller.abort();
  }, [loadAccount, loadTrail, version, view]);

  const more = async () => {
    if (!cursor) return;
    setLoading(true);
    try {
      const page = await listTransactions({ account: accountId }, cursor, undefined, PAGE);
      setRows((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (e) {
      setError((e as Error).message);
    }
    setLoading(false);
  };

  if (missing) {
    return (
      <div className="pt-16 text-center">
        <p className="text-body">That account isn’t here.</p>
        <Button className="mt-4" onClick={() => navigate('/accounts')}>Back to accounts</Button>
      </div>
    );
  }

  const owed = account ? isOwed(account.type) : false;
  const figure = !account
    ? '0.00'
    : account.credit
      ? account.credit.owed
      : owed
        ? negateAmount(account.balance)
        : account.balance;
  const figureLabel = account?.type === 'borrowed' ? 'You owe' : account?.type === 'lent' ? 'Owed to you' : owed ? 'Owed' : 'Balance';
  // ACC-31. Money lent or borrowed moves by transfer, so its page names the two
  // transfers you actually make; every other account keeps + and ⇄.
  const actions =
    account?.type === 'lent'
      ? [
          { label: 'Lend more', preset: { counterAccountId: account.id, type: 'transfer' as const } },
          { label: 'Paid back', preset: { accountId: account.id, type: 'transfer' as const } },
        ]
      : account?.type === 'borrowed'
        ? [
            { label: 'Borrow more', preset: { accountId: account.id, type: 'transfer' as const } },
            { label: 'Pay back', preset: { counterAccountId: account.id, type: 'transfer' as const } },
          ]
        : null;
  const days = rows ? group(rows, (r) => r.txn_date) : [];
  const months = rows ? group(rows, (r) => r.txn_date.slice(0, 7)) : [];

  return (
    <>
      <header className="flex items-center gap-3 pb-3 pt-4">
        <button type="button" onClick={() => navigate('/accounts')} aria-label="Close"
          className="flex h-tap w-tap shrink-0 items-center justify-center rounded-full bg-surface text-ink shadow-card active:bg-surface-2">
          <CloseIcon size={20} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-center text-headline">{account?.name ?? ' '}</h1>
        <button type="button" onClick={() => setEditing(true)} disabled={!account}
          className="min-h-tap shrink-0 rounded-full bg-accent-soft px-4 text-body font-semibold text-accent active:scale-95 disabled:opacity-40">
          Edit
        </button>
      </header>

      {account ? (
        <section className="rounded-card p-5 shadow-card" style={{ backgroundColor: `${account.colour}24` }}
          aria-label={`${account.name} balance`}>
          <div className="flex items-center gap-3">
            <GlyphTile icon={account.icon} colour={account.colour} size={40} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-headline">{account.name}</span>
              <span className="block text-footnote text-ink-2">
                {kindLabelOf(account.type, account.subtype)}
                {account.archived && ' · archived'}
                {!account.counts_in_cash_on_hand && !account.archived && ' · not in cash on hand'}
              </span>
            </span>
            {!account.archived && !actions && (
              <div className="flex shrink-0 gap-2">
                <button type="button" aria-label={`Add a transaction on ${account.name}`}
                  onClick={() => openSheet(undefined, undefined, { accountId: account.id })}
                  className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-on-accent shadow-raised active:scale-95">
                  <PlusIcon size={24} />
                </button>
                <button type="button" aria-label={`Transfer from ${account.name}`}
                  onClick={() => openSheet(undefined, undefined, { accountId: account.id, type: 'transfer' })}
                  className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface text-accent shadow-card active:scale-95">
                  <TransferIcon size={22} />
                </button>
              </div>
            )}
          </div>
          <p className="mt-5 text-footnote text-ink-2">{figureLabel}</p>
          <p className={`num text-display ${!owed && account.balance.startsWith('-') ? 'text-danger' : ''}`}>
            {formatPHP(figure)}
          </p>
          {account.credit?.due_now != null && (
            <p className="mt-1 text-footnote text-ink-2">
              Due now <span className="num font-semibold text-ink">{formatPHP(account.credit.due_now)}</span>
              {' · '}
              {account.credit.bills.some((b) => b.overdue) ? <span className="font-semibold text-danger">overdue</span>
                : format(parseISO(account.credit.payment_due), 'd MMM')}
              {' · counted in cash on hand'}
            </p>
          )}
          {actions && !account.archived && (
            <div className="mt-4 grid grid-cols-2 gap-2.5">
              {actions.map((action, i) => (
                <button key={action.label} type="button" onClick={() => openSheet(undefined, undefined, action.preset)}
                  className={`min-h-tap rounded-full px-4 text-body font-semibold transition active:scale-[0.98] ${
                    i === 0 ? 'bg-surface text-accent shadow-card' : 'bg-accent text-on-accent shadow-raised'
                  }`}>
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </section>
      ) : (
        <div className="skeleton h-44 rounded-card" aria-hidden="true" />
      )}

      {account?.credit && !account.archived && (
        <>
          <div className="mt-3">
            <CreditDetails account={account} onCheck={() => setChecking(true)} />
          </div>
          <CardPayments account={account} />
        </>
      )}

      <div className="flex items-center justify-between gap-3 px-1 pb-2 pt-5">
        <h2 className="text-headline">Transactions</h2>
        <div className="w-44">
          <Segmented<View> label="Group by" value={view} onChange={setView}
            options={[{ value: 'day', label: 'Day' }, { value: 'month', label: 'Month' }]} />
        </div>
      </div>

      {error && (
        <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error}{' '}
          <button type="button" className="font-semibold underline" onClick={() => void loadTrail(view === 'month')}>Try again</button>
        </p>
      )}

      {rows === null && !error && <div className="skeleton h-48 rounded-card" aria-hidden="true" />}
      {rows && rows.length === 0 && (
        <p className="rounded-2xl border border-dashed border-line px-4 py-3 text-footnote text-ink-2">
          Nothing has moved in or out of this account yet.
        </p>
      )}

      {view === 'day' &&
        days.map((d) => (
          <section key={d.key} className="mb-3 overflow-hidden rounded-card bg-surface shadow-card">
            <div className="flex items-baseline justify-between gap-2 border-b border-line px-4 py-2.5">
              <span className="text-footnote font-semibold">{format(parseISO(d.key), 'EEE, MMM d')}</span>
              <InOut rows={d.rows} />
            </div>
            <div className="divide-y divide-line">
              {d.rows.map((row) => (
                <button key={row.id} type="button" onClick={() => openSheet(row)} className="block w-full transition active:bg-surface-2">
                  <TransactionRow row={row} lookups={lookups} accountId={accountId} />
                </button>
              ))}
            </div>
          </section>
        ))}

      {view === 'month' &&
        months.map((m) => {
          const { inward, outward } = totals(m.rows);
          const net = fromCentavos(inward - outward);
          return (
            <section key={m.key} className="mb-3 rounded-card bg-surface p-4 shadow-card">
              <div className="flex items-baseline justify-between">
                <span className="text-body font-semibold">{format(parseISO(`${m.key}-01`), 'MMMM yyyy')}</span>
                <span className="text-caption text-ink-3">
                  {m.rows.length} transaction{m.rows.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-3 divide-x divide-line text-center">
                <div>
                  <p className="text-caption text-ok">IN</p>
                  <p className="num text-footnote font-semibold">{formatPHP(fromCentavos(inward))}</p>
                </div>
                <div>
                  <p className="text-caption text-ink-3">OUT</p>
                  <p className="num text-footnote font-semibold">{formatPHP(fromCentavos(outward))}</p>
                </div>
                <div>
                  <p className="text-caption text-ink-3">Change</p>
                  <p className={`num text-footnote font-semibold ${net.startsWith('-') ? 'text-danger' : ''}`}>
                    {net.startsWith('-') ? '' : '+'}
                    {formatPHP(net)}
                  </p>
                </div>
              </div>
            </section>
          );
        })}

      {loading && rows !== null && <p className="py-3 text-center text-footnote text-ink-3">Loading…</p>}
      {cursor && !loading && (
        <Button block variant="secondary" onClick={() => void more()}>
          Show older
        </Button>
      )}
      {rows && !cursor && account && account.type !== 'investment' && (
        <p className="py-3 text-center text-footnote text-ink-3">
          {owed ? 'Opened owing ' : 'Opened with '}
          <span className="num">{formatPHP(owed ? negateAmount(account.opening_balance) : account.opening_balance)}</span>
        </p>
      )}

      <AccountSheet open={editing} account={account} onClose={() => setEditing(false)} onSaved={() => void loadAccount()} />
      <StatementSheet open={checking} account={checking ? account : null} onClose={() => setChecking(false)}
        onChanged={() => { void loadAccount(); void loadTrail(view === 'month'); }} />
    </>
  );
}
