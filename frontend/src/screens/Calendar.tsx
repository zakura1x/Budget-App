/**
 * The calendar (CAL-01..CAL-07).
 *
 * Each day is shaded by what was spent on it, measured against the budget per
 * day - or, with no budget, against a typical day this month - so one rent
 * payment does not wash every other day out. The shade is intensity only,
 * never green/amber/red: those mean money state everywhere else.
 *
 * WEEK · MONTH · YEAR (CAL-06). The week lists its seven days with their
 * entries; the year is twelve small heatmaps from GET /calendar/{year}, each
 * month exactly as the month view gives it - tap one to open it.
 *
 * UPCOMING (CAL-07). Days after today show what is SCHEDULED - recurring
 * charges and income, subscriptions, installment payments, card bills and
 * loan dues - faded, from the Months ahead projection (GET /projection, which
 * reads THE schedule, occurrences()). One schedule, so the calendar and Months
 * ahead can never disagree. Scheduled money never joins a day's or a month's
 * spent total, which stays what was actually spent; the header says
 * "₱X scheduled" beside it. Tap a future day for the list; each opens its plan.
 *
 * Swipe the grid or use the arrows for another week, month or year.
 */
import {
  addDays,
  addMonths,
  addWeeks,
  addYears,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  parseISO,
  startOfMonth,
  startOfWeek,
  startOfYear,
} from 'date-fns';
import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarSwitch } from '../components/CalendarSwitch';
import { ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Sheet } from '../components/ui/Sheet';
import { useLookups } from '../hooks/useLookups';
import { getMonth, getYear, type CalendarDay, type CalendarMonth } from '../lib/calendar';
import { centavos, formatPHP, fromCentavos, splitDecimal } from '../lib/money';
import { ensureRules } from '../lib/prefetch';
import { keys, STALE } from '../lib/queryKeys';
import { getProjection, type ProjectedItem } from '../lib/recurring';
import { listTransactions, localToday, type Transaction } from '../lib/transactions';
import { usePreferencesStore } from '../stores/preferencesStore';
import { useUiStore } from '../stores/uiStore';

const SWIPE_PX = 60;

type View = 'week' | 'month' | 'year';

/** Static, so Tailwind sees every class. */
const LEVEL: Record<number, string> = {
  0: 'bg-surface text-ink',
  1: 'bg-accent/15 text-ink',
  2: 'bg-accent/35 text-ink',
  3: 'bg-accent/65 text-on-accent',
  4: 'bg-accent text-on-accent',
};

/**
 * A cell-sized amount: "850", "1.2k", "12k", "1.5M". Truncated, never rounded
 * up, and read off the string - the full figure is one tap away.
 */
export function compactAmount(value: string): string {
  const { int } = splitDecimal(value);
  const shorten = (digits: number, suffix: string) => {
    const whole = int.slice(0, int.length - digits);
    const tenth = int[int.length - digits];
    return whole.length >= 2 || tenth === '0' ? `${whole}${suffix}` : `${whole}.${tenth}${suffix}`;
  };
  if (int.length <= 3) return int;
  if (int.length <= 6) return shorten(3, 'k');
  return shorten(6, 'M');
}

// ------------------------------------------------------------- the schedule

/**
 * CAL-07. What a scheduled item takes out of cash on hand - its `effect`, the
 * figure Months ahead adds up. A plan's charge on a loan that is not counted,
 * or a card payment between two counted accounts, moves nothing: they are
 * listed on the day, never totalled as money leaving (2026-09-28 - a ₱5,000
 * loan installment was first counted as ₱5,000 going out).
 */
const takesOut = (item: ProjectedItem) => Math.max(-centavos(item.effect), 0);

/**
 * CAL-07. Every scheduled item after today, by day, from the Months ahead
 * projection - twelve months of it, cached with Months ahead's own key.
 */
function useScheduled(): Map<string, ProjectedItem[]> {
  const { data } = useQuery({
    queryKey: keys.projection(12),
    queryFn: ({ signal }) => getProjection(12, signal),
    staleTime: STALE.derived,
  });
  const today = localToday();
  const byDay = new Map<string, ProjectedItem[]>();
  for (const month of data?.months ?? []) {
    for (const item of month.items) {
      if (item.paused || item.on <= today) continue;
      byDay.set(item.on, [...(byDay.get(item.on) ?? []), item]);
    }
  }
  return byDay;
}

