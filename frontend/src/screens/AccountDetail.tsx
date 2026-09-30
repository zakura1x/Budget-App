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
import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AccountSheet } from '../components/AccountSheet';
import { BalanceCheck } from '../components/BalanceCheck';
import { AccountDues } from '../components/AccountDues';
import { AccountPayments } from '../components/AccountPayments';
import { AccountPlans } from '../components/AccountPlans';
import { ExplainLink } from '../components/ExplainLink';
import { GoalCard, GoalMoneySheet, GoalSheet } from '../components/GoalSheets';
import { PlanPaymentSheet } from '../components/PlanPaymentSheet';
import { CardPayments } from '../components/CardPayments';
import { CreditDetails } from '../components/CreditDetails';
import { CloseIcon, PlusIcon, TransferIcon } from '../components/Icons';
import { StatementSheet } from '../components/StatementSheet';
import { GlyphTile } from '../components/StylePicker';
import { TransactionRow, moneyIn } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Segmented } from '../components/ui/Segmented';
import { useLookups } from '../hooks/useLookups';
import { CHECKABLE, isOwed, kindLabelOf, listAccounts, owedWithPlans } from '../lib/accounts';
import { keys, STALE } from '../lib/queryKeys';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { type Rule } from '../lib/recurring';
import { listGoals, type Goal } from '../lib/security';
import { listTransactions, localToday, type Transaction } from '../lib/transactions';
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
  // TXN-23. A tap shows the entry; the preview's Edit button opens the sheet.
  const openPreview = useUiStore((s) => s.openPreview);

  const [rows, setRows] = useState<Transaction[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [view, setView] = useState<View>('day');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  /** REC-32. The plans open on this account, and the one being paid. */
  const [openPlans, setOpenPlans] = useState<Rule[]>([]);
  const [paying, setPaying] = useState<Rule | null>(null);
  const [editingGoal, setEditingGoal] = useState<Goal | null>(null);
  const [goalMoney, setGoalMoney] = useState<{ goal: Goal; mode: 'add' | 'use' } | null>(null);

  // This page used to fetch the whole account list for itself while `useLookups`
  // fetched the same list beside it - the duplicate in plan §1.3. One shared key now.
  const accountsQuery = useQuery({
    queryKey: keys.accounts(),
    queryFn: ({ signal }) => listAccounts(signal),
    staleTime: STALE.lookups,
  });
  const account = accountsQuery.data?.accounts.find((a) => a.id === accountId) ?? null;
  const missing = accountsQuery.isSuccess && account === null;

  /** GOA-08 - the goals setting money aside in this account (several may share it). */
  const goalsQuery = useQuery({
    queryKey: keys.goals(),
    queryFn: ({ signal }) => listGoals(signal),
    staleTime: STALE.lookups,
  });
  const goals = useMemo(
    () => (goalsQuery.data ?? []).filter((g) => g.account_id === accountId),
    [goalsQuery.data, accountId],
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

  /**
   * ACC-37. What this account has earned in interest so far this month, summed
   * from the trail that is already on screen - null while the loaded rows do
   * not reach back to the first of the month, so a part-month is never shown
   * as the whole one.
   */
  const earnedThisMonth = useMemo(() => {
    if (!account?.interest || rows === null) return null;
    const month = localToday().slice(0, 7);
    if (cursor !== null && !rows.some((row) => row.txn_date < `${month}-01`)) return null;
    const earned = rows
      .filter((row) => row.interest_on && row.txn_date.startsWith(month))
      .reduce((sum, row) => sum + centavos(row.amount), 0);
    return earned > 0 ? fromCentavos(earned) : null;
  }, [account, rows, cursor]);

  /**
   * ACC-08/12. What has moved in or out of an investment account since the day
   * its value was last typed - the difference between the figure on the banner
   * and the figure the user typed, said out loud so neither looks wrong.
   */
  const movedSince = useMemo(() => {
    if (account?.type !== 'investment' || account.current_value === null) return null;
    const difference = centavos(account.balance) - centavos(account.current_value);
    return difference === 0 ? null : { amount: fromCentavos(Math.abs(difference)), inward: difference > 0 };
  }, [account]);

  /**
   * REC-14. The two halves of what an account owes, when a plan has still to
   * bill: what is on it now, and what the plans will add. Shown so neither
   * figure looks like a mistake.
   */
  const plansUnbilled = useMemo(() => {
    if (!account || account.plans_unbilled === '0.00') return null;
    if (account.credit) return { billed: account.credit.owed, plans: account.plans_unbilled, label: 'billed' };
    // REC-32. On a loan the plans are paid on the plans themselves, so their part
    // is what is LEFT TO PAY on them, and the rest is the loan's own balance.
    // With nothing else borrowed the line says nothing the plan rows below do not.
    const onPlans = openPlans.reduce((sum, rule) => sum + centavos(rule.installment?.left_to_pay ?? '0.00'), 0);
    const own = centavos(owedWithPlans(account)) - onPlans;
    if (own === 0 || onPlans === 0) return null;
    return { billed: fromCentavos(own), plans: fromCentavos(onPlans), label: 'borrowed' };
  }, [account, openPlans]);

  // The trail stays hand-rolled (plan D9): it pages by cursor, and the Month
  // view walks every page. It still reloads on the write signal.
  useEffect(() => {
    const controller = new AbortController();
    void loadTrail(view === 'month', controller.signal);
    return () => controller.abort();
  }, [loadTrail, version, view]);

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
  // REC-14. What you owe includes the installments not billed yet: a plan is
  // money owed from the day you take it, on a card and on a loan alike.
  const figure = !account
    ? '0.00'
    : account.credit
      ? account.credit.owed_with_plans
      : owed
        ? owedWithPlans(account)
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
          className="flex h-tap w-tap shrink-0 items-center justify-center rounded-full bg-surface text-ink press">
          <CloseIcon size={20} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-center text-headline">{account?.name ?? ' '}</h1>
        <button type="button" onClick={() => setEditing(true)} disabled={!account}
          className="min-h-tap shrink-0 press rounded-full bg-accent-soft px-4 text-body font-semibold text-accent-ink disabled:opacity-40">
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
                  className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-on-accent press">
                  <PlusIcon size={24} />
                </button>
                <button type="button" aria-label={`Transfer from ${account.name}`}
                  onClick={() => openSheet(undefined, undefined, { accountId: account.id, type: 'transfer' })}
                  className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface text-accent-ink press">
                  <TransferIcon size={22} />
                </button>
              </div>
            )}
          </div>
          {account.available !== null && account.available !== undefined ? (
            // GOA-08: the bank's balance and what is left to spend, side by side and equally large.
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2">
              <div className="min-w-0">
                <p className="text-footnote text-ink-2">{figureLabel}</p>
                <p className={`num text-title sm:text-display ${!owed && account.balance.startsWith('-') ? 'text-danger' : ''}`}>
                  {formatPHP(figure)}
                </p>
              </div>
              <div className="min-w-0">
                <p className="text-footnote text-ink-2">Available</p>
                <p className={`num text-title sm:text-display ${account.available.startsWith('-') ? 'text-danger' : ''}`}>
                  {formatPHP(account.available)}
                </p>
              </div>
            </div>
          ) : (
            <>
              <p className="mt-5 text-footnote text-ink-2">{figureLabel}</p>
              <p className={`num text-display ${!owed && account.balance.startsWith('-') ? 'text-danger' : ''}`}>
                {formatPHP(figure)}
              </p>
            </>
          )}
          {account.credit?.available != null && (
            <p className="mt-1 text-footnote text-ink-2">
              Left to spend <span className="num font-semibold text-ink">{formatPHP(account.credit.available)}</span>
              {' of '}
              <span className="num">{formatPHP(account.credit.limit as string)}</span>
            </p>
          )}
          {account.available !== null && account.available !== undefined && (
            <p className="mt-1 text-footnote text-ink-2">
              <span className="num font-semibold text-ink">{formatPHP(account.set_aside)}</span> set aside for goals
            </p>
          )}
          {plansUnbilled !== null && (
            <p className="mt-1 text-footnote text-ink-2">
              <span className="num">{formatPHP(plansUnbilled.billed)}</span> {plansUnbilled.label}
              {' · '}
              <span className="num font-semibold text-ink">{formatPHP(plansUnbilled.plans)}</span>
              {account.credit ? ' of plans still to bill' : ' left on plans'}
            </p>
          )}
          {account.type === 'investment' && movedSince !== null && (
            <p className="mt-1 text-footnote text-ink-2">
              <span className="num">{formatPHP(account.current_value as string)}</span> last valued
              {account.valuations.length > 0 && ` ${format(parseISO(account.valuations[account.valuations.length - 1]!.on), 'd MMM')}`}
              {' · '}
              <span className="num font-semibold text-ink">{formatPHP(movedSince.amount)}</span>{' '}
              {movedSince.inward ? 'up since' : 'down since'}
            </p>
          )}
          {account.interest && !account.archived && (
            <p className="mt-1 text-footnote text-ink-2">
              Earning <span className="num font-semibold text-ink">{formatPHP(account.interest.per_day)}</span> a day
              {' · '}
              <span className="num">{formatPHP(account.interest.per_year)}</span> a year
              {earnedThisMonth !== null && (
                <>
                  {' · '}
                  <span className="num font-semibold text-ok">{formatPHP(earnedThisMonth)}</span> this month
                </>
              )}
            </p>
          )}
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
                <button key={action.label} type="button"
                  onClick={() =>
                    // REC-32. Paying back a loan that carries a plan pays the PLAN, so the
                    // money counts against it and an extra payment asks what it should do.
                    action.label === 'Pay back' && openPlans[0]
                      ? setPaying(openPlans[0])
                      : openSheet(undefined, undefined, action.preset)
                  }
                  className={`press min-h-tap rounded-xl px-4 text-body font-bold ${
                    i === 0 ? 'bg-surface text-ink' : 'bg-accent text-on-accent'
                  }`}>
                  {action.label}
                </button>
              ))}
            </div>
          )}
          {/* misc/AI AI-40 - names the account; the server reads it and checks it is this user's */}
          <ExplainLink ask={`Tell me about ${account.name}`} context={{ account_id: account.id }} label="Ask about this account" />
        </section>
      ) : (
        <div className="skeleton h-44 rounded-card" aria-hidden="true" />
      )}

      {account && CHECKABLE.includes(account.type) && !account.archived && <BalanceCheck account={account} />}

      {account?.credit && !account.archived && (
        <>
          <div className="mt-3">
            <CreditDetails account={account} onCheck={() => setChecking(true)} />
          </div>
          <CardPayments account={account} />
        </>
      )}

      {account && (
        <PlanPaymentSheet rule={paying} accounts={lookups.accounts} onClose={() => setPaying(null)} />
      )}

      {goals.length > 0 && account && !account.archived && (
        <div className="mt-3 space-y-3">
          {goals.map((g) => (
            <GoalCard key={g.id} goal={g} accountName={account.name} onEdit={() => setEditingGoal(g)}
              onAdd={() => setGoalMoney({ goal: g, mode: 'add' })} onUse={() => setGoalMoney({ goal: g, mode: 'use' })} />
          ))}
        </div>
      )}
      <GoalSheet open={editingGoal !== null} goal={editingGoal} onClose={() => setEditingGoal(null)} />
      <GoalMoneySheet goal={goalMoney?.goal ?? null} mode={goalMoney?.mode ?? 'add'} onClose={() => setGoalMoney(null)} />

      {account && !account.credit && !account.archived && (
        <div className="mt-3 space-y-3">
          {/* ACC-40. A loan's own bills, above its plans: what is due is the
              question you open the page with, and the plan behind it is the
              answer to the next one. */}
          <AccountDues account={account} />
          <AccountPlans account={account} onPay={setPaying} onPlans={setOpenPlans} />
          {/* REC-14. A loan or a borrowed account gets the same monthly payment
              as a card: without it, a plan on one could not be paid at all. */}
          {(account.type === 'borrowed' || account.type === 'lent' || account.plans_unbilled !== '0.00') && (
            <AccountPayments account={account} />
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 px-1 pb-2 pt-5">
        <h2 className="text-headline">Transactions</h2>
        <div className="w-44">
          <Segmented<View> label="Group by" value={view} onChange={setView}
            options={[{ value: 'day', label: 'Day' }, { value: 'month', label: 'Month' }]} />
        </div>
      </div>

      {(error || accountsQuery.error) && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error ?? accountsQuery.error?.message}{' '}
          <button type="button" className="font-semibold underline"
            onClick={() => { void accountsQuery.refetch(); void loadTrail(view === 'month'); }}>Try again</button>
        </p>
      )}

      {rows === null && !error && <div className="skeleton h-48 rounded-card" aria-hidden="true" />}
      {rows && rows.length === 0 && (
        <p className="rounded-2xl border-2 border-dashed border-stroke/70 px-4 py-3 text-footnote text-ink-2">
          Nothing has moved in or out of this account yet.
        </p>
      )}

      {view === 'day' &&
        days.map((d) => (
          <section key={d.key} className="mb-3 overflow-hidden rounded-card bg-surface shadow-card">
            <div className="flex items-baseline justify-between gap-2 border-b border-stroke/40 px-4 py-2.5">
              <span className="text-footnote font-semibold">{format(parseISO(d.key), 'EEE, MMM d')}</span>
              <InOut rows={d.rows} />
            </div>
            <div className="divide-y divide-stroke/80">
              {d.rows.map((row) => (
                <button key={row.id} type="button" onClick={() => row.id > 0 && openPreview(row)}
                  className="block w-full transition active:bg-surface-2">
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
              <div className="mt-3 grid grid-cols-3 divide-x divide-stroke/80 text-center">
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

      {/* The sheet invalidates what it wrote; this screen's own effect is keyed on
          the same signal, so the account and its trail reload without being asked. */}
      <AccountSheet open={editing} account={account} onClose={() => setEditing(false)}
        onSaved={() => undefined} />
      <StatementSheet open={checking} account={checking ? account : null} onClose={() => setChecking(false)} />
    </>
  );
}
