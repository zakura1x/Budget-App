/**
 * Savings goals' card and sheets (GOA-01..08), shared by the Goals screen, the
 * Accounts tab and an account's own page.
 *
 * Since 2026-09-16 a goal holds money SET ASIDE inside its account (GOA-08).
 * "Add money" earmarks part of the balance and "Use it" releases it; nothing
 * moves, so the balance still matches the bank, while what is set aside comes
 * off what the account has available and off cash on hand. Several goals can
 * share one account, each claiming only its own part.
 */
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { centavos, formatPHP, toDecimalString } from '../lib/money';
import { addToGoal, createGoal, deleteGoal, releaseFromGoal, updateGoal, type Goal } from '../lib/security';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { MoneyField } from './ui/MoneyField';
import { Sheet } from './ui/Sheet';
import { TextField } from './ui/TextField';

const HOLDS_MONEY = ['cash', 'debit', 'savings'];
const typed = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);
const valid = (value: string) => {
  try {
    return centavos(toDecimalString(value || '0')) > 0;
  } catch {
    return false;
  }
};
/** Everything that shows a balance or cash on hand reloads on the ledger's version. */
const refreshEverything = () => useLedgerStore.setState((s) => ({ version: s.version + 1 }));

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={`min-h-tap shrink-0 rounded-xl px-3 text-footnote font-medium transition ${selected ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2'}`}>
      {children}
    </button>
  );
}

export function GoalSheet({ goal, open, onClose, onSaved }: {
  goal: Goal | null; open: boolean; goals?: Goal[]; onClose: () => void; onSaved?: () => void;
}) {
  const lookups = useLookups();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [date, setDate] = useState('');
  const [accountId, setAccountId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setName(goal?.name ?? '');
    setTarget(goal ? typed(goal.target) : '');
    setDate(goal?.target_date ?? '');
    setAccountId(goal?.account_id ?? null);
    setError(null);
    setBusy(false);
  }, [open, goal]);

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
        <TextField label="Name" value={name} maxLength={60} placeholder="Emergency fund" onChange={(e) => setName(e.target.value)} />
        <MoneyField label="Target" value={target} placeholder="30000" onChange={setTarget} />
        <label className="block text-footnote font-semibold text-ink-2">
          By (optional)
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="mt-1.5 block min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-body font-normal text-ink" />
        </label>
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
            const body = { name: name.trim(), target: toDecimalString(target), target_date: date || null, account_id: accountId as number };
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
  return (
    <Card>
      <button type="button" onClick={onEdit} className="block w-full text-left">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-headline">{goal.name}</span>
          {goal.reached && <span className="shrink-0 text-caption font-semibold text-ok">Reached</span>}
        </div>
        <p className={`num mt-1 ${compact ? 'text-body font-semibold' : 'text-title'}`}>
          {formatPHP(goal.saved)} <span className="text-footnote font-normal text-ink-2">of {formatPHP(goal.target)}</span>
        </p>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
          <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(Number(goal.ratio), 1) * 100}%` }} />
        </div>
        <p className="mt-1.5 text-footnote text-ink-3">
          Set aside in {accountName ?? 'the account'}
          {!goal.reached && ` · ${formatPHP(goal.remaining)} to go`}
          {goal.target_date && ` · by ${format(parseISO(goal.target_date), 'd MMM yyyy')}`}
        </p>
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
