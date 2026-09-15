/**
 * Budget management (BUD-01..BUD-13).
 *
 * One budget: a rhythm (monthly, weekly, or a custom length), an amount, and
 * how that amount is shared out across categories. Allocations stay in force
 * from period to period until they are changed, so a new month starts already
 * budgeted - BUD-13's "copy last period" with nothing to copy.
 *
 * The sliders move in whole pesos and the running "left to allocate" is exact
 * centavo arithmetic on strings - the same rule as every other amount here.
 * Over-allocating is allowed but said out loud: the budget total is the real
 * limit, and the categories are a plan inside it.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { TextField } from '../components/ui/TextField';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { createBudget, getBudget, ratio, updateBudget, type Budget as BudgetShape, type PeriodKind } from '../lib/budgets';
import { usePreferencesStore } from '../stores/preferencesStore';
import type { Category } from '../lib/categories';
import { centavos, formatPHP, fromCentavos, sanitizeAmount, toDecimalString } from '../lib/money';
import { localToday } from '../lib/transactions';
import { useBudgetStore } from '../stores/budgetStore';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** Centavos in a typed amount, or 0 while it is half-typed. */
function cents(typed: string): number {
  try {
    return centavos(toDecimalString(typed || '0'));
  } catch {
    return 0;
  }
}

function typedFrom(amount: string): string {
  return amount.endsWith('.00') ? amount.slice(0, -3) : amount;
}

function ProgressBar({ used, over, warnAt = 0.8 }: { used: number; over: boolean; warnAt?: number }) {
  const tone = over ? 'bg-danger' : used >= warnAt ? 'bg-warn' : 'bg-ok';
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className={`h-full rounded-full ${tone} transition-[width] duration-500 ease-ios`}
        style={{ width: `${Math.min(used, 1) * 100}%` }} />
    </div>
  );
}

