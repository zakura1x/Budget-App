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
  kind:
    | 'over'
    | 'approaching'
    | 'pace'
    | 'category_over'
    | 'card_due'
    | 'card_limit_over'
    | 'card_limit_approaching'
    | 'card_limit_pace'
    | 'subscription_due'
    | 'subscription_cancel_by'
    | 'statement_differs';
  severity: 'danger' | 'warn';
  message: string;
  category_id: number | null;
  account_id: number | null;
  /** subscription_due (SUB-06). */
  rule_id?: number | null;
  /** "today" / "in 3 days" - card_due and the subscription alerts. Word it from this, never from `message`. */
  when?: string | null;
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
  /** BUD-17 - "Your spending has changed": only in a period's first days, and only when it drifted over 15%. */
  reminder?: { suggested: string; in_force: string; periods: number } | null;
}

/** BUD-17 - one category's line in a suggested budget. `history` lines up with Suggestion.periods. */
export interface SuggestedLine {
  category_id: number;
  history: string[];
  median: string;
  average: string;
  scheduled: string;
  current: string | null;
  spent_in: number;
  suggested: string;
  reason: 'median' | 'scheduled' | 'kept' | 'single';
}

/** BUD-17 - a budget worked out from recent spending. Reading it writes nothing. */
export interface Suggestion {
  period: Period;
  kind: PeriodKind;
  asked: number;
  periods: Period[];
  in_force: string | null;
  lines: SuggestedLine[];
  occasional: { category_id: number; history: string[]; spent_in: number }[];
  buffer: string;
  total: string;
  income: string | null;
  over_income: boolean;
  fitted: boolean;
  cannot_fit: boolean;
  step: string;
  trim: number;
  /** false: no finished period of entries to work from yet */
  ready: boolean;
}

export interface SuggestionAsk {
  periods: 1 | 3 | 6;
  step?: number;
  trim: 0 | 5 | 10;
  fit: boolean;
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

export type Theme = 'system' | 'light' | 'dark';

/** UX-05 (2026-09-18): the colour palette - every one has a light and a dark. */
export type Palette = 'classic' | 'candy' | 'lime' | 'mono';

export interface Preferences {
  carry_over: boolean;
  daily_allowance_mode: AllowanceMode;
  alert_warn_threshold_pct: number;
  alert_pace_enabled: boolean;
  theme: Theme;
  palette: Palette;
  budget_period: PeriodKind;
  month_start_day: number;
  /** 1 Monday .. 7 Sunday */
  week_start_day: number;
  auto_lock_minutes: number;
  /** BUD-17 - a suggested budget rounds up to this many pesos: 1, 10, 50, 100, 500 or 1000. */
  budget_round_step?: number;
  /** BUD-17 - the period-start "your spending has changed" reminder. */
  budget_suggestion_nudge?: boolean;
  /** GOA-12 - offer to set money aside when income of at least this many pesos lands; 0 is off. */
  payday_prompt_min?: number;
  /** GOA-11 - the emergency advisor's three answers. */
  safety_work?: 'employee' | 'contract' | 'self';
  safety_dependents?: '0' | '1-2' | '3+';
  safety_earners?: '1' | '2+';
  /** UX-14 - vibrate on keys, saves and deletes; Android only. */
  haptics?: boolean;
  /** AI-50 (misc/AI): opted in to the AI companion. */
  assistant?: boolean;
  /** AI-60 (misc/AI A6): keep conversations this many days; 0 = gone on lock. */
  assistant_history_days?: 0 | 30 | 90 | 365;
  [key: string]: unknown;
}

const today = () => `today=${localToday()}`;

export const getStatus = (on?: string | null, signal?: AbortSignal) =>
  // `alerts` are today's: without a budget, still a card's bill or a subscription.
  api<{ status: BudgetStatus | null; alerts: Alert[] }>(`/budgets/current?${today()}${on ? `&on=${on}` : ''}`, { signal });

export const getBudget = (signal?: AbortSignal) => api<{ budget: Budget | null }>(`/budgets?${today()}`, { signal });

export const createBudget = (body: BudgetDraft) => api<Budget>(`/budgets?${today()}`, { method: 'POST', body });

export const updateBudget = (id: number, body: BudgetDraft) =>
  api<Budget>(`/budgets/${id}?${today()}`, { method: 'PATCH', body });

export const getSuggestion = (ask: SuggestionAsk, signal?: AbortSignal) => {
  const params = new URLSearchParams({ periods: String(ask.periods), trim: String(ask.trim), fit: String(ask.fit) });
  if (ask.step !== undefined) params.set('step', String(ask.step));
  return api<Suggestion>(`/budgets/suggestion?${today()}&${params.toString()}`, { signal });
};

/** BUD-17 - "Not now": the reminder stays away until the next period. Kept on the server, never in the browser. */
export const dismissReminder = () => api<void>(`/budgets/suggestion/dismiss?${today()}`, { method: 'POST' });

export const getPreferences = (signal?: AbortSignal) => api<Preferences>('/settings/preferences', { signal });

export const updatePreferences = (changes: Partial<Preferences>) =>
  api<Preferences>('/settings/preferences', { method: 'PATCH', body: changes });

/** A ratio string as a 0..n number, for drawing only. */
export const ratio = (value: string): number => Number(value);
