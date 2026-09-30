/**
 * The monthly review (STA-12) - a finished period, looked back on.
 *
 * Reached from Stats ("Review this period") and offered on Home in the first
 * days of a new period (ReviewCard). The period is a budget period when there
 * is a budget, else a calendar month; ‹ steps back one, › forward until the
 * period that has not finished yet.
 *
 * Everything is derived on the server from the working set, the rules and the
 * balances. Net worth is deliberately absent: a card's typed bills carry no
 * date, so a past net worth could not be rebuilt honestly.
 */
import { useQuery } from '@tanstack/react-query';
import { addDays, format, parseISO } from 'date-fns';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ExplainLink } from '../components/ExplainLink';
import { ScreenHeader } from '../components/ScreenHeader';
import { GlyphTile } from '../components/StylePicker';
import { Card, SectionTitle } from '../components/ui/Card';
import { ListGroup } from '../components/ui/ListRow';
import { useLookups } from '../hooks/useLookups';
import { centavos, formatPHP, fromCentavos } from '../lib/money';
import { keys, STALE } from '../lib/queryKeys';
import { getReview, type Review as ReviewData } from '../lib/stats';

/** A stored category colour is a fill for a black glyph; this one stands in for a deleted category. */
const NEUTRAL = '#8E8E93';
const iso = (d: Date) => format(d, 'yyyy-MM-dd');
const unsigned = (value: string) => value.replace(/^-/, '');
const negative = (value: string) => value.startsWith('-');
const zero = (value: string) => /^-?0(\.0+)?$/.test(value);

/** "August in review"; a budget period across two months is "Aug–Sep review", which still fits one line. */
function title(review: ReviewData): string {
  const start = parseISO(review.period.start);
  const end = parseISO(review.period.end);
  if (review.period.span === 'month' || start.getMonth() === end.getMonth()) return `${format(start, 'MMMM')} in review`;
  return `${format(start, 'MMM')}–${format(end, 'MMM')} review`;
}

function span(review: ReviewData): string {
  const a = parseISO(review.period.start);
  const b = parseISO(review.period.end);
  return a.getFullYear() === b.getFullYear()
    ? `${format(a, 'd MMM')} – ${format(b, 'd MMM yyyy')}`
    : `${format(a, 'd MMM yyyy')} – ${format(b, 'd MMM yyyy')}`;
}

const EVENT: Record<ReviewData['plans'][number]['event'], string> = {
  started: 'Started',
  finished: 'Paid off',
  cancelled: 'Cancelled',
  price: 'Price changed',
};

