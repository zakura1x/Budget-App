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
 */
import { create } from 'zustand';
import {
  listTransactions,
  type DayTotal,
  type Filters,
  type Outcome,
  type Transaction,
} from '../lib/transactions';

const PENDING_BASE = -1;

interface LedgerState {
  items: Transaction[];
  days: Record<string, DayTotal>;
  cursor: string | null;
  total: number;
  filters: Filters;
  loading: boolean;
  error: string | null;
  /** Bumped on every successful write, so screens showing balances can refetch. */
  version: number;
  nextPendingId: number;

  load: (filters?: Filters) => Promise<void>;
  loadMore: () => Promise<void>;
  applyOutcome: (outcome: Outcome, replacedId?: number) => void;
  removeIds: (ids: number[]) => void;
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

  load: async (filters) => {
    const next = filters ?? get().filters;
    set({ loading: true, error: null, filters: next });
    try {
      const page = await listTransactions(next);
      set({
        items: page.items,
        days: Object.fromEntries(page.days.map((d) => [d.on, d])),
        cursor: page.next_cursor,
        total: page.total_count,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
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
    set((s) => {
      const incoming = outcome.transactions.filter((row) => visible(row, s.filters));
      const drop = new Set([...outcome.transactions.map((t) => t.id), ...(replacedId !== undefined ? [replacedId] : [])]);
      return {
        items: ordered([...s.items.filter((row) => !drop.has(row.id)), ...incoming]),
        version: s.version + 1,
      };
    });
    // Day subtotals are the server's to compute; refresh them quietly.
    void get().load();
  },

  removeIds: (ids) => {
    set((s) => ({ items: s.items.filter((row) => !ids.includes(row.id)), version: s.version + 1 }));
    void get().load();
  },

  addPending: (row) => {
    const id = get().nextPendingId;
    set((s) => ({ items: ordered([{ ...row, id }, ...s.items]), nextPendingId: id - 1 }));
    return id;
  },

  failPending: (id) => set((s) => ({ items: s.items.filter((row) => row.id !== id) })),

  reset: () => set({ ...empty, version: get().version + 1 }),
}));

export const isPending = (row: Transaction) => row.id < 0;
