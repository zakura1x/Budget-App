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
 * from cash on hand a second time. A card with typed bills shows those bills,
 * and so does a counted loan, whose dues are its bills (ACC-40),
 * each opening what it is made of (ACC-35, 2026-09-19).
 *
 * A card bill is taken in the month it is DUE (2026-09-19, user: November's
 * bill was showing in October). Home holds the next bill back earlier, so a
 * month says how much of its end figure Home will be holding (`bills_held`).
 *
 * Totals of the card bills to pay (2026-09-19, user): each month shows every
 * bill due in it - the ones already set aside included - and the look-ahead
 * shows what is left of every typed bill, per card and all together. Summed in
 * centavos from the figures the server sent; nothing new is worked out here.
 *
 * TRY A PLAN (REC-27): the rule sheet, but its button runs the plan through
 * the months ahead instead of saving it. Every month then shows what it does -
 * the end figure and the lowest point with the plan, beside today's - and
 * "Save this plan" is the ordinary createRule. Stop trying puts it back.
 *
 * Nothing here is saved or posted; it is recomputed on every view.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { BillSheet } from '../components/BillSheet';
import { RuleSheet } from '../components/RuleSheet';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Sheet } from '../components/ui/Sheet';
import { useLookups } from '../hooks/useLookups';
import type { Bill } from '../lib/accounts';
import { ApiError } from '../lib/api';
import { afterWrite, MONEY } from '../lib/invalidate';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { queryClient } from '../lib/queryClient';
import { keys, STALE } from '../lib/queryKeys';
import {
  createRule,
  getCardLookahead,
  getProjection,
  TRIAL_RULE_ID,
  whatIf,
  type CardLookahead,
  type ProjectedMonth,
  type Projection as Data,
  type RuleDraft,
  type RuleKind,
} from '../lib/recurring';

const negative = (value: string) => value.startsWith('-');
const short = (iso: string) => format(parseISO(iso), 'd MMM');

const BILL_KINDS = new Set(['bill', 'bill_plans', 'bill_now']);

/**
 * Every bill due in the month, whether or not today's cash on hand already holds it - a card's
 * typed bills (ACC-35) and a counted loan's own dues (ACC-40), which are the same kind of money.
 */
function billsDue(month: ProjectedMonth): string {
  return fromCentavos(month.items.filter((i) => BILL_KINDS.has(i.kind) && !i.paused).reduce((sum, i) => sum + centavos(i.amount), 0));
}

/** What is left to pay of every typed bill on these cards. */
function billsLeft(cards: CardLookahead[]): string {
  return fromCentavos(cards.flatMap((c) => c.bills ?? []).reduce((sum, b) => sum + centavos(b.left), 0));
}

function monthLabel(month: ProjectedMonth, basis: Data['basis']): string {
  if (basis === 'calendar') return format(parseISO(month.start), 'MMMM yyyy');
  return `${short(month.start)} – ${format(parseISO(month.end), 'd MMM yyyy')}`;
}

/**
 * REC-27. What the tried plan does to a month, against the same month without it -
 * the end figure's change, and whether it takes the lowest point below zero.
 */
function TrialDelta({ month, before }: { month: ProjectedMonth; before: ProjectedMonth }) {
  const change = centavos(month.closing) - centavos(before.closing);
  const lowChange = centavos(month.low_point) - centavos(before.low_point);
  const committed = centavos(month.committed) - centavos(before.committed);
  if (change === 0 && lowChange === 0) {
    if (committed <= 0) return <p className="mt-2 text-caption text-ink-3">The plan changes nothing this month.</p>;
    // REC-23: fixed charges count inside the budget, so a plan that fits it leaves the end figure where it
    // was - and leaves that much less of the budget for everything else. Said out loud (2026-09-28): "changes
    // nothing" was the wrong answer to "can I afford it".
    return (
      <p className="mt-2 rounded-lg border-2 border-stroke px-2 py-1 text-caption text-ink-2">
        Fits in your budget — <span className="num font-semibold text-ink">{formatPHP(fromCentavos(committed))}</span> less
        of it left for everything else (<span className="num">{formatPHP(month.committed)}</span> of{' '}
        <span className="num">{formatPHP(month.budget)}</span> now fixed)
      </p>
    );
  }
  const newlyBelow = negative(month.low_point) && !negative(before.low_point);
  return (
    <p className={`mt-2 rounded-lg border-2 px-2 py-1 text-caption ${newlyBelow ? 'border-danger text-danger' : 'border-stroke text-ink-2'}`}>
      <span className="num font-semibold">{formatPHP(fromCentavos(Math.abs(change)))}</span>
      {change < 0 ? ' less' : ' more'} at the end than without it (<span className="num">{formatPHP(before.closing)}</span>)
      {newlyBelow && ' · it takes the lowest point below zero'}
    </p>
  );
}

