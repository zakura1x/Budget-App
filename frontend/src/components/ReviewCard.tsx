/**
 * STA-12 - "August is over. See how it went?" on Home, in the first days of a
 * new period. "Not now" is kept in the preferences on the server, so it is not
 * asked again for that period on any device.
 */
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { afterWrite } from '../lib/invalidate';
import { keys, STALE } from '../lib/queryKeys';
import { dismissReview, getReviewOffer } from '../lib/stats';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

export function ReviewCard() {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: keys.reviewOffer(),
    queryFn: ({ signal }) => getReviewOffer(signal),
    staleTime: STALE.derived,
  });
  const [busy, setBusy] = useState(false);
  const period = data?.period;
  if (!period) return null;

  const name = period.span === 'month'
    ? format(parseISO(period.start), 'MMMM')
    : `${format(parseISO(period.start), 'd MMM')} – ${format(parseISO(period.end), 'd MMM')}`;
  const notNow = async () => {
    setBusy(true);
    try {
      await dismissReview();
      afterWrite('stats', 'preferences');
    } catch {
      /* the card simply stays; nothing was lost */
    }
    setBusy(false);
  };

  return (
    <Card className="mb-3 space-y-3">
      <div>
        <p className="text-headline">{name} is over</p>
        <p className="text-footnote text-ink-2">See how it went - what you spent, what changed, and where the budget ended up.</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Button onClick={() => navigate(`/review?on=${period.start}`)}>See the review</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void notNow()}>Not now</Button>
      </div>
    </Card>
  );
}
