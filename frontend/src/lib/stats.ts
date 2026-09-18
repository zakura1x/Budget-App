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
