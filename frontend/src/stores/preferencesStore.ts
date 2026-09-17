/**
 * The user's preferences while unlocked - theme, week start, auto-lock. Loaded
 * after unlock, dropped on lock and sign-out, never persisted (SEC-29): they
 * come from the API, so they live in memory like everything else it returns.
 */
import { create } from 'zustand';
import { getPreferences, updatePreferences, type Preferences } from '../lib/budgets';
import { applyTheme } from '../lib/pwa';

interface PreferencesState {
  prefs: Preferences | null;
  load: () => Promise<void>;
  change: (changes: Partial<Preferences>) => Promise<void>;
  /**
   * Drop the preferences. `keepTheme` leaves the theme on the page: locking
   * is the same person stepping away, so the PIN screen should still look the
   * way they chose (2026-09-16, user). Signing out clears it - the next person
   * to sign in on this device gets the device's own setting.
   */
  reset: (options?: { keepTheme?: boolean }) => void;
}

export const usePreferencesStore = create<PreferencesState>((set, get) => ({
  prefs: null,

  load: async () => {
    try {
      const prefs = await getPreferences();
      set({ prefs });
      applyTheme(prefs.theme);
    } catch {
      /* the screens that need them load their own */
    }
  },

  change: async (changes) => {
    const previous = get().prefs;
    if (previous) set({ prefs: { ...previous, ...changes } }); // the control moves at once
    if (changes.theme) applyTheme(changes.theme);
    try {
      const prefs = await updatePreferences(changes);
      set({ prefs });
      applyTheme(prefs.theme);
    } catch (e) {
      set({ prefs: previous });
      applyTheme(previous?.theme);
      throw e;
    }
  },

  reset: ({ keepTheme = false } = {}) => {
    set({ prefs: null });
    if (!keepTheme) applyTheme(null);
  },
}));
