/**
 * /budgets and the budget settings - types and calls (BUD-01..BUD-15).
 *
 * Every call passes the user's own `today`. The daily allowance is about the
 * user's day, and a server in another timezone would otherwise be a day off for
 * part of every day.
 *
 * Amounts and ratios are strings. A ratio ("0.8350") is turned into a number
 * only to draw a ring or a bar - never to add money up.
 */
import { api } from './api';
import { localToday } from './transactions';

export type PeriodKind = 'weekly' | 'monthly' | 'custom';
export type AllowanceMode = 'remaining_over_days_left' | 'fixed_daily';

export interface Allocation {
  id: number;
  category_id: number;
  amount: string;
}

export interface Budget {
  id: number;
  period: PeriodKind;
  month_start_day: number;
  week_start_day: number;
  custom_days: number | null;
  custom_anchor: string | null;
  amount: string;
  structure_from: string;
  allocations: Allocation[];
}

export interface Period {
  start: string;
  end: string;
  days: number;
}

export interface Allowance {
  mode: AllowanceMode;
  budget: string;
  carried_in: string;
  available: string;
  spent: string;
  spent_before_today: string;
  spent_today: string;
  remaining: string;
  daily: string;
  left_today: string;
  over_by: string;
  days_total: number;
  days_elapsed: number;
  days_left: number;
  used_ratio: string;
}

export interface CategoryProgress {
  category_id: number;
  allocated: string;
  spent: string;
  remaining: string;
  used_ratio: string;
  over: boolean;
}

export interface Alert {
  kind: 'over' | 'approaching' | 'pace' | 'category_over' | 'card_due';
  severity: 'danger' | 'warn';
  message: string;
  category_id: number | null;
  account_id: number | null;
}

export interface BudgetStatus {
  budget: Budget;
  period: Period;
  previous_period: Period;
  next_period: Period;
  is_current: boolean;
  carry_over: boolean;
  allowance: Allowance;
  categories: CategoryProgress[];
  allocated: string;
  unallocated: string;
  alerts: Alert[];
}

export interface BudgetDraft {
  period?: PeriodKind;
  amount?: string;
  month_start_day?: number;
  week_start_day?: number;
  custom_days?: number;
  custom_anchor?: string;
  allocations?: { category_id: number; amount: string }[];
}

export interface Preferences {
  carry_over: boolean;
  daily_allowance_mode: AllowanceMode;
  alert_warn_threshold_pct: number;
  alert_pace_enabled: boolean;
  [key: string]: unknown;
}

const today = () => `today=${localToday()}`;

export const getStatus = (on?: string | null, signal?: AbortSignal) =>
  api<{ status: BudgetStatus | null }>(`/budgets/current?${today()}${on ? `&on=${on}` : ''}`, { signal });

export const getBudget = (signal?: AbortSignal) => api<{ budget: Budget | null }>(`/budgets?${today()}`, { signal });

export const createBudget = (body: BudgetDraft) => api<Budget>(`/budgets?${today()}`, { method: 'POST', body });

export const updateBudget = (id: number, body: BudgetDraft) =>
  api<Budget>(`/budgets/${id}?${today()}`, { method: 'PATCH', body });

export const getPreferences = (signal?: AbortSignal) => api<Preferences>('/settings/preferences', { signal });

export const updatePreferences = (changes: Partial<Preferences>) =>
  api<Preferences>('/settings/preferences', { method: 'PATCH', body: changes });

/** A ratio string as a 0..n number, for drawing only. */
export const ratio = (value: string): number => Number(value);
