/**
 * BUD-17 - a budget suggested from recent spending (2026-09-28, user).
 *
 * The server works it out from the last 1, 3 or 6 FINISHED periods - exactly
 * what the budget counts, so the suggestion and the progress bars can never
 * disagree - and this sheet shows it, line by line, with why:
 *
 *   median     the typical period; one big purchase does not set the budget
 *   scheduled  never below what bills, subscriptions and installments will
 *              charge that category this period
 *   kept       budgeted now, not spent on lately - kept, you put it there
 *   single     only one period to go on
 *
 * It SUGGESTS (the user's decision): "Use this" fills the Plan editor below
 * and nothing is saved until Save there, through the one writer the budget
 * already has. The rounding step comes from Settings and can be tried
 * differently here without changing the setting.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useEffect, useState } from 'react';
import { useLookups } from '../hooks/useLookups';
import { getSuggestion, type Suggestion, type SuggestionAsk } from '../lib/budgets';
import { formatPHP } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { usePreferencesStore } from '../stores/preferencesStore';
import { GlyphTile } from './StylePicker';
import { Button } from './ui/Button';
import { Segmented } from './ui/Segmented';
import { Sheet } from './ui/Sheet';

const STEPS = [1, 10, 50, 100, 500, 1000];

/** "month", "week" or "period" - the budget's own rhythm, in the words the lines use. */
function unitOf(kind: Suggestion['kind']): string {
  return kind === 'monthly' ? 'month' : kind === 'weekly' ? 'week' : 'period';
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`;
const pesos = (step: number) => formatPHP(`${step}.00`).replace('.00', '');

function reasonText(line: Suggestion['lines'][number], periods: number, unit: string): string {
  if (line.reason === 'scheduled') return `${formatPHP(line.scheduled)} already scheduled`;
  if (line.reason === 'kept') return `no regular spending in ${plural(periods, unit)} — keep it, or clear it below`;
  if (line.reason === 'single') return `last ${unit}`;
  return `median of ${plural(periods, unit)} · average ${formatPHP(line.average)}`;
}

export function SuggestionSheet({
  open,
  onClose,
  onUse,
}: {
  open: boolean;
  onClose: () => void;
  /** Fill the editor: the total, and an amount per category. Nothing is saved here. */
  onUse: (total: string, allocations: Record<number, string>) => void;
}) {
  const lookups = useLookups();
  const setting = Number(usePreferencesStore((s) => s.prefs?.budget_round_step) ?? 100);
  const [ask, setAsk] = useState<SuggestionAsk>({ periods: 3, trim: 0, fit: false });

  // Every opening starts from the defaults - the step from Settings, three periods, nothing trimmed.
  useEffect(() => {
    if (open) setAsk({ periods: 3, trim: 0, fit: false });
  }, [open]);

  const { data, error, isFetching } = useQuery({
    queryKey: keys.suggestion(ask.periods, ask.step, ask.trim, ask.fit),
    queryFn: ({ signal }) => getSuggestion(ask, signal),
    staleTime: STALE.derived,
    enabled: open,
  });

  const unit = data ? unitOf(data.kind) : 'month';
  const used = data?.periods.length ?? 0;
  const step = ask.step ?? setting;

  const use = () => {
    if (!data?.ready) return;
    onUse(data.total, Object.fromEntries(data.lines.map((l) => [l.category_id, l.suggested])));
  };

  return (
    <Sheet open={open} onClose={onClose} title="Suggested budget">
      <div className="space-y-4 pb-2">
        <Segmented<'1' | '3' | '6'>
          label="Based on"
          value={String(ask.periods) as '1' | '3' | '6'}
          onChange={(value) => setAsk((a) => ({ ...a, periods: Number(value) as 1 | 3 | 6, fit: false }))}
          options={[
            { value: '1', label: `1 ${unit}` },
            { value: '3', label: `3 ${unit}s` },
            { value: '6', label: `6 ${unit}s` },
          ]}
        />

        {error && <p className="text-footnote text-danger">{(error as Error).message}</p>}
        {!data && !error && <div className="skeleton h-48 rounded-card" aria-hidden="true" />}

        {data && !data.ready && (
          <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
            Nothing to suggest from yet. A suggestion needs at least one finished {unit} of entries — come back
            after this one ends.
          </p>
        )}

        {data?.ready && (
          <>
            <div className={`text-center transition-opacity ${isFetching ? 'opacity-60' : ''}`}>
              <output className="num block text-display">{formatPHP(data.total)}</output>
              <p className="text-footnote text-ink-2">
                a {unit}, for {format(parseISO(data.period.start), 'd MMM')} – {format(parseISO(data.period.end), 'd MMM')}
                {used < data.asked && ` · based on ${plural(used, unit)}, all there is so far`}
              </p>
              {data.in_force && (
                <p className="num text-footnote text-ink-3">Your budget now is {formatPHP(data.in_force)}</p>
              )}
            </div>

            {data.over_income && data.income && (
              <div className="space-y-2 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
                <p className="text-footnote">
                  That’s more than you usually take in — <span className="num font-semibold">{formatPHP(data.income)}</span> a {unit}.
                </p>
                <Button variant="secondary" onClick={() => setAsk((a) => ({ ...a, fit: true }))}>Fit to my income</Button>
              </div>
            )}
            {data.fitted && (
              <p className="rounded-card border-2 border-stroke bg-surface-2 px-4 py-3 text-footnote text-ink-2">
                {data.cannot_fit
                  ? 'What is already scheduled is more than you usually take in, so only that is budgeted.'
                  : 'Fitted to what you usually take in: everything above what is scheduled came down in step.'}{' '}
                <button type="button" className="font-semibold text-accent-ink" onClick={() => setAsk((a) => ({ ...a, fit: false }))}>
                  Undo
                </button>
              </p>
            )}

            <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
              {data.lines.map((line) => {
                const category = lookups.categoryById.get(line.category_id);
                return (
                  <div key={line.category_id} className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      {category && <GlyphTile icon={category.icon} colour={category.colour} size={32} />}
                      <span className="min-w-0 flex-1 truncate text-body">{category?.name ?? 'Category'}</span>
                      <span className="num text-body font-semibold">{formatPHP(line.suggested)}</span>
                    </div>
                    <p className="num mt-1 text-caption text-ink-3">
                      {line.history.map((h) => formatPHP(h)).join(' · ')}
                      {line.current !== null && ` · now ${formatPHP(line.current)}`}
                    </p>
                    <p className="text-caption text-ink-2">{reasonText(line, used, unit)}</p>
                  </div>
                );
              })}
            </div>

            {(data.occasional.length > 0 || data.buffer !== '0.00') && (
              <p className="px-1 text-footnote text-ink-2">
                {data.occasional.length > 0 && (
                  <>
                    Not given an amount of their own — spent in fewer than half the {unit}s:{' '}
                    {data.occasional
                      .map((o) => `${lookups.categoryById.get(o.category_id)?.name ?? 'a category'} (${o.spent_in} of ${used})`)
                      .join(', ')}
                    .{' '}
                  </>
                )}
                <span className="num">{formatPHP(data.buffer)}</span> is left unassigned for them and anything else. A
                cost that comes once a year is better set aside for in Savings goals.
              </p>
            )}

            <div className="space-y-3 rounded-card border-2 border-stroke bg-surface-2 px-4 py-3">
              <Segmented<'0' | '5' | '10'>
                label="Spend less"
                value={String(ask.trim) as '0' | '5' | '10'}
                onChange={(value) => setAsk((a) => ({ ...a, trim: Number(value) as 0 | 5 | 10 }))}
                options={[
                  { value: '0', label: 'As it is' },
                  { value: '5', label: '5% less' },
                  { value: '10', label: '10% less' },
                ]}
              />
              <label className="flex items-center justify-between gap-3 text-footnote">
                <span>Round up to</span>
                <select
                  value={step}
                  onChange={(e) => setAsk((a) => ({ ...a, step: Number(e.target.value) }))}
                  className="num min-h-tap rounded-xl border-2 border-stroke bg-surface px-3 text-body text-ink"
                >
                  {STEPS.map((s) => <option key={s} value={s}>{pesos(s)}{s === setting ? ' (your setting)' : ''}</option>)}
                </select>
              </label>
              <p className="text-caption text-ink-3">Trimming never goes below what is already scheduled.</p>
            </div>

            <Button block size="lg" onClick={use} disabled={isFetching}>Use this</Button>
            <p className="text-center text-caption text-ink-3">Fills in the plan below — nothing changes until you save it.</p>
          </>
        )}
      </div>
    </Sheet>
  );
}