export function Review() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const on = params.get('on') ?? undefined;
  const { categoryById } = useLookups();
  const { data: review, isPending, error } = useQuery({
    queryKey: keys.review(on),
    queryFn: ({ signal }) => getReview(on, signal),
    staleTime: STALE.derived,
  });

  const category = (id: number | null) => (id != null ? categoryById.get(id) : undefined);

  return (
    <>
      <ScreenHeader
        title={review ? title(review) : 'Review'}
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/stats')}>‹ Stats</button>}
        action={review && (
          <div className="flex gap-1">
            <button type="button" aria-label="Earlier" onClick={() => setParams({ on: iso(addDays(parseISO(review.period.start), -1)) })}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press">‹</button>
            <button type="button" aria-label="Later" disabled={!review.later} onClick={() => review.later && setParams({ on: review.later })}
              className="flex h-tap w-tap items-center justify-center rounded-xl bg-surface text-headline text-ink-2 press disabled:opacity-40">›</button>
          </div>
        )}
      />
      {/* misc/AI AI-40 - the assistant looks back on the LAST finished period, so only offered on that one */}
      {review && !review.later && (
        <ExplainLink ask="How did I do last period?" context={{ screen: 'review' }} label="Ask about this period" />
      )}

      {isPending && <p className="py-6 text-center text-footnote text-ink-3">Loading…</p>}
      {error && <p className="py-6 text-center text-footnote text-danger">Could not load this review.</p>}

      {review && (
        <>
          <p className="label mb-3 text-ink-2">{span(review)}</p>

          <Card className="space-y-2">
            <p className="label text-ink-2">Spent</p>
            <p className="num text-display">{formatPHP(review.spent)}</p>
            <SpentAgainst review={review} />
            <div className="grid grid-cols-2 gap-3 border-t-2 border-stroke/20 pt-3">
              <div>
                <p className="text-footnote text-ink-2">Came in</p>
                <p className="num text-headline">{formatPHP(review.earned)}</p>
              </div>
              <div>
                <p className="text-footnote text-ink-2">{negative(review.net) ? 'Spent more than came in' : 'Left over'}</p>
                <p className={`num text-headline ${negative(review.net) ? 'text-danger' : 'text-ok'}`}>{formatPHP(unsigned(review.net))}</p>
              </div>
            </div>
          </Card>

          {review.budget && (
            <Card className="mt-3 space-y-1">
              <p className="label text-ink-2">The budget</p>
              {negative(review.budget.remaining) ? (
                <p className="text-headline text-danger">Over by <span className="num">{formatPHP(unsigned(review.budget.remaining))}</span></p>
              ) : (
                <p className="text-headline text-ok">Under by <span className="num">{formatPHP(review.budget.remaining)}</span></p>
              )}
              <p className="text-footnote text-ink-2">
                <span className="num">{formatPHP(review.budget.spent)}</span> of <span className="num">{formatPHP(review.budget.available)}</span>
                {!zero(review.budget.carried_in) && <> · <span className="num">{formatPHP(review.budget.carried_in)}</span> carried in</>}
              </p>
              {review.budget.carry_over && (
                <p className="text-footnote text-ink-3">
                  {negative(review.budget.remaining) ? 'The next period started that much short.' : 'What was left carried into the next period.'}
                </p>
              )}
            </Card>
          )}

          {review.changes.length > 0 && (
            <>
              <SectionTitle>What changed most</SectionTitle>
              <ListGroup>
                {review.changes.map((c) => {
                  const found = category(c.category_id);
                  const up = !negative(c.change);
                  return (
                    <div key={c.category_id ?? 'none'} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                      <GlyphTile icon={found?.icon ?? 'tag'} colour={found?.colour ?? NEUTRAL} size={36} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body">{found?.name ?? 'Uncategorised'}</span>
                        <span className="block truncate text-footnote text-ink-2">
                          <span className="num">{formatPHP(c.amount)}</span>, was <span className="num">{formatPHP(c.previous)}</span>
                        </span>
                      </span>
                      <span className={`num shrink-0 text-body ${up ? 'text-danger' : 'text-ok'}`}>
                        {up ? '▲' : '▼'} {formatPHP(unsigned(c.change))}
                      </span>
                    </div>
                  );
                })}
              </ListGroup>
            </>
          )}

          {review.purchases.length > 0 && (
            <>
              <SectionTitle>Biggest purchases</SectionTitle>
              <ListGroup>
                {review.purchases.map((p) => {
                  const found = category(p.category_id);
                  return (
                    <div key={p.transaction_id} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                      <GlyphTile icon={found?.icon ?? 'cart'} colour={found?.colour ?? NEUTRAL} size={36} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body">{p.merchant || found?.name || 'A purchase'}</span>
                        <span className="block truncate text-footnote text-ink-2">{format(parseISO(p.on), 'd MMM')}</span>
                      </span>
                      <span className="num shrink-0 text-body">{formatPHP(p.amount)}</span>
                    </div>
                  );
                })}
              </ListGroup>
            </>
          )}

          {review.plans.length > 0 && (
            <>
              <SectionTitle>Plans and subscriptions</SectionTitle>
              <ListGroup>
                {review.plans.map((e, i) => (
                  <div key={`${e.rule_id}-${e.event}-${i}`} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body">{e.name}</span>
                      <span className="block truncate text-footnote text-ink-2">
                        {EVENT[e.event]} {format(parseISO(e.on), 'd MMM')}
                        {e.event === 'price' && e.previous_amount && <> · was <span className="num">{formatPHP(e.previous_amount)}</span></>}
                      </span>
                    </span>
                    {e.amount && <span className="num shrink-0 text-body">{formatPHP(e.amount)}</span>}
                  </div>
                ))}
              </ListGroup>
            </>
          )}

          {(!zero(review.cashback) || !zero(review.interest)) && (
            <>
              <SectionTitle>Money back</SectionTitle>
              <Card className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-footnote text-ink-2">Cashback</p>
                  <p className="num text-headline">{formatPHP(review.cashback)}</p>
                </div>
                <div>
                  <p className="text-footnote text-ink-2">Savings interest</p>
                  <p className="num text-headline">{formatPHP(review.interest)}</p>
                </div>
              </Card>
            </>
          )}

          <SectionTitle>Cash on hand</SectionTitle>
          <Card className="space-y-1">
            <p className="text-body">
              <span className="num">{formatPHP(review.cash_start)}</span>
              <span className="text-ink-3"> → </span>
              <span className="num font-bold">{formatPHP(review.cash_end)}</span>
            </p>
            <CashChange start={review.cash_start} end={review.cash_end} />
            <p className="text-caption text-ink-3">The accounts counted in cash on hand today, at their plain balances.</p>
          </Card>
        </>
      )}
    </>
  );
}

function SpentAgainst({ review }: { review: ReviewData }) {
  const now = centavos(review.spent);
  const before = centavos(review.previous_spent);
  if (before === 0) return <p className="text-footnote text-ink-2">Nothing spent the period before.</p>;
  const difference = fromCentavos(now - before);
  const less = now < before;
  return (
    <p className="text-footnote text-ink-2">
      <span className={`num font-semibold ${less ? 'text-ok' : 'text-danger'}`}>{formatPHP(unsigned(difference))}</span>
      {less ? ' less' : ' more'} than the period before (<span className="num">{formatPHP(review.previous_spent)}</span>)
    </p>
  );
}

function CashChange({ start, end }: { start: string; end: string }) {
  const change = fromCentavos(centavos(end) - centavos(start));
  if (zero(change)) return <p className="text-footnote text-ink-2">No change over the period.</p>;
  return (
    <p className={`text-footnote ${negative(change) ? 'text-danger' : 'text-ok'}`}>
      {negative(change) ? 'Down' : 'Up'} <span className="num">{formatPHP(unsigned(change))}</span> over the period
    </p>
  );
}
