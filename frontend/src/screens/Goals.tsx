/**
 * Savings goals (GOA-01..09).
 *
 * A goal holds money SET ASIDE inside its account (GOA-08): nothing moves, the
 * balance still matches the bank, and what is set aside comes off what is
 * available to spend. A goal is a saving, a SINKING FUND for a cost that comes
 * back, or the emergency fund (Phase 13).
 *
 * Bills that come ONCE A YEAR with no sinking fund following them are offered
 * below (GOA-09): "Set aside for it" opens a sinking fund that follows the bill,
 * so its amount and due date come from the bill's next occurrence.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoalCard, GoalMoneySheet, GoalSheet } from '../components/GoalSheets';
import { PlusIcon } from '../components/Icons';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { useLookups } from '../hooks/useLookups';
import { formatPHP } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { getYearlyBills, listGoals, type Goal, type GoalDraft } from '../lib/security';

export function Goals() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const [editing, setEditing] = useState<{ open: boolean; goal: Goal | null; preset: Partial<GoalDraft> | null }>({
    open: false, goal: null, preset: null,
  });
  const [goalMoney, setGoalMoney] = useState<{ goal: Goal; mode: 'add' | 'use' } | null>(null);

  const { data: goals, error } = useQuery({
    queryKey: keys.goals(),
    queryFn: ({ signal }) => listGoals(signal),
    staleTime: STALE.lookups,
  });
  const { data: bills = [] } = useQuery({
    queryKey: keys.yearlyBills(),
    queryFn: ({ signal }) => getYearlyBills(signal),
    staleTime: STALE.derived,
  });

  return (
    <>
      <ScreenHeader
        title="Savings goals"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
        action={<Button onClick={() => setEditing({ open: true, goal: null, preset: null })} aria-label="Add goal"><PlusIcon size={20} />Add</Button>}
      />
      {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error.message}</p>}
      {goals === undefined && !error && <div className="skeleton h-40 rounded-card" aria-hidden="true" />}
      {goals && goals.length === 0 && (
        <Card className="text-center">
          <p className="text-body">No goals yet.</p>
          <p className="mx-auto mt-1 max-w-xs text-footnote text-ink-2">
            An emergency fund, a laptop, a trip — or a sinking fund for a bill that comes once a year. The money is set
            aside inside an account you choose.
          </p>
          <Button className="mt-4" onClick={() => setEditing({ open: true, goal: null, preset: null })}>Add a goal</Button>
        </Card>
      )}
      <div className="space-y-3">
        {(goals ?? []).map((g) => (
          <GoalCard key={g.id} goal={g} accountName={lookups.accountById.get(g.account_id)?.name}
            onEdit={() => setEditing({ open: true, goal: g, preset: null })} onAdd={() => setGoalMoney({ goal: g, mode: 'add' })}
            onUse={() => setGoalMoney({ goal: g, mode: 'use' })} />
        ))}
      </div>

      {bills.length > 0 && (
        <>
          <SectionTitle>Bills that come once a year</SectionTitle>
          <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {bills.map((bill) => (
              <div key={bill.rule_id} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">{bill.name}</span>
                  <span className="num block text-footnote text-ink-2">
                    {formatPHP(bill.amount)} · due {format(parseISO(bill.on), 'd MMM yyyy')}
                  </span>
                </span>
                <Button variant="secondary" onClick={() => setEditing({
                  open: true, goal: null,
                  preset: { name: bill.name, target: bill.amount, target_date: bill.on, kind: 'sinking', rule_id: bill.rule_id },
                })}>
                  Set aside for it
                </Button>
              </div>
            ))}
          </div>
          <p className="px-1 pt-2 text-footnote text-ink-3">
            A sinking fund puts a little by each month, so a once-a-year bill is never a surprise.
          </p>
        </>
      )}

      {/* The sheets call afterWrite themselves, which refreshes this list. */}
      <GoalSheet open={editing.open} goal={editing.goal} preset={editing.preset}
        onClose={() => setEditing({ open: false, goal: null, preset: null })} />
      <GoalMoneySheet goal={goalMoney?.goal ?? null} mode={goalMoney?.mode ?? 'add'} onClose={() => setGoalMoney(null)} />
    </>
  );
}
