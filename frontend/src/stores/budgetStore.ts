/**
 * The budget status the home screen is drawn from - in page memory only, and
 * cleared when the app locks or signs out (SEC-29).
 *
 * `on` is the period being looked at: null means the current one. A write's
 * Outcome carries the CURRENT period's status; it replaces what is shown only
 * when the current period is what is shown, so browsing last month and adding
 * a coffee does not yank the screen back to today.
 *
 * `alerts` are today's alerts when there is NO budget - a card's bill, a
 * subscription, a statement that does not match - which need no budget to
 * matter. With a budget they arrive inside `status` as before.
 *
 * `load` SKIPS the request when what is on screen is still fresh
 * (misc/UX_RESPONSIVENESS_PLAN.md step 4): `/budgets/current` is the slowest
 * call in the app at ~600 ms, and Home asked for it on every single visit.
 * Every write forces it instead (`afterWrite` -> `load(null, { force: true })`),
 * so skipping can only ever hide another tab's change for a minute.
 */
import { create } from 'zustand';
import { getStatus, type Alert, type BudgetStatus } from '../lib/budgets';
import { localToday } from '../lib/transactions';

/** How long a period's status is trusted without asking again. */
const FRESH_MS = 60_000;

/** A period is only "the same answer" on the same day - the server answers as of `today`. */
const freshnessKey = (on: string | null) => `${on ?? 'current'}:${localToday()}`;

/**
 * The request for each period while it is in the air. Freshness alone is not
 * enough: prefetching on a tab press and the screen mounting 100 ms later both
 * ask BEFORE either answer lands, so neither sees the other's marker and the
 * app asks twice (seen in logs/app.jsonl, 2026-09-20). React Query dedupes its
 * own keys this way; these two stores are not queries, so they do it here.
 */
const inFlight = new Map<string, Promise<void>>();

interface BudgetState {
  status: BudgetStatus | null;
  alerts: Alert[];
  /** The alerts of the CURRENT period, whatever period is on screen - the tab-bar badge reads these. */
  currentAlerts: number;
  on: string | null;
  loaded: boolean;
  loading: boolean;
  error: string | null;

  /** When each period was last fetched, by `freshnessKey`. */
  fetchedAt: Record<string, number>;

  load: (on?: string | null, options?: { force?: boolean }) => Promise<void>;
  acceptOutcome: (status: BudgetStatus | null | undefined) => void;
  reset: () => void;
}

export const useBudgetStore = create<BudgetState>((set, get) => ({
  status: null,
  alerts: [],
  currentAlerts: 0,
  on: null,
  loaded: false,
  loading: false,
  error: null,
  fetchedAt: {},

  load: async (on, options) => {
    const target = on === undefined ? get().on : on;
    const key = freshnessKey(target);
    const at = get().fetchedAt[key];
    // Already showing this period, fetched within the minute: nothing to ask.
    if (!options?.force && at !== undefined && Date.now() - at < FRESH_MS && get().on === target && get().loaded) return;

    const pending = inFlight.get(key);
    // The same question, already asked: wait for that answer instead of a second one.
    if (pending && !options?.force) return pending;

    set({ loading: true, error: null, on: target });
    const run = async () => {
      try {
        const { status, alerts } = await getStatus(target);
        set((s) => ({
          status,
          alerts: status ? [] : alerts ?? [],
          loaded: true,
          loading: false,
          fetchedAt: { ...s.fetchedAt, [key]: Date.now() },
          currentAlerts: !status ? (alerts ?? []).length : status.is_current ? status.alerts.length : s.currentAlerts,
        }));
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    };
    // A forced reload queues BEHIND anything in flight, so the answer that
    // lands last is the one taken after the write, never the one before it.
    const request = pending ? pending.then(run, run) : run();
    inFlight.set(key, request);
    try {
      await request;
    } finally {
      if (inFlight.get(key) === request) inFlight.delete(key);
    }
  },

  acceptOutcome: (status) => {
    if (status === undefined) return;
    set((s) => ({
      status: s.on === null ? status : s.status,
      currentAlerts: status ? status.alerts.length : s.alerts.length,
      loaded: true,
      // The write answered with the current period's status, so it is as good
      // as a fetch - Home does not have to ask again when it next opens.
      fetchedAt: s.on === null ? { ...s.fetchedAt, [freshnessKey(null)]: Date.now() } : s.fetchedAt,
    }));
  },

  reset: () => {
    inFlight.clear(); // nothing asked before the lock may be joined after it
    set({ status: null, alerts: [], currentAlerts: 0, on: null, loaded: false, loading: false, error: null, fetchedAt: {} });
  },
}));
