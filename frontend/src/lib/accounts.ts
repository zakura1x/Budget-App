/**
 * /accounts - types and calls.
 *
 * Every amount is a STRING here and stays one all the way to the screen
 * (money.ts formats it). Nothing in this file calls Number() on a figure, and
 * nothing it returns is cached anywhere but React state (SEC-29).
 *
 * Every read passes the user's own `today`: a card's bill, its open cycle and
 * whether a payment is due soon all turn on the user's day (ACC-19..22).
 */
import { api, ApiError } from './api';
import { localToday } from './transactions';

export type AccountType = 'cash' | 'debit' | 'credit' | 'savings' | 'investment';

/** One closed statement (ACC-19/20/24). `difference` is null until the bank's total is entered. */
export interface Statement {
  account_id: number;
  start: string;
  closes: string;
  due: string;
  amount: string;
  paid_since_close: string;
  left_to_pay: string;
  overdue: boolean;
  bank_total: string | null;
  difference: string | null;
}

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
  /** The last closed statement - the bill - and what is left of it. */
  bill: Statement;
  amount_due: string;
  /** Your own limit per statement cycle (ACC-21); not the bank's. */
  spending_limit: string | null;
  limit_spent: string;
  limit_left: string | null;
  period_days: number;
  period_days_elapsed: number;
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

/** ACC-28. What to do with the difference between a typed balance and the account's own. */
export type BalanceAction = 'adjust' | 'fix_opening';

export interface AccountDraft {
  name: string;
  type: AccountType;
  /** Set when creating an account; an edit changes the current balance instead. */
  opening_balance?: string;
  colour?: string;
  icon?: string;
  counts_in_cash_on_hand?: boolean;
  note?: string | null;
  statement_closing_day?: number;
  payment_due_day?: number;
  credit_limit?: string | null;
  spending_limit?: string | null;
  /** ACC-27. The balance you typed on an existing account - signed, so a card you owe on is negative. */
  balance?: string;
  balance_action?: BalanceAction;
  balance_note?: string | null;
}

/** The server's question when a typed balance differs (409 BALANCE_DIFFERS). */
export interface BalanceQuestion {
  before: string;
  after: string;
  difference: string;
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

const today = () => `today=${localToday()}`;

export const listAccounts = (signal?: AbortSignal) => api<AccountList>(`/accounts?${today()}`, { signal });

export const createAccount = (body: AccountDraft) => api<Account>(`/accounts?${today()}`, { method: 'POST', body });

export const updateAccount = (id: number, body: AccountDraft) =>
  api<Account>(`/accounts/${id}?${today()}`, { method: 'PATCH', body });

export const setArchived = (id: number, archived: boolean) =>
  api<Account>(`/accounts/${id}/archive?${today()}`, { method: 'POST', body: { archived } });

export const addValuation = (id: number, value: string, on?: string) =>
  api<Account>(`/accounts/${id}/valuations?${today()}`, { method: 'POST', body: { value, on } });

/** The difference the server is asking about, or null if this was a different error. */
export function balanceQuestion(error: unknown): BalanceQuestion | null {
  if (!(error instanceof ApiError) || error.code !== 'BALANCE_DIFFERS') return null;
  const { before, after, difference } = error.body;
  return typeof before === 'string' && typeof after === 'string' && typeof difference === 'string'
    ? { before, after, difference }
    : null;
}
