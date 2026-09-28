/**
 * Savings goals' card and sheets (GOA-01..08), shared by the Goals screen, the
 * Accounts tab and an account's own page.
 *
 * Since 2026-09-16 a goal holds money SET ASIDE inside its account (GOA-08).
 * "Add money" earmarks part of the balance and "Use it" releases it; nothing
 * moves, so the balance still matches the bank, while what is set aside comes
 * off what the account has available and off cash on hand. Several goals can
 * share one account, each claiming only its own part.
 *
 * Phase 13 (2026-09-28): a goal has a KIND. A sinking fund (GOA-09) puts money
 * by for a cost that comes back - it can repeat every year, or follow a yearly
 * bill whose next occurrence sets its amount and date. The emergency fund
 * (GOA-10) is the one goal the emergency cover reads. Every card shows this
 * month's part: what the month asks for, and what is set aside in it already.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { afterWrite } from '../lib/invalidate';
import { centavos, formatPHP, toDecimalString } from '../lib/money';
import {
  addToGoal,
  createGoal,
  deleteGoal,
  releaseFromGoal,
  updateGoal,
  type Goal,
  type GoalDraft,
  type GoalKind,
} from '../lib/security';
import { localToday } from '../lib/transactions';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { MoneyField } from './ui/MoneyField';
import { Segmented } from './ui/Segmented';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';
import { Toggle } from './ui/Toggle';

export const KIND_LABEL: Record<GoalKind, string> = {
  saving: 'Saving',
  sinking: 'Sinking fund',
  emergency: 'Emergency fund',
};

const HOLDS_MONEY = ['cash', 'debit', 'savings'];
const typed = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);
const valid = (value: string) => {
  try {
    return centavos(toDecimalString(value || '0')) > 0;
  } catch {
    return false;
  }
};
/**
 * GOA-08. A goal writes no transaction - it only sets money aside inside its
 * account - so the ledger and the allowance are untouched; what moves is every
 * balance, `available` and cash on hand.
 */
const refreshEverything = () => afterWrite('accounts', 'goals');

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={`min-h-tap shrink-0 rounded-xl px-3 text-footnote font-medium transition ${selected ? 'bg-accent text-on-accent shadow-edge' : 'bg-surface text-ink-2 shadow-edge active:bg-surface-2'}`}>
      {children}
    </button>
  );
}

