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
  reset: () => void;
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

  reset: () => {
    set({ prefs: null });
    applyTheme(null);
  },
}));
