/**
 * Settings (UX-05, BUD-04/05/07/11/14/15, SEC-08/16/21..24).
 *
 *   Appearance    light, dark or the device's own
 *   Budget        carry-over, the allowance mode, and the defaults a new
 *                 budget starts from
 *   Alerts        the warning threshold, the pace warning
 *   Security      password, PIN, how soon the app locks, rotating the
 *                 encryption key
 *   Your data     backup & data, what is encrypted
 *   Delete        the whole account
 *
 * Carry-over keeps its sentence of explanation - "carry over" does not say that
 * an overspend follows you too (FEATURES.md §13-B). Key rotation says what it
 * cannot reach (§17).
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PalettePicker } from '../components/PalettePicker';
import { ScreenHeader } from '../components/ScreenHeader';
import { ChangePasswordSheet, ChangePinSheet, DeleteAccountSheet, RotateKeySheet } from '../components/SecuritySheets';
import { Card, SectionTitle } from '../components/ui/Card';
import { ListGroup, ListRow } from '../components/ui/ListRow';
import { Segmented } from '../components/ui/Segmented';
import { Toggle } from '../components/ui/Toggle';
import { ApiError } from '../lib/api';
import type { AllowanceMode, PeriodKind, Preferences, Theme } from '../lib/budgets';
import { afterWrite } from '../lib/invalidate';
import { formatPHP } from '../lib/money';
import { useAuthStore } from '../stores/authStore';
import { usePreferencesStore } from '../stores/preferencesStore';

const WEEKDAYS = [
  { value: 1, label: 'Monday' }, { value: 2, label: 'Tuesday' }, { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' }, { value: 5, label: 'Friday' }, { value: 6, label: 'Saturday' }, { value: 7, label: 'Sunday' },
] as const;
const LOCK_CHOICES = [1, 2, 5, 10, 15, 30];
/** BUD-17 - what a suggested budget rounds up to, in pesos (the server's STEPS). */
const ROUND_STEPS = [1, 10, 50, 100, 500, 1000];
/** GOA-12 - income of at least this many pesos offers to set some aside; 0 is off. */
const PAYDAY_CHOICES = [0, 1000, 2000, 5000, 10000, 20000, 50000];
/** The preferences that change a figure rather than how the app looks or locks. */
const MOVES_FIGURES = [
  'carry_over', 'daily_allowance_mode', 'alert_warn_threshold_pct',
  'alert_pace_enabled', 'budget_period', 'month_start_day', 'week_start_day',
  // BUD-17 - the suggestion and the reminder in the budget status
  'budget_round_step', 'budget_suggestion_nudge',
  // GOA-12 - whether Home asks to set money aside
  'payday_prompt_min',
] as const;

