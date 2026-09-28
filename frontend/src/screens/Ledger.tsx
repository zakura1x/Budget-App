/**
 * The ledger (TXN-11..TXN-14).
 *
 * Grouped by day under sticky headers, each carrying that day's subtotal -
 * computed by the server over the whole filtered set, so a day that runs
 * across two pages still shows its real total. Transfers are in neither
 * figure; they move money, they do not spend it.
 *
 * Tap a row to edit it. Swipe it left for Edit and Delete. The list pages in
 * as it scrolls, over the server's warm working set - searching and filtering
 * never reach SQL, because SQL cannot see inside a payload.
 */
import { format, isToday, isYesterday, parseISO } from 'date-fns';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScreenHeader } from '../components/ScreenHeader';
import { TransactionRow } from '../components/TransactionRow';
import { offerUndo } from '../components/UndoToast';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Sheet } from '../components/ui/Sheet';
import { useLookups } from '../hooks/useLookups';
import { ApiError } from '../lib/api';
import { formatPHP } from '../lib/money';
import { deleteTransaction, type Filters, type Transaction, type TransactionType } from '../lib/transactions';
import { isPending, useLedgerStore } from '../stores/ledgerStore';
import { useUiStore } from '../stores/uiStore';

const REVEAL_PX = 152;

function dayLabel(on: string): string {
  const day = parseISO(on);
  if (isToday(day)) return 'Today';
  if (isYesterday(day)) return 'Yesterday';
  // The year only when it is not this one - "Fri 11 Sep", but "Tue 30 Dec 2025".
  return format(day, day.getFullYear() === new Date().getFullYear() ? 'EEE d MMM' : 'EEE d MMM yyyy');
}

/** A row that slides left to show Edit and Delete. Vertical drags stay a scroll. */
function SwipeRow({
  row,
  open,
  onOpen,
  onEdit,
  onDelete,
  children,
}: {
  row: Transaction;
  open: boolean;
  onOpen: (id: number | null) => void;
  onEdit: () => void;
  onDelete: () => void;
  children: React.ReactNode;
}) {
  const start = useRef<{ x: number; y: number; horizontal: boolean | null } | null>(null);
  const [dx, setDx] = useState(0);
  const offset = start.current?.horizontal ? dx : open ? -REVEAL_PX : 0;

  return (
    <div className="relative overflow-hidden bg-surface">
      <div className="absolute inset-y-0 right-0 flex" aria-hidden={!open}>
        <button type="button" tabIndex={open ? 0 : -1} onClick={onEdit}
          className="w-[76px] bg-surface-2 text-footnote font-semibold text-ink">
          Edit
        </button>
        <button type="button" tabIndex={open ? 0 : -1} onClick={onDelete}
          className="w-[76px] bg-danger text-footnote font-semibold text-white">
          Delete
        </button>
      </div>
      <button
        type="button"
        disabled={isPending(row)}
        onClick={() => (open ? onOpen(null) : onEdit())}
        onPointerDown={(e) => {
          start.current = { x: e.clientX, y: e.clientY, horizontal: null };
        }}
        onPointerMove={(e) => {
          const s = start.current;
          if (!s) return;
          const moveX = e.clientX - s.x;
          const moveY = e.clientY - s.y;
          if (s.horizontal === null && Math.hypot(moveX, moveY) > 8) s.horizontal = Math.abs(moveX) > Math.abs(moveY);
          if (s.horizontal) setDx(Math.max(-REVEAL_PX, Math.min(0, (open ? -REVEAL_PX : 0) + moveX)));
        }}
        onPointerUp={() => {
          const s = start.current;
          start.current = null;
          if (s?.horizontal) onOpen(dx < -REVEAL_PX / 2 ? row.id : null);
          setDx(0);
        }}
        onPointerCancel={() => {
          start.current = null;
          setDx(0);
        }}
        style={{ transform: `translateX(${offset}px)`, touchAction: 'pan-y' }}
        className="relative block w-full bg-surface transition-transform duration-200 ease-ios active:bg-surface-2"
      >
        {children}
      </button>
    </div>
  );
}