function MonthCard({ month, basis, onOpen, before }: {
  month: ProjectedMonth; basis: Data['basis']; onOpen: () => void; before?: ProjectedMonth;
}) {
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
        cash on hand at the end{month.bills !== '0.00' && ` · after ${formatPHP(month.bills)} of bills`}
        {(month.bills_set_aside ?? '0.00') !== '0.00' && ` · ${formatPHP(month.bills_set_aside)} of bills due already set aside`}
      </p>
      {(month.bills_held ?? '0.00') !== '0.00' && (
        <p className="num text-caption text-ink-3">
          Home will hold back {formatPHP(month.bills_held)} of it for bills due next month
        </p>
      )}
      {billsDue(month) !== '0.00' && (
        <p className="num mt-2 flex justify-between border-t border-stroke/40 pt-2 text-footnote">
          <span className="text-ink-2">Bills due this month</span>
          <span className="font-semibold">{formatPHP(billsDue(month))}</span>
        </p>
      )}
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
      {before && <TrialDelta month={month} before={before} />}
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
              <p className="flex justify-between"><span className="text-ink-2">Bills</span>−{formatPHP(month.bills)}</p>
            )}
            {(month.bills_set_aside ?? '0.00') !== '0.00' && (
              <p className="text-caption text-ink-3">
                {formatPHP(month.bills_set_aside)} of bills due this month is already out of today's cash on hand,
                so it is not taken again here.
              </p>
            )}
            {month.transfers !== '0.00' && (
              <p className="flex justify-between"><span className="text-ink-2">Transfers out of cash on hand</span>{formatPHP(month.transfers)}</p>
            )}
            <p className="flex justify-between border-t border-stroke/40 pt-1 font-semibold"><span>Ends with</span>{formatPHP(month.closing)}</p>
            {billsDue(month) !== '0.00' && (
              <p className="flex justify-between pt-1"><span className="text-ink-2">Bills due this month</span>{formatPHP(billsDue(month))}</p>
            )}
            {(month.bills_held ?? '0.00') !== '0.00' && (
              <p className="text-caption text-ink-3">
                Each card bill is taken here in the month it is due. Home holds the next one back as soon as the one
                before is due, so at the end of this month it will show {formatPHP(month.bills_held)} less.
              </p>
            )}
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
                      {(item.kind === 'bill' || item.kind === 'bill_plans') && ' · card bill'}
                      {item.kind === 'bill_now' && ' · already set aside'}
                      {item.kind === 'interest' && ' · estimated at today’s balance'}
                      {item.rule_id === TRIAL_RULE_ID && ' · the plan you are trying'}
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

