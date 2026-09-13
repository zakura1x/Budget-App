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

export type TransactionType = 'expense' | 'income' | 'transfer';

export interface Split {
  category_id: number | null;
  amount: string;
  note: string | null;
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
  created_at: string | null;
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
}

export interface TransactionDraft {
  type: TransactionType;
  amount: string;
  account_id: number;
  txn_date: string;
  category_id?: number;
  splits?: { category_id: number; amount: string; note?: string | null }[];
  counter_account_id?: number;
  merchant?: string | null;
  notes?: string | null;
}

export interface Filters {
  from?: string;
  to?: string;
  category?: number;
  account?: number;
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

export const listTransactions = (filters: Filters, cursor?: string | null, signal?: AbortSignal) =>
  api<Page>(`/transactions?${query(filters, cursor)}`, { signal });

export const createTransaction = (body: TransactionDraft) =>
  api<Outcome>('/transactions', { method: 'POST', body });

export const updateTransaction = (id: number, body: TransactionDraft) =>
  api<Outcome>(`/transactions/${id}`, { method: 'PATCH', body });

export const deleteTransaction = (id: number) => api<Outcome>(`/transactions/${id}`, { method: 'DELETE' });

export const repeatLast = (on: string) =>
  api<Outcome>('/transactions/repeat-last', { method: 'POST', body: { on } });

/** Today in the user's own timezone, as the API's date string. */
export function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
