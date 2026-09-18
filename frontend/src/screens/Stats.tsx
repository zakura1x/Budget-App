/**
 * Stats (STA-01..STA-11) - one request, every chart.
 *
 * The range is the budget period (a calendar month with no budget), a month,
 * a year, or two dates. The arrows step to the range before or after by
 * asking the server for the day beyond an edge - the server resolves the
 * range, so a payday period never drifts.
 *
 * What is drawn:
 *   - spent, earned, a day's average, and the range before - "by this point"
 *     while the range is still running (STA-04/05/07)
 *   - the forecast (STA-11): the rate so far run to the end, beside the budget
 *   - the donut by category, with a tap to drill into sub-categories (STA-01/02)
 *   - the trend line (STA-03), top merchants (STA-06), accounts (STA-08), tags
 *
 * Every category keeps its own colour - the same one the ledger and the budget
 * screen show. Chart strokes come from theme.css through useThemeColours, and
 * ok/warn/danger appear only on the forecast, where they mean money state.
 * Amounts become numbers only to size a slice or place a point.
 */
import { addDays, format, parseISO } from 'date-fns';
import { useEffect, useMemo, useState } from 'react';
import { Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CalendarSwitch } from '../components/CalendarSwitch';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { useLookups, type Lookups } from '../hooks/useLookups';
import { useThemeColours, type ThemeColours } from '../hooks/useThemeColours';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { getOverview, type CategoryShare, type Overview, type Range } from '../lib/stats';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';

type Mode = 'budget' | 'month' | 'year' | 'custom';

const NEUTRAL = '#8E8E93';
/** recharts draws SVG text with attributes, so the mono face is named here, as tailwind.config.js does. */
const MONO = '"JetBrains Mono", ui-monospace, monospace';
const TONE = { ok: 'text-ok', warn: 'text-warn', danger: 'text-danger' } as const;

const iso = (d: Date) => format(d, 'yyyy-MM-dd');
/** A decimal string as a number - for drawing only. */
const draw = (value: string) => centavos(value) / 100;
const peso = (n: number) => formatPHP(fromCentavos(Math.round(n * 100)));

function rangeLabel(start: string, end: string): string {
  const a = parseISO(start);
  const b = parseISO(end);
  if (a.getFullYear() !== b.getFullYear()) return `${format(a, 'd MMM yyyy')} – ${format(b, 'd MMM yyyy')}`;
  if (a.getMonth() === b.getMonth()) return `${format(a, 'd')} – ${format(b, 'd MMM yyyy')}`;
  return `${format(a, 'd MMM')} – ${format(b, 'd MMM yyyy')}`;
}

function unitOf(overview: Overview): string {
  if (overview.span === 'budget') return 'period';
  if (overview.span === 'month') return 'month';
  if (overview.span === 'year') return 'year';
  return 'range';
}

/** "12% more than" / "the same as" - or null with nothing to compare. */
function compared(now: string, before: string): string | null {
  const base = centavos(before);
  if (base <= 0) return null;
  const pct = Math.round(((centavos(now) - base) / base) * 100);
  return pct === 0 ? 'The same as' : `${Math.abs(pct)}% ${pct > 0 ? 'more than' : 'less than'}`;
}

// ------------------------------------------------------------------ summary

