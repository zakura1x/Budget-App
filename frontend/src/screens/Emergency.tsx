/**
 * Emergency fund (GOA-10, GOA-11).
 *
 * How long your emergency money lasts - the emergency fund goal's money if you
 * have one, otherwise cash on hand (the user's decision, 2026-09-28) - over
 * ESSENTIAL monthly spending: essential categories (by name until switched,
 * under Categories) and everything a repeating rule posts.
 *
 * What it should be comes from rules, not a model: nothing leaves the
 * encryption boundary, and every rule that fired is listed with its reason.
 * The user approved the table on 2026-09-28 (app/core/utils/emergency.py).
 * Three questions shape it; the answers are encrypted preferences.
 *
 * It suggests: "Make it the target" changes the goal only when tapped. A guide,
 * not financial advice.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoalSheet } from '../components/GoalSheets';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { ApiError } from '../lib/api';
import { afterWrite } from '../lib/invalidate';
import { formatPHP } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { getEmergency, updateGoal, type EmergencyAdvice, type GoalDraft } from '../lib/security';
import { usePreferencesStore } from '../stores/preferencesStore';

type Work = EmergencyAdvice['work'];
type Dependents = EmergencyAdvice['dependents'];
type Earners = EmergencyAdvice['earners'];

function tone(advice: EmergencyAdvice): string {
  if (!advice.measurable) return 'text-ink';
  const months = Number(advice.cover_months);
  if (months >= advice.target_months) return 'text-ok';
  return months * 2 >= advice.target_months ? 'text-warn' : 'text-danger';
}

export function Emergency() {
  const navigate = useNavigate();
  const change = usePreferencesStore((s) => s.change);
  const [preset, setPreset] = useState<Partial<GoalDraft> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const { data: advice, error: loadError } = useQuery({
    queryKey: keys.emergency(),
    queryFn: ({ signal }) => getEmergency(signal),
    staleTime: STALE.derived,
  });

  const answer = async (changes: { safety_work?: Work; safety_dependents?: Dependents; safety_earners?: Earners }) => {
    setError(null);
    try {
      await change(changes);
      afterWrite('goals', 'preferences'); // the advice reads the answers
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
    }
  };

  const makeTarget = async () => {
    if (!advice) return;
    if (advice.goal_id === null) {
      setPreset({ name: 'Emergency fund', target: advice.target, kind: 'emergency' });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateGoal(advice.goal_id, { target: advice.target });
      afterWrite('goals', 'accounts');
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save.');
    }
    setBusy(false);
  };

  return (
    <>
      <ScreenHeader
        title="Emergency fund"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />
      {(loadError || error) && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error ?? (loadError as Error).message}
        </p>
      )}
      {!advice && !loadError && <div className="skeleton h-72 rounded-card" aria-hidden="true" />}

      {advice && (
        <div className="space-y-4">
          <Card className="space-y-2">
            <p className="text-footnote text-ink-2">Your emergency money lasts</p>
            <p className={`num text-display ${tone(advice)}`}>
              {advice.measurable ? `${advice.cover_months} months` : '—'}
            </p>
            <p className="text-footnote text-ink-2">
              <span className="num font-semibold text-ink">{formatPHP(advice.money)}</span>
              {advice.source === 'goal' ? ' set aside in your emergency fund goal' : ' — all of cash on hand, as there is no emergency fund goal yet'}
              {' · '}essentials of <span className="num">{formatPHP(advice.essentials.monthly)}</span> a month
            </p>
            {advice.essentials.guessing && (
              <p className="text-caption text-ink-3">
                No category is marked essential yet, so this guesses 70% of your spending.{' '}
                <button type="button" className="font-semibold text-accent-ink" onClick={() => navigate('/categories')}>
                  Mark them under Categories
                </button>
              </p>
            )}
          </Card>

          <Card className="space-y-4">
            <p className="text-body font-semibold">
              {advice.answered ? 'About you' : 'Three questions first — they change the answer'}
            </p>
            <div className="space-y-1.5">
              <p className="text-footnote text-ink-2">Your work</p>
              <Segmented<Work> label="Your work" compact value={advice.work} onChange={(v) => void answer({ safety_work: v })}
                options={[{ value: 'employee', label: 'Employee' }, { value: 'contract', label: 'Contract' }, { value: 'self', label: 'Self-employed' }]} />
            </div>
            <div className="space-y-1.5">
              <p className="text-footnote text-ink-2">People who depend on you</p>
              <Segmented<Dependents> label="Dependents" compact value={advice.dependents} onChange={(v) => void answer({ safety_dependents: v })}
                options={[{ value: '0', label: 'None' }, { value: '1-2', label: '1–2' }, { value: '3+', label: '3 or more' }]} />
            </div>
            <div className="space-y-1.5">
              <p className="text-footnote text-ink-2">Earners at home</p>
              <Segmented<Earners> label="Earners" compact value={advice.earners} onChange={(v) => void answer({ safety_earners: v })}
                options={[{ value: '1', label: 'Just me' }, { value: '2+', label: 'Two or more' }]} />
            </div>
          </Card>

          <Card className="space-y-3">
            <p className="text-footnote text-ink-2">Aim for</p>
            <p className="num text-title">
              {advice.target_months} months — {formatPHP(advice.target)}
            </p>
            {advice.per_month !== '0.00' ? (
              <p className="text-footnote text-ink-2">
                <span className="num font-semibold text-ink">{formatPHP(advice.per_month)}</span> a month reaches it in 12 months.
              </p>
            ) : (
              advice.measurable && <p className="text-footnote font-semibold text-ok">You are there.</p>
            )}
            <SectionTitle>Why</SectionTitle>
            <ul className="-mt-1 divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2">
              {advice.fired.map((rule) => (
                <li key={rule.code} className="flex items-baseline justify-between gap-3 px-3 py-2 text-footnote">
                  <span>{rule.text}</span>
                  <span className="num shrink-0 font-semibold">
                    {rule.code === 'base' ? `${rule.months} months` : `${rule.months > 0 ? '+' : ''}${rule.months}`}
                  </span>
                </li>
              ))}
            </ul>
            {advice.short_history && (
              <p className="text-caption text-ink-3">
                Fewer than 3 months of income recorded, so only the starting point applies for now.
              </p>
            )}
            <Button block onClick={() => void makeTarget()} disabled={busy || advice.target === '0.00'}>
              {advice.goal_id === null ? 'Start an emergency fund goal' : `Make ${formatPHP(advice.target)} its target`}
            </Button>
            {saved && <p className="text-footnote text-ok">Saved as your emergency fund's target.</p>}
          </Card>

          <p className="px-1 text-footnote text-ink-3">
            A guide worked out from your own figures by fixed rules — not financial advice. Nothing changes unless you tap.
          </p>
        </div>
      )}

      <GoalSheet open={preset !== null} goal={null} preset={preset} onClose={() => setPreset(null)} />
    </>
  );
}
