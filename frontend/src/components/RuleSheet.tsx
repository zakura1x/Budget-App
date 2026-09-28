/**
 * Add or edit a recurring rule of any kind (REC-01..30, SUB-01..08).
 *
 * One sheet because it is one engine: a salary, Netflix and a phone on
 * installments differ only in the fields their kind adds. The next five dates
 * are previewed from the server's own schedule as you type, so what the sheet
 * promises is exactly what will post.
 *
 *   standard      amount, schedule, end condition; a changed amount takes
 *                 effect from a date and never rewrites what posted (REC-20)
 *   subscription  the same, plus reminder days (SUB-06)
 *   installment   price and months; interest if known, otherwise the first
 *                 statement confirms it (REC-28/29). Once payments post, the
 *                 terms are fixed - skip one or pay the rest off instead
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import type { Lookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { flatten } from '../lib/categories';
import { afterWrite, MONEY } from '../lib/invalidate';
import { centavos, formatPHP, toDecimalString } from '../lib/money';
import {
  createRule,
  deleteRule,
  revertInstallment,
  pauseRule,
  payOff,
  previewRule,
  skipOccurrence,
  updateRule,
  type Frequency,
  type Occurrence,
  type Rule,
  type RuleDraft,
  type RuleKind,
  type RuleType,
} from '../lib/recurring';
import { localToday } from '../lib/transactions';
import { ReceiptControl } from './ReceiptControl';
import { SubscriptionControls } from './SubscriptionControls';
import { Button } from './ui/Button';
import { Segmented } from './ui/Segmented';
import { Sheet } from './ui/Sheet';
import { MoneyField } from './ui/MoneyField';
import { TextField } from './ui/TextField';

const typedFrom = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);
const longDay = (iso: string) => format(parseISO(iso), 'd MMM yyyy');
const positive = (typed: string) => {
  try {
    return centavos(toDecimalString(typed || '0')) > 0;
  } catch {
    return false;
  }
};

const TITLES: Record<RuleKind, [string, string]> = {
  standard: ['New recurring', 'Edit recurring'],
  subscription: ['New subscription', 'Edit subscription'],
  installment: ['New installment', 'Edit installment'],
};

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`min-h-tap shrink-0 rounded-xl px-3 text-footnote font-medium transition ${
        selected ? 'bg-accent text-on-accent shadow-edge' : 'bg-surface text-ink-2 shadow-edge active:bg-surface-2'
      }`}
    >
      {children}
    </button>
  );
}

export interface RuleSheetProps {
  open: boolean;
  rule: Rule | null;
  kind: RuleKind;
  /** A detected subscription to start from (SUB-03). */
  prefill?: RuleDraft | null;
  lookups: Lookups;
  onClose: () => void;
  /** Optional: the sheet already calls `afterWrite`, so a screen rarely needs this. */
  onSaved?: () => void;
  /**
   * REC-27. A what-if: the button runs the plan through the months ahead
   * instead of saving it. Only for a NEW rule; the screen that asked shows the
   * result and saves it through the ordinary createRule if you choose to.
   */
  onTry?: (draft: RuleDraft) => Promise<void>;
}