export function GoalSheet({ goal, open, onClose, onSaved, preset }: {
  goal: Goal | null; open: boolean; goals?: Goal[]; onClose: () => void; onSaved?: () => void;
  /** A NEW goal set up by the screen that opened it - a sinking fund for a yearly bill, the emergency fund's target. */
  preset?: Partial<GoalDraft> | null;
}) {
  const lookups = useLookups();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [date, setDate] = useState('');
  const [accountId, setAccountId] = useState<number | null>(null);
  const [kind, setKind] = useState<GoalKind>('saving');
  const [repeats, setRepeats] = useState(false);
  const [ruleId, setRuleId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    const start = goal ?? preset;
    setName(start?.name ?? '');
    setTarget(start?.target ? typed(start.target) : '');
    setDate(start?.target_date ?? '');
    setAccountId(start?.account_id ?? null);
    setKind(start?.kind ?? 'saving');
    setRepeats(Boolean(start?.repeats_yearly));
    setRuleId(start?.rule_id ?? null);
    setError(null);
    setBusy(false);
  }, [open, goal, preset]);
  // GOA-09. Following a bill, its next occurrence IS the amount and the date - there is nothing to type.
  const following = kind === 'sinking' && ruleId !== null;

  // GOA-08: several goals may share an account, so every account that holds money is a choice.
  const choices = lookups.accounts.filter((a) => HOLDS_MONEY.includes(a.type) && (!a.archived || a.id === goal?.account_id));
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      refreshEverything();
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
      setBusy(false);
    }
  };
  const account = lookups.accountById.get(goal?.account_id ?? -1);

  return (
    <Sheet open={open} onClose={onClose} title={goal ? 'Edit goal' : 'New goal'}>
      <div className="space-y-4 pb-2">
        <Segmented<GoalKind>
          label="Kind of goal"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'saving', label: 'Saving' },
            { value: 'sinking', label: 'Sinking fund' },
            { value: 'emergency', label: 'Emergency' },
          ]}
        />
        <p className="-mt-2 text-footnote text-ink-3">
          {kind === 'sinking'
            ? 'Money put by for a cost that comes back — insurance, registration, school fees, Christmas.'
            : kind === 'emergency'
              ? 'Money for when something goes wrong. Its cover shows under More → Emergency fund; there is one.'
              : 'Something you are saving up for — a laptop, a trip.'}
        </p>
        <TextField label="Name" value={name} maxLength={60} placeholder={kind === 'sinking' ? 'Car insurance' : 'Emergency fund'}
          onChange={(e) => setName(e.target.value)} />
        {following ? (
          <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
            <p className="text-footnote text-ink-2">
              Follows a yearly bill: <span className="num font-semibold text-ink">{formatPHP(toDecimalString(target || '0'))}</span>
              {date && <> due <span className="num">{format(parseISO(date), 'd MMM yyyy')}</span></>} — its amount and date
              come from the bill, and move on with it each year.
            </p>
            <Button variant="secondary" onClick={() => setRuleId(0)}>Stop following it</Button>
          </div>
        ) : (
          <>
            <MoneyField label="Target" value={target} placeholder="30000" onChange={setTarget} />
            <label className="block text-footnote font-semibold text-ink-2">
              {kind === 'sinking' ? 'Due' : 'By (optional)'}
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
            </label>
            {kind === 'sinking' && (
              <Toggle checked={repeats} onChange={setRepeats} label="Every year"
                hint="Once the date has passed, it moves on a year — the fund starts again for next time." />
            )}
          </>
        )}
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Saved in</p>
          <div className="flex flex-wrap gap-2">
            {choices.map((a) => <Chip key={a.id} selected={accountId === a.id} onClick={() => setAccountId(a.id)}>{a.name}</Chip>)}
          </div>
          {choices.length === 0 && (
            <p className="text-footnote text-ink-2">Add a savings, debit or cash account first, under Accounts.</p>
          )}
          <p className="mt-2 text-footnote text-ink-3">
            Money you add is set aside inside this account: its balance stays the same as your bank shows, and what is
            available to spend goes down.
          </p>
        </div>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button block size="lg" disabled={busy || !name.trim() || !valid(target) || accountId === null}
          onClick={() => void run(() => {
            const body: GoalDraft = {
              name: name.trim(), target: toDecimalString(target), target_date: date || null, account_id: accountId as number,
              kind, repeats_yearly: kind === 'sinking' && repeats,
              ...(kind === 'sinking' && ruleId !== null ? { rule_id: ruleId } : goal?.rule_id ? { rule_id: 0 } : {}),
            };
            return goal ? updateGoal(goal.id, body) : createGoal(body);
          })}>
          {goal ? 'Save changes' : 'Add goal'}
        </Button>
        {goal && (
          <Button variant="ghost" block className="text-danger" disabled={busy} onClick={() => void run(() => deleteGoal(goal.id))}>
            Delete goal — what it set aside in {account?.name ?? 'the account'} becomes available again
          </Button>
        )}
      </div>
    </Sheet>
  );
}

/**
 * GOA-08. Add money to a goal (set it aside) or use it (release it). One sheet,
 * two directions; the server checks the limits - what is still available in
 * the account, or what the goal holds - and says so in its own words.
 */
export function GoalMoneySheet({ goal, mode, onClose, onSaved }: {
  goal: Goal | null; mode: 'add' | 'use'; onClose: () => void; onSaved?: () => void;
}) {
  const lookups = useLookups();
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setAmount('');
    setNote('');
    setError(null);
    setBusy(false);
  }, [goal, mode]);
  if (!goal) return null;
  const account = lookups.accountById.get(goal.account_id)?.name ?? 'the account';
  const adding = mode === 'add';

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { amount: toDecimalString(amount), on: localToday(), note: note.trim() || null };
      await (adding ? addToGoal(goal.id, body) : releaseFromGoal(goal.id, body));
      refreshEverything();
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
      setBusy(false);
    }
  };

  return (
    <Sheet open onClose={onClose} title={adding ? `Add to ${goal.name}` : `Use from ${goal.name}`}>
      <div className="space-y-4 pb-2">
        <p className="text-footnote text-ink-2">
          {adding ? (
            <>Available in {account}: <span className="num font-semibold text-ink">{formatPHP(goal.account_available)}</span></>
          ) : (
            <>Set aside for this goal: <span className="num font-semibold text-ink">{formatPHP(goal.saved)}</span></>
          )}
        </p>
        <MoneyField label="Amount" value={amount} placeholder={adding ? '5000' : typed(goal.saved)} onChange={setAmount} />
        <TextField label="Note (optional)" value={note} maxLength={120}
          placeholder={adding ? 'Payday' : 'What it was for'} onChange={(e) => setNote(e.target.value)} />
        <p className="text-footnote text-ink-3">
          {adding
            ? `Nothing moves: ${account}'s balance stays ${formatPHP(goal.account_balance)}, the same as your bank shows. This comes off what is available to spend, and off cash on hand.`
            : `This money is available to spend again. If you bought something with it, record the purchase as usual.`}
        </p>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button block size="lg" disabled={busy || !valid(amount)} onClick={() => void run()}>
          {adding ? 'Set it aside' : 'Use it'}
        </Button>
      </div>
    </Sheet>
  );
}