function FilterSheet({
  open,
  onClose,
  filters,
  onApply,
  lookups,
}: {
  open: boolean;
  onClose: () => void;
  filters: Filters;
  onApply: (next: Filters) => void;
  lookups: ReturnType<typeof useLookups>;
}) {
  const [draft, setDraft] = useState<Filters>(filters);
  useEffect(() => {
    if (open) setDraft(filters);
  }, [open, filters]);

  const pick = (key: 'account' | 'category' | 'tag', id: number) =>
    setDraft((d) => ({ ...d, [key]: d[key] === id ? undefined : id }));
  const chip = (selected: boolean) =>
    `min-h-tap rounded-xl px-3 text-footnote font-medium transition ${selected ? 'bg-accent text-on-accent shadow-edge' : 'bg-surface text-ink-2 shadow-edge active:bg-surface-2'}`;

  return (
    <Sheet open={open} onClose={onClose} title="Filter">
      <div className="space-y-5 pb-2">
        <Segmented<'all' | TransactionType>
          label="Type"
          value={draft.type ?? 'all'}
          onChange={(value) => setDraft((d) => ({ ...d, type: value === 'all' ? undefined : value }))}
          options={[
            { value: 'all', label: 'All' },
            { value: 'expense', label: 'Spent' },
            { value: 'income', label: 'Earned' },
            { value: 'transfer', label: 'Moved' },
            { value: 'adjustment', label: 'Adjusted' },
          ]}
        />
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Account</p>
          <div className="flex flex-wrap gap-2">
            {lookups.accounts.map((a) => (
              <button key={a.id} type="button" className={chip(draft.account === a.id)} onClick={() => pick('account', a.id)}>
                {a.name}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-footnote font-semibold text-ink-2">Category</p>
          <div className="flex flex-wrap gap-2">
            {lookups.tree.map((c) => (
              <button key={c.id} type="button" className={chip(draft.category === c.id)} onClick={() => pick('category', c.id)}>
                {c.name}
              </button>
            ))}
          </div>
          <p className="mt-2 text-footnote text-ink-3">A main category includes its sub-categories.</p>
        </div>
        {lookups.tags.length > 0 && (
          <div>
            <p className="mb-2 text-footnote font-semibold text-ink-2">Tag</p>
            <div className="flex flex-wrap gap-2">
              {lookups.tags.map((t) => (
                <button key={t.id} type="button" className={chip(draft.tag === t.id)} onClick={() => pick('tag', t.id)}>
                  {t.name}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <label className="text-footnote font-semibold text-ink-2">
            From
            <input type="date" value={draft.from ?? ''} onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value || undefined }))}
              className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
          </label>
          <label className="text-footnote font-semibold text-ink-2">
            To
            <input type="date" value={draft.to ?? ''} onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value || undefined }))}
              className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
          </label>
        </div>
        <Button block size="lg" onClick={() => { onApply({ ...draft, q: filters.q }); onClose(); }}>
          Show transactions
        </Button>
        <Button variant="ghost" block onClick={() => { onApply({ q: filters.q }); onClose(); }}>
          Clear filters
        </Button>
      </div>
    </Sheet>
  );
}

