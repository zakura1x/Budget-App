/**
 * UI state only. Stores in this app never hold the DEK, tokens, or any
 * decrypted figure beyond what is on screen - and none of them persist to
 * browser storage (SEC-29).
 */
import { create } from 'zustand';
import type { Rule, RuleDraft, RuleKind } from '../lib/recurring';
import type { EntryType, Transaction } from '../lib/transactions';

/** The one rule sheet the + button and a card's page share (REC-31): a new rule of a kind, or an existing rule. */
export interface RuleSheetRequest {
  kind: RuleKind;
  rule: Rule | null;
  prefill: RuleDraft | null;
}

/** What a NEW entry starts as, when the screen opening the sheet knows - "a purchase I forgot" on a card. */
export interface AddPreset {
  accountId?: number;
  /** A transfer INTO this account - paying back a loan, lending more (ACC-31). */
  counterAccountId?: number;
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
  /**
   * TXN-23 (2026-09-20, user). The transaction being LOOKED at: tapping a row
   * anywhere opens this read-only preview, and its Edit button opens the sheet.
   * A tap used to open the editor itself, which made a glance at an entry a
   * chance to change it.
   */
  preview: Transaction | null;
  openPreview: (row: Transaction) => void;
  closePreview: () => void;
  ruleSheet: RuleSheetRequest | null;
  openRuleSheet: (request: RuleSheetRequest) => void;
  closeRuleSheet: () => void;
  /** ACC-36. Which headline the Accounts tab shows - in memory only, back to cash on hand after a lock. */
  headline: 'cash' | 'net';
  setHeadline: (headline: 'cash' | 'net') => void;
  /**
   * TXN-25. The entry just deleted, for the Undo toast - in memory for a few
   * seconds and then gone; Recently deleted under More keeps it for 30 days.
   */
  undo: { id: number; label: string } | null;
  offerUndo: (id: number, label: string) => void;
  clearUndo: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  addSheetOpen: false,
  editing: null,
  addOn: null,
  addPreset: null,
  // Opening the editor closes the preview it was opened from: one sheet at a time.
  openAddSheet: (editing, on, preset) =>
    set({ addSheetOpen: true, editing: editing ?? null, addOn: on ?? null, addPreset: preset ?? null, preview: null }),
  closeAddSheet: () => set({ addSheetOpen: false, editing: null, addOn: null, addPreset: null }),
  preview: null,
  openPreview: (row) => set({ preview: row }),
  closePreview: () => set({ preview: null }),
  ruleSheet: null,
  // Opening a rule closes the add sheet: two sheets stacked would fight over the page's scroll lock.
  openRuleSheet: (request) =>
    set({ ruleSheet: request, addSheetOpen: false, editing: null, addOn: null, addPreset: null, preview: null }),
  closeRuleSheet: () => set({ ruleSheet: null }),
  headline: 'cash',
  setHeadline: (headline) => set({ headline }),
  undo: null,
  offerUndo: (id, label) => set({ undo: { id, label } }),
  clearUndo: () => set({ undo: null }),
}));