function CardAhead({ card, onOpenBill }: { card: CardLookahead; onOpenBill: (bill: Bill) => void }) {
  if ((card.bills ?? []).length > 0) {
    // ACC-35. The bills typed from the card's app - the same figures as its Bills section.
    return (
      <Card padded={false} className="overflow-hidden">
        <p className="flex items-baseline justify-between gap-2 px-4 pb-1 pt-3">
          <span className="text-headline">{card.name}</span>
          <span className="num text-footnote text-ink-2">{formatPHP(billsLeft([card]))} to pay</span>
        </p>
        <ul className="divide-y divide-stroke/80">
          {card.bills.map((bill) => {
            const parts = bill.lines.filter((l) => l.kind === 'purchase' || l.kind === 'plan' || l.kind === 'inside_typed');
            return (
              <li key={bill.due}>
                <button type="button" onClick={() => onOpenBill(bill)} className="block w-full px-4 py-2.5 text-left active:bg-surface-2">
                  <span className="num flex items-baseline justify-between gap-2">
                    <span className={`text-footnote ${bill.overdue ? 'font-semibold text-danger' : 'text-ink-2'}`}>
                      Bill due {short(bill.due)}{bill.overdue && ' · overdue'}
                    </span>
                    <span className="text-body font-semibold">{formatPHP(bill.left)} ›</span>
                  </span>
                  <span className="num block truncate text-caption text-ink-3">
                    {parts.length
                      ? parts.map((l) => `${l.name ?? (l.rule_id !== null ? 'Plan' : 'Purchase')} ${formatPHP(l.amount)}`).join(' · ')
                      : 'From the card’s app'}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Card>
    );
  }
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

const TRY_KINDS: { kind: RuleKind; label: string }[] = [
  { kind: 'installment', label: 'An installment' },
  { kind: 'subscription', label: 'A subscription' },
  { kind: 'standard', label: 'A bill or income' },
];

export function Projection() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const [months, setMonths] = useState<'3' | '6' | '12'>('12');
  const [chosen, setChosen] = useState<ProjectedMonth | null>(null);
  const [bill, setBill] = useState<Bill | null>(null);
  /** REC-27. The kind being set up in the sheet, and the plan being tried - never saved until you say so. */
  const [trySheet, setTrySheet] = useState<RuleKind | null>(null);
  /** misc/AI AI-44 - an installment the assistant worked out, handed over to be tried here (and saved, or not). */
  const [tryPrefill, setTryPrefill] = useState<RuleDraft | null>(null);
  const location = useLocation();
  useEffect(() => {
    const asked = (location.state as { tryInstallment?: RuleDraft } | null)?.tryInstallment;
    if (!asked) return;
    setTryPrefill({ ...asked, kind: 'installment', type: 'expense' });
    setTrySheet('installment');
    navigate('.', { replace: true, state: null }); // once: a refresh must not reopen it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [trial, setTrial] = useState<RuleDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [trialError, setTrialError] = useState<string | null>(null);
  const span = Number(months) as 3 | 6 | 12;

  const { data: tried } = useQuery({
    queryKey: keys.whatIf(span, JSON.stringify(trial)),
    queryFn: () => whatIf(trial as RuleDraft, span),
    staleTime: STALE.derived,
    enabled: trial !== null,
  });

  /** The sheet's button: checked by the server first, so a plan it would refuse never shows as tried. */
  const tryPlan = async (draft: RuleDraft) => {
    const result = await whatIf(draft, span);
    queryClient.setQueryData(keys.whatIf(span, JSON.stringify(draft)), result);
    setTrialError(null);
    setTrial(draft);
  };

  const savePlan = async () => {
    if (!trial) return;
    setSaving(true);
    setTrialError(null);
    try {
      await createRule(trial);
      afterWrite(...MONEY); // it may post today, and it changes every month ahead
      setTrial(null);
    } catch (e) {
      setTrialError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setSaving(false);
  };

  // A key per span, so switching 3 / 6 / 12 months and back is instant.
  const { data, error } = useQuery({
    queryKey: keys.projection(Number(months) as 3 | 6 | 12),
    queryFn: ({ signal }) => getProjection(Number(months) as 3 | 6 | 12, signal),
    staleTime: STALE.derived,
  });
  const { data: cards = [] } = useQuery({
    queryKey: keys.cardLookahead(),
    queryFn: ({ signal }) => getCardLookahead(signal),
    staleTime: STALE.derived,
  });

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
      {error && <p className="mt-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>}
      {!data && !error && <div className="skeleton mt-3 h-72 rounded-card" aria-hidden="true" />}
      {data && !trial && (
        <Card className="mt-3 space-y-2">
          <p className="text-body font-semibold">Try a plan before committing</p>
          <p className="text-footnote text-ink-2">“Can I afford a phone at ₱3,000 × 12?” Set it up and see every month with it — nothing is saved.</p>
          <div className="flex flex-wrap gap-2">
            {TRY_KINDS.map((k) => (
              <Button key={k.kind} variant="secondary" onClick={() => setTrySheet(k.kind)}>{k.label}</Button>
            ))}
          </div>
        </Card>
      )}
      {trial && (
        <Card className="mt-3 space-y-3">
          <div>
            <p className="label text-ink-2">Trying</p>
            <p className="text-headline">{trial.name}</p>
            <p className="text-footnote text-ink-2">Every month below shows what it does. Nothing is saved yet.</p>
          </div>
          {trialError && <p className="text-footnote text-danger">{trialError}</p>}
          <div className="grid grid-cols-2 gap-2">
            <Button onClick={() => void savePlan()} disabled={saving}>Save this plan</Button>
            <Button variant="secondary" onClick={() => setTrial(null)} disabled={saving}>Stop trying</Button>
          </div>
        </Card>
      )}
      {data && (
        <>
          <p className="num px-1 pb-1 pt-3 text-footnote text-ink-2">
            From {formatPHP(data.cash_on_hand)} cash on hand today. Everyday spending is your budget; carry-over is not assumed.
          </p>
          {trial && !tried && <div className="skeleton h-72 rounded-card" aria-hidden="true" />}
          <div className="space-y-3">
            {(trial ? tried?.with_plan.months ?? [] : data.months).map((month, index) => (
              <MonthCard key={month.start} month={month} basis={data.basis} onOpen={() => setChosen(month)}
                before={trial ? tried?.without.months[index] : undefined} />
            ))}
          </div>
        </>
      )}
      {cards.length > 0 && (
        <>
          <SectionTitle>Card statements ahead</SectionTitle>
          {billsLeft(cards) !== '0.00' && (
            <div className="num mb-3 flex items-baseline justify-between rounded-card border-2 border-stroke bg-surface px-4 py-3 shadow-edge">
              <span className="text-footnote text-ink-2">All card bills to pay</span>
              <span className="text-body font-semibold">{formatPHP(billsLeft(cards))}</span>
            </div>
          )}
          <div className="space-y-3">
            {cards.map((card) => <CardAhead key={card.account_id} card={card} onOpenBill={setBill} />)}
          </div>
          <p className="px-1 pt-2 text-footnote text-ink-3">
            Charges already count against cash on hand on the day they post — paying the bill doesn’t count them again.
          </p>
        </>
      )}
      <MonthSheet month={chosen} basis={data?.basis ?? 'calendar'} onClose={() => setChosen(null)} />
      <BillSheet bill={bill} onClose={() => setBill(null)} />
      <RuleSheet
        open={trySheet !== null}
        rule={null}
        kind={trySheet ?? 'installment'}
        prefill={tryPrefill}
        lookups={lookups}
        onClose={() => { setTrySheet(null); setTryPrefill(null); }}
        onTry={tryPlan}
      />
    </>
  );
}
