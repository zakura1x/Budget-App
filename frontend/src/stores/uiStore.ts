/**
 * UI state only. Stores in this app never hold the DEK, tokens, or any
 * decrypted figure beyond what is on screen - and none of them persist to
 * browser storage (SEC-29).
 */
import { create } from 'zustand';
import type { Transaction } from '../lib/transactions';

interface UiState {
  addSheetOpen: boolean;
  /** The transaction the sheet is editing, or null when adding a new one. */
  editing: Transaction | null;
  openAddSheet: (editing?: Transaction) => void;
  closeAddSheet: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  addSheetOpen: false,
  editing: null,
  openAddSheet: (editing) => set({ addSheetOpen: true, editing: editing ?? null }),
  closeAddSheet: () => set({ addSheetOpen: false, editing: null }),
}));
