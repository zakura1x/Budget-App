/**
 * /recurring, /subscriptions and /projection - types and calls
 * (REC-01..30, SUB-00..08).
 *
 * One engine: a subscription and an installment are recurring rules with a
 * `kind`. Only the server posts from a rule, and `expandRecurring` is safe to
 * call on every open - it posts what is due and nothing twice.
 */
import { api, ApiError } from './api';
import { localToday, type Transaction, type TransactionDraft } from './transactions';

export type RuleKind = 'standard' | 'subscription' | 'installment';
export type RuleType = 'expense' | 'income' | 'transfer';
export type Frequency = 'daily' | 'weekly' | 'monthly' | 'yearly' | 'semi_monthly';

export interface InstallmentStatus {
  price: string;
  interest: string;
  total: string;
  payments: number;
  per_payment: string;
  terms: 'provisional' | 'confirmed';
  paid: string;
  remaining: string;
  payments_posted: number;
  payoff_on: string | null;
  closed: boolean;
  /** REC-32 - what you have actually paid on the plan, and what is left to pay. */
  money_paid: string;
  left_to_pay: string;
  /** The next payment still to post - smaller after an extra payment that lowered it. */
  current_payment: string;
  /** Scheduled payments not posted yet - fewer after an extra payment that shortened it. */
  payments_left: number;
  prepaid: string;
}

/** REC-32 - what the extra part of a payment does to the plan. */
export type PrepaymentMode = 'lower' | 'shorten';

export interface PlanPayment {
  amount: string;
  from_account_id: number;
  on?: string;
  mode?: PrepaymentMode;
}

/** One way an extra payment could change the plan - the numbers the question shows. */
export interface PrepaymentOutcome {
  payment: string;
  payments: number;
  payoff_on: string | null;
}

/** The server's question when a payment is more than what is due (409 PREPAYMENT_CHOICE). */
export interface PrepaymentQuestion {
  due: string;
  extra: string;
  lower: PrepaymentOutcome;
  shorten: PrepaymentOutcome;
}

export interface Rule {
  id: number;
  kind: RuleKind;
  type: RuleType;
  name: string;
  account_id: number;
  counter_account_id: number | null;
  category_id: number | null;
  interest_category_id: number | null;
  merchant: string | null;
  notes: string | null;
  tag_ids: number[];
  frequency: Frequency;
  interval: number;
  start: string;
  days: number[];
  end_after: number | null;
  end_on: string | null;
  amount: string;
  amounts: { on: string; amount: string }[];
  paused: boolean;
  skips: string[];
  closed_on: string | null;
  posted_through: string;
  next_on: string | null;
  next_amount: string | null;
  problem: string | null;
  reminder_days: number | null;
  installment: InstallmentStatus | null;
  /** REC-34 - the purchase this plan replaced (hidden until converted back). Optional: an older server sends none. */
  from_transaction?: number | null;
  receipt_id?: number | null;
}

export interface RuleDraft {
  kind?: RuleKind;
  type?: RuleType;
  name?: string;
  account_id?: number;
  counter_account_id?: number | null;
  category_id?: number | null;
  interest_category_id?: number | null;
  merchant?: string | null;
  notes?: string | null;
  tag_ids?: number[];
  frequency?: Frequency;
  interval?: number;
  start?: string;
  days?: number[];
  end_after?: number;
  end_on?: string;
  clear_end?: boolean;
  amount?: string;
  amount_from?: string;
  price?: string;
  payments?: number;
  interest?: string;
  post_past?: boolean;
  reminder_days?: number;
}

export interface Occurrence {
  on: string;
  number: number;
  amount: string;
  paused: boolean;
  final: boolean;
}

export interface SubscriptionItem {
  rule: Rule;
  monthly: string;
  due_in_days: number | null;
  remind: boolean;
}

export interface SubscriptionOverview {
  items: SubscriptionItem[];
  monthly_total: string;
  budget_share: string | null;
  upcoming: { rule_id: number; name: string; on: string; amount: string; account_id: number }[];
}

export interface Candidate {
  merchant: string;
  amount: string;
  account_id: number;
  category_id: number | null;
  months: number;
  last_on: string;
  next_on: string;
  transaction_ids: number[];
}

export interface ProjectedItem {
  on: string;
  rule_id: number;
  name: string;
  /**
   * 'bill' / 'bill_plans': a typed card bill entering cash on hand (ACC-35),
   * rule_id 0. 'interest': a month of savings interest (ACC-37), also rule_id 0.
   */
  kind: RuleKind | 'bill' | 'bill_plans' | 'bill_now' | 'interest';
  type: RuleType;
  account_id: number;
  counter_account_id: number | null;
  amount: string;
  /** On cash on hand - signed, 0.00 when no counted account is involved. */
  effect: string;
  paused: boolean;
  final: boolean;
}

export interface ProjectedMonth {
  start: string;
  end: string;
  current: boolean;
  opening: string;
  income: string;
  committed: string;
  transfers: string;
  budget: string;
  spending: string;
  closing: string;
  low_point: string;
  low_on: string;
  overcommitted: boolean;
  items: ProjectedItem[];
  /** ACC-35 - typed card bills taken this month, on top of spending. */
  bills: string;
  /** ACC-35 - bills due this month that today's cash on hand already holds: shown, not taken again. */
  bills_set_aside: string;
}

export interface Projection {
  today: string;
  basis: 'budget' | 'calendar';
  cash_on_hand: string;
  months: ProjectedMonth[];
}

export interface CardLookahead {
  account_id: number;
  name: string;
  spending_limit: string | null;
  statements: {
    start: string;
    closes: string;
    due: string;
    posted: string;
    recurring: string;
    total: string;
    limit_share: string | null;
    items: ProjectedItem[];
  }[];
}