export function Ledger() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const { items, days, cursor, total, filters, loading, error, load, loadMore, removeIds } = useLedgerStore();
  const openSheet = useUiStore((s) => s.openAddSheet);
  const [search, setSearch] = useState(filters.q ?? '');
  const [openId, setOpenId] = useState<number | null>(null);
  const [filtering, setFiltering] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Search as you type, without a request per keystroke.
  useEffect(() => {
    if ((filters.q ?? '') === search) return;
    const timer = window.setTimeout(() => void load({ ...filters, q: search || undefined }), 250);
    return () => window.clearTimeout(timer);
  }, [search, filters, load]);

  // Page in as the end of the list comes into view.
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !cursor) return;
    const observer = new IntersectionObserver((entries) => entries[0]?.isIntersecting && void loadMore(), {
      rootMargin: '400px',
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [cursor, loadMore]);

  const remove = async (row: Transaction) => {
    setOpenId(null);
    try {
      const outcome = await deleteTransaction(row.id);
      removeIds(outcome.transactions.map((t) => t.id), outcome);
      offerUndo(row); // TXN-25
    } catch (e) {
      useLedgerStore.setState({ error: e instanceof ApiError ? e.message : 'That did not delete.' });
    }
  };

  const groups: { on: string; rows: Transaction[] }[] = [];
  for (const row of items) {
    const last = groups[groups.length - 1];
    if (last && last.on === row.txn_date) last.rows.push(row);
    else groups.push({ on: row.txn_date, rows: [row] });
  }

  const activeFilters = [filters.type, filters.account, filters.category, filters.tag, filters.from, filters.to].filter(
    (v) => v !== undefined,
  ).length;

  return (
    <>
      <ScreenHeader
        title="Transactions"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/')}>‹ Home</button>}
        action={
          <Button variant="secondary" onClick={() => setFiltering(true)}>
            Filter{activeFilters ? ` · ${activeFilters}` : ''}
          </Button>
        }
      />

      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search merchants and notes"
        aria-label="Search transactions"
        className="mb-3 min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3.5 text-body outline-none placeholder:text-ink-3 focus:shadow-[var(--lift)_var(--lift)_0_0_rgb(var(--c-shadow))]"
      />

      {error && (
        <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">
          {error}{' '}
          <button type="button" className="font-semibold underline" onClick={() => void load()}>
            Reload
          </button>
        </p>
      )}

      {!loading && items.length === 0 && !error && (
        <Card className="text-center">
          <p className="text-body">{activeFilters || filters.q ? 'Nothing matches.' : 'No transactions yet.'}</p>
          <p className="mt-1 text-footnote text-ink-2">
            {activeFilters || filters.q ? 'Try a different search or clear the filters.' : 'Tap + to add your first one.'}
          </p>
        </Card>
      )}

      {groups.map((group) => {
        const totals = days[group.on];
        return (
          <section key={group.on} className="mb-3">
            <h2 className="sticky top-0 z-10 -mx-4 flex items-baseline justify-between bg-bg/95 px-5 pb-1.5 pt-3 backdrop-blur">
              <span className="text-footnote font-semibold text-ink-2">{dayLabel(group.on)}</span>
              <span className="num text-footnote text-ink-3">
                {totals && totals.spent !== '0.00' && `−${formatPHP(totals.spent)}`}
                {totals && totals.spent !== '0.00' && totals.earned !== '0.00' && ' · '}
                {totals && totals.earned !== '0.00' && `+${formatPHP(totals.earned)}`}
              </span>
            </h2>
            <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
              {group.rows.map((row) => (
                <SwipeRow
                  key={row.id}
                  row={row}
                  open={openId === row.id}
                  onOpen={setOpenId}
                  onEdit={() => { setOpenId(null); openSheet(row); }}
                  onDelete={() => void remove(row)}
                >
                  <TransactionRow row={row} lookups={lookups} />
                </SwipeRow>
              ))}
            </div>
          </section>
        );
      })}

      <div ref={sentinel} className="h-px" />
      {loading && <p className="py-4 text-center text-footnote text-ink-3">Loading…</p>}
      {!cursor && items.length > 0 && (
        <p className="py-4 text-center text-footnote text-ink-3">
          {total} transaction{total === 1 ? '' : 's'}
        </p>
      )}

      <FilterSheet open={filtering} onClose={() => setFiltering(false)} filters={filters} onApply={(next) => void load(next)} lookups={lookups} />
    </>
  );
}
