import { format } from 'date-fns';
import { PhaseNote, ScreenHeader } from '../components/ScreenHeader';
import { Card } from '../components/ui/Card';
import { Ring } from '../components/ui/Ring';
import { useAuthStore } from '../stores/authStore';

/**
 * The home screen. In Phase 5 the ring shows the real period, and the hero
 * line becomes "You can spend ₱612 today". Until then it shows the layout,
 * with no figures - there are none yet, and a made-up number on a budget
 * app's home screen is worse than none.
 */
export function Home() {
  const today = new Date();
  const name = useAuthStore((s) => s.session?.user.display_name);
  return (
    <>
      <ScreenHeader
        title={name ? `Hi, ${name}` : 'Budget'}
        subtitle={format(today, 'EEEE, d MMMM')}
      />

      <Card className="flex flex-col items-center py-7">
        <Ring progress={0} label="No budget yet">
          <span className="text-footnote font-medium text-ink-2">You can spend today</span>
          <span className="num mt-1 text-display text-ink-3">—</span>
          <span className="mt-1 text-caption text-ink-3">no budget set</span>
        </Ring>
        <div className="mt-6 grid w-full grid-cols-2 divide-x divide-line text-center">
          <div>
            <p className="text-caption uppercase tracking-wide text-ink-3">Spent</p>
            <p className="num text-headline text-ink-3">—</p>
          </div>
          <div>
            <p className="text-caption uppercase tracking-wide text-ink-3">Remaining</p>
            <p className="num text-headline text-ink-3">—</p>
          </div>
        </div>
      </Card>

      <PhaseNote phase="5">Your budget, the daily allowance and the ring. Transactions arrive in Phase 4.</PhaseNote>
    </>
  );
}
