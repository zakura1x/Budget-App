/**
 * Settings - Phase 5 opens the budget behaviour: carry-over (BUD-11), the
 * allowance mode (BUD-07/08) and the pace alert (BUD-15). The rest of Settings
 * arrives in Phase 8b.
 *
 * Carry-over gets a sentence of explanation, not just a label - "carry over"
 * does not say that an overspend follows you too (FEATURES.md §13-B).
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Toggle } from '../components/ui/Toggle';
import { ApiError } from '../lib/api';
import { getPreferences, updatePreferences, type AllowanceMode, type Preferences } from '../lib/budgets';
import { useBudgetStore } from '../stores/budgetStore';

export function Settings() {
  const navigate = useNavigate();
  const reloadBudget = useBudgetStore((s) => s.load);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getPreferences(controller.signal)
      .then(setPrefs)
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
  }, []);

  const change = async (changes: Partial<Preferences>) => {
    if (!prefs) return;
    const previous = prefs;
    setPrefs({ ...prefs, ...changes }); // the switch moves at once; the server confirms
    setError(null);
    try {
      setPrefs(await updatePreferences(changes));
      void reloadBudget(null);
    } catch (e) {
      setPrefs(previous);
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
  };

  return (
    <>
      <ScreenHeader
        title="Settings"
        subtitle={<button type="button" className="text-accent" onClick={() => navigate('/more')}>‹ More</button>}
      />

      {!prefs && !error && <div className="skeleton h-64 rounded-card" aria-hidden="true" />}
      {error && <p className="mb-3 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      {prefs && (
        <>
          <SectionTitle>Budget</SectionTitle>
          <Card className="space-y-4">
            <Toggle
              checked={prefs.carry_over}
              onChange={(value) => void change({ carry_over: value })}
              label="Carry over to the next period"
              hint="What you don't spend is added to next period — and if you overspend, that comes off it. Off, every period starts fresh."
            />
            <div className="border-t border-line pt-4">
              <p className="mb-2 text-body">Daily allowance</p>
              <Segmented<AllowanceMode>
                label="Daily allowance"
                value={prefs.daily_allowance_mode}
                onChange={(value) => void change({ daily_allowance_mode: value })}
                options={[
                  { value: 'remaining_over_days_left', label: 'Spread what’s left' },
                  { value: 'fixed_daily', label: 'Same every day' },
                ]}
              />
              <p className="mt-2 text-footnote text-ink-2">
                {prefs.daily_allowance_mode === 'fixed_daily'
                  ? 'The period’s budget divided by its days, the same figure every day.'
                  : 'What is left, divided by the days left. Overspend today and tomorrow’s figure drops to make up for it.'}
              </p>
            </div>
          </Card>

          <SectionTitle>Alerts</SectionTitle>
          <Card>
            <Toggle
              checked={prefs.alert_pace_enabled}
              onChange={(value) => void change({ alert_pace_enabled: value })}
              label="Warn when spending runs ahead"
              hint={`Shown when you have used more of the budget than of the period — while there is still time to slow down. Over-budget warnings start at ${prefs.alert_warn_threshold_pct}%.`}
            />
          </Card>
          <p className="px-1 pt-2 text-footnote text-ink-3">
            Alerts appear in the app when you open it. Nothing is sent to your phone — that would mean decrypting your
            budget while you are not signed in.
          </p>
        </>
      )}
    </>
  );
}