export function Settings() {
  const navigate = useNavigate();
  const { prefs, load, change: save } = usePreferencesStore();
  const serverLock = useAuthStore((s) => s.session?.auto_lock_minutes ?? 5);
  const pinSet = useAuthStore((s) => s.session?.pin_set ?? false);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<'password' | 'pin' | 'rotate' | 'delete' | null>(null);

  useEffect(() => {
    if (!prefs) void load();
  }, [prefs, load]);

  const change = async (changes: Partial<Preferences>) => {
    setError(null);
    try {
      await save(changes);
      // Only some preferences move a figure: the period's shape, what carries
      // over, how the daily allowance is worked out, when an alert fires. The
      // theme, the palette and the auto-lock do not, and must not send the app
      // off refetching. `afterWrite` forces the reload past the freshness check.
      if (MOVES_FIGURES.some((key) => key in changes)) afterWrite('budget', 'calendar', 'stats');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
  };

  const locks = LOCK_CHOICES.filter((m) => m <= serverLock);

  return (
    <>
      <ScreenHeader
        title="Settings"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />

      {!prefs && !error && <div className="skeleton h-64 rounded-card" aria-hidden="true" />}
      {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      {prefs && (
        <>
          <SectionTitle>Appearance</SectionTitle>
          <Card className="space-y-4">
            <PalettePicker value={prefs.palette ?? 'classic'} onChange={(value) => void change({ palette: value })} />
            <Segmented<Theme>
              label="Light or dark"
              value={prefs.theme ?? 'system'}
              onChange={(value) => void change({ theme: value })}
              options={[
                { value: 'system', label: 'Device' },
                { value: 'light', label: 'Light' },
                { value: 'dark', label: 'Dark' },
              ]}
            />
            <Toggle
              checked={prefs.haptics ?? true}
              onChange={(value) => void change({ haptics: value })}
              label="Vibrate on taps"
              hint="A short buzz on keys, saves and deletes. Android only - an iPhone does not let a web app vibrate."
            />
          </Card>

          <SectionTitle>Budget</SectionTitle>
          <Card className="space-y-4">
            <Toggle
              checked={prefs.carry_over}
              onChange={(value) => void change({ carry_over: value })}
              label="Carry over to the next period"
              hint="What you don't spend is added to next period — and if you overspend, that comes off it. Off, every period starts fresh."
            />
            <div className="border-t border-stroke/40 pt-4">
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
            <div className="space-y-3 border-t border-stroke/40 pt-4">
              <p className="text-body">A new budget starts as</p>
              <Segmented<PeriodKind>
                label="Budget period"
                value={prefs.budget_period}
                onChange={(value) => void change({ budget_period: value })}
                options={[
                  { value: 'monthly', label: 'Monthly' },
                  { value: 'weekly', label: 'Weekly' },
                ]}
              />
              <label className="flex items-center justify-between gap-3 text-body">
                <span>Month starts on day</span>
                <select
                  value={prefs.month_start_day}
                  onChange={(e) => void change({ month_start_day: Number(e.target.value) })}
                  className="num min-h-tap rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink"
                >
                  {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </label>
              <div>
                {/* A select, not seven buttons: seven do not fit a 390px row. */}
                <label className="flex items-center justify-between gap-3 text-body">
                  <span>Weeks start on</span>
                  <select
                    value={prefs.week_start_day}
                    onChange={(e) => void change({ week_start_day: Number(e.target.value) })}
                    className="min-h-tap rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink"
                  >
                    {WEEKDAYS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </label>
                <p className="mt-2 text-footnote text-ink-3">Also the first column of the calendar.</p>
              </div>
            </div>
            {/* BUD-17 (user, 2026-09-28): the suggested budget rounds up to this step, and the reminder can be turned off. */}
            <div className="space-y-3 border-t border-stroke/40 pt-4">
              <label className="flex items-center justify-between gap-3 text-body">
                <span>Round suggestions up to</span>
                <select
                  value={Number(prefs.budget_round_step ?? 100)}
                  onChange={(e) => void change({ budget_round_step: Number(e.target.value) })}
                  className="num min-h-tap rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink"
                >
                  {ROUND_STEPS.map((step) => <option key={step} value={step}>{formatPHP(`${step}.00`).replace('.00', '')}</option>)}
                </select>
              </label>
              <label className="flex items-center justify-between gap-3 text-body">
                <span>Offer to set money aside when income is at least</span>
                <select
                  value={Number(prefs.payday_prompt_min ?? 5000)}
                  onChange={(e) => void change({ payday_prompt_min: Number(e.target.value) })}
                  className="num min-h-tap shrink-0 rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink"
                >
                  {PAYDAY_CHOICES.map((v) => <option key={v} value={v}>{v === 0 ? 'Never' : formatPHP(`${v}.00`).replace('.00', '')}</option>)}
                </select>
              </label>
              <Toggle
                checked={prefs.budget_suggestion_nudge !== false}
                onChange={(value) => void change({ budget_suggestion_nudge: value })}
                label="Remind me when my spending changes"
                hint="In the first days of a period, if your recent spending is more than 15% away from your budget. It only opens a suggestion — nothing changes until you save."
              />
            </div>
          </Card>

          <SectionTitle>Alerts</SectionTitle>
          <Card className="space-y-4">
            <div>
              <p className="mb-2 text-body">Warn me when the budget is</p>
              <Segmented<'70' | '80' | '90'>
                label="Warning threshold"
                value={String(prefs.alert_warn_threshold_pct) as '70' | '80' | '90'}
                onChange={(value) => void change({ alert_warn_threshold_pct: Number(value) })}
                options={[
                  { value: '70', label: '70% used' },
                  { value: '80', label: '80% used' },
                  { value: '90', label: '90% used' },
                ]}
              />
            </div>
            <div className="border-t border-stroke/40 pt-3">
              <Toggle
                checked={prefs.alert_pace_enabled}
                onChange={(value) => void change({ alert_pace_enabled: value })}
                label="Warn when spending runs ahead"
                hint="When you have used more of the budget than of the period — while there is still time to slow down."
              />
            </div>
          </Card>
          <p className="px-1 pt-2 text-footnote text-ink-3">
            Alerts appear in the app when you open it. Nothing is sent to your phone — that would mean decrypting your
            budget while you are not signed in.
          </p>

          <SectionTitle>Security</SectionTitle>
          <ListGroup>
            <ListRow title="Change password" chevron onClick={() => setSheet('password')} />
            <ListRow title={pinSet ? 'Change PIN' : 'Set a PIN'} subtitle="Unlocks this device - never your data" chevron
              onClick={() => setSheet('pin')} />
            <ListRow title="Signed-in devices" subtitle="Sign-ins, other devices, Face ID and fingerprint" chevron
              onClick={() => navigate('/security')} />
          </ListGroup>
          <Card className="mt-3">
            <p className="mb-2 text-body">Lock after I stop using it for</p>
            <Segmented<string>
              label="Auto-lock"
              value={String(Math.min(prefs.auto_lock_minutes, serverLock))}
              onChange={(value) => void change({ auto_lock_minutes: Number(value) })}
              options={locks.map((m) => ({ value: String(m), label: `${m} min` }))}
            />
            <p className="mt-2 text-footnote text-ink-3">
              Locking empties your key from the server’s memory. {serverLock} minutes is this server’s limit.
            </p>
          </Card>
          <div className="mt-3">
            <ListGroup>
              <ListRow title="Rotate my encryption key" subtitle="Someone may have got hold of my key" chevron
                onClick={() => setSheet('rotate')} />
            </ListGroup>
          </div>

          <SectionTitle>Your data</SectionTitle>
          <ListGroup>
            <ListRow title="Backup & data" subtitle="Back up now, restore, export or import CSV" chevron onClick={() => navigate('/backup')} />
            <ListRow title="About your encryption" subtitle="What is protected, and what is not" chevron
              onClick={() => navigate('/about-encryption')} />
          </ListGroup>

          <SectionTitle>Account</SectionTitle>
          <ListGroup>
            <ListRow title={<span className="text-danger">Delete my account</span>} subtitle="Everything, permanently" chevron
              onClick={() => setSheet('delete')} />
          </ListGroup>
        </>
      )}

      <ChangePasswordSheet open={sheet === 'password'} onClose={() => setSheet(null)} />
      <ChangePinSheet open={sheet === 'pin'} onClose={() => setSheet(null)} />
      <DeleteAccountSheet open={sheet === 'delete'} onClose={() => setSheet(null)} />
      <RotateKeySheet open={sheet === 'rotate'} onClose={() => setSheet(null)} />
    </>
  );
}
