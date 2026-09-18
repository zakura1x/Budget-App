/**
 * Recurring (REC-01..17, SUB-01..08) - bills and income, subscriptions and
 * installments: three views of one engine, so three tabs over one list.
 *
 *   Bills & income  every standard rule with its next date
 *   Subscriptions   the monthly total and its share of the budget, what
 *                   charges in the next 30 days, reminders due, and the
 *                   repeating charges the app noticed - one tap to track,
 *                   never tracked without that tap (SUB-03)
 *   Installments    a progress card per plan and everything still owed
 *                   across all of them (REC-17)
 */
import { format, parseISO } from 'date-fns';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PlusIcon } from '../components/Icons';
import { RuleSheet } from '../components/RuleSheet';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { useLookups, type Lookups } from '../hooks/useLookups';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import {
  getDetected,
  getSubscriptions,
  listRules,
  scheduleLabel,
  type Candidate,
  type Rule,
  type RuleDraft,
  type RuleKind,
  type SubscriptionOverview,
} from '../lib/recurring';
import { useLedgerStore } from '../stores/ledgerStore';

const NEUTRAL = '#8E8E93';
const short = (iso: string) => format(parseISO(iso), 'd MMM');

function RuleRow({ rule, lookups, onOpen, trailing }: { rule: Rule; lookups: Lookups; onOpen: () => void; trailing?: string }) {
  const category = rule.category_id != null ? lookups.categoryById.get(rule.category_id) : undefined;
  const account = lookups.accountById.get(rule.account_id);
  const status = rule.problem ?? (rule.paused ? 'Paused' : rule.next_on ? `Next ${short(rule.next_on)}` : 'Ended');
  const income = rule.type === 'income';
  return (
    <button type="button" onClick={onOpen}
      className={`flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left transition active:bg-surface-2 ${rule.paused ? 'opacity-60' : ''}`}>
      <GlyphTile icon={rule.type === 'transfer' ? 'undo' : category?.icon ?? 'tag'} colour={category?.colour ?? NEUTRAL} size={40} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body">{rule.name}</span>
        <span className="block truncate text-footnote text-ink-2">
          {/* The date first: a long account name must never truncate it away. */}
          <span className={rule.problem ? 'text-danger' : ''}>{status}</span> · {scheduleLabel(rule)} ·{' '}
          {account?.name ?? 'Account'}
        </span>
      </span>
      <span className={`num shrink-0 text-body font-semibold ${income ? 'text-ok' : ''}`}>
        {trailing ?? `${income ? '+' : ''}${formatPHP(rule.next_amount ?? rule.amount)}`}
      </span>
    </button>
  );
}

function PlanCard({ rule, lookups, onOpen }: { rule: Rule; lookups: Lookups; onOpen: () => void }) {
  const plan = rule.installment;
  if (!plan) return null;
  const whole = centavos(plan.total);
  const paid = whole > 0 ? Math.min(centavos(plan.paid) / whole, 1) : 0;
  const account = lookups.accountById.get(rule.account_id);
  return (
    <button type="button" onClick={onOpen} className="block w-full rounded-card bg-surface p-4 text-left press">
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block truncate text-headline">{rule.name}</span>
          <span className="block text-footnote text-ink-2">
            {account?.name ?? 'Account'} · {formatPHP(plan.per_payment)} × {plan.payments}
          </span>
        </span>
        {plan.closed ? (
          <span className="shrink-0 rounded-md bg-surface-2 px-2 py-1 font-mono text-caption font-bold uppercase text-ink-2 shadow-edge">Paid off</span>
        ) : plan.terms === 'provisional' ? (
          <span className="shrink-0 rounded-md bg-surface-2 px-2 py-1 font-mono text-caption font-bold uppercase text-ink-2 shadow-edge">Terms not confirmed</span>
        ) : null}
      </div>
      <p className="num mt-3 text-title">{formatPHP(plan.remaining)} <span className="text-footnote font-normal text-ink-2">left</span></p>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2 shadow-edge" aria-hidden="true">
        <div className="h-full rounded-full bg-accent" style={{ width: `${paid * 100}%` }} />
      </div>
      <p className="mt-1.5 text-footnote text-ink-3">
        {plan.payments_posted} of {plan.payments} paid
        {!plan.closed && plan.payoff_on && ` · done ${format(parseISO(plan.payoff_on), 'MMM yyyy')}`}
        {!plan.closed && rule.next_on && ` · next ${short(rule.next_on)}`}
      </p>
    </button>
  );
}

