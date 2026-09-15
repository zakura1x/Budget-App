/**
 * The calendar (CAL-01..CAL-05).
 *
 * Each day is shaded by what was spent on it, measured against the budget per
 * day - or, with no budget, against a typical day this month - so one rent
 * payment does not wash every other day out. The shade is intensity only,
 * never green/amber/red: those mean money state everywhere else.
 *
 * Swipe the grid or use the arrows for another month. Tap a day for its
 * transactions, from the ledger's own list; add one on that day from there.
 */
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  parseISO,
  startOfMonth,
  startOfWeek,
} from 'date-fns';
import { useEffect, useRef, useState } from 'react';
import { ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Sheet } from '../components/ui/Sheet';
import { useLookups } from '../hooks/useLookups';
import { getMonth, type CalendarDay, type CalendarMonth } from '../lib/calendar';
import { formatPHP, splitDecimal } from '../lib/money';
import { listTransactions, type Transaction } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { usePreferencesStore } from '../stores/preferencesStore';
import { useUiStore } from '../stores/uiStore';

const SWIPE_PX = 60;

/** Static, so Tailwind sees every class. */
const LEVEL: Record<number, string> = {
  0: 'bg-surface-2/60 text-ink',
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

function DaySheet({ day, onClose }: { day: CalendarDay | null; onClose: () => void }) {
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const openSheet = useUiStore((s) => s.openAddSheet);
  const [rows, setRows] = useState<Transaction[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!day) return;
    setRows(null);
    setError(null);
    const controller = new AbortController();
    listTransactions({ from: day.on, to: day.on }, null, controller.signal)
      .then((page) => setRows(page.items))
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, [day, version]);

  const open = (row?: Transaction) => {
    onClose();
    openSheet(row, row ? undefined : day?.on);
  };

  return (
    <Sheet open={day !== null} onClose={onClose} title={day ? format(parseISO(day.on), 'EEEE d MMMM') : undefined}>
      {day && (
        <div className="space-y-3 pb-2">
          <p className="num text-footnote text-ink-2">
            {day.spent !== '0.00' ? `${formatPHP(day.spent)} spent` : 'Nothing spent'}
            {day.earned !== '0.00' && ` · ${formatPHP(day.earned)} earned`}
          </p>
          {error && <p className="text-footnote text-danger">{error}</p>}
          {rows === null && !error && <div className="skeleton h-28 rounded-card" aria-hidden="true" />}
          {rows && rows.length > 0 && (
            <div className="divide-y divide-line overflow-hidden rounded-card bg-surface-2/40">
              {rows.map((row) => (
                <button key={row.id} type="button" onClick={() => open(row)} className="block w-full transition active:bg-surface-2">
                  <TransactionRow row={row} lookups={lookups} />
                </button>
              ))}
            </div>
          )}
          {rows && rows.length === 0 && <p className="text-body text-ink-2">No transactions on this day.</p>}
          <Button block variant="secondary" onClick={() => open()}>
            Add one on this day
          </Button>
        </div>
      )}
    </Sheet>
  );
}

export function Calendar() {
  const version = useLedgerStore((s) => s.version);
  // Settings: 1 Monday .. 7 Sunday; date-fns counts 0 Sunday .. 6 Saturday.
  const weekStart = usePreferencesStore((s) => s.prefs?.week_start_day ?? 1);
  const WEEK_STARTS_ON = (weekStart % 7) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [data, setData] = useState<CalendarMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<CalendarDay | null>(null);
  const swipe = useRef<number | null>(null);

  useEffect(() => {
    setError(null);
    const controller = new AbortController();
    getMonth(month.getFullYear(), month.getMonth() + 1, controller.signal)
      .then(setData)
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, [month, version]);

  const shown = data && data.year === month.getFullYear() && data.month === month.getMonth() + 1 ? data : null;
  const byDate = new Map((shown?.days ?? []).map((d) => [d.on, d]));
  const cells = eachDayOfInterval({
    start: startOfWeek(month, { weekStartsOn: WEEK_STARTS_ON }),
    end: endOfWeek(endOfMonth(month), { weekStartsOn: WEEK_STARTS_ON }),
  });
  const go = (delta: number) => setMonth((m) => addMonths(m, delta));
  const referenced = shown?.days.find((d) => d.reference_kind !== null && d.reference !== null);

  return (
    <>
      <ScreenHeader
        title={format(month, 'MMMM')}
        subtitle={
          <span className="num">
            {format(month, 'yyyy')}
            {shown && ` · ${formatPHP(shown.spent)} spent`}
          </span>
        }
        action={
          <div className="flex gap-1">
            <button type="button" aria-label="Previous month" onClick={() => go(-1)}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 shadow-card active:bg-surface-2">
              ‹
            </button>
            <button type="button" aria-label="Next month" onClick={() => go(1)}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 shadow-card active:bg-surface-2">
              ›
            </button>
          </div>
        }
      />

      {error && <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

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
        <div className="grid grid-cols-7 pb-2 text-center text-caption font-semibold uppercase text-ink-3">
          {cells.slice(0, 7).map((d) => (
            <span key={d.toISOString()}>{format(d, 'EEEEE')}</span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {cells.map((d) => {
            const inMonth = isSameMonth(d, month);
            const day = inMonth ? byDate.get(format(d, 'yyyy-MM-dd')) : undefined;
            if (!inMonth) {
              return (
                <span key={d.toISOString()} className="num flex aspect-square items-start justify-center pt-1.5 text-footnote text-ink-3/50">
                  {format(d, 'd')}
                </span>
              );
            }
            const spent = day && day.spent !== '0.00';
            return (
              <button
                key={d.toISOString()}
                type="button"
                disabled={!day}
                onClick={() => day && setChosen(day)}
                aria-label={`${format(d, 'EEEE d MMMM')}${spent ? `, ${formatPHP(day.spent)} spent` : ''}`}
                className={[
                  'num flex aspect-square flex-col items-center justify-start rounded-xl pt-1.5 transition active:scale-95',
                  day ? LEVEL[day.level] : LEVEL[0],
                  isToday(d) ? 'ring-2 ring-inset ring-accent' : '',
                ].join(' ')}
              >
                <span className={`text-footnote ${isToday(d) ? 'font-bold' : 'font-medium'}`}>{format(d, 'd')}</span>
                {spent && <span className="mt-0.5 text-caption leading-none opacity-90">{compactAmount(day.spent)}</span>}
                {!spent && day && day.count > 0 && <span className="mt-1.5 h-1 w-1 rounded-full bg-ink-3" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
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
        {shown && shown.earned !== '0.00' && (
          <span className="num text-caption text-ink-3">{formatPHP(shown.earned)} earned</span>
        )}
      </div>
      {referenced?.reference && (
        <p className="mt-1 px-1 text-caption text-ink-3">
          {referenced.reference_kind === 'budget'
            ? `Shaded against your budget of ${formatPHP(referenced.reference)} a day.`
            : `No budget for this month — shaded against a typical day (${formatPHP(referenced.reference)}).`}
        </p>
      )}

      <DaySheet day={chosen} onClose={() => setChosen(null)} />
    </>
  );
}
