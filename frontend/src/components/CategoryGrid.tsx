/**
 * Home's spending by category, as a grid of tiles (2026-09-15, after
 * sample_ui/). Each tile is the category's icon inside a ring and what was
 * spent on it over the period Home is showing.
 *
 * The ring is how much of the category's budget is used when it has one,
 * otherwise its share of the period's spending - drawn in the category's own
 * stored colour, like the ledger and the pie. An over-budget category says so
 * in money-state red on its amount; the ring does not change colour.
 *
 * Figures come from GET /stats/overview for exactly the period on Home, so the
 * tiles add up to the "Spent" on the budget card.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Lookups } from '../hooks/useLookups';
import { ratio, type CategoryProgress } from '../lib/budgets';
import { formatPHP } from '../lib/money';
import { getOverview, type Overview, type Range } from '../lib/stats';
import { useLedgerStore } from '../stores/ledgerStore';
import { Glyph } from './Glyph';

const NEUTRAL = '#8E8E93';
const SIZE = 52;
const THICKNESS = 4;

function CategoryRing({ progress, colour, icon }: { progress: number; colour: string; icon: string }) {
  const radius = (SIZE - THICKNESS) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(Math.max(progress, 0), 1);
  return (
    <span className="relative flex items-center justify-center" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={radius} fill="none" strokeWidth={THICKNESS + 3} className="stroke-stroke" />
        <circle cx={SIZE / 2} cy={SIZE / 2} r={radius} fill="none" strokeWidth={THICKNESS} className="stroke-surface-2" />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={radius}
          fill="none"
          strokeWidth={THICKNESS}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          style={{ stroke: colour }}
          className="transition-[stroke-dashoffset] duration-700 ease-ios"
        />
      </svg>
      <span
        className="flex items-center justify-center rounded-full text-black"
        style={{ width: SIZE - 16, height: SIZE - 16, backgroundColor: colour }}
      >
        <Glyph name={icon} size={20} />
      </span>
    </span>
  );
}

export function CategoryGrid({
  range, progress, lookups,
}: { range: Range; progress: CategoryProgress[]; lookups: Lookups }) {
  const navigate = useNavigate();
  const version = useLedgerStore((s) => s.version);
  const [overview, setOverview] = useState<Overview | null>(null);
  const key = 'span' in range ? `${range.span}:${range.on}` : `${range.from}:${range.to}`;

  useEffect(() => {
    const controller = new AbortController();
    getOverview(range, controller.signal)
      .then(setOverview)
      .catch(() => {
        /* the budget card carries the error; the grid just stays empty */
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  if (!overview) return <div className="skeleton h-40 rounded-card" aria-hidden="true" />;

  const budgets = new Map(progress.map((p) => [p.category_id, p]));
  const spent = overview.categories.filter((c) => c.amount !== '0.00');

  return (
    <section aria-label="Spending by category">
      <div className="flex items-end justify-between px-1 pb-2 pt-5">
        <h2 className="text-headline">
          Expense <span className="num text-ink-2">{formatPHP(overview.totals.spent)}</span>
        </h2>
        <button type="button" onClick={() => navigate('/stats')} className="min-h-tap px-1 text-footnote font-semibold text-accent-ink">
          Stats
        </button>
      </div>
      {spent.length === 0 ? (
        <p className="rounded-2xl border-2 border-dashed border-stroke/70 px-4 py-3 text-footnote text-ink-2">
          Nothing spent in this period yet.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2.5">
          {spent.map((share) => {
            const category = share.category_id !== null ? lookups.categoryById.get(share.category_id) : undefined;
            const budget = share.category_id !== null ? budgets.get(share.category_id) : undefined;
            const name = category?.name ?? 'Uncategorised';
            return (
              <div key={share.category_id ?? 'none'}
                className="flex flex-col items-center gap-1.5 rounded-card bg-surface px-2 py-3 text-center shadow-card">
                <span className="line-clamp-1 w-full text-caption font-medium text-ink-2">{name}</span>
                <CategoryRing
                  progress={budget ? ratio(budget.used_ratio) : ratio(share.share)}
                  colour={category?.colour ?? NEUTRAL}
                  icon={category?.icon ?? 'tag'}
                />
                <span className={`num w-full truncate text-footnote font-semibold ${budget?.over ? 'text-danger' : 'text-ink'}`}>
                  {formatPHP(share.amount)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
