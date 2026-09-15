/**
 * UI state only. Stores in this app never hold the DEK, tokens, or any
 * decrypted figure beyond what is on screen - and none of them persist to
 * browser storage (SEC-29).
 */
import { create } from 'zustand';
import type { EntryType, Transaction } from '../lib/transactions';

/** What a NEW entry starts as, when the screen opening the sheet knows - "a purchase I forgot" on a card. */
export interface AddPreset {
  accountId?: number;
  type?: EntryType;
}

interface UiState {
  addSheetOpen: boolean;
  /** The transaction the sheet is editing, or null when adding a new one. */
  editing: Transaction | null;
  /** The date a new entry starts on - a day tapped in the calendar - or null for today. */
  addOn: string | null;
  addPreset: AddPreset | null;
  openAddSheet: (editing?: Transaction, on?: string, preset?: AddPreset) => void;
  closeAddSheet: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  addSheetOpen: false,
  editing: null,
  addOn: null,
  addPreset: null,
  openAddSheet: (editing, on, preset) =>
    set({ addSheetOpen: true, editing: editing ?? null, addOn: on ?? null, addPreset: preset ?? null }),
  closeAddSheet: () => set({ addSheetOpen: false, editing: null, addOn: null, addPreset: null }),
}));
