/**
 * /accounts - types and calls.
 *
 * Every amount is a STRING here and stays one all the way to the screen
 * (money.ts formats it). Nothing in this file calls Number() on a figure, and
 * nothing it returns is cached anywhere but React state (SEC-29).
 */
import { api } from './api';

export type AccountType = 'cash' | 'debit' | 'credit' | 'savings' | 'investment';

export interface Credit {
  limit: string | null;
  statement_closing_day: number;
  payment_due_day: number;
  period_start: string;
  period_closes: string;
  payment_due: string;
  due_for_statement_closing: string;
  period_spend: string;
  owed: string;
  unpaid_installments: string;
  available: string | null;
  due_in_days: number;
  due_soon: boolean;
}

export interface Valuation {
  on: string;
  value: string;
  note: string | null;
}

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  opening_balance: string;
  balance: string;
  colour: string;
  icon: string;
  archived: boolean;
  counts_in_cash_on_hand: boolean;
  sort_order: number;
  note: string | null;
  credit: Credit | null;
  valuations: Valuation[];
  current_value: string | null;
}

export interface CashOnHand {
  total: string;
  account_ids: number[];
  excluded_ids: number[];
}

export interface AccountList {
  accounts: Account[];
  cash_on_hand: CashOnHand;
}

export interface AccountDraft {
  name: string;
  type: AccountType;
  opening_balance: string;
  colour?: string;
  icon?: string;
  counts_in_cash_on_hand?: boolean;
  note?: string | null;
  statement_closing_day?: number;
  payment_due_day?: number;
  credit_limit?: string | null;
}

export const TYPE_LABEL: Record<AccountType, string> = {
  cash: 'Cash',
  debit: 'Bank',
  credit: 'Credit card',
  savings: 'Savings',
  investment: 'Investment',
};

/** What each type is for, in the words someone setting one up would use. */
export const TYPE_HINT: Record<AccountType, string> = {
  cash: 'Money in your pocket',
  debit: 'An everyday bank account',
  credit: 'Billed monthly, paid later',
  savings: 'Money set aside',
  investment: 'A value you type in yourself',
};

export const TYPE_ICON: Record<AccountType, string> = {
  cash: 'cash',
  debit: 'card',
  credit: 'credit-card',
  savings: 'piggy-bank',
  investment: 'chart',
};

export const listAccounts = (signal?: AbortSignal) => api<AccountList>('/accounts', { signal });

export const createAccount = (body: AccountDraft) => api<Account>('/accounts', { method: 'POST', body });

export const updateAccount = (id: number, body: AccountDraft) =>
  api<Account>(`/accounts/${id}`, { method: 'PATCH', body });

export const setArchived = (id: number, archived: boolean) =>
  api<Account>(`/accounts/${id}/archive`, { method: 'POST', body: { archived } });

export const addValuation = (id: number, value: string, on?: string) =>
  api<Account>(`/accounts/${id}/valuations`, { method: 'POST', body: { value, on } });
