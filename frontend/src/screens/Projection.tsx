/**
 * Months ahead (REC-21..26, FEATURES.md §20).
 *
 * Each month from today's cash on hand: what comes in, what the budget and
 * the fixed charges take, and where it ends - carried into the next month.
 * The lowest point shows in red when it goes below zero: rent on the 1st and
 * pay on the 15th can empty an account mid-month that ends the month fine.
 *
 * Tap a month for every projected item, by account. Below, each card's next
 * statements with the recurring charges landing on them - shown, never taken
 * from cash on hand a second time.
 *
 * Nothing here is saved or posted; it is recomputed on every view.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Sheet } from '../components/ui/Sheet';
import { useLookups } from '../hooks/useLookups';
import { formatPHP } from '../lib/money';
import { getCardLookahead, getProjection, type CardLookahead, type ProjectedMonth, type Projection as Data } from '../lib/recurring';
import { useLedgerStore } from '../stores/ledgerStore';

const negative = (value: string) => value.startsWith('-');
const short = (iso: string) => format(parseISO(iso), 'd MMM');

function monthLabel(month: ProjectedMonth, basis: Data['basis']): string {
  if (basis === 'calendar') return format(parseISO(month.start), 'MMMM yyyy');
  return `${short(month.start)} – ${format(parseISO(month.end), 'd MMM yyyy')}`;
}

function MonthCard({ month, basis, onOpen }: { month: ProjectedMonth; basis: Data['basis']; onOpen: () => void }) {
  const low = negative(month.low_point);
  return (
    <button type="button" onClick={onOpen} className="block w-full rounded-card bg-surface p-4 text-left press">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-footnote font-semibold text-ink-2">
          {monthLabel(month, basis)}
          {month.current && ' · the rest of it'}
        </span>
        {month.overcommitted && <span className="text-caption font-semibold text-warn">Overcommitted</span>}
      </div>
      <p className={`num mt-1 text-title ${negative(month.closing) ? 'text-danger' : ''}`}>{formatPHP(month.closing)}</p>
      <p className="num text-caption text-ink-3">
        cash on hand at the end{month.bills !== '0.00' && ` · after ${formatPHP(month.bills)} of card bills`}
        {(month.bills_set_aside ?? '0.00') !== '0.00' && ` · ${formatPHP(month.bills_set_aside)} of bills due already set aside`}
      </p>
      <div className="mt-3 grid grid-cols-3 divide-x divide-stroke/80 text-center">
        <div>
          <p className="text-caption text-ink-3">Coming in</p>
          <p className="num text-footnote font-semibold text-ok">+{formatPHP(month.income)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Spending</p>
          <p className="num text-footnote font-semibold">−{formatPHP(month.spending)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Lowest</p>
          <p className={`num text-footnote font-semibold ${low ? 'text-danger' : ''}`}>{formatPHP(month.low_point)}</p>
          <p className="text-caption text-ink-3">{short(month.low_on)}</p>
        </div>
      </div>
    </button>
  );
}

function MonthSheet({ month, basis, onClose }: { month: ProjectedMonth | null; basis: Data['basis']; onClose: () => void }) {
  const lookups = useLookups();
  const groups = new Map<number, ProjectedMonth['items']>();
  for (const item of month?.items ?? []) groups.set(item.account_id, [...(groups.get(item.account_id) ?? []), item]);

  return (
    <Sheet open={month !== null} onClose={onClose} title={month ? monthLabel(month, basis) : undefined}>
      {month && (
        <div className="space-y-4 pb-2">
          <div className="num space-y-1 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote">
            <p className="flex justify-between"><span className="text-ink-2">Starts with</span>{formatPHP(month.opening)}</p>
            <p className="flex justify-between"><span className="text-ink-2">Coming in</span>+{formatPHP(month.income)}</p>
            <p className="flex justify-between"><span className="text-ink-2">Spending</span>−{formatPHP(month.spending)}</p>
            <p className="text-caption text-ink-3">
              The larger of your budget ({formatPHP(month.budget)}) and fixed charges ({formatPHP(month.committed)}) —
              fixed charges already count against the budget.
            </p>
            {month.bills !== '0.00' && (
              <p className="flex justify-between"><span className="text-ink-2">Card bills</span>−{formatPHP(month.bills)}</p>
            )}
            {(month.bills_set_aside ?? '0.00') !== '0.00' && (
              <p className="text-caption text-ink-3">
                {formatPHP(month.bills_set_aside)} of card bills due this month is already out of today's cash on hand,
                so it is not taken again here.
              </p>
            )}
            {month.transfers !== '0.00' && (
              <p className="flex justify-between"><span className="text-ink-2">Transfers out of cash on hand</span>{formatPHP(month.transfers)}</p>
            )}
            <p className="flex justify-between border-t border-stroke/40 pt-1 font-semibold"><span>Ends with</span>{formatPHP(month.closing)}</p>
          </div>
          {month.overcommitted && (
            <p className="rounded-2xl border-2 border-warn bg-warn/10 px-4 py-3 text-footnote text-warn">
              Fixed charges alone are more than your budget this month — the plan no longer fits it.
            </p>
          )}
          {month.items.length === 0 && <p className="text-body text-ink-2">Nothing scheduled — only the budget.</p>}
          {[...groups.entries()].map(([accountId, items]) => (
            <div key={accountId}>
              <p className="mb-1.5 text-footnote font-semibold text-ink-2">{lookups.accountById.get(accountId)?.name ?? 'Account'}</p>
              <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2 px-3">
                {items.map((item) => (
                  <li key={`${item.rule_id}-${item.on}-${item.name}`} className={`num flex min-h-11 items-center justify-between gap-2 text-footnote ${item.paused ? 'opacity-50' : ''}`}>
                    <span className="min-w-0 truncate">
                      <span className="text-ink-2">{short(item.on)}</span> · {item.name}
                      {item.kind === 'bill' && ' · card bill'}
                      {item.kind === 'bill_now' && ' · already set aside'}
                      {item.kind === 'interest' && ' · estimated at today’s balance'}
                      {item.final && ' · last payment'}
                      {item.paused && ' · paused, not counted'}
                    </span>
                    <span className={`shrink-0 font-semibold ${item.type === 'income' ? 'text-ok' : ''} ${
                      item.kind === 'bill_now' ? 'text-ink-3' : ''
                    }`}>
                      {item.type === 'income' ? '+' : item.type === 'expense' ? '−' : ''}
                      {formatPHP(item.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Sheet>
  );
}

function CardAhead({ card }: { card: CardLookahead }) {
  return (
    <Card padded={false} className="overflow-hidden">
      <p className="px-4 pb-1 pt-3 text-headline">{card.name}</p>
      <ul className="divide-y divide-stroke/80">
        {card.statements.map((s, index) => (
          <li key={s.closes} className="px-4 py-2.5">
            <div className="num flex items-baseline justify-between gap-2">
              <span className="text-footnote text-ink-2">Closes {short(s.closes)} · due {short(s.due)}</span>
              <span className="text-body font-semibold">{formatPHP(s.total)}</span>
            </div>
            <p className="num text-caption text-ink-3">
              {index === 0 && s.posted !== '0.00' && `${formatPHP(s.posted)} already on it · `}
              {s.items.filter((i) => !i.paused).map((i) => `${i.name} ${formatPHP(i.amount)}${i.final ? ' (last)' : ''}`).join(' · ') || 'No recurring charges'}
              {s.limit_share !== null && s.recurring !== '0.00' && ` · ${Math.round(Number(s.limit_share) * 100)}% of your limit already committed`}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function Projection() {
  const navigate = useNavigate();
  const version = useLedgerStore((s) => s.version);
  const [months, setMonths] = useState<'3' | '6' | '12'>('12');
  const [data, setData] = useState<Data | null>(null);
  const [cards, setCards] = useState<CardLookahead[]>([]);
  const [chosen, setChosen] = useState<ProjectedMonth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    Promise.all([getProjection(Number(months) as 3 | 6 | 12, controller.signal), getCardLookahead(controller.signal)])
      .then(([projection, lookahead]) => {
        setData(projection);
        setCards(lookahead);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, [months, version]);

  return (
    <>
      <ScreenHeader
        title="Months ahead"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />
      <Segmented<'3' | '6' | '12'>
        label="How far"
        value={months}
        onChange={setMonths}
        options={[
          { value: '3', label: '3 months' },
          { value: '6', label: '6 months' },
          { value: '12', label: '12 months' },
        ]}
      />
      {error && <p className="mt-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}
      {!data && !error && <div className="skeleton mt-3 h-72 rounded-card" aria-hidden="true" />}
      {data && (
        <>
          <p className="num px-1 pb-1 pt-3 text-footnote text-ink-2">
            From {formatPHP(data.cash_on_hand)} cash on hand today. Everyday spending is your budget; carry-over is not assumed.
          </p>
          <div className="space-y-3">
            {data.months.map((month) => (
              <MonthCard key={month.start} month={month} basis={data.basis} onOpen={() => setChosen(month)} />
            ))}
          </div>
        </>
      )}
      {cards.length > 0 && (
        <>
          <SectionTitle>Card statements ahead</SectionTitle>
          <div className="space-y-3">
            {cards.map((card) => <CardAhead key={card.account_id} card={card} />)}
          </div>
          <p className="px-1 pt-2 text-footnote text-ink-3">
            Charges already count against cash on hand on the day they post — paying the bill doesn’t count them again.
          </p>
        </>
      )}
      <MonthSheet month={chosen} basis={data?.basis ?? 'calendar'} onClose={() => setChosen(null)} />
    </>
  );
}
