/**
 * /calendar - one month of days (CAL-01..CAL-05). A day's own transactions
 * come from listTransactions({ from: day, to: day }), the ledger's own list.
 */
import { api } from './api';

export interface CalendarDay {
  on: string;
  spent: string;
  earned: string;
  count: number;
  /** 0 nothing spent .. 4 more than twice the reference. */
  level: 0 | 1 | 2 | 3 | 4;
  reference: string | null;
  /** "budget": the budget per day. "typical": the month's median spending day. */
  reference_kind: 'budget' | 'typical' | null;
}

export interface CalendarMonth {
  year: number;
  month: number;
  start: string;
  end: string;
  spent: string;
  earned: string;
  days: CalendarDay[];
}

export const getMonth = (year: number, month: number, signal?: AbortSignal) =>
  api<CalendarMonth>(`/calendar/${year}/${month}`, { signal });

/** CAL-06 - twelve months, each exactly as getMonth gives it. */
export interface CalendarYear {
  year: number;
  spent: string;
  earned: string;
  months: CalendarMonth[];
}

export const getYear = (year: number, signal?: AbortSignal) => api<CalendarYear>(`/calendar/${year}`, { signal });
