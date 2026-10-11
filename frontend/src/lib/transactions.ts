/**
 * /transactions - types and calls.
 *
 * Amounts are strings, from the numpad to the wire and back (money.ts). Every
 * transaction carries `splits`; a simple one has exactly one (TXN-16).
 *
 * Every write resolves to an Outcome: the rows written, the accounts they
 * touched with their new balances, and cash on hand - so the screen that made
 * the change never has to ask again.
 */
import { api } from './api';
import type { Account, CashOnHand } from './accounts';
import type { BudgetStatus } from './budgets';

/** What can be entered. */
export type EntryType = 'expense' | 'income' | 'transfer';
/**
 * What the ledger can show. A balance adjustment (ACC-29) is never entered: it
 * comes from setting an account's balance, and can be deleted but not edited.
 */
export type TransactionType = EntryType | 'adjustment';

export interface Split {
  category_id: number | null;
  amount: string;
  note: string | null;
}

/**
 * TXN-22 - cashback on a purchase. The purchase keeps its full amount; this is
 * a real income row beside it, on the account and day chosen.
 */
export interface Cashback {
  amount: string;
  account_id: number;
  category_id: number;
  on: string;
  /** Where the amount came from ("2% back"); nothing recomputes from it. */
  rate: string | null;
}

export interface CashbackDraft {
  amount: string;
  category_id: number;
  account_id?: number;
  on?: string;
  rate?: string | null;
}

export interface Transaction {
  id: number;
  type: TransactionType;
  txn_date: string;
  amount: string;
  account_id: number;
  splits: Split[];
  merchant: string | null;
  notes: string | null;
  direction: 'out' | 'in' | null;
  counter_account_id: number | null;
  pair_id: number | null;
  /** TXN-10 - always empty on a transfer or an adjustment. */
  tag_ids: number[];
  /** REC-04 - the rule that posted it, or the installment it pays. */
  recurring_id?: number | null;
  recurring_on?: string | null;
  /** ACC-37 - the day of savings interest this credited; set only by the server. */
  interest_on?: string | null;
  /** TXN-22 - what this purchase earns back. */
  cashback?: Cashback | null;
  /** The income row that credits it; and, on that row, the purchase it came from. */
  cashback_id?: number | null;
  cashback_of?: number | null;
  /** TXN-15 - the receipt, if one is attached. */
  attachment_id?: number | null;
  created_at: string | null;
  /** ACC-26 - the day the bank posted it, when that moved it to a later statement. */
  card_posted_on?: string | null;
}

export interface DayTotal {
  on: string;
  spent: string;
  earned: string;
}

export interface Page {
  items: Transaction[];
  next_cursor: string | null;
  total_count: number;
  days: DayTotal[];
}

export interface Outcome {
  transactions: Transaction[];
  accounts: Account[];
  cash_on_hand: CashOnHand;
  /** The current period, recomputed by this write - null with no budget. */
  budget_status: BudgetStatus | null;
}

export interface TransactionDraft {
  type: EntryType;
  amount: string;
  account_id: number;
  txn_date: string;
  category_id?: number;
  splits?: { category_id: number; amount: string; note?: string | null }[];
  counter_account_id?: number;
  merchant?: string | null;
  notes?: string | null;
  tag_ids?: number[];
  /**
   * TXN-22. Left out, an edit keeps the cashback that is there; sent as null it
   * removes it and the credit row with it.
   */
  cashback?: CashbackDraft | null;
}

export interface Filters {
  from?: string;
  to?: string;
  category?: number;
  account?: number;
  tag?: number;
  type?: TransactionType;
  q?: string;
}

function query(filters: Filters, cursor?: string | null, limit = 50): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null) params.set(key, String(value));
  }
  if (cursor) params.set('cursor', cursor);
  params.set('limit', String(limit));
  return params.toString();
}

/** `limit` is 1-200 on the server; an account's trail asks for a full 200. */
export const listTransactions = (filters: Filters, cursor?: string | null, signal?: AbortSignal, limit = 50) =>
  api<Page>(`/transactions?${query(filters, cursor, limit)}`, { signal });

export const getTransaction = (id: number, signal?: AbortSignal) => api<Transaction>(`/transactions/${id}`, { signal });

export const createTransaction = (body: TransactionDraft) =>
  api<Outcome>(`/transactions?today=${localToday()}`, { method: 'POST', body });

export const updateTransaction = (id: number, body: TransactionDraft) =>
  api<Outcome>(`/transactions/${id}?today=${localToday()}`, { method: 'PATCH', body });

export const deleteTransaction = (id: number) =>
  api<Outcome>(`/transactions/${id}?today=${localToday()}`, { method: 'DELETE' });

/**
 * TXN-24 - a merchant typed before, and the category its LATEST entry was
 * filed under (null when that entry was split, or its category is archived).
 */
export interface Merchant {
  name: string;
  type: 'expense' | 'income';
  count: number;
  category_id: number | null;
  last_used: string;
}

export const listMerchants = (signal?: AbortSignal) => api<Merchant[]>('/transactions/merchants', { signal });

/** TXN-25 - one line of Recently deleted. `reason` says why Restore is not offered. */
export interface Deleted {
  transaction: Transaction;
  deleted_at: string;
  restorable: boolean;
  reason: string | null;
}

export const listDeleted = (signal?: AbortSignal) => api<Deleted[]>('/transactions/deleted', { signal });

/** TXN-25 - Undo, and Restore. Brings back whatever went with it: a transfer's other leg, a purchase's cashback. */
export const restoreTransaction = (id: number) =>
  api<Outcome>(`/transactions/${id}/restore?today=${localToday()}`, { method: 'POST' });

/** Today in the user's own timezone, as the API's date string. */
export function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
