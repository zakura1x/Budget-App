/**
 * The budget status the home screen is drawn from - in page memory only, and
 * cleared when the app locks or signs out (SEC-29).
 *
 * `on` is the period being looked at: null means the current one. A write's
 * Outcome carries the CURRENT period's status; it replaces what is shown only
 * when the current period is what is shown, so browsing last month and adding
 * a coffee does not yank the screen back to today.
 */
import { create } from 'zustand';
import { getStatus, type BudgetStatus } from '../lib/budgets';

interface BudgetState {
  status: BudgetStatus | null;
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
  currentAlerts: 0,
  on: null,
  loaded: false,
  loading: false,
  error: null,

  load: async (on) => {
    const target = on === undefined ? get().on : on;
    set({ loading: true, error: null, on: target });
    try {
      const { status } = await getStatus(target);
      set((s) => ({
        status,
        loaded: true,
        loading: false,
        currentAlerts: !status ? 0 : status.is_current ? status.alerts.length : s.currentAlerts,
      }));
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  acceptOutcome: (status) => {
    if (status === undefined) return;
    set((s) => ({
      status: s.on === null ? status : s.status,
      currentAlerts: status ? status.alerts.length : 0,
      loaded: true,
    }));
  },

  reset: () => set({ status: null, currentAlerts: 0, on: null, loaded: false, loading: false, error: null }),
}));
