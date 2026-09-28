/**
 * Accounts (ACC-01..ACC-30) - a main tab since 2026-09-15, so an account is
 * one tap from anywhere rather than a trip through More.
 *
 * The screen opens on CASH ON HAND, because that is the number this app is
 * about (ACC-17) — "what is in my pockets", not net worth. Beneath it, the
 * two halves it is made of: what is in the counted accounts, and what is owed
 * on the counted cards. Both come from the same counted set as the total, so
 * the three figures can never appear to disagree.
 *
 * Every account is a small tile - cards included - grouped by type, each
 * group with its own total and folding away like the sample. A tile opens the
 * account's own page (AccountDetail): its trail of money in and out, editing,
 * and for a card the bill, own limit and statement check. A card's tile says
 * only what cannot wait: overdue, due soon, or a statement that differs.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AccountSheet } from '../components/AccountSheet';
import { cardStatus, isZero } from '../components/CreditDetails';
import { ChevronRightIcon, PlusIcon, TransferIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { isOwed, listAccounts, owedWithPlans, visible, type Account, type AccountType } from '../lib/accounts';
import { keys, STALE } from '../lib/queryKeys';
import { getEmergency, listGoals, type Goal } from '../lib/security';
import { GoalCard, GoalMoneySheet, GoalSheet } from '../components/GoalSheets';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { useUiStore } from '../stores/uiStore';

/** The order the groups appear in; cards last, as they are money you owe. */
const GROUPS: { type: AccountType; title: string }[] = [
  { type: 'cash', title: 'Cash' },
  { type: 'debit', title: 'Bank' },
  { type: 'savings', title: 'Savings' },
  { type: 'credit', title: 'Credit cards' },
  { type: 'borrowed', title: 'Borrowed & loans' },
  { type: 'lent', title: 'Lent' },
  { type: 'investment', title: 'Investments' },
  { type: 'member', title: 'Member cards' },
];

/** The words over a figure: what an owed balance or money lent out reads as. */
const FIGURE_LABEL: Partial<Record<AccountType, string>> = { credit: 'Owed', borrowed: 'You owe', lent: 'Owed to you' };

/** Exact centavo sum of balances, as a decimal string. */
const sum = (accounts: Account[]) => fromCentavos(accounts.reduce((total, a) => total + centavos(a.balance), 0));
/** Exact centavo sum of what each adds to cash on hand (ACC-35). */
const cashSum = (accounts: Account[]) =>
  fromCentavos(accounts.reduce((total, a) => total + centavos(a.cash_amount ?? a.balance), 0));
const negate = (value: string) => (value.startsWith('-') ? value.slice(1) : isZero(value) ? value : `-${value}`);

/** One account as a tile: icon, name, balance - or, for a card, what is owed. */
function AccountTile({ account, onOpen }: { account: Account; onOpen: (a: Account) => void }) {
  const credit = account.credit;
  const owed = isOwed(account.type);
  // ACC-35. A card with bills leads with what is due now; what it owes in all is the line under it.
  const billed = credit && credit.due_now !== null ? credit : null;
  // REC-14. What you owe counts the installments not billed yet; a card with
  // typed bills still shows what is due NOW, which is what ACC-35 is for.
  const figure = billed ? (billed.due_now as string)
    : credit ? credit.owed_with_plans
      : owed ? owedWithPlans(account) : account.balance;
  const negative = !owed && account.balance.startsWith('-');
  // Whole pesos to fit the tile - cut from the string, never rounded through a float.
  const whole = (amount: string) => formatPHP(amount.split('.')[0] ?? '0', { places: 0 });
  // What is left to spend, unless something needs attention more (overdue, a statement that differs).
  const left = credit?.available != null && !account.archived
    ? { text: `${whole(credit.available)} left`, className: 'text-ink-3' }
    : null;
  const status = billed
    ? billed.bills.some((b) => b.overdue)
      ? { text: 'Overdue', className: 'text-danger' }
      : left ?? { text: `Owed ${whole(billed.owed)}`, className: 'text-ink-3' }
    : credit && !account.archived ? cardStatus(credit) ?? left : null;
  const label = billed
    ? isZero(billed.due_now as string) ? 'Bills paid' : `Due ${format(parseISO(billed.payment_due), 'd MMM')}`
    : FIGURE_LABEL[account.type];
  // "Not counted" is news only where counting is the default.
  const notCountedIsNews = account.type !== 'lent' && account.type !== 'borrowed' && account.type !== 'investment';
  return (
    <button
      type="button"
      onClick={() => onOpen(account)}
      aria-label={`${account.name}, ${label ? `${label.toLowerCase()} ` : ''}${formatPHP(figure)}`}
      className={`flex min-h-28 flex-col items-start gap-2 rounded-card bg-surface p-3 text-left press ${
        account.archived ? 'opacity-60' : ''
      }`}
    >
      <GlyphTile icon={account.icon} colour={account.colour} size={36} />
      <span className="line-clamp-2 w-full break-words text-footnote font-medium text-ink">{account.name}</span>
      <span className="mt-auto w-full">
        {label && <span className="block text-caption text-ink-3">{label}</span>}
        <span className={`num block truncate text-footnote font-semibold ${negative ? 'text-danger' : 'text-ink'}`}>
          {formatPHP(figure)}
        </span>
        {status ? (
          <span className={`block truncate text-caption font-semibold ${status.className}`}>{status.text}</span>
        ) : (
          notCountedIsNews && !account.counts_in_cash_on_hand && !account.archived && <span className="block text-caption text-ink-3">Not counted</span>
        )}
      </span>
    </button>
  );
}

