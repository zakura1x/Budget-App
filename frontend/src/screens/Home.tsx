/**
 * Home - the number the app exists to show (BUD-06).
 *
 * "You can spend ₱612 today" is the hero, inside a ring of how much of the
 * period is used. The ring's colour is money state and nothing else: green,
 * then amber once the budget is 80% used or spending is running ahead of the
 * calendar, then red once it is gone (BUD-10).
 *
 * The figure is fixed for the day. Spending today moves "left today"; tomorrow
 * recomputes. When the period's money is gone the hero says ₱0.00 and how far
 * over - never a negative daily figure.
 *
 * Under the card, what that period was spent on as a grid of category tiles
 * (CategoryGrid, 2026-09-15). Swipe the card, or use the arrows, to look at
 * other periods - the grid follows. Alerts come in
 * the same response as the figures (BUD-12/14/15), and every write answers
 * with a fresh status, so the ring animates without a second request.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CategoryGrid } from '../components/CategoryGrid';
import { ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Ring, toneFor, type Tone } from '../components/ui/Ring';
import { useLookups, type Lookups } from '../hooks/useLookups';
import { ratio, type Alert, type BudgetStatus } from '../lib/budgets';
import { formatPHP } from '../lib/money';
import { expandRecurring } from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { useAuthStore } from '../stores/authStore';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';

const RECENT = 5;
const SWIPE_PX = 60;

const isZero = (value: string) => /^-?0+(\.0+)?$/.test(value);
const negate = (value: string) => (value.startsWith('-') ? value.slice(1) : `-${value}`);

function periodLabel(start: string, end: string): string {
  const from = parseISO(start);
  const to = parseISO(end);
  const sameYear = from.getFullYear() === to.getFullYear() && to.getFullYear() === new Date().getFullYear();
  return `${format(from, 'd MMM')} – ${format(to, sameYear ? 'd MMM' : 'd MMM yyyy')}`;
}

function toneOf(status: BudgetStatus): Tone {
  const a = status.allowance;
  if (!isZero(a.over_by) || status.alerts.some((x) => x.kind === 'over')) return 'danger';
  if (status.alerts.some((x) => x.kind === 'approaching' || x.kind === 'pace')) return 'warn';
  return toneFor(ratio(a.used_ratio));
}

function alertText(alert: Alert, status: BudgetStatus | null, lookups: Lookups): string {
  if (alert.kind === 'over' && status) return `You are ${formatPHP(status.allowance.over_by)} over this period's budget.`;
  if (alert.kind === 'category_over') {
    const name = lookups.categoryById.get(alert.category_id ?? -1)?.name ?? 'A category';
    return `${name} is over its budget.`;
  }
  const card = alert.account_id !== null ? lookups.accountById.get(alert.account_id) : undefined;
  const name = card?.name ?? 'A card';
  if (alert.kind === 'card_due') {
    // ACC-20 - the amount still owed on the bill, not the whole card.
    const due = card?.credit && !isZero(card.credit.amount_due) ? `${formatPHP(card.credit.amount_due)} ` : '';
    const when = alert.message.replace(/^A card payment is due /, '');
    return `${name}: ${due}due ${when}.`;
  }
  if (alert.kind === 'card_limit_over') return `${name} is at your spending limit for this cycle.`;
  if (alert.kind === 'card_limit_approaching') {
    const left = card?.credit?.limit_left;
    return left ? `${name}: ${formatPHP(left)} left of your limit this cycle.` : `${name} is close to your limit.`;
  }
  if (alert.kind === 'card_limit_pace') return `${name} is being spent faster than its cycle is passing.`;
  if (alert.kind === 'statement_differs') return `${name}: the last statement doesn’t match the bank’s total. Check it under Accounts.`;
  return `${alert.message}.`;
}

function AlertBanner({ alerts, status, lookups }: { alerts: Alert[]; status: BudgetStatus | null; lookups: Lookups }) {
  const [first, ...rest] = alerts;
  if (!first) return null;
  const danger = alerts.some((a) => a.severity === 'danger');
  return (
    <div
      role="status"
      className={`mb-3 rounded-2xl px-4 py-3 text-footnote ${danger ? 'bg-danger/10 text-danger' : 'bg-warn/10 text-warn'}`}
    >
      <p className="font-semibold">{alertText(first, status, lookups)}</p>
      {rest.length > 0 && (
        <ul className="mt-1 space-y-0.5 opacity-90">
          {rest.map((alert, i) => (
            <li key={`${alert.kind}-${i}`}>{alertText(alert, status, lookups)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BudgetCard({ status }: { status: BudgetStatus }) {
  const load = useBudgetStore((s) => s.load);
  const start = useRef<number | null>(null);
  const a = status.allowance;
  const tone = toneOf(status);
  const over = !isZero(a.over_by);
  const leftNegative = a.left_today.startsWith('-');

  const go = (target: 'previous' | 'next' | 'current') =>
    void load(target === 'current' ? null : status[target === 'previous' ? 'previous_period' : 'next_period'].start);

  return (
    <Card
      className="flex touch-pan-y flex-col items-center py-5"
      onPointerDown={(e) => (start.current = e.clientX)}
      onPointerUp={(e) => {
        if (start.current === null) return;
        const dx = e.clientX - start.current;
        start.current = null;
        if (dx > SWIPE_PX) go('previous');
        if (dx < -SWIPE_PX) go('next');
      }}
    >
      <div className="mb-3 flex w-full items-center justify-between px-1">
        <button type="button" aria-label="Previous period" onClick={() => go('previous')}
          className="flex h-tap w-tap items-center justify-center rounded-xl text-headline text-ink-2 active:bg-surface-2">
          ‹
        </button>
        <button type="button" onClick={() => !status.is_current && go('current')} className="min-h-tap px-2 text-center">
          <span className="block text-footnote font-semibold text-ink">{periodLabel(status.period.start, status.period.end)}</span>
          <span className="block text-caption text-ink-3">
            {status.is_current
              ? `${a.days_left} day${a.days_left === 1 ? '' : 's'} left`
              : 'Tap to go back to today'}
          </span>
        </button>
        <button type="button" aria-label="Next period" onClick={() => go('next')}
          className="flex h-tap w-tap items-center justify-center rounded-xl text-headline text-ink-2 active:bg-surface-2">
          ›
        </button>
      </div>

      <Ring
        progress={ratio(a.used_ratio)}
        tone={tone}
        label={`${Math.round(Math.min(ratio(a.used_ratio), 9.99) * 100)} percent of this period's budget used`}
      >
        {status.is_current ? (
          <>
            <span className="text-footnote font-medium text-ink-2">You can spend today</span>
            <span className="num mt-1 text-display">{formatPHP(a.daily)}</span>
            <span className={`mt-1 text-footnote ${over || leftNegative ? 'text-danger' : 'text-ink-2'}`}>
              {over
                ? `${formatPHP(a.over_by)} over this period`
                : leftNegative
                  ? `${formatPHP(negate(a.left_today))} over today`
                  : `${formatPHP(a.left_today)} left today`}
            </span>
          </>
        ) : isZero(a.budget) && isZero(a.carried_in) ? (
          // A period from before the budget existed: say so, rather than "₱0.00 of ₱0.00".
          <>
            <span className="text-footnote font-medium text-ink-2">No budget this period</span>
            <span className="num mt-1 text-display">{formatPHP(a.spent)}</span>
            <span className="mt-1 text-footnote text-ink-2">spent</span>
          </>
        ) : (
          <>
            <span className="text-footnote font-medium text-ink-2">Spent</span>
            <span className="num mt-1 text-display">{formatPHP(a.spent)}</span>
            <span className="mt-1 text-footnote text-ink-2">of {formatPHP(a.available)}</span>
          </>
        )}
      </Ring>

      <div className="mt-5 grid w-full grid-cols-2 divide-x divide-line text-center">
        <div>
          <p className="text-caption text-ink-3">Spent</p>
          <p className="num text-headline">{formatPHP(a.spent)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">{a.remaining.startsWith('-') ? 'Over' : 'Remaining'}</p>
          <p className={`num text-headline ${a.remaining.startsWith('-') ? 'text-danger' : ''}`}>
            {formatPHP(a.remaining.startsWith('-') ? negate(a.remaining) : a.remaining)}
          </p>
        </div>
      </div>
      {!isZero(a.carried_in) && (
        <p className="mt-3 text-footnote text-ink-3">
          {a.carried_in.startsWith('-')
            ? `Includes ${formatPHP(negate(a.carried_in))} overspent last period`
            : `Includes ${formatPHP(a.carried_in)} carried over`}
        </p>
      )}
    </Card>
  );
}

export function Home() {
  const today = new Date();
  const navigate = useNavigate();
  const name = useAuthStore((s) => s.session?.user.display_name);
  const { items, filters, load, error } = useLedgerStore();
  const { status, alerts, loaded, load: loadBudget, error: budgetError } = useBudgetStore();
  const openSheet = useUiStore((s) => s.openAddSheet);
  const lookups = useLookups();
  const [, setTick] = useState(0);

  useEffect(() => {
    // Home always shows the unfiltered ledger, whatever the ledger screen left behind.
    const filtered = Object.values(filters).some((v) => v !== undefined);
    if (filtered || items.length === 0) void load({});
    void loadBudget(null);
    // REC-05. Post whatever recurring charges fell due since the last open -
    // idempotent on the server - and refresh the figures only if any did.
    const catchUp = () =>
      expandRecurring()
        .then((result) => {
          if (result.posted === 0) return;
          useLedgerStore.setState((s) => ({ version: s.version + 1 }));
          void load({});
          void loadBudget(null);
        })
        .catch(() => {
          /* a failed catch-up retries on the next open; nothing is half-posted */
        });
    void catchUp();
    // Coming back to the app on a new day must not show yesterday's allowance.
    const onVisible = () =>
      document.visibilityState === 'visible' && (setTick((n) => n + 1), void loadBudget(null), void catchUp());
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const recent = items.slice(0, RECENT);

  return (
    <>
      <ScreenHeader
        title={name ? `Hi, ${name}` : 'Budget'}
        subtitle={format(today, 'EEEE, d MMMM')}
        action={
          status && (
            <Button variant="secondary" onClick={() => navigate('/budget')}>
              Budget
            </Button>
          )
        }
      />

      {status
        ? status.is_current && <AlertBanner alerts={status.alerts} status={status} lookups={lookups} />
        : <AlertBanner alerts={alerts} status={null} lookups={lookups} />}
      {(error || budgetError) && (
        <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error ?? budgetError}</p>
      )}

      {status ? (
        <BudgetCard status={status} />
      ) : loaded ? (
        <Card className="py-7 text-center">
          <p className="text-headline">Set a budget to see what you can spend today.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            One amount for the month or week. The app works out a daily figure and keeps it honest as you spend.
          </p>
          <Button className="mt-4" onClick={() => navigate('/budget')}>
            Set a budget
          </Button>
        </Card>
      ) : (
        <div className="skeleton h-[26rem] rounded-card" aria-hidden="true" />
      )}

      <CategoryGrid
        range={status ? { from: status.period.start, to: status.period.end } : { span: 'month', on: localToday() }}
        progress={status?.categories ?? []}
        lookups={lookups}
      />

      <div className="flex items-end justify-between">
        <SectionTitle>Recent</SectionTitle>
        {items.length > 0 && (
          <button type="button" onClick={() => navigate('/transactions')}
            className="min-h-tap px-1 text-footnote font-semibold text-accent">
            See all
          </button>
        )}
      </div>
      {recent.length > 0 ? (
        <div className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
          {recent.map((row) => (
            <button key={row.id} type="button" onClick={() => row.id > 0 && openSheet(row)}
              className="block w-full transition active:bg-surface-2">
              <TransactionRow row={row} lookups={lookups} />
            </button>
          ))}
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-line px-4 py-3 text-footnote text-ink-2">
          Nothing yet. Tap + and type an amount — that is the whole entry.
        </p>
      )}
    </>
  );
}
