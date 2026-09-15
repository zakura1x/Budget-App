/**
 * Savings goals (GOA-01..07).
 *
 * A goal is a target on one account, and its progress is that account's
 * balance - so the goal and the account can never disagree. "Add money" makes a
 * real transfer from another account. One goal per account, in a cash, debit
 * or savings account; deleting a goal leaves the money where it is.
 */
import { format, parseISO } from 'date-fns';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Sheet } from '../components/ui/Sheet';
import { TextField } from '../components/ui/TextField';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { centavos, formatPHP, sanitizeAmount, toDecimalString } from '../lib/money';
import { contributeToGoal, createGoal, deleteGoal, listGoals, updateGoal, type Goal } from '../lib/security';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';

const HOLDS_MONEY = ['cash', 'debit', 'savings'];
const typed = (amount: string) => (amount.endsWith('.00') ? amount.slice(0, -3) : amount);
const valid = (value: string) => {
  try {
    return centavos(toDecimalString(value || '0')) > 0;
  } catch {
    return false;
  }
};

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={`min-h-tap shrink-0 rounded-xl px-3 text-footnote font-medium transition ${selected ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2'}`}>
      {children}
    </button>
  );
}

function GoalSheet({ goal, open, goals, onClose, onSaved }: { goal: Goal | null; open: boolean; goals: Goal[]; onClose: () => void; onSaved: () => void }) {
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

  const taken = new Set(goals.filter((g) => g.id !== goal?.id).map((g) => g.account_id));
  const choices = lookups.accounts.filter((a) => HOLDS_MONEY.includes(a.type) && !a.archived && !taken.has(a.id));
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onSaved();
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
        <TextField label="Target" value={target} inputMode="decimal" placeholder="30000" onChange={(e) => setTarget(sanitizeAmount(e.target.value))} />
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
            <p className="text-footnote text-ink-2">Add a savings, debit or cash account without a goal first, under More → Accounts.</p>
          )}
          <p className="mt-2 text-footnote text-ink-3">The goal’s progress is this account’s balance — one goal per account.</p>
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
            Delete goal — the money stays in {account?.name ?? 'the account'}
          </Button>
        )}
      </div>
    </Sheet>
  );
}

function AddMoneySheet({ goal, onClose, onSaved }: { goal: Goal | null; onClose: () => void; onSaved: () => void }) {
  const lookups = useLookups();
  const applyOutcome = useLedgerStore((s) => s.applyOutcome);
  const [amount, setAmount] = useState('');
  const [from, setFrom] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setAmount('');
    setFrom(null);
    setError(null);
    setBusy(false);
  }, [goal]);
  if (!goal) return null;
  const sources = lookups.accounts.filter((a) => a.id !== goal.account_id && !a.archived && a.type !== 'investment');
  const into = lookups.accountById.get(goal.account_id);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      applyOutcome(await contributeToGoal(goal.id, { amount: toDecimalString(amount), from_account_id: from as number, txn_date: localToday() }));
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
      setBusy(false);
    }
  };

  return (
    <Sheet open onClose={onClose} title={`Add to ${goal.name}`}>
      <div className="space-y-4 pb-2">
        <TextField label="Amount" value={amount} inputMode="decimal" placeholder="5000" onChange={(e) => setAmount(sanitizeAmount(e.target.value))} />
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">From</p>
          <div className="flex flex-wrap gap-2">
            {sources.map((a) => <Chip key={a.id} selected={from === a.id} onClick={() => setFrom(a.id)}>{a.name}</Chip>)}
          </div>
        </div>
        <p className="text-footnote text-ink-3">A real transfer into {into?.name ?? 'the goal’s account'} — you’ll see it in the ledger, and your budget is not touched.</p>
        {error && <p className="text-footnote text-danger">{error}</p>}
        <Button block size="lg" disabled={busy || !valid(amount) || from === null} onClick={() => void run()}>Move the money</Button>
      </div>
    </Sheet>
  );
}

export function Goals() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const version = useLedgerStore((s) => s.version);
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ open: boolean; goal: Goal | null }>({ open: false, goal: null });
  const [adding, setAdding] = useState<Goal | null>(null);

  const load = useCallback((signal?: AbortSignal) =>
    listGoals(signal).then((found) => { setGoals(found); setError(null); })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message)), []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, version]);

  return (
    <>
      <ScreenHeader
        title="Savings goals"
        subtitle={<button type="button" className="text-accent" onClick={() => navigate('/more')}>‹ More</button>}
        action={<Button onClick={() => setEditing({ open: true, goal: null })} aria-label="Add goal"><PlusIcon size={20} />Add</Button>}
      />
      {error && <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}
      {goals === null && !error && <div className="skeleton h-40 rounded-card" aria-hidden="true" />}
      {goals && goals.length === 0 && (
        <Card className="text-center">
          <p className="text-body">No goals yet.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            An emergency fund, a laptop, a trip. Pick the account the money sits in; the goal follows its balance.
          </p>
          <Button className="mt-4" onClick={() => setEditing({ open: true, goal: null })}>Add a goal</Button>
        </Card>
      )}
      <div className="space-y-3">
        {(goals ?? []).map((g) => {
          const account = lookups.accountById.get(g.account_id);
          return (
            <Card key={g.id}>
              <button type="button" onClick={() => setEditing({ open: true, goal: g })} className="block w-full text-left">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-headline">{g.name}</span>
                  {g.reached && <span className="shrink-0 text-caption font-semibold text-ok">Reached</span>}
                </div>
                <p className="num mt-1 text-title">
                  {formatPHP(g.saved)} <span className="text-footnote font-normal text-ink-2">of {formatPHP(g.target)}</span>
                </p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(Number(g.ratio), 1) * 100}%` }} />
                </div>
                <p className="mt-1.5 text-footnote text-ink-3">
                  {account?.name ?? 'Account'}
                  {!g.reached && ` · ${formatPHP(g.remaining)} to go`}
                  {g.target_date && ` · by ${format(parseISO(g.target_date), 'd MMM yyyy')}`}
                </p>
              </button>
              <Button className="mt-3" variant="secondary" block onClick={() => setAdding(g)}>Add money</Button>
            </Card>
          );
        })}
      </div>
      <GoalSheet open={editing.open} goal={editing.goal} goals={goals ?? []} onClose={() => setEditing({ open: false, goal: null })} onSaved={() => void load()} />
      <AddMoneySheet goal={adding} onClose={() => setAdding(null)} onSaved={() => void load()} />
    </>
  );
}
