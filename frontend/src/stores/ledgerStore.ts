/**
 * The ledger as the screen holds it - decrypted rows the API returned, kept
 * in page memory only.
 *
 * Nothing here is persisted (SEC-29), and `reset()` is called the moment the
 * app locks or signs out: the working set on the server is dropped with the
 * key, and the copy in the page must go with it.
 *
 * Optimistic insert: `addPending` shows a row before the response lands; the
 * response replaces it, or `failPending` takes it back out.
 *
 * `load` SKIPS the request when the same filters were fetched within the
 * minute (misc/UX_RESPONSIVENESS_PLAN.md step 4), so opening Home again costs
 * nothing. Every write forces it - `afterWrite('transactions')`, and the
 * `Outcome` paths below - so what is on screen can only lag another tab.
 */
import { create } from 'zustand';
import {
  listTransactions,
  type DayTotal,
  type Filters,
  type Outcome,
  type Transaction,
} from '../lib/transactions';
import { invalidateGroups, MONEY } from '../lib/queryKeys';
import { useBudgetStore } from './budgetStore';

const PENDING_BASE = -1;

/** How long the same filtered page is trusted without asking again. */
const FRESH_MS = 60_000;

const freshnessKey = (filters: Filters) =>
  JSON.stringify([filters.from, filters.to, filters.category, filters.account, filters.tag, filters.type, filters.q]);

/**
 * The request for each set of filters while it is in the air. Prefetching on a
 * tab press and the screen mounting 100 ms later both ask before either answer
 * lands, so neither sees the other's marker - the second one is waste (seen in
 * logs/app.jsonl, 2026-09-20). React Query dedupes its own keys; this store is
 * not a query, so it does it here.
 */
const inFlight = new Map<string, Promise<void>>();

interface LedgerState {
  items: Transaction[];
  days: Record<string, DayTotal>;
  cursor: string | null;
  total: number;
  filters: Filters;
  loading: boolean;
  error: string | null;
  /** Bumped on every successful write. One reader left: the account page's trail. */
  version: number;
  nextPendingId: number;
  /** The filters last fetched, and when - so an unchanged, fresh page is not asked for again. */
  fetchedKey: string | null;
  fetchedAt: number;

  load: (filters?: Filters, options?: { force?: boolean }) => Promise<void>;
  loadMore: () => Promise<void>;
  applyOutcome: (outcome: Outcome, replacedId?: number) => void;
  removeIds: (ids: number[], outcome?: Outcome) => void;
  addPending: (row: Omit<Transaction, 'id'>) => number;
  failPending: (id: number) => void;
  reset: () => void;
}

const empty = {
  items: [] as Transaction[],
  days: {} as Record<string, DayTotal>,
  cursor: null,
  total: 0,
  filters: {} as Filters,
  loading: false,
  error: null,
  nextPendingId: PENDING_BASE,
  fetchedKey: null,
  fetchedAt: 0,
};

/** Newest first, then newest id - the server's order, kept locally. */
const ordered = (rows: Transaction[]) =>
  [...rows].sort((a, b) => (a.txn_date === b.txn_date ? b.id - a.id : a.txn_date < b.txn_date ? 1 : -1));

/** The ledger shows a transfer once, as its out leg - the same rule as the server. */
const visible = (row: Transaction, filters: Filters) =>
  row.type !== 'transfer' || filters.account !== undefined || row.direction === 'out';

export const useLedgerStore = create<LedgerState>((set, get) => ({
  ...empty,
  version: 0,

  load: async (filters, options) => {
    const next = filters ?? get().filters;
    const key = freshnessKey(next);
    // The same page, asked for again within the minute: keep what is on screen.
    if (!options?.force && key === get().fetchedKey && Date.now() - get().fetchedAt < FRESH_MS) return;

    const pending = inFlight.get(key);
    // The same question, already asked: wait for that answer instead of a second one.
    if (pending && !options?.force) return pending;

    set({ loading: true, error: null, filters: next });
    const run = async () => {
      try {
        const page = await listTransactions(next);
        set({
          items: page.items,
          days: Object.fromEntries(page.days.map((d) => [d.on, d])),
          cursor: page.next_cursor,
          total: page.total_count,
          loading: false,
          fetchedKey: key,
          fetchedAt: Date.now(),
        });
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    };
    // A forced reload queues BEHIND anything in flight, so the rows that land
    // last are the ones read after the write, never the ones from before it.
    const request = pending ? pending.then(run, run) : run();
    inFlight.set(key, request);
    try {
      await request;
    } finally {
      if (inFlight.get(key) === request) inFlight.delete(key);
    }
  },

  loadMore: async () => {
    const { cursor, filters, loading } = get();
    if (!cursor || loading) return;
    set({ loading: true });
    try {
      const page = await listTransactions(filters, cursor);
      set((s) => ({
        items: [...s.items, ...page.items.filter((row) => !s.items.some((have) => have.id === row.id))],
        days: { ...s.days, ...Object.fromEntries(page.days.map((d) => [d.on, d])) },
        cursor: page.next_cursor,
        total: page.total_count,
        loading: false,
      }));
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  applyOutcome: (outcome, replacedId) => {
    useBudgetStore.getState().acceptOutcome(outcome.budget_status);
    // The rows and the allowance are already in hand, from the Outcome; every
    // other cached figure the write moved - balances, the calendar day, the
    // stats slice, a plan's remaining - has to be asked for again.
    invalidateGroups(MONEY);
    set((s) => {
      const incoming = outcome.transactions.filter((row) => visible(row, s.filters));
      const drop = new Set([...outcome.transactions.map((t) => t.id), ...(replacedId !== undefined ? [replacedId] : [])]);
      return {
        items: ordered([...s.items.filter((row) => !drop.has(row.id)), ...incoming]),
        version: s.version + 1,
      };
    });
    // Day subtotals are the server's to compute; refresh them quietly.
    void get().load(undefined, { force: true });
  },

  removeIds: (ids, outcome) => {
    if (outcome) useBudgetStore.getState().acceptOutcome(outcome.budget_status);
    invalidateGroups(MONEY);
    set((s) => ({ items: s.items.filter((row) => !ids.includes(row.id)), version: s.version + 1 }));
    void get().load(undefined, { force: true });
  },

  addPending: (row) => {
    const id = get().nextPendingId;
    set((s) => ({ items: ordered([{ ...row, id }, ...s.items]), nextPendingId: id - 1 }));
    return id;
  },

  failPending: (id) => set((s) => ({ items: s.items.filter((row) => row.id !== id) })),

  reset: () => {
    inFlight.clear(); // nothing asked before the lock may be joined after it
    set({ ...empty, version: get().version + 1 });
  },
}));

export const isPending = (row: Transaction) => row.id < 0;
