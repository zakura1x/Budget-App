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
 */
import { create } from 'zustand';
import { getStatus, type Alert, type BudgetStatus } from '../lib/budgets';

interface BudgetState {
  status: BudgetStatus | null;
  alerts: Alert[];
  /** The alerts of the CURRENT period, whatever period is on screen - the tab-bar badge reads these. */
  currentAlerts: number;
  on: string | null;
  loaded: boolean;
  loading: boolean;
  error: string | null;

  load: (on?: string | null) => Promise<void>;
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

  load: async (on) => {
    const target = on === undefined ? get().on : on;
    set({ loading: true, error: null, on: target });
    try {
      const { status, alerts } = await getStatus(target);
      set((s) => ({
        status,
        alerts: status ? [] : alerts ?? [],
        loaded: true,
        loading: false,
        currentAlerts: !status ? (alerts ?? []).length : status.is_current ? status.alerts.length : s.currentAlerts,
      }));
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  acceptOutcome: (status) => {
    if (status === undefined) return;
    set((s) => ({
      status: s.on === null ? status : s.status,
      currentAlerts: status ? status.alerts.length : s.alerts.length,
      loaded: true,
    }));
  },

  reset: () => set({ status: null, alerts: [], currentAlerts: 0, on: null, loaded: false, loading: false, error: null }),
}));