export function Recurring() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const [tab, setTab] = useState<RuleKind>('standard');
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [subs, setSubs] = useState<SubscriptionOverview | null>(null);
  const [detected, setDetected] = useState<Candidate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ open: boolean; rule: Rule | null; prefill: RuleDraft | null }>({
    open: false, rule: null, prefill: null,
  });

  const load = useCallback((signal?: AbortSignal) => {
    return Promise.all([listRules(undefined, signal), getSubscriptions(signal), getDetected(signal)])
      .then(([ruleList, overview, candidates]) => {
        setRules(ruleList);
        setSubs(overview);
        setDetected(candidates);
        setError(null);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, version]);

  const shown = (rules ?? []).filter((r) => r.kind === tab);
  const open = (rule: Rule | null, prefill: RuleDraft | null = null) => setSheet({ open: true, rule, prefill });
  const owed = shown.filter((r) => r.installment && !r.installment.closed)
    .reduce((sum, r) => sum + centavos(r.installment?.remaining ?? '0'), 0);
  const empty = rules !== null && shown.length === 0;

  return (
    <>
      <ScreenHeader
        title="Recurring"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
        action={
          <Button onClick={() => open(null)} aria-label="Add">
            <PlusIcon size={20} />
            Add
          </Button>
        }
      />

      <Segmented<RuleKind>
        label="Kind"
        value={tab}
        onChange={setTab}
        options={[
          { value: 'standard', label: 'Bills & pay' },
          { value: 'subscription', label: 'Subscriptions' },
          { value: 'installment', label: 'Installments' },
        ]}
      />

      {error && (
        <p className="mt-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error}{' '}
          <button type="button" className="font-semibold underline" onClick={() => void load()}>Try again</button>
        </p>
      )}
      {rules === null && !error && <div className="skeleton mt-3 h-40 rounded-card" aria-hidden="true" />}

      {tab === 'subscription' && subs && (
        <Card className="mt-3">
          <p className="text-footnote font-medium text-ink-2">Subscriptions a month</p>
          <p className="num text-display">{formatPHP(subs.monthly_total)}</p>
          {subs.budget_share !== null && (
            <p className="text-footnote text-ink-2">{Math.round(Number(subs.budget_share) * 100)}% of this month’s budget</p>
          )}
          {subs.items.filter((i) => i.remind).map((i) => (
            <p key={i.rule.id} className="mt-2 rounded-card border-2 border-warn bg-warn/10 px-3 py-2 text-footnote font-semibold text-warn">
              {i.rule.name} charges {i.due_in_days === 0 ? 'today' : `in ${i.due_in_days} day${i.due_in_days === 1 ? '' : 's'}`}
            </p>
          ))}
        </Card>
      )}
      {tab === 'installment' && rules !== null && shown.length > 0 && (
        <Card className="mt-3">
          <p className="text-footnote font-medium text-ink-2">Still owed across all plans</p>
          <p className="num text-display">{formatPHP(fromCentavos(owed))}</p>
          <p className="text-footnote text-ink-3">Paid month by month — never taken from cash on hand up front.</p>
        </Card>
      )}

      {empty && (
        <Card className="mt-3 text-center">
          <p className="text-body">
            {tab === 'standard' ? 'No recurring bills or income yet.' : tab === 'subscription' ? 'No subscriptions tracked.' : 'No installment plans.'}
          </p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            {tab === 'standard'
              ? 'Rent, salary on the 15th and 30th, a savings transfer — set once, posted on the day.'
              : tab === 'subscription'
                ? 'Netflix, Spotify, the gym — see what they cost you each month.'
                : 'A phone at ₱40,000 over 6 months. Enter the price and months; the first bill tells the interest.'}
          </p>
          <Button className="mt-4" onClick={() => open(null)}>Add one</Button>
        </Card>
      )}

      {tab === 'installment' ? (
        <div className="mt-3 space-y-3">
          {shown.map((rule) => <PlanCard key={rule.id} rule={rule} lookups={lookups} onOpen={() => open(rule)} />)}
        </div>
      ) : (
        shown.length > 0 && (
          <div className="mt-3 divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {shown.map((rule) => {
              const monthly = tab === 'subscription' ? subs?.items.find((i) => i.rule.id === rule.id)?.monthly : undefined;
              return (
                <RuleRow key={rule.id} rule={rule} lookups={lookups} onOpen={() => open(rule)}
                  trailing={monthly && rule.frequency !== 'monthly' ? `${formatPHP(monthly)}/mo` : undefined} />
              );
            })}
          </div>
        )
      )}

      {tab === 'subscription' && subs && subs.upcoming.length > 0 && (
        <>
          <SectionTitle>Next 30 days</SectionTitle>
          <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {subs.upcoming.map((u) => (
              <div key={`${u.rule_id}-${u.on}`} className="num flex min-h-12 items-center justify-between px-4 text-body">
                <span><span className="text-ink-2">{short(u.on)}</span> · {u.name}</span>
                <span className="font-semibold">{formatPHP(u.amount)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === 'subscription' && detected.length > 0 && (
        <>
          <SectionTitle>Looks like a subscription</SectionTitle>
          <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {detected.map((c) => (
              <div key={`${c.merchant}-${c.amount}-${c.account_id}`} className="flex min-h-14 items-center gap-3 px-4 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">{c.merchant}</span>
                  <span className="num block text-footnote text-ink-2">
                    {formatPHP(c.amount)} · {c.months} months · next {short(c.next_on)}
                  </span>
                </span>
                <Button variant="secondary" onClick={() => open(null, {
                  kind: 'subscription', type: 'expense', name: c.merchant, merchant: c.merchant, amount: c.amount,
                  account_id: c.account_id, category_id: c.category_id, start: c.next_on, frequency: 'monthly',
                })}>
                  Track
                </Button>
              </div>
            ))}
          </div>
          <p className="px-1 pt-2 text-footnote text-ink-3">Nothing is charged until you track it.</p>
        </>
      )}

      <RuleSheet
        open={sheet.open}
        rule={sheet.rule}
        kind={tab}
        prefill={sheet.prefill}
        lookups={lookups}
        onClose={() => setSheet((s) => ({ ...s, open: false }))}
        onSaved={() => void load()}
      />
    </>
  );
}