const outgoing = (items: ProjectedItem[] | undefined) =>
  fromCentavos((items ?? []).reduce((sum, i) => sum + takesOut(i), 0));

function scheduledLabel(item: ProjectedItem): string {
  if (item.kind === 'bill' || item.kind === 'bill_plans' || item.kind === 'bill_now') return 'bill';
  if (item.kind === 'interest') return 'savings interest, estimated';
  if (item.kind === 'installment') return item.final ? 'installment · last payment' : 'installment';
  if (item.kind === 'subscription') return 'subscription';
  return item.type === 'income' ? 'income' : item.type === 'transfer' ? 'transfer' : 'repeating';
}

/** CAL-07. A day's scheduled items; each opens its plan, or a bill its account. */
function ScheduledList({ items, onOpened }: { items: ProjectedItem[]; onOpened: () => void }) {
  const navigate = useNavigate();
  const openRuleSheet = useUiStore((s) => s.openRuleSheet);
  const [error, setError] = useState<string | null>(null);

  const open = async (item: ProjectedItem) => {
    setError(null);
    if (item.rule_id <= 0) {
      onOpened();
      navigate(`/accounts/${item.account_id}`); // a bill, a due, interest - its account holds the story
      return;
    }
    try {
      const rule = (await ensureRules()).find((r) => r.id === item.rule_id);
      if (!rule) throw new Error('gone');
      onOpened();
      openRuleSheet({ kind: rule.kind, rule, prefill: null });
    } catch {
      setError('That plan could not be opened.');
    }
  };

  return (
    <div className="space-y-1.5">
      <p className="text-footnote font-semibold text-ink-2">Scheduled</p>
      <ul className="divide-y divide-stroke/80 overflow-hidden rounded-card border-2 border-dashed border-stroke bg-surface-2">
        {items.map((item) => (
          <li key={`${item.rule_id}-${item.name}-${item.account_id}`}>
            <button type="button" onClick={() => void open(item)}
              className="flex min-h-12 w-full items-center justify-between gap-3 px-3 py-2 text-left active:bg-surface">
              <span className="min-w-0">
                <span className="block truncate text-body">{item.name}</span>
                <span className="block text-caption text-ink-3">{scheduledLabel(item)}</span>
              </span>
              <span className={`num shrink-0 text-footnote font-semibold ${item.type === 'income' ? 'text-ok' : 'text-ink-2'}`}>
                {item.type === 'income' ? '+' : item.type === 'expense' ? '−' : ''}
                {formatPHP(item.amount)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="text-footnote text-danger">{error}</p>}
    </div>
  );
}

// --------------------------------------------------------------------- day

function DaySheet({ day, scheduled, onClose }: { day: CalendarDay | null; scheduled: ProjectedItem[]; onClose: () => void }) {
  const lookups = useLookups();
  const openSheet = useUiStore((s) => s.openAddSheet);
  const openPreview = useUiStore((s) => s.openPreview);

  // Reopening a day you already looked at draws from the cache; it no longer
  // blanks to a skeleton on every write, either (plan §1.5).
  const { data: rows, error } = useQuery({
    queryKey: keys.transactionsIn(day?.on ?? '', day?.on ?? ''),
    queryFn: ({ signal }) => listTransactions({ from: day!.on, to: day!.on }, null, signal).then((page) => page.items),
    enabled: day !== null,
  });

  const open = (row?: Transaction) => {
    onClose();
    // TXN-23. A row opens the preview; the day's own button still starts a new entry.
    if (row) openPreview(row);
    else openSheet(undefined, day?.on);
  };

  return (
    <Sheet open={day !== null} onClose={onClose} title={day ? format(parseISO(day.on), 'EEEE d MMMM') : undefined}>
      {day && (
        <div className="space-y-3 pb-2">
          <p className="num text-footnote text-ink-2">
            {day.spent !== '0.00' ? `${formatPHP(day.spent)} spent` : 'Nothing spent'}
            {day.earned !== '0.00' && ` · ${formatPHP(day.earned)} earned`}
          </p>
          {scheduled.length > 0 && <ScheduledList items={scheduled} onOpened={onClose} />}
          {error && <p className="text-footnote text-danger">{error.message}</p>}
          {rows === undefined && !error && <div className="skeleton h-28 rounded-card" aria-hidden="true" />}
          {rows && rows.length > 0 && (
            <div className="divide-y divide-stroke/80 overflow-hidden rounded-card border-2 border-stroke bg-surface-2">
              {rows.map((row) => (
                <button key={row.id} type="button" onClick={() => open(row)} className="block w-full transition active:bg-surface-2">
                  <TransactionRow row={row} lookups={lookups} />
                </button>
              ))}
            </div>
          )}
          {rows && rows.length === 0 && scheduled.length === 0 && <p className="text-body text-ink-2">No transactions on this day.</p>}
          <Button block variant="secondary" onClick={() => open()}>
            Add one on this day
          </Button>
        </div>
      )}
    </Sheet>
  );
}

// ------------------------------------------------------------------- month

/** Income · Expense · Balance for the month, and its transactions by day. */
function MonthList({ month, spent, earned }: { month: Date; spent: string; earned: string }) {
  const lookups = useLookups();
  const navigate = useNavigate();
  const openPreview = useUiStore((s) => s.openPreview);
  const from = format(month, 'yyyy-MM-dd');
  const to = format(endOfMonth(month), 'yyyy-MM-dd');

  // The grid above shows the month's error. Stepping back to a month already
  // seen is instant: no `setPage(null)` blanking it first (plan §1.5).
  const { data: page } = useQuery({
    queryKey: keys.transactionsIn(from, to),
    queryFn: ({ signal }) => listTransactions({ from, to }, null, signal),
    staleTime: STALE.derived,
  });

  const balance = fromCentavos(centavos(earned) - centavos(spent));
  const days = new Map((page?.days ?? []).map((d) => [d.on, d]));
  const groups: { on: string; rows: Transaction[] }[] = [];
  for (const row of page?.items ?? []) {
    const last = groups[groups.length - 1];
    if (last && last.on === row.txn_date) last.rows.push(row);
    else groups.push({ on: row.txn_date, rows: [row] });
  }

  return (
    <>
      <Card className="mt-4 grid grid-cols-3 divide-x divide-stroke/80 py-3 text-center">
        <div>
          <p className="text-caption text-ink-3">Income</p>
          <p className="num text-footnote font-semibold text-ok">{formatPHP(earned)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Expense</p>
          <p className="num text-footnote font-semibold">{formatPHP(spent)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Balance</p>
          <p className={`num text-footnote font-semibold ${balance.startsWith('-') ? 'text-danger' : ''}`}>{formatPHP(balance)}</p>
        </div>
      </Card>

      {page === undefined && <div className="skeleton mt-3 h-40 rounded-card" aria-hidden="true" />}
      {page && page.items.length === 0 && (
        <p className="mt-3 rounded-2xl border-2 border-dashed border-stroke/70 px-4 py-3 text-footnote text-ink-2">
          Nothing recorded this month.
        </p>
      )}
      {groups.map((group) => {
        const total = days.get(group.on);
        return (
          <section key={group.on} className="mt-3">
            <div className="flex items-baseline justify-between px-1 pb-1.5">
              <span className="text-footnote font-semibold text-ink-2">{format(parseISO(group.on), 'EEE d MMM')}</span>
              {total && total.spent !== '0.00' && (
                <span className="num text-caption text-ink-3">{formatPHP(total.spent)} spent</span>
              )}
            </div>
            <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
              {group.rows.map((row) => (
                <button key={row.id} type="button" onClick={() => row.id > 0 && openPreview(row)}
                  className="block w-full transition active:bg-surface-2">
                  <TransactionRow row={row} lookups={lookups} />
                </button>
              ))}
            </div>
          </section>
        );
      })}
      {page?.next_cursor && (
        <Button block variant="secondary" className="mt-3" onClick={() => navigate('/transactions')}>
          See all {page.total_count} in the ledger
        </Button>
      )}
    </>
  );
}

function MonthGrid({ month, data, weekStartsOn, scheduled, onDay }: {
  month: Date;
  data: CalendarMonth | null;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  scheduled: Map<string, ProjectedItem[]>;
  onDay: (day: CalendarDay) => void;
}) {
  const byDate = new Map((data?.days ?? []).map((d) => [d.on, d]));
  const cells = eachDayOfInterval({
    start: startOfWeek(month, { weekStartsOn }),
    end: endOfWeek(endOfMonth(month), { weekStartsOn }),
  });
  return (
    <>
      <div className="grid grid-cols-7 pb-2 text-center text-caption font-semibold uppercase text-ink-3">
        {cells.slice(0, 7).map((d) => (
          <span key={d.toISOString()}>{format(d, 'EEEEE')}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((d) => {
          const on = format(d, 'yyyy-MM-dd');
          if (!isSameMonth(d, month)) {
            return (
              <span key={on} className="num flex aspect-square items-start justify-center pt-1.5 text-footnote text-ink-3/50">
                {format(d, 'd')}
              </span>
            );
          }
          const day = byDate.get(on);
          const spent = day && day.spent !== '0.00';
          const ahead = scheduled.get(on);
          const out = outgoing(ahead);
          const onlyIn = ahead && out === '0.00' && ahead.some((i) => i.type === 'income');
          return (
            <button
              key={on}
              type="button"
              disabled={!day}
              onClick={() => day && onDay(day)}
              aria-label={`${format(d, 'EEEE d MMMM')}${spent ? `, ${formatPHP(day.spent)} spent` : ''}${out !== '0.00' ? `, ${formatPHP(out)} scheduled` : ''}`}
              className={[
                'num flex aspect-square flex-col items-center justify-start rounded-lg pt-1.5 transition active:translate-x-px active:translate-y-px',
                ahead ? 'border-2 border-dashed border-stroke' : 'shadow-edge',
                day ? LEVEL[day.level] : LEVEL[0],
              ].join(' ')}
            >
              <span
                className={`text-footnote ${isToday(d) ? 'rounded bg-highlight px-1.5 font-bold text-on-highlight shadow-edge' : 'font-medium'}`}
                aria-current={isToday(d) ? 'date' : undefined}
              >
                {format(d, 'd')}
              </span>
              {spent && <span className="mt-0.5 text-caption leading-none opacity-90">{compactAmount(day.spent)}</span>}
              {!spent && out !== '0.00' && (
                <span className="mt-0.5 text-caption leading-none text-ink-3">{compactAmount(out)}</span>
              )}
              {!spent && onlyIn && <span className="mt-0.5 text-caption leading-none text-ok">+</span>}
              {!spent && !ahead && day && day.count > 0 && <span className="mt-1.5 h-1 w-1 rounded-full bg-ink-3" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
    </>
  );
}

// -------------------------------------------------------------------- week

/** CAL-06. Seven days with their entries - and, ahead of today, what is scheduled on each. */
function WeekView({ start, scheduled }: { start: Date; scheduled: Map<string, ProjectedItem[]> }) {
  const lookups = useLookups();
  const openPreview = useUiStore((s) => s.openPreview);
  const openSheet = useUiStore((s) => s.openAddSheet);
  const days = eachDayOfInterval({ start, end: addDays(start, 6) });
  const from = format(start, 'yyyy-MM-dd');
  const to = format(addDays(start, 6), 'yyyy-MM-dd');

  const { data: page, error } = useQuery({
    queryKey: keys.transactionsIn(from, to),
    queryFn: ({ signal }) => listTransactions({ from, to }, null, signal, 200),
    staleTime: STALE.derived,
  });
  const totals = new Map((page?.days ?? []).map((d) => [d.on, d]));

  if (error) return <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>;
  if (!page) return <div className="skeleton h-96 rounded-card" aria-hidden="true" />;

  return (
    <div className="space-y-3">
      {days.map((d) => {
        const on = format(d, 'yyyy-MM-dd');
        const rows = page.items.filter((r) => r.txn_date === on);
        const ahead = scheduled.get(on) ?? [];
        const total = totals.get(on);
        return (
          <section key={on}>
            <div className="flex items-baseline justify-between px-1 pb-1.5">
              <span className={`text-footnote font-semibold ${isToday(d) ? 'rounded bg-highlight px-1.5 text-on-highlight' : 'text-ink-2'}`}>
                {format(d, 'EEE d MMM')}
              </span>
              <span className="num text-caption text-ink-3">
                {total && total.spent !== '0.00' ? `${formatPHP(total.spent)} spent` : ''}
                {outgoing(ahead) !== '0.00' && `${total && total.spent !== '0.00' ? ' · ' : ''}${formatPHP(outgoing(ahead))} scheduled`}
              </span>
            </div>
            {rows.length > 0 && (
              <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
                {rows.map((row) => (
                  <button key={row.id} type="button" onClick={() => row.id > 0 && openPreview(row)}
                    className="block w-full transition active:bg-surface-2">
                    <TransactionRow row={row} lookups={lookups} />
                  </button>
                ))}
              </div>
            )}
            {ahead.length > 0 && <div className={rows.length ? 'mt-2' : ''}><ScheduledList items={ahead} onOpened={() => undefined} /></div>}
            {rows.length === 0 && ahead.length === 0 && (
              <button type="button" onClick={() => openSheet(undefined, on)}
                className="w-full rounded-2xl border-2 border-dashed border-stroke/70 px-4 py-2.5 text-left text-footnote text-ink-3">
                Nothing — add one on this day
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}

// -------------------------------------------------------------------- year

/** CAL-06. Twelve small heatmaps; tap one to open that month. */
function YearView({ year, weekStartsOn, onMonth }: {
  year: number;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onMonth: (month: Date) => void;
}) {
  const { data, error } = useQuery({
    queryKey: keys.calendarYear(year),
    queryFn: ({ signal }) => getYear(year, signal),
    staleTime: STALE.derived,
  });
  if (error) return <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>;
  if (!data) return <div className="skeleton h-96 rounded-card" aria-hidden="true" />;

  return (
    <>
      <div className="grid grid-cols-3 gap-2.5">
        {data.months.map((m) => {
          const first = new Date(m.year, m.month - 1, 1);
          const lead = (first.getDay() - weekStartsOn + 7) % 7;
          return (
            <button key={m.month} type="button" onClick={() => onMonth(first)}
              className="press rounded-card bg-surface p-2 text-left" aria-label={`${format(first, 'MMMM')}, ${formatPHP(m.spent)} spent`}>
              <span className="flex items-baseline justify-between gap-1">
                <span className="text-footnote font-semibold">{format(first, 'MMM')}</span>
                <span className="num text-caption text-ink-3">{m.spent === '0.00' ? '—' : compactAmount(m.spent)}</span>
              </span>
              <span className="mt-1.5 grid grid-cols-7 gap-[2px]" aria-hidden="true">
                {Array.from({ length: lead }, (_, i) => <span key={`lead-${i}`} />)}
                {m.days.map((d) => (
                  <span key={d.on} className={`aspect-square rounded-[2px] ${d.level === 0 ? 'bg-surface-2' : LEVEL[d.level]}`} />
                ))}
              </span>
            </button>
          );
        })}
      </div>
      <Card className="mt-4 grid grid-cols-2 divide-x divide-stroke/80 py-3 text-center">
        <div>
          <p className="text-caption text-ink-3">Income</p>
          <p className="num text-footnote font-semibold text-ok">{formatPHP(data.earned)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Expense</p>
          <p className="num text-footnote font-semibold">{formatPHP(data.spent)}</p>
        </div>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ screen

export function Calendar() {
  // Settings: 1 Monday .. 7 Sunday; date-fns counts 0 Sunday .. 6 Saturday.
  const weekStart = usePreferencesStore((s) => s.prefs?.week_start_day ?? 1);
  const WEEK_STARTS_ON = (weekStart % 7) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  const [view, setView] = useState<View>('month');
  const [cursor, setCursor] = useState(() => new Date());
  const [chosen, setChosen] = useState<CalendarDay | null>(null);
  const swipe = useRef<number | null>(null);
  const scheduled = useScheduled();

  const month = startOfMonth(cursor);
  const week = startOfWeek(cursor, { weekStartsOn: WEEK_STARTS_ON });
  const year = startOfYear(cursor).getFullYear();

  // One key per month, so swiping back to a month already seen draws it at
  // once instead of emptying the grid and asking again.
  const { data, error } = useQuery({
    queryKey: keys.calendar(month.getFullYear(), month.getMonth() + 1),
    queryFn: ({ signal }) => getMonth(month.getFullYear(), month.getMonth() + 1, signal),
    staleTime: STALE.derived,
    enabled: view === 'month',
  });

  const shown = data && data.year === month.getFullYear() && data.month === month.getMonth() + 1 ? data : null;
  const go = (delta: number) =>
    setCursor((c) => (view === 'week' ? addWeeks(c, delta) : view === 'year' ? addYears(c, delta) : addMonths(c, delta)));
  const referenced = shown?.days.find((d) => d.reference_kind !== null && d.reference !== null);

  // CAL-07. What is scheduled in the month shown, beside what was spent - never added to it.
  const monthAhead = fromCentavos(
    [...scheduled.entries()]
      .filter(([on]) => on.startsWith(format(month, 'yyyy-MM')))
      .reduce((sum, [, items]) => sum + centavos(outgoing(items)), 0),
  );

  const title = view === 'year' ? String(year) : view === 'week'
    ? `${format(week, 'd MMM')} – ${format(addDays(week, 6), 'd MMM')}`
    : format(month, 'MMMM');
  const subtitle = view === 'month' ? (
    <span className="num">
      {format(month, 'yyyy')}
      {shown && ` · ${formatPHP(shown.spent)} spent`}
      {monthAhead !== '0.00' && ` · ${formatPHP(monthAhead)} scheduled`}
    </span>
  ) : view === 'week' ? <span className="num">{format(week, 'yyyy')}</span> : undefined;
  const unit = view === 'week' ? 'week' : view === 'year' ? 'year' : 'month';

  return (
    <>
      <CalendarSwitch />
      <ScreenHeader
        title={title}
        subtitle={subtitle}
        action={
          <div className="flex gap-1">
            <button type="button" aria-label={`Previous ${unit}`} onClick={() => go(-1)}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press">
              ‹
            </button>
            <button type="button" aria-label={`Next ${unit}`} onClick={() => go(1)}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press">
              ›
            </button>
          </div>
        }
      />

      <div className="mb-3">
        <Segmented<View>
          label="Calendar view"
          value={view}
          onChange={setView}
          options={[
            { value: 'week', label: 'Week' },
            { value: 'month', label: 'Month' },
            { value: 'year', label: 'Year' },
          ]}
        />
      </div>

      {view === 'week' && <WeekView start={week} scheduled={scheduled} />}

      {view === 'year' && (
        <YearView year={year} weekStartsOn={WEEK_STARTS_ON} onMonth={(m) => { setCursor(m); setView('month'); }} />
      )}

      {view === 'month' && (
        <>
          {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>}

          <Card
            className="touch-pan-y px-2.5"
            onPointerDown={(e) => (swipe.current = e.clientX)}
            onPointerUp={(e) => {
              if (swipe.current === null) return;
              const dx = e.clientX - swipe.current;
              swipe.current = null;
              if (dx > SWIPE_PX) go(-1);
              if (dx < -SWIPE_PX) go(1);
            }}
          >
            <MonthGrid month={month} data={shown} weekStartsOn={WEEK_STARTS_ON} scheduled={scheduled} onDay={setChosen} />
            {!shown && !error && <p className="pt-3 text-center text-footnote text-ink-3">Loading…</p>}
          </Card>

          <div className="mt-3 flex items-center justify-between px-1">
            <div className="flex items-center gap-1.5 text-caption text-ink-3" aria-hidden="true">
              Less
              {[0, 1, 2, 3, 4].map((level) => (
                <span key={level} className={`h-3.5 w-3.5 rounded ${LEVEL[level]}`} />
              ))}
              More
            </div>
            {monthAhead !== '0.00' && (
              <span className="flex items-center gap-1.5 text-caption text-ink-3">
                <span className="h-3.5 w-3.5 rounded border-2 border-dashed border-stroke" aria-hidden="true" />
                scheduled
              </span>
            )}
          </div>
          {referenced?.reference && (
            <p className="mt-1 px-1 text-caption text-ink-3">
              {referenced.reference_kind === 'budget'
                ? `Shaded against your budget of ${formatPHP(referenced.reference)} a day.`
                : `No budget for this month — shaded against a typical day (${formatPHP(referenced.reference)}).`}
            </p>
          )}

          {shown && <MonthList month={month} spent={shown.spent} earned={shown.earned} />}
        </>
      )}

      <DaySheet day={chosen} scheduled={chosen ? scheduled.get(chosen.on) ?? [] : []} onClose={() => setChosen(null)} />
    </>
  );
}
