import { format } from 'date-fns';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { PhaseNote, ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { Card, SectionTitle } from '../components/ui/Card';
import { Ring } from '../components/ui/Ring';
import { useLookups } from '../hooks/useLookups';
import { useAuthStore } from '../stores/authStore';
import { useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';

const RECENT = 5;

/**
 * The home screen. In Phase 5 the ring shows the real period, and the hero
 * line becomes "You can spend ₱612 today". Until then it shows the layout,
 * with no figures - there are none yet, and a made-up number on a budget
 * app's home screen is worse than none.
 *
 * Below it, the last few entries: the proof that the one you just added
 * landed, one glance away from the [+] that added it.
 */
export function Home() {
  const today = new Date();
  const navigate = useNavigate();
  const name = useAuthStore((s) => s.session?.user.display_name);
  const { items, filters, load, error } = useLedgerStore();
  const openSheet = useUiStore((s) => s.openAddSheet);
  const lookups = useLookups();

  // Home always shows the unfiltered ledger, whatever the ledger screen left behind.
  useEffect(() => {
    const filtered = Object.values(filters).some((v) => v !== undefined);
    if (filtered || items.length === 0) void load({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const recent = items.slice(0, RECENT);

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

      {error && <p className="mt-4 rounded-2xl bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      <div className="flex items-end justify-between">
        <SectionTitle>Recent</SectionTitle>
        {items.length > 0 && (
          <button type="button" onClick={() => navigate('/transactions')}
            className="min-h-tap px-1 text-footnote font-semibold text-accent">
            See all
          </button>
        )}
      </div>
      {recent.length > 0 ? (
        <div className="divide-y divide-line overflow-hidden rounded-card bg-surface shadow-card">
          {recent.map((row) => (
            <button key={row.id} type="button" onClick={() => row.id > 0 && openSheet(row)}
              className="block w-full transition active:bg-surface-2">
              <TransactionRow row={row} lookups={lookups} />
            </button>
          ))}
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-line px-4 py-3 text-footnote text-ink-2">
          Nothing yet. Tap + and type an amount — that is the whole entry.
        </p>
      )}

      <PhaseNote phase="5">Your budget, the daily allowance and the ring.</PhaseNote>
    </>
  );
}
