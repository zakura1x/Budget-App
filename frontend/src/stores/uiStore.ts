/**
 * UI state only. Stores in this app never hold the DEK, tokens, or any
 * decrypted figure beyond what is on screen - and none of them persist to
 * browser storage (SEC-29).
 */
import { create } from 'zustand';

interface UiState {
  addSheetOpen: boolean;
  openAddSheet: () => void;
  closeAddSheet: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  addSheetOpen: false,
  openAddSheet: () => set({ addSheetOpen: true }),
  closeAddSheet: () => set({ addSheetOpen: false }),
}));