function Summary({ overview }: { overview: Overview }) {
  const { totals, previous } = overview;
  const unit = unitOf(overview);
  const byNow = previous.spent_to_same_day;
  const comparison = compared(totals.spent, byNow ?? previous.spent);
  const net = totals.net.startsWith('-');

  return (
    <Card>
      <p className="text-footnote font-medium text-ink-2">Spent</p>
      <p className="num text-display">{formatPHP(totals.spent)}</p>
      {comparison && (
        <p className="mt-1 text-footnote text-ink-2">
          {comparison} {byNow !== null ? `last ${unit} by this point` : `the ${unit} before`} (
          <span className="num">{formatPHP(byNow ?? previous.spent)}</span>)
        </p>
      )}
      <div className="mt-4 grid grid-cols-3 divide-x divide-stroke/80 text-center">
        <div>
          <p className="text-caption text-ink-3">Earned</p>
          <p className="num text-body font-semibold text-ok">{formatPHP(totals.earned)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">{net ? 'Spent more by' : 'Kept'}</p>
          <p className="num text-body font-semibold">{formatPHP(net ? totals.net.slice(1) : totals.net)}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">A day</p>
          <p className="num text-body font-semibold">{formatPHP(totals.average_daily_spend)}</p>
        </div>
      </div>
      {(totals.adjustment_losses !== '0.00' || totals.adjustment_gains !== '0.00') && (
        <p className="mt-3 rounded-xl bg-surface-2 px-3 py-2 text-footnote text-ink-2">
          Includes balance adjustments — your budget does not count them:{' '}
          <span className="num">
            {[
              totals.adjustment_losses !== '0.00' && `${formatPHP(totals.adjustment_losses)} unrecorded loss`,
              totals.adjustment_gains !== '0.00' && `${formatPHP(totals.adjustment_gains)} unrecorded gain`,
            ].filter(Boolean).join(' · ')}
          </span>
        </p>
      )}
    </Card>
  );
}

// ----------------------------------------------------------------- forecast

function ForecastCard({ overview, colours }: { overview: Overview; colours: ThemeColours }) {
  const f = overview.forecast;
  const series = useMemo(() => {
    if (!f || overview.granularity !== 'day') return [];
    const today = f.days_elapsed - 1;
    const rate = draw(f.spent_to_date) / f.days_elapsed;
    let running = 0;
    return overview.trend.map((point, i) => {
      if (i <= today) running += draw(point.spent);
      return {
        label: format(parseISO(point.start), 'd'),
        actual: i <= today ? running : null,
        projected: i >= today ? draw(f.spent_to_date) + rate * (i - today) : null,
      };
    });
  }, [f, overview]);
  if (!f) return null;

  const available = f.budget_available;
  const over = available ? centavos(f.projected) - centavos(available) : 0;
  const tone = !available ? null : over > 0 ? 'danger' : centavos(f.projected) * 10 > centavos(available) * 9 ? 'warn' : 'ok';

  return (
    <Card className="mt-3">
      <p className="text-footnote font-medium text-ink-2">Forecast</p>
      <p className="mt-0.5 text-headline">
        At this rate you finish the {unitOf(overview)} at{' '}
        <span className={`num ${tone ? TONE[tone] : ''}`}>{formatPHP(f.projected)}</span>.
      </p>
      <p className="mt-1 text-footnote text-ink-2">
        <span className="num">{formatPHP(f.daily_rate)}</span> a day so far · {f.days_left} day{f.days_left === 1 ? '' : 's'} left
        {available && (
          <>
            {' · '}
            {over > 0 ? (
              <span className="num text-danger">{formatPHP(fromCentavos(over))} over your budget</span>
            ) : (
              <span className="num">budget {formatPHP(available)}</span>
            )}
          </>
        )}
      </p>
      {f.days_elapsed < 3 && (
        <p className="mt-1 text-footnote text-ink-3">Early days — this settles as the {unitOf(overview)} goes on.</p>
      )}
      {series.length > 0 && (
        <div className="mt-3 h-40">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <XAxis dataKey="label" tick={{ fill: colours['ink-2'], fontSize: 10, fontFamily: MONO }} tickLine={false}
                axisLine={{ stroke: colours.line }} interval="preserveStartEnd" minTickGap={24} />
              <YAxis hide domain={[0, 'auto']} />
              {available && (
                <ReferenceLine y={draw(available)} stroke={colours['ink-3']} strokeDasharray="4 4"
                  label={{ value: 'Budget', position: 'insideTopLeft', fill: colours['ink-2'], fontSize: 10, fontFamily: MONO }} />
              )}
              <Line type="linear" dataKey="actual" stroke={colours.ink} strokeWidth={3} dot={false} connectNulls={false}
                isAnimationActive={false} />
              <Line type="linear" dataKey="projected" stroke={tone ? colours[tone] : colours['ink-2']} strokeWidth={2}
                strokeDasharray="5 5" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------- categories

interface Slice {
  key: string;
  id: number | null;
  name: string;
  icon: string;
  colour: string;
  amount: string;
  previous: string | null;
  count: number;
  drillable: boolean;
}

function CategoryCard({ overview, lookups, colours }: { overview: Overview; lookups: Lookups; colours: ThemeColours }) {
  const [kind, setKind] = useState<'expense' | 'income'>('expense');
  const [drill, setDrill] = useState<number | null>(null);
  useEffect(() => setDrill(null), [overview, kind]);

  const list = kind === 'expense' ? overview.categories : overview.income_categories;
  const parent = drill !== null ? list.find((c) => c.category_id === drill) : undefined;

  const slice = (share: CategoryShare, self = false): Slice => {
    if (share.unrecorded) {
      // ACC-29. Balance adjustments: one row, no category and nothing under it (2026-09-18).
      return {
        key: 'unrecorded', id: null, name: kind === 'expense' ? 'Unrecorded loss' : 'Unrecorded gain',
        icon: 'dots', colour: NEUTRAL, amount: share.amount, previous: kind === 'expense' ? share.previous_amount : null,
        count: share.transaction_count, drillable: false,
      };
    }
    const category = share.category_id !== null ? lookups.categoryById.get(share.category_id) : undefined;
    return {
      key: `${share.category_id}-${self}`,
      id: share.category_id,
      name: self ? `${category?.name ?? 'Uncategorised'}, not in a sub-category` : category?.name ?? 'Uncategorised',
      icon: category?.icon ?? 'tag',
      colour: category?.colour ?? NEUTRAL,
      amount: self ? share.direct : share.amount,
      previous: kind === 'expense' && !self ? share.previous_amount : null,
      count: share.transaction_count,
      drillable: !parent && !self && share.children.length > 0,
    };
  };

  const slices: Slice[] = parent
    ? [...parent.children.map((c) => slice(c)), ...(centavos(parent.direct) > 0 ? [slice(parent, true)] : [])]
        .sort((a, b) => centavos(b.amount) - centavos(a.amount))
    : list.map((c) => slice(c));
  const sum = slices.reduce((n, s) => n + centavos(s.amount), 0);
  const centre = parent ? lookups.categoryById.get(parent.category_id ?? -1)?.name ?? 'Uncategorised' : kind === 'expense' ? 'Spent' : 'Earned';

  return (
    <>
      <SectionTitle>By category</SectionTitle>
      <Card>
        <Segmented
          label="Category kind"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'expense', label: 'Spending' },
            { value: 'income', label: 'Income' },
          ]}
        />
        {parent && (
          <button type="button" onClick={() => setDrill(null)} className="mt-3 min-h-tap text-footnote font-semibold text-accent-ink">
            ‹ All categories
          </button>
        )}
        {slices.length === 0 ? (
          <p className="py-6 text-center text-footnote text-ink-2">No {kind === 'expense' ? 'spending' : 'income'} in this range.</p>
        ) : (
          <>
            <div className="relative mx-auto mt-3 h-52 w-52">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={slices.map((s) => ({ name: s.name, value: centavos(s.amount) }))} dataKey="value"
                    innerRadius="58%" outerRadius="98%" paddingAngle={0}
                    stroke={colours.stroke} strokeWidth={2} startAngle={90} endAngle={-270} isAnimationActive={false}>
                    {slices.map((s) => (
                      <Cell key={s.key} fill={s.colour} className={s.drillable ? 'cursor-pointer' : ''}
                        onClick={() => s.drillable && setDrill(s.id)} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-8 text-center">
                <span className="truncate text-caption text-ink-3">{centre}</span>
                <span className="num text-headline">{formatPHP(fromCentavos(sum))}</span>
              </div>
            </div>
            <ul className="mt-3 divide-y divide-stroke/80">
              {slices.map((s) => {
                const pct = sum > 0 ? Math.round((centavos(s.amount) / sum) * 100) : 0;
                const Row = s.drillable ? 'button' : 'div';
                return (
                  <li key={s.key}>
                    <Row
                      {...(s.drillable ? { type: 'button' as const, onClick: () => setDrill(s.id) } : {})}
                      className="flex min-h-14 w-full items-center gap-3 py-2 text-left"
                    >
                      <GlyphTile icon={s.icon} colour={s.colour} size={36} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body">{s.name}</span>
                        <span className="block text-footnote text-ink-3">
                          {pct}% · {s.count} transaction{s.count === 1 ? '' : 's'}
                          {s.previous !== null && ` · ${formatPHP(s.previous)} before`}
                        </span>
                      </span>
                      <span className="num shrink-0 text-body font-semibold">{formatPHP(s.amount)}</span>
                      {s.drillable && <span className="text-ink-3" aria-hidden="true">›</span>}
                    </Row>
                  </li>
                );
              })}
            </ul>
            {!parent && kind === 'expense' && (
              <p className="pt-1 text-footnote text-ink-3">A split purchase counts in each of its categories.</p>
            )}
          </>
        )}
      </Card>
    </>
  );
}

// -------------------------------------------------------------------- trend

function TrendCard({ overview, colours }: { overview: Overview; colours: ThemeColours }) {
  // One line at a time: a payday is often ten times a day's spending, and on a
  // shared axis it would flatten the spending line to nothing.
  const [series, setSeries] = useState<'spent' | 'earned'>('spent');
  const pattern = overview.granularity === 'month' ? 'MMM' : overview.granularity === 'week' ? 'd MMM' : 'd';
  const data = overview.trend.map((p) => ({
    label: format(parseISO(p.start), pattern),
    value: draw(series === 'spent' ? p.spent : p.earned),
  }));

  return (
    <>
      <SectionTitle>Over time</SectionTitle>
      <Card>
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <Segmented
              label="Trend"
              value={series}
              onChange={setSeries}
              options={[
                { value: 'spent', label: 'Spent' },
                { value: 'earned', label: 'Earned' },
              ]}
            />
          </div>
          <span className="text-footnote text-ink-3">per {overview.granularity}</span>
        </div>
        <div className="mt-2 h-44">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <XAxis dataKey="label" tick={{ fill: colours['ink-2'], fontSize: 10, fontFamily: MONO }} tickLine={false}
                axisLine={{ stroke: colours.line }} interval="preserveStartEnd" minTickGap={20} />
              <YAxis hide domain={[0, 'auto']} />
              <Tooltip
                formatter={(value) => peso(Number(value))}
                contentStyle={{ background: colours.surface, border: `2px solid ${colours.stroke}`, borderRadius: 8, fontSize: 12, fontFamily: MONO, boxShadow: `4px 4px 0 ${colours.stroke}` }}
                labelStyle={{ color: colours['ink-2'] }}
              />
              <Line type="linear" dataKey="value" name={series === 'spent' ? 'Spent' : 'Earned'}
                stroke={series === 'spent' ? colours.ink : colours.ok} strokeWidth={3} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </>
  );
}

// -------------------------------------------------------------------- lists

function Ranked({ title, note, rows }: {
  title: string;
  note?: string;
  rows: { key: string; lead: React.ReactNode; name: string; detail: string; amount: string }[];
}) {
  if (rows.length === 0) return null;
  return (
    <>
      <SectionTitle>{title}</SectionTitle>
      <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
        {rows.map((row) => (
          <div key={row.key} className="flex min-h-14 items-center gap-3 px-4 py-2">
            {row.lead}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body">{row.name}</span>
              <span className="block text-footnote text-ink-3">{row.detail}</span>
            </span>
            <span className="num shrink-0 text-body font-semibold">{row.amount}</span>
          </div>
        ))}
      </div>
      {note && <p className="px-1 pt-2 text-footnote text-ink-3">{note}</p>}
    </>
  );
}

const count = (n: number) => `${n} transaction${n === 1 ? '' : 's'}`;

// ------------------------------------------------------------------- screen

export function Stats() {
  const lookups = useLookups();
  const colours = useThemeColours();
  const version = useLedgerStore((s) => s.version);
  const [mode, setMode] = useState<Mode>('budget');
  const [on, setOn] = useState(localToday());
  const [custom, setCustom] = useState({ from: iso(addDays(new Date(), -29)), to: localToday() });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const range: Range | null =
    mode === 'custom'
      ? custom.from && custom.to && custom.from <= custom.to ? { from: custom.from, to: custom.to } : null
      : { span: mode, on };

  useEffect(() => {
    if (!range) return;
    setError(null);
    const controller = new AbortController();
    getOverview(range, controller.signal)
      .then(setOverview)
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, on, custom.from, custom.to, version]);

  const step = (direction: -1 | 1) => {
    if (!overview) return;
    setOn(iso(addDays(parseISO(direction < 0 ? overview.start : overview.end), direction)));
  };

  return (
    <>
      <CalendarSwitch />
      <ScreenHeader
        title="Stats"
        subtitle={overview ? rangeLabel(overview.start, overview.end) : ' '}
        action={
          mode !== 'custom' && (
            <div className="flex gap-1">
              <button type="button" aria-label="Earlier" onClick={() => step(-1)}
                className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press">
                ‹
              </button>
              <button type="button" aria-label="Later" onClick={() => step(1)}
                className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press">
                ›
              </button>
            </div>
          )
        }
      />

      <Segmented<Mode>
        label="Range"
        value={mode}
        onChange={(next) => {
          setMode(next);
          setOn(localToday());
        }}
        options={[
          { value: 'budget', label: 'Period' },
          { value: 'month', label: 'Month' },
          { value: 'year', label: 'Year' },
          { value: 'custom', label: 'Custom' },
        ]}
      />

      {mode === 'custom' && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          {(['from', 'to'] as const).map((edge) => (
            <label key={edge} className="text-footnote font-semibold capitalize text-ink-2">
              {edge}
              <input type="date" value={custom[edge]}
                onChange={(e) => setCustom((c) => ({ ...c, [edge]: e.target.value }))}
                className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
            </label>
          ))}
        </div>
      )}

      <div className="mt-3">
        {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}
        {!overview && !error && <div className="skeleton h-72 rounded-card" aria-hidden="true" />}
        {overview && (
          <>
            <Summary overview={overview} />
            <ForecastCard overview={overview} colours={colours} />
            {overview.totals.transaction_count === 0 ? (
              <Card className="mt-3 text-center">
                <p className="text-body">Nothing spent or earned in this range.</p>
                <p className="mt-1 text-footnote text-ink-2">Try an earlier one, or a longer range.</p>
              </Card>
            ) : (
              <>
                <CategoryCard overview={overview} lookups={lookups} colours={colours} />
                <TrendCard overview={overview} colours={colours} />
                <Ranked
                  title="Top merchants"
                  rows={overview.merchants.map((m) => ({
                    key: m.name, name: m.name, detail: count(m.transaction_count), amount: formatPHP(m.amount),
                    lead: <GlyphTile icon="cart" colour={NEUTRAL} size={36} />,
                  }))}
                />
                <Ranked
                  title="By account"
                  rows={overview.accounts.map((a) => {
                    const account = lookups.accountById.get(a.account_id);
                    return {
                      key: String(a.account_id), name: account?.name ?? 'Account',
                      detail: a.earned !== '0.00' ? `${formatPHP(a.earned)} earned` : 'Spent',
                      amount: formatPHP(a.spent),
                      lead: <GlyphTile icon={account?.icon ?? 'wallet'} colour={account?.colour ?? NEUTRAL} size={36} />,
                    };
                  })}
                />
                <Ranked
                  title="By tag"
                  note={overview.tags.length > 1 ? 'A purchase with two tags counts toward both.' : undefined}
                  rows={overview.tags.map((t) => {
                    const tag = lookups.tagById.get(t.tag_id);
                    return {
                      key: String(t.tag_id), name: tag?.name ?? 'Tag', detail: count(t.transaction_count),
                      amount: formatPHP(t.spent),
                      lead: <span className="mx-3 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: tag?.colour ?? NEUTRAL }} aria-hidden="true" />,
                    };
                  })}
                />
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