export function RuleSheet({ open, rule, kind: newKind, prefill, lookups, onClose, onSaved, onTry }: RuleSheetProps) {
  const kind = rule?.kind ?? newKind;
  const [type, setType] = useState<RuleType>('expense');
  const [name, setName] = useState('');
  const [merchant, setMerchant] = useState('');
  const [accountId, setAccountId] = useState<number | null>(null);
  const [counterId, setCounterId] = useState<number | null>(null);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [amount, setAmount] = useState('');
  const [amountFrom, setAmountFrom] = useState(localToday());
  const [frequency, setFrequency] = useState<Frequency>('monthly');
  const [interval, setInterval] = useState('1');
  const [days, setDays] = useState(['15', '30']);
  const [start, setStart] = useState(localToday());
  const [endMode, setEndMode] = useState<'never' | 'after' | 'on'>('never');
  const [endAfter, setEndAfter] = useState('12');
  const [endOn, setEndOn] = useState('');
  const [price, setPrice] = useState('');
  const [payments, setPayments] = useState('12');
  const [interest, setInterest] = useState('');
  const [reminder, setReminder] = useState('3');
  const [postPast, setPostPast] = useState(false);
  const [preview, setPreview] = useState<Occurrence[] | null>(null);
  const [confirmingPayoff, setConfirmingPayoff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const source = rule;
    setError(null);
    setBusy(false);
    setConfirmingPayoff(false);
    setType(source?.type ?? prefill?.type ?? 'expense');
    setName(source?.name ?? prefill?.name ?? '');
    setMerchant(source?.merchant ?? prefill?.merchant ?? '');
    setAccountId(source?.account_id ?? prefill?.account_id ?? lookups.accounts.find((a) => !a.archived)?.id ?? null);
    setCounterId(source?.counter_account_id ?? prefill?.counter_account_id ?? null);
    setCategoryId(source?.category_id ?? prefill?.category_id ?? null);
    setAmount(source ? typedFrom(source.installment ? '0.00' : source.amount) : prefill?.amount ? typedFrom(prefill.amount) : '');
    setAmountFrom(localToday());
    setFrequency(source?.frequency ?? prefill?.frequency ?? 'monthly');
    setInterval(String(source?.interval ?? 1));
    setDays(source?.days.length ? source.days.map(String) : ['15', '30']);
    setStart(source?.start ?? prefill?.start ?? localToday());
    setEndMode(source?.end_after ? 'after' : source?.end_on ? 'on' : 'never');
    setEndAfter(String(source?.end_after ?? 12));
    setEndOn(source?.end_on ?? '');
    setPrice(source?.installment ? typedFrom(source.installment.price) : '');
    setPayments(String(source?.installment?.payments ?? 12));
    setInterest(source?.installment?.terms === 'confirmed' ? typedFrom(source.installment.interest) : '');
    setReminder(String(source?.reminder_days ?? 3));
    setPostPast(false);
  }, [open, rule, prefill, lookups.accounts]);

  const locked = Boolean(rule?.installment && rule.installment.payments_posted > 0);
  const categories = useMemo(
    () => flatten(lookups.tree).filter((c) => c.kind === type && !c.archived),
    [lookups.tree, type],
  );
  /**
   * TXN-05, the same two-step picker as the add sheet (2026-09-16, user: the
   * whole category list at once is unusable after an import). MAIN categories
   * only; the sub-categories of the one chosen appear under it, optional.
   */
  const mains = useMemo(
    () => lookups.tree.filter((c) => c.kind === type && !c.archived),
    [lookups.tree, type],
  );
  const chosenCategory = categoryId !== null ? categories.find((c) => c.id === categoryId) : undefined;
  const mainId = chosenCategory ? chosenCategory.parent_id ?? chosenCategory.id : null;
  const main = mains.find((c) => c.id === mainId);
  const subs = (main?.children ?? []).filter((c) => !c.archived);
  const accounts = lookups.accounts.filter((a) => !a.archived || a.id === rule?.account_id);

  const problem = (() => {
    if (accountId === null) return 'Choose an account';
    if (type === 'transfer') {
      if (counterId === null || counterId === accountId) return 'Choose where the money goes';
    } else if (categoryId === null) return 'Choose a category';
    if (kind === 'installment') {
      if (!positive(price)) return 'Type the price';
      if (!(Number(payments) >= 1)) return 'How many payments?';
      if (interest.trim() && !positive(interest) && interest.replace(/[0.]/g, '') !== '') return 'Check the interest';
    } else if (!positive(amount)) return 'Type an amount';
    if (frequency === 'semi_monthly' && (days[0] === days[1] || days.some((d) => !(Number(d) >= 1 && Number(d) <= 31))))
      return 'Pick two different days';
    if (endMode === 'on' && !endOn) return 'Choose the last date';
    return null;
  })();

  const draft = (): RuleDraft => {
    const body: RuleDraft = {
      kind,
      type,
      name: name.trim() || undefined,
      account_id: accountId ?? undefined,
      frequency,
      start,
      notes: undefined,
    };
    if (type === 'transfer') body.counter_account_id = counterId;
    else {
      body.category_id = categoryId;
      body.merchant = merchant.trim() || undefined;
    }
    if (frequency === 'semi_monthly') body.days = days.map(Number);
    else body.interval = Math.max(1, Number(interval) || 1);
    if (kind === 'installment') {
      body.price = toDecimalString(price);
      body.payments = Number(payments);
      if (interest.trim()) body.interest = toDecimalString(interest);
    } else {
      body.amount = toDecimalString(amount);
      if (rule && body.amount !== rule.amount) body.amount_from = amountFrom;
      if (endMode === 'after') body.end_after = Number(endAfter);
      else if (endMode === 'on') body.end_on = endOn;
      else if (rule) body.clear_end = true;
    }
    if (kind === 'subscription') body.reminder_days = Number(reminder);
    return body;
  };

  const previewKey = problem === null ? JSON.stringify(draft()) : '';
  useEffect(() => {
    if (!open || !previewKey) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewRule(JSON.parse(previewKey) as RuleDraft, controller.signal)
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, previewKey]);

  // A write can post transactions (a rule starting today, a payoff): refresh what shows money.
  const refreshMoney = () => afterWrite(...MONEY);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      refreshMoney();
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
      setBusy(false);
    }
  };

  const trying = Boolean(onTry) && !rule;

  const save = async () => {
    if (trying && onTry) {
      // REC-27. Nothing is written: the screen shows the months ahead with this plan in them.
      setBusy(true);
      setError(null);
      try {
        await onTry({ ...draft(), post_past: postPast });
        onClose();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'That could not be tried. Check it and try again.');
      }
      setBusy(false);
      return;
    }
    await run(() => (rule ? updateRule(rule.id, { ...draft(), post_past: undefined }) : createRule({ ...draft(), post_past: postPast })));
  };

  const plan = rule?.installment;
  const startsInPast = !rule && start < localToday();

  return (
    <Sheet open={open} onClose={onClose} title={TITLES[kind][rule ? 1 : 0]}>
      <div className="space-y-4 pb-2">
        {plan && (
          <div className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
            <p className="num text-headline">{formatPHP(plan.remaining)} left</p>
            <p className="text-footnote text-ink-2">
              {plan.payments_posted} of {plan.payments} paid
              {plan.payoff_on && ` · done ${format(parseISO(plan.payoff_on), 'MMM yyyy')}`}
              {plan.terms === 'provisional' && ' · Terms not confirmed'}
            </p>
            {plan.terms === 'provisional' && (
              <p className="mt-1 text-footnote text-ink-3">
                The first statement with a payment confirms the interest — check it under Accounts.
              </p>
            )}
          </div>
        )}
        {rule?.problem && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{rule.problem}.</p>}

        {kind === 'standard' && !rule && (
          <Segmented<RuleType>
            label="Type"
            value={type}
            onChange={(next) => {
              setType(next);
              setCategoryId(null);
            }}
            options={[
              { value: 'expense', label: 'Expense' },
              { value: 'income', label: 'Income' },
              { value: 'transfer', label: 'Transfer' },
            ]}
          />
        )}

        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
          placeholder={kind === 'subscription' ? 'Netflix' : kind === 'installment' ? 'Phone' : type === 'income' ? 'Salary' : 'Rent'} />

        {kind === 'installment' ? (
          <div className="grid grid-cols-2 gap-3">
            <MoneyField label="Price" value={price} disabled={locked} placeholder="40000" onChange={setPrice} />
            <TextField label="Payments" value={payments} disabled={locked} inputMode="numeric"
              onChange={(e) => setPayments(e.target.value.replace(/\D/g, '').slice(0, 3))} />
            <MoneyField className="col-span-2" label="Total interest (optional)" value={interest} disabled={locked}
              onChange={setInterest}
              hint={interest.trim() ? 'Each payment posts the price and the interest as two splits.'
                : 'The first statement will tell — the app asks when you check it.'} />
          </div>
        ) : (
          <MoneyField label="Amount" value={amount} placeholder="0.00" onChange={setAmount} />
        )}
        {rule && kind !== 'installment' && positive(amount) && toDecimalString(amount) !== rule.amount && (
          <label className="block text-footnote font-semibold text-ink-2">
            New amount from
            <input type="date" value={amountFrom} min={rule.start} onChange={(e) => e.target.value && setAmountFrom(e.target.value)}
              className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
            <span className="mt-1 block font-normal text-ink-3">Charges already posted keep their amount.</span>
          </label>
        )}

        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">{type === 'transfer' ? 'From' : type === 'income' ? 'Into' : 'Paid from'}</p>
          <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1">
            {accounts.map((a) => (
              <Chip key={a.id} selected={accountId === a.id} onClick={() => setAccountId(a.id)}>{a.name}</Chip>
            ))}
          </div>
        </div>
        {type === 'transfer' ? (
          <div>
            <p className="mb-2 text-footnote font-semibold text-ink-2">To</p>
            <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 py-1">
              {accounts.filter((a) => a.id !== accountId).map((a) => (
                <Chip key={a.id} selected={counterId === a.id} onClick={() => setCounterId(a.id)}>{a.name}</Chip>
              ))}
            </div>
          </div>
        ) : (
          <div>
            <p className="mb-2 text-footnote font-semibold text-ink-2">Category</p>
            <div className="flex flex-wrap gap-2">
              {mains.map((c) => (
                <Chip key={c.id} selected={mainId === c.id} onClick={() => setCategoryId(c.id)}>{c.name}</Chip>
              ))}
              {mains.length === 0 && <p className="text-footnote text-ink-3">Add a {type} category first.</p>}
            </div>
            {subs.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-footnote text-ink-3" aria-hidden="true">↳</span>
                {subs.map((c) => (
                  <Chip key={c.id} selected={categoryId === c.id}
                    // Tapping the chosen one again goes back to the main category alone.
                    onClick={() => setCategoryId(categoryId === c.id ? (mainId as number) : c.id)}>
                    {c.name}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 p-3">
          <Segmented<Frequency>
            label="How often"
            value={frequency}
            onChange={(next) => !locked && setFrequency(next)}
            options={[
              { value: 'weekly', label: 'Week' },
              { value: 'semi_monthly', label: '2× mo' },
              { value: 'monthly', label: 'Month' },
              { value: 'yearly', label: 'Year' },
            ]}
          />
          {frequency === 'semi_monthly' ? (
            <div className="grid grid-cols-2 gap-3">
              {days.map((value, index) => (
                <TextField key={index} label={index === 0 ? 'First day' : 'Second day'} value={value} inputMode="numeric"
                  disabled={locked}
                  onChange={(e) => setDays((d) => d.map((x, i) => (i === index ? e.target.value.replace(/\D/g, '').slice(0, 2) : x)))} />
              ))}
              <p className="col-span-2 text-footnote text-ink-3">A day the month doesn’t have becomes its last day — the 30th is 28 Feb.</p>
            </div>
          ) : (
            <TextField label={`Every how many ${frequency === 'weekly' ? 'weeks' : frequency === 'yearly' ? 'years' : 'months'}`}
              value={interval} inputMode="numeric" disabled={locked}
              onChange={(e) => setInterval(e.target.value.replace(/\D/g, '').slice(0, 2))} />
          )}
          <label className="block text-footnote font-semibold text-ink-2">
            {kind === 'installment' ? 'First payment' : 'Starts'}
            <input type="date" value={start} disabled={locked} onChange={(e) => e.target.value && setStart(e.target.value)}
              className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink disabled:opacity-60" />
          </label>
          {startsInPast && (
            <label className="flex items-center gap-2 text-footnote text-ink-2">
              <input type="checkbox" checked={postPast} onChange={(e) => setPostPast(e.target.checked)} className="h-5 w-5" />
              Also record the ones already due (leave off if you entered them yourself)
            </label>
          )}
          {kind !== 'installment' && (
            <>
              <Segmented<'never' | 'after' | 'on'>
                label="Ends"
                value={endMode}
                onChange={setEndMode}
                options={[
                  { value: 'never', label: 'Never' },
                  { value: 'after', label: 'After' },
                  { value: 'on', label: 'On a date' },
                ]}
              />
              {endMode === 'after' && (
                <TextField label="Number of times" value={endAfter} inputMode="numeric"
                  onChange={(e) => setEndAfter(e.target.value.replace(/\D/g, '').slice(0, 3))} />
              )}
              {endMode === 'on' && (
                <input type="date" value={endOn} onChange={(e) => setEndOn(e.target.value)} aria-label="Last date"
                  className="block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink" />
              )}
            </>
          )}
          {kind === 'subscription' && (
            <TextField label="Remind me this many days before" value={reminder} inputMode="numeric"
              onChange={(e) => setReminder(e.target.value.replace(/\D/g, '').slice(0, 2))} hint="Shown on Home when you open the app — never a push." />
          )}
        </div>

        {preview && preview.length > 0 && (
          <div>
            <p className="mb-1.5 text-footnote font-semibold text-ink-2">Next {preview.length}</p>
            <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2 px-3">
              {preview.map((o) => (
                <li key={o.on} className="num flex min-h-10 items-center justify-between text-footnote">
                  <span className="text-ink-2">
                    {longDay(o.on)}
                    {o.final && ' · last'}
                  </span>
                  <span className="font-semibold">{formatPHP(o.amount)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* SUB-07 - cancel, resume, and "remind me to cancel by". */}
        {rule && kind === 'subscription' && <SubscriptionControls rule={rule} onDone={onClose} />}

        {error && <p className="text-footnote text-danger">{error}</p>}

        {confirmingPayoff && plan ? (
          <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 p-4">
            <p className="text-body">
              Record <span className="num font-semibold">{formatPHP(plan.remaining)}</span> paid today and close the plan?
            </p>
            <Button block onClick={() => void run(() => payOff(rule.id))} disabled={busy}>Pay it off</Button>
            <Button variant="ghost" block onClick={() => setConfirmingPayoff(false)} disabled={busy}>Not now</Button>
          </div>
        ) : (
          <>
            <Button block size="lg" onClick={() => void save()} disabled={busy || problem !== null}>
              {problem ?? (rule ? 'Save changes' : trying ? 'See what it does' : 'Save')}
            </Button>
            {rule && (
              <div className="grid grid-cols-2 gap-2">
                {/* SUB-07. A cancelled subscription has nothing to pause or skip - Resume lives above, in its own words. */}
                {kind !== 'installment' && !rule.cancelled_on && (
                  <Button variant="secondary" disabled={busy} onClick={() => void run(() => pauseRule(rule.id, !rule.paused))}>
                    {rule.paused ? 'Resume' : 'Pause'}
                  </Button>
                )}
                {rule.next_on && !rule.cancelled_on && (
                  <Button variant="secondary" disabled={busy} onClick={() => void run(() => skipOccurrence(rule.id, rule.next_on as string))}>
                    Skip {format(parseISO(rule.next_on), 'd MMM')}
                  </Button>
                )}
                {plan && !plan.closed && (
                  <Button variant="secondary" disabled={busy} onClick={() => setConfirmingPayoff(true)}>Pay off</Button>
                )}
                <Button variant="ghost" className="text-danger" disabled={busy} onClick={() => void run(() => deleteRule(rule.id))}>
                  Delete
                </Button>
              </div>
            )}
            {rule?.from_transaction && (
              // REC-34. Made from a purchase: it can go back to being that one purchase.
              <div className="space-y-2">
                {rule.receipt_id && (
                  <ReceiptControl transactionId={rule.from_transaction} attachmentId={rule.receipt_id} readOnly />
                )}
                <Button variant="secondary" block disabled={busy} onClick={() => void run(() => revertInstallment(rule.id))}>
                  Convert back to one purchase
                </Button>
                <p className="text-center text-footnote text-ink-3">
                  Removes this plan and the payments it recorded, and brings the purchase back as it was.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
