/**
 * Savings goals (GOA-01..07).
 *
 * A goal is a target on one account, and its progress is that account's
 * balance - so the goal and the account can never disagree. "Add money" makes a
 * real transfer from another account. One goal per account, in a cash, debit
 * or savings account; deleting a goal leaves the money where it is.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoalCard, GoalMoneySheet, GoalSheet } from '../components/GoalSheets';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { useLookups } from '../hooks/useLookups';
import { keys, STALE } from '../lib/queryKeys';
import { listGoals, type Goal } from '../lib/security';

export function Goals() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const [editing, setEditing] = useState<{ open: boolean; goal: Goal | null }>({ open: false, goal: null });
  const [goalMoney, setGoalMoney] = useState<{ goal: Goal; mode: 'add' | 'use' } | null>(null);

  const { data: goals, error } = useQuery({
    queryKey: keys.goals(),
    queryFn: ({ signal }) => listGoals(signal),
    staleTime: STALE.lookups,
  });

  return (
    <>
      <ScreenHeader
        title="Savings goals"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
        action={<Button onClick={() => setEditing({ open: true, goal: null })} aria-label="Add goal"><PlusIcon size={20} />Add</Button>}
      />
      {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>}
      {goals === undefined && !error && <div className="skeleton h-40 rounded-card" aria-hidden="true" />}
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
        {(goals ?? []).map((g) => (
          <GoalCard key={g.id} goal={g} accountName={lookups.accountById.get(g.account_id)?.name}
            onEdit={() => setEditing({ open: true, goal: g })} onAdd={() => setGoalMoney({ goal: g, mode: 'add' })}
            onUse={() => setGoalMoney({ goal: g, mode: 'use' })} />
        ))}
      </div>
      {/* The sheets call afterWrite themselves, which refreshes this list. */}
      <GoalSheet open={editing.open} goal={editing.goal} onClose={() => setEditing({ open: false, goal: null })} />
      <GoalMoneySheet goal={goalMoney?.goal ?? null} mode={goalMoney?.mode ?? 'add'} onClose={() => setGoalMoney(null)} />
    </>
  );
}
