/**
 * /stats/overview - every chart on the Stats tab in one response
 * (STA-01..STA-11). Amounts and shares are strings; a share becomes a number
 * only to size a slice.
 */
import { api } from './api';
import { localToday } from './transactions';

export type Span = 'budget' | 'month' | 'year';
export type Granularity = 'day' | 'week' | 'month';

export interface CategoryShare {
  category_id: number | null;
  amount: string;
  share: string;
  transaction_count: number;
  previous_amount: string;
  /** On the parent itself, not one of its sub-categories. */
  direct: string;
  children: CategoryShare[];
  /** ACC-29 - the balance adjustments' own row (category_id is null). Optional: an older server sends none. */
  unrecorded?: boolean;
}

export interface Overview {
  start: string;
  end: string;
  span: Span | null;
  granularity: Granularity;
  totals: {
    spent: string;
    earned: string;
    net: string;
    transaction_count: number;
    days: number;
    days_counted: number;
    average_daily_spend: string;
    adjustment_losses: string;
    adjustment_gains: string;
  };
  categories: CategoryShare[];
  income_categories: CategoryShare[];
  previous: { start: string; end: string; spent: string; earned: string; spent_to_same_day: string | null };
  trend: { start: string; end: string; spent: string; earned: string }[];
  merchants: { name: string; amount: string; transaction_count: number }[];
  accounts: { account_id: number; spent: string; earned: string }[];
  tags: { tag_id: number; spent: string; transaction_count: number }[];
  forecast: {
    spent_to_date: string;
    days_elapsed: number;
    days_left: number;
    daily_rate: string;
    projected: string;
    budget_available: string | null;
  } | null;
  /** STA-10 - at the end of each trend bucket up to today; plain balances of the accounts counted today. */
  cash_on_hand?: { on: string; amount: string }[];
}

export type Range = { span: Span; on: string } | { from: string; to: string };

export function getOverview(range: Range, signal?: AbortSignal) {
  const params = new URLSearchParams({ today: localToday() });
  if ('span' in range) {
    params.set('span', range.span);
    params.set('on', range.on);
  } else {
    params.set('from', range.from);
    params.set('to', range.to);
  }
  return api<Overview>(`/stats/overview?${params.toString()}`, { signal });
}

/** STA-12 - one finished period looked back on. Derived on the server; nothing is stored. */
export interface ReviewPeriod {
  start: string;
  end: string;
  span: 'budget' | 'month';
}

export interface Review {
  period: ReviewPeriod;
  spent: string;
  earned: string;
  net: string;
  previous_spent: string;
  budget: { available: string; carried_in: string; spent: string; remaining: string; carry_over: boolean } | null;
  changes: { category_id: number | null; amount: string; previous: string; change: string }[];
  plans: {
    rule_id: number;
    name: string;
    kind: string;
    event: 'started' | 'finished' | 'cancelled' | 'price';
    on: string;
    amount: string | null;
    previous_amount: string | null;
  }[];
  purchases: { transaction_id: number; on: string; amount: string; category_id: number | null; merchant: string | null }[];
  cashback: string;
  interest: string;
  cash_start: string;
  cash_end: string;
  /** The next period's first day, when it has finished too - else there is nothing later to review. */
  later: string | null;
}

export function getReview(on: string | undefined, signal?: AbortSignal) {
  const params = new URLSearchParams({ today: localToday() });
  if (on) params.set('on', on);
  return api<Review>(`/stats/review?${params.toString()}`, { signal });
}

export const getReviewOffer = (signal?: AbortSignal) =>
  api<{ period: ReviewPeriod | null }>(`/stats/review/offer?today=${localToday()}`, { signal });

/** Home's "Not now" - kept in the preferences on the server. */
export const dismissReview = () => api<null>(`/stats/review/dismiss?today=${localToday()}`, { method: 'POST' });