function GroupHeader({
  title, count, label, amount, open, onToggle,
}: { title: string; count: number; label: string; amount: string; open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      className="flex min-h-tap w-full items-center gap-2 px-1 pb-1 pt-4 text-left">
      <span className="text-headline">{title}</span>
      <span className="num rounded-md bg-surface px-1.5 text-caption font-bold text-ink shadow-edge">{count}</span>
      <span className="ml-auto text-footnote text-ink-2">
        {label} <span className="num font-semibold text-ink">{formatPHP(amount)}</span>
      </span>
      <ChevronRightIcon size={16} className={`text-ink-3 transition ${open ? 'rotate-90' : ''}`} />
    </button>
  );
}

export function Accounts() {
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [folded, setFolded] = useState<Set<string>>(() => new Set(['archived']));
  const [editingGoal, setEditingGoal] = useState<{ open: boolean; goal: Goal | null }>({ open: false, goal: null });
  const [goalMoney, setGoalMoney] = useState<{ goal: Goal; mode: 'add' | 'use' } | null>(null);

  // The same key `useLookups` reads, so opening this tab costs nothing when the
  // answer is still fresh, and a write refreshes both at once.
  const { data, error, refetch } = useQuery({
    queryKey: keys.accounts(),
    queryFn: ({ signal }) => listAccounts(signal),
    staleTime: STALE.lookups,
  });

  /** GOA - savings goals, shown with the accounts they live in (2026-09-16, user). */
  // The accounts are the page; a goal list that fails to load just stays away.
  const { data: goals = [] } = useQuery({
    queryKey: keys.goals(),
    queryFn: ({ signal }) => listGoals(signal),
    staleTime: STALE.lookups,
  });

  const open = (account: Account) => navigate(`/accounts/${account.id}`);
  const toggle = (key: string) =>
    setFolded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // ACC-39. The wallet is not an account you keep - it never appears here, in
  // either list, and its balance is in no total on this screen.
  const shown = data ? visible(data.accounts) : [];
  const active = shown.filter((a) => !a.archived);
  const archived = shown.filter((a) => a.archived);
  const counted = active.filter((a) => data?.cash_on_hand.account_ids.includes(a.id));
  // The halves are summed from what each account adds to cash on hand - for a card with bills, only
  // what is due now (ACC-35) - so they always add up to the server's total.
  const inAccounts = cashSum(counted.filter((a) => !isOwed(a.type)));
  // Signed: owing is negative, so what is owed is the negation. A loan only lands here if its switch
  // was turned on, and then the label says so.
  const onCards = negate(cashSum(counted.filter((a) => isOwed(a.type))));
  const cardsInCredit = onCards.startsWith('-');
  const owedWhere = counted.some((a) => a.type === 'borrowed') ? 'cards & loans' : 'cards';
  const billed = counted.some((a) => a.credit?.due_now != null);
  // GOA-10. Asked for once and cached with the goals; a figure beside the headline, never part of it.
  const { data: emergency } = useQuery({
    queryKey: keys.emergency(),
    queryFn: ({ signal }) => getEmergency(signal),
    staleTime: STALE.derived,
  });
  const headline = useUiStore((s) => s.headline);
  const setHeadline = useUiStore((s) => s.setHeadline);
  const net = headline === 'net';
  const outOfNetWorth = active.filter((a) => !a.counts_in_net_worth).length;
  const notCounted = active.length - counted.length;
  const goalsSaved = fromCentavos(goals.reduce((total, goal) => total + centavos(goal.saved), 0));
  // GOA-08. What counted accounts hold aside for goals - already out of cash on hand, so the headline says so.
  const setAsideTotal = counted.reduce((total, a) => total + centavos(a.set_aside ?? '0.00'), 0);

  return (
    <>
      <ScreenHeader
        title="Accounts"
        action={
          <button type="button" onClick={() => setAdding(true)} aria-label="Add account"
            className="flex h-tap w-tap items-center justify-center rounded-full bg-accent text-on-accent press">
            <PlusIcon size={22} />
          </button>
        }
      />

      {data ? (
        <section className="rounded-card bg-accent p-5 text-on-accent shadow-raised" aria-label={net ? 'Net worth' : 'Cash on hand'}>
          <div className="flex items-center justify-between gap-3">
            <p className="label">{net ? 'Net worth' : 'Cash on hand'}</p>
            <button type="button" onClick={() => setHeadline(net ? 'cash' : 'net')}
              aria-label={net ? 'Show cash on hand' : 'Show net worth'}
              className="press flex min-h-tap items-center gap-1.5 rounded-full bg-surface px-3 text-caption font-bold text-ink">
              <TransferIcon size={14} />
              {net ? 'Cash on hand' : 'Net worth'}
            </button>
          </div>
          {net ? (
            <>
              <p className="num text-display">{formatPHP(data.net_worth.total)}</p>
              <div className="mt-4 grid grid-cols-2 gap-3 border-t-2 border-on-accent/30 pt-3">
                <div>
                  <p className="text-caption opacity-75">Assets</p>
                  <p className="num text-headline">{formatPHP(data.net_worth.assets)}</p>
                </div>
                <div>
                  <p className="text-caption opacity-75">Liabilities</p>
                  <p className="num text-headline">{formatPHP(data.net_worth.liabilities)}</p>
                </div>
              </div>
              <p className="mt-3 text-caption opacity-75">
                Everything you have, less every debt in full — cards, loans and plans not billed yet.
                {outOfNetWorth > 0 && ` · ${outOfNetWorth} account${outOfNetWorth === 1 ? '' : 's'} left out`}
              </p>
            </>
          ) : (
            <>
              <p className="num text-display">{formatPHP(data.cash_on_hand.total)}</p>
              <div className="mt-4 grid grid-cols-2 gap-3 border-t-2 border-on-accent/30 pt-3">
                <div>
                  <p className="text-caption opacity-75">In accounts</p>
                  <p className="num text-headline">{formatPHP(inAccounts)}</p>
                </div>
                <div>
                  <p className="text-caption opacity-75">
                    {cardsInCredit ? `In credit on ${owedWhere}` : billed ? `Due now on ${owedWhere}` : `Owed on ${owedWhere}`}
                  </p>
                  <p className="num text-headline">{formatPHP(cardsInCredit ? onCards.slice(1) : onCards)}</p>
                </div>
              </div>
              <p className="mt-3 text-caption opacity-75">
                {active.length === 0
                  ? 'Nothing tracked yet'
                  : `Across ${counted.length} of ${active.length} account${active.length === 1 ? '' : 's'}`}
                {notCounted > 0 && ` · ${notCounted} not counted`}
                {billed && ' · cards count this month’s bill'}
                {setAsideTotal > 0 && ` · ${formatPHP(fromCentavos(setAsideTotal))} set aside for goals`}
              </p>
              <button type="button" onClick={() => navigate('/projection')}
                className="press mt-3 flex min-h-tap w-full items-center justify-between rounded-xl bg-surface px-4 text-footnote font-bold text-ink">
                <span>Months ahead — cash on hand by month</span>
                <ChevronRightIcon size={16} />
              </button>
              {/* GOA-10. How long the emergency money lasts, beside cash on hand; the screen says why. */}
              {emergency?.measurable && (
                <button type="button" onClick={() => navigate('/emergency')}
                  className="press mt-2 flex min-h-tap w-full items-center justify-between rounded-xl bg-surface px-4 text-footnote font-bold text-ink">
                  <span className="text-left">
                    Emergency money lasts <span className="num">{emergency.cover_months}</span> months
                    <span className="whitespace-nowrap font-normal text-ink-2"> · aim for {emergency.target_months}</span>
                  </span>
                  <ChevronRightIcon size={16} />
                </button>
              )}
            </>
          )}
        </section>
      ) : (
        !error && <div className="skeleton h-44 rounded-card" aria-hidden="true" />
      )}

      {error && (
        <p className="mt-4 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error.message} <button type="button" className="font-semibold underline" onClick={() => void refetch()}>Try again</button>
        </p>
      )}

      {data && active.length === 0 && !error && (
        <Card className="mt-4 text-center">
          <p className="text-body">Add the accounts you actually spend from.</p>
          <p className="mt-1 text-footnote text-ink-2">
            Your wallet, your bank, your card. Everything else is built on top of them.
          </p>
          <Button className="mt-4" onClick={() => setAdding(true)}>
            Add your first account
          </Button>
        </Card>
      )}

      {GROUPS.map(({ type, title }) => {
        const members = active.filter((a) => a.type === type);
        if (members.length === 0) return null;
        const owed = isOwed(type);
        const total = sum(members);
        const shown = !folded.has(type);
        return (
          <section key={type}>
            <GroupHeader
              title={title}
              count={members.length}
              label={FIGURE_LABEL[type] ?? 'Bal.'}
              amount={owed ? negate(total) : total}
              open={shown}
              onToggle={() => toggle(type)}
            />
            {shown && (
              <div className="grid grid-cols-3 gap-2.5">
                {members.map((account) => (
                  <AccountTile key={account.id} account={account} onOpen={open} />
                ))}
              </div>
            )}
          </section>
        );
      })}

      {data && active.length > 0 && (
        <section aria-label="Savings goals">
          <div className="flex min-h-tap items-center gap-2 px-1 pb-1 pt-4">
            <button type="button" onClick={() => toggle('goals')} aria-expanded={!folded.has('goals')}
              className="flex min-w-0 flex-1 items-center gap-2 text-left">
              <span className="text-headline">Savings goals</span>
              {goals.length > 0 && (
                <span className="num rounded-md bg-surface px-1.5 text-caption font-bold text-ink shadow-edge">{goals.length}</span>
              )}
              {goals.length > 0 && (
                <span className="ml-auto text-footnote text-ink-2">
                  Saved <span className="num font-semibold text-ink">{formatPHP(goalsSaved)}</span>
                </span>
              )}
              <ChevronRightIcon size={16} className={`shrink-0 text-ink-3 transition ${folded.has('goals') ? '' : 'rotate-90'}`} />
            </button>
          </div>
          {!folded.has('goals') && (goals.length === 0 ? (
            <button type="button" onClick={() => setEditingGoal({ open: true, goal: null })}
              className="block w-full rounded-card bg-surface p-4 text-left press">
              <span className="block text-body font-semibold text-accent-ink">+ Add a savings goal</span>
              <span className="mt-0.5 block text-footnote text-ink-3">
                An emergency fund, a trip, a laptop - its progress is the balance of the account it sits in.
              </span>
            </button>
          ) : (
            <div className="space-y-2.5">
              {goals.map((goal) => (
                <GoalCard key={goal.id} goal={goal} compact
                  accountName={data.accounts.find((a) => a.id === goal.account_id)?.name}
                  onEdit={() => navigate(`/accounts/${goal.account_id}`)}
                  onAdd={() => setGoalMoney({ goal, mode: 'add' })} onUse={() => setGoalMoney({ goal, mode: 'use' })} />
              ))}
              <button type="button" onClick={() => setEditingGoal({ open: true, goal: null })}
                className="min-h-tap w-full rounded-full text-footnote font-semibold text-accent-ink active:bg-accent-soft">
                + Add a goal
              </button>
            </div>
          ))}
        </section>
      )}

      {archived.length > 0 && (
        <section className="mt-2">
          <GroupHeader
            title="Archived"
            count={archived.length}
            label="Bal."
            amount={sum(archived)}
            open={!folded.has('archived')}
            onToggle={() => toggle('archived')}
          />
          {!folded.has('archived') && (
            <div className="grid grid-cols-3 gap-2.5">
              {archived.map((account) => (
                <AccountTile key={account.id} account={account} onOpen={open} />
              ))}
            </div>
          )}
        </section>
      )}

      <AccountSheet open={adding} account={null} onClose={() => setAdding(false)} onSaved={() => undefined} />
      <GoalSheet open={editingGoal.open} goal={editingGoal.goal}
        onClose={() => setEditingGoal({ open: false, goal: null })} />
      <GoalMoneySheet goal={goalMoney?.goal ?? null} mode={goalMoney?.mode ?? 'add'} onClose={() => setGoalMoney(null)} />
    </>
  );
}