export function Budget() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const { status, load: loadStatus } = useBudgetStore();

  const [budget, setBudget] = useState<BudgetShape | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [period, setPeriod] = useState<PeriodKind>('monthly');
  const [amount, setAmount] = useState('');
  const [monthStart, setMonthStart] = useState('1');
  const [weekStart, setWeekStart] = useState(1);
  const [customDays, setCustomDays] = useState('14');
  const [customAnchor, setCustomAnchor] = useState(localToday());
  const [allocations, setAllocations] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const hydrate = (b: BudgetShape | null) => {
    setBudget(b);
    setLoaded(true);
    if (!b) {
      // A first budget starts from the defaults chosen in Settings.
      const prefs = usePreferencesStore.getState().prefs;
      if (prefs) {
        setPeriod(prefs.budget_period);
        setMonthStart(String(prefs.month_start_day));
        setWeekStart(prefs.week_start_day);
      }
      return;
    }
    setPeriod(b.period);
    setAmount(typedFrom(b.amount));
    setMonthStart(String(b.month_start_day));
    setWeekStart(b.week_start_day);
    if (b.custom_days) setCustomDays(String(b.custom_days));
    if (b.custom_anchor) setCustomAnchor(b.custom_anchor);
    setAllocations(Object.fromEntries(b.allocations.map((a) => [a.category_id, typedFrom(a.amount)])));
  };

  useEffect(() => {
    const controller = new AbortController();
    getBudget(controller.signal)
      .then(({ budget: b }) => hydrate(b))
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    void loadStatus(null);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Spending categories, parents first with their sub-categories after them.
  const categories = useMemo<Category[]>(
    () => lookups.tree.filter((c) => c.kind === 'expense' && !c.archived).flatMap((p) => [p, ...p.children.filter((c) => !c.archived)]),
    [lookups.tree],
  );
  const progress = new Map((status?.categories ?? []).map((c) => [c.category_id, c]));

  const totalCents = cents(amount);
  const allocatedCents = Object.values(allocations).reduce((sum, v) => sum + cents(v), 0);
  const leftCents = totalCents - allocatedCents;
  const maxPesos = Math.max(Math.floor(totalCents / 100), 0);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    const structure = {
      period,
      month_start_day: Number(monthStart) || 1,
      week_start_day: weekStart,
      ...(period === 'custom' ? { custom_days: Number(customDays) || 14, custom_anchor: customAnchor } : {}),
    };
    const body = {
      ...structure,
      amount: toDecimalString(amount || '0'),
      allocations: Object.entries(allocations)
        .filter(([, value]) => cents(value) > 0)
        .map(([id, value]) => ({ category_id: Number(id), amount: toDecimalString(value) })),
    };
    try {
      const result = budget ? await updateBudget(budget.id, body) : await createBudget(body);
      hydrate(result);
      setSaved(true);
      void loadStatus(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not save. Try again.');
    }
    setBusy(false);
  };

  if (!loaded) return <div className="skeleton mt-16 h-96 rounded-card" aria-hidden="true" />;

  return (
    <>
      <ScreenHeader
        title="Budget"
        subtitle={<button type="button" className="text-accent" onClick={() => navigate('/')}>‹ Home</button>}
      />

      <Card className="space-y-5">
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">How often it resets</p>
          <Segmented<PeriodKind>
            label="Budget period"
            value={period}
            onChange={setPeriod}
            options={[
              { value: 'monthly', label: 'Monthly' },
              { value: 'weekly', label: 'Weekly' },
              { value: 'custom', label: 'Custom' },
            ]}
          />
        </div>

        {period === 'monthly' && (
          <TextField
            label="Starts on day"
            value={monthStart}
            onChange={(e) => setMonthStart(e.target.value.replace(/\D/g, '').slice(0, 2))}
            inputMode="numeric"
            hint="Budget from payday — 25 runs the 25th to the 24th of the next month."
          />
        )}
        {period === 'weekly' && (
          <div>
            <p className="mb-2 text-footnote font-semibold text-ink-2">Starts on</p>
            <div className="flex flex-wrap gap-2">
              {WEEKDAYS.map((day, i) => (
                <button key={day} type="button" onClick={() => setWeekStart(i + 1)} aria-pressed={weekStart === i + 1}
                  className={`min-h-tap rounded-xl px-3 text-footnote font-medium ${weekStart === i + 1 ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-2'}`}>
                  {day.slice(0, 3)}
                </button>
              ))}
            </div>
          </div>
        )}
        {period === 'custom' && (
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Days long" value={customDays} inputMode="numeric"
              onChange={(e) => setCustomDays(e.target.value.replace(/\D/g, '').slice(0, 3))} />
            <label className="text-footnote font-semibold text-ink-2">
              First day
              <input type="date" value={customAnchor} onChange={(e) => e.target.value && setCustomAnchor(e.target.value)}
                className="mt-1.5 block min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-body font-normal text-ink" />
            </label>
          </div>
        )}

        <TextField
          label="Amount each period"
          value={amount}
          onChange={(e) => setAmount(sanitizeAmount(e.target.value))}
          inputMode="decimal"
          placeholder="30,000.00"
          hint={budget ? 'A change applies to the current period straight away.' : undefined}
        />
      </Card>

      <div className="flex items-end justify-between">
        <SectionTitle>By category</SectionTitle>
        <span className={`num px-1 pb-2 text-footnote font-semibold ${leftCents < 0 ? 'text-danger' : 'text-ink-2'}`}>
          {leftCents < 0 ? `${formatPHP(fromCentavos(-leftCents))} over-allocated` : `${formatPHP(fromCentavos(leftCents))} left to allocate`}
        </span>
      </div>

      {categories.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-line px-4 py-3 text-footnote text-ink-2">
          Add spending categories under More → Categories to share the budget out.
        </p>
      ) : (
        <div className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
          {categories.map((category) => {
            const value = allocations[category.id] ?? '';
            const pesos = Math.floor(cents(value) / 100);
            const used = progress.get(category.id);
            return (
              <div key={category.id} className={`px-4 py-3 ${category.parent_id ? 'pl-10' : ''}`}>
                <div className="flex items-center gap-3">
                  <GlyphTile icon={category.icon} colour={category.colour} size={category.parent_id ? 28 : 36} />
                  <span className="min-w-0 flex-1 truncate text-body">{category.name}</span>
                  <input
                    value={value}
                    onChange={(e) => setAllocations((a) => ({ ...a, [category.id]: sanitizeAmount(e.target.value) }))}
                    inputMode="decimal"
                    placeholder="0"
                    aria-label={`${category.name} allocation`}
                    className="num min-h-tap w-28 rounded-xl bg-surface-2 px-3 text-right text-body"
                  />
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(maxPesos, pesos)}
                  step={maxPesos > 5000 ? 100 : 10}
                  value={pesos}
                  onChange={(e) => setAllocations((a) => ({ ...a, [category.id]: e.target.value === '0' ? '' : e.target.value }))}
                  aria-label={`${category.name} allocation slider`}
                  className="mt-2 w-full accent-accent"
                  disabled={maxPesos === 0}
                />
                {used && (
                  <div className="mt-1 space-y-1">
                    <ProgressBar used={ratio(used.used_ratio)} over={used.over} />
                    <p className={`num text-caption ${used.over ? 'text-danger' : 'text-ink-3'}`}>
                      {formatPHP(used.spent)} of {formatPHP(used.allocated)} spent this period
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="px-1 pt-2 text-footnote text-ink-3">
        Category amounts carry into every new period until you change them.
      </p>

      {error && <p className="mt-3 text-footnote text-danger">{error}</p>}
      {saved && <p className="mt-3 text-footnote text-ok">Saved.</p>}

      <Button block size="lg" className="mt-4" onClick={() => void save()} disabled={busy || totalCents <= 0}>
        {budget ? 'Save budget' : 'Start budgeting'}
      </Button>
      <Button variant="ghost" block className="mt-2" onClick={() => navigate('/settings')}>
        Carry-over and daily allowance settings
      </Button>
    </>
  );
}