const today = () => `today=${localToday()}`;

export const listRules = (kind?: RuleKind, signal?: AbortSignal) =>
  api<Rule[]>(`/recurring?${today()}${kind ? `&kind=${kind}` : ''}`, { signal });

export const createRule = (body: RuleDraft) => api<Rule>(`/recurring?${today()}`, { method: 'POST', body });

export const updateRule = (id: number, body: RuleDraft) =>
  api<Rule>(`/recurring/${id}?${today()}`, { method: 'PATCH', body });

export const deleteRule = (id: number) => api<void>(`/recurring/${id}`, { method: 'DELETE' });

export const previewRule = (body: RuleDraft, signal?: AbortSignal) =>
  api<Occurrence[]>(`/recurring/preview?${today()}`, { method: 'POST', body, signal });

export const pauseRule = (id: number, paused: boolean) =>
  api<Rule>(`/recurring/${id}/pause?${today()}`, { method: 'POST', body: { paused } });

export const skipOccurrence = (id: number, on: string) =>
  api<Rule>(`/recurring/${id}/skip?${today()}`, { method: 'POST', body: { on } });

export const payOff = (id: number) => api<Rule>(`/recurring/${id}/payoff?${today()}`, { method: 'POST' });

/**
 * REC-33. Record a repeating charge's next occurrence now - paid early, so it
 * does not post again on its own day. Installments use payPlan instead.
 */
export const payNow = (id: number) =>
  api<Rule>(`/recurring/${id}/pay-now?${today()}`, { method: 'POST', body: {} });

/**
 * REC-32. Pay money on a plan from another account. An extra payment first
 * answers PREPAYMENT_CHOICE - read it with prepaymentQuestion() - and is sent
 * again with a `mode` once the user has chosen.
 */
export const payPlan = (id: number, body: PlanPayment) =>
  api<Rule>(`/recurring/${id}/payments?${today()}`, { method: 'POST', body });

/** The choice the server is asking for, or null if this was a different error. */
export function prepaymentQuestion(error: unknown): PrepaymentQuestion | null {
  if (!(error instanceof ApiError) || error.code !== 'PREPAYMENT_CHOICE') return null;
  const { due, extra, lower, shorten } = error.body as Record<string, unknown>;
  const outcome = (value: unknown): value is PrepaymentOutcome =>
    typeof value === 'object' && value !== null && typeof (value as PrepaymentOutcome).payment === 'string';
  return typeof due === 'string' && typeof extra === 'string' && outcome(lower) && outcome(shorten)
    ? { due, extra, lower, shorten }
    : null;
}

export const expandRecurring = () =>
  api<{ posted: number; rules: number; needs_attention: number[] }>(`/recurring/expand?${today()}`, { method: 'POST' });

export const getSubscriptions = (signal?: AbortSignal) =>
  api<SubscriptionOverview>(`/subscriptions?${today()}`, { signal });

export const getDetected = (signal?: AbortSignal) => api<Candidate[]>(`/subscriptions/detected?${today()}`, { signal });

export const getProjection = (months: 3 | 6 | 12, signal?: AbortSignal) =>
  api<Projection>(`/projection?${today()}&months=${months}`, { signal });

export const getCardLookahead = (signal?: AbortSignal) =>
  api<CardLookahead[]>(`/projection/cards?${today()}`, { signal });

export const FREQUENCY_LABEL: Record<Frequency, string> = {
  daily: 'Every day',
  weekly: 'Every week',
  monthly: 'Every month',
  yearly: 'Every year',
  semi_monthly: 'Twice a month',
};

/** "Every month", "Every 2 weeks", "15th & 30th". */
export function scheduleLabel(rule: Pick<Rule, 'frequency' | 'interval' | 'days'>): string {
  if (rule.frequency === 'semi_monthly') return rule.days.map(ordinal).join(' & ');
  if (rule.interval <= 1) return FREQUENCY_LABEL[rule.frequency];
  const unit = { daily: 'days', weekly: 'weeks', monthly: 'months', yearly: 'years' }[rule.frequency];
  return `Every ${rule.interval} ${unit}`;
}

export function ordinal(n: number): string {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${suffix}`;
}


// ------------------------------------------------ REC-34: a purchase paid in installments

/** How a purchase is spread. `start` left out = the bill the purchase belongs to (a loan: a month later). */
export interface InstallmentTerms {
  payments: number;
  start?: string;
  interest?: string;
}

export interface InstallmentPreview {
  start: string;
  payments: { on: string; amount: string }[];
  /** Payments dated today or earlier - posted as soon as the plan is saved. */
  due_now: number;
  on_closed_statement: boolean;
}

export const previewInstallments = (
  body: InstallmentTerms & { account_id: number; amount: string; txn_date: string; card_posted_on?: string | null },
  signal?: AbortSignal,
) => api<InstallmentPreview>(`/recurring/installments/preview?${today()}`, { method: 'POST', body, signal });

/** A purchase already recorded, turned into a plan - the purchase is replaced by it. */
export const convertPurchase = (transactionId: number, terms: InstallmentTerms) =>
  api<Rule>(`/recurring/installments/from/${transactionId}?${today()}`, { method: 'POST', body: terms });

/** The add sheet: a new purchase, paid in installments from the start. */
export const createPurchaseWithPlan = (purchase: TransactionDraft, terms: InstallmentTerms) =>
  api<Rule>(`/recurring/installments?${today()}`, { method: 'POST', body: { purchase, terms } });

/** The plan and its payments go; the purchase it was made from comes back. */
export const revertInstallment = (ruleId: number) =>
  api<Transaction>(`/recurring/${ruleId}/revert?${today()}`, { method: 'POST' });