/**
 * One goal at a glance: set aside of target, the bar, the account it lives in,
 * what is left and by when - and Add money / Use it. The card itself is the way
 * in (`onEdit`); `compact` only tightens it for a list.
 */
export function GoalCard({ goal, accountName, onEdit, onAdd, onUse, compact = false }: {
  goal: Goal;
  accountName?: string;
  onEdit: () => void;
  onAdd?: () => void;
  onUse?: () => void;
  compact?: boolean;
}) {
  // An older server sends no shortfall; that is not a shortfall.
  const short = (goal.short_by ?? '0.00') !== '0.00';
  const kind = goal.kind ?? 'saving';
  return (
    <Card>
      <button type="button" onClick={onEdit} className="block w-full text-left">
        {kind !== 'saving' && (
          <p className="label text-ink-2">
            {KIND_LABEL[kind]}
            {goal.rule_id ? ' · follows a yearly bill' : goal.repeats_yearly ? ' · every year' : ''}
          </p>
        )}
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-headline">{goal.name}</span>
          {goal.reached && <span className="shrink-0 text-caption font-semibold text-ok">Reached</span>}
        </div>
        <p className={`num mt-1 ${compact ? 'text-body font-semibold' : 'text-title'}`}>
          {formatPHP(goal.saved)} <span className="text-footnote font-normal text-ink-2">of {formatPHP(goal.target)}</span>
        </p>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2 shadow-edge" aria-hidden="true">
          <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(Number(goal.ratio), 1) * 100}%` }} />
        </div>
        <p className="mt-1.5 text-footnote text-ink-3">
          Set aside in {accountName ?? 'the account'}
          {!goal.reached && ` · ${formatPHP(goal.remaining)} to go`}
          {goal.target_date && ` · by ${format(parseISO(goal.target_date), 'd MMM yyyy')}`}
        </p>
        {/* GOA-05 - this month and the target's own both count; rounded up so the last month is never short. */}
        {goal.per_month && goal.months_left && (
          <p className="mt-1 text-footnote text-ink-2">
            <span className="num font-semibold text-ink">{formatPHP(goal.per_month)}</span>
            {goal.months_left === 1
              ? ' to set aside this month to be on time'
              : ` a month for ${goal.months_left} months to be on time`}
          </p>
        )}
        {goal.overdue && (
          <p className="mt-1 text-footnote text-ink-2">The target date has passed — move it, or keep adding when you can.</p>
        )}
        {/* GOA-09. This month's part, ticked off as it is set aside - worked out from where the month began. */}
        {goal.month_need && !goal.reached && (
          <p className="mt-1 text-footnote text-ink-2">
            This month: <span className="num font-semibold text-ink">{formatPHP(goal.month_added ?? '0.00')}</span> of{' '}
            <span className="num">{formatPHP(goal.month_need)}</span> set aside
            {goal.month_done && <span className="font-semibold text-ok"> ✓ done</span>}
          </p>
        )}
        {short && (
          <p className="mt-1 text-footnote font-semibold text-warn">
            {accountName ?? 'The account'} holds {formatPHP(goal.account_balance)} — {formatPHP(goal.short_by)} short of
            what its goals set aside.
          </p>
        )}
      </button>
      {(onAdd || onUse) && (
        <div className={`mt-3 grid gap-2 ${onUse && goal.saved !== '0.00' ? 'grid-cols-2' : 'grid-cols-1'}`}>
          {onAdd && <Button variant="secondary" onClick={onAdd}>Add money</Button>}
          {onUse && goal.saved !== '0.00' && (
            <Button variant="ghost" onClick={onUse}>Use it</Button>
          )}
        </div>
      )}
    </Card>
  );
}
