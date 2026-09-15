/**
 * /accounts/{id}/statements/{closes} - the statement check (ACC-24..26).
 *
 * One number goes up (the bank's total); the difference comes back derived.
 * Every way of explaining it is an ordinary transaction on the server, so the
 * answer to each call is simply the statement as it now stands.
 */
import type { Statement } from './accounts';
import { api } from './api';
import { localToday, type Transaction } from './transactions';

export type Suggestion = 'charge' | 'posted_next' | 'forgot' | 'installment_interest' | 'installment_change';

/** REC-29 - an installment with a payment on this statement. */
export interface StatementPlan {
  rule_id: number;
  name: string;
  per_payment: string;
  terms: 'provisional' | 'confirmed';
  /** Every scheduled payment posted so far - confirming the interest corrects them all. */
  payments_posted: number;
  payments_on_statement: number;
  /** What the app has for this plan's payments on this statement. */
  on_statement: string;
}

export interface StatementCheck {
  statement: Statement;
  /** The bank's figure is in, and nothing is left unexplained. */
  checked: boolean;
  /** Purchases from the last days before closing that the bank may have posted later. */
  late_candidates: Transaction[];
  /** Likeliest first. Leaving it is always allowed. */
  suggestions: Suggestion[];
  /** REC-29 - installments with a payment on this statement, either terms. */
  installments: StatementPlan[];
}

const path = (accountId: number, closes: string, action = '') =>
  `/accounts/${accountId}/statements/${closes}${action}?today=${localToday()}`;

export const getStatement = (accountId: number, closes: string, signal?: AbortSignal) =>
  api<StatementCheck>(path(accountId, closes), { signal });

export const checkStatement = (accountId: number, closes: string, bankTotal: string) =>
  api<StatementCheck>(path(accountId, closes, '/check'), { method: 'POST', body: { bank_total: bankTotal } });

/** A fee or interest the app did not know about - posted to the card on the closing date. */
export const recordCharge = (
  accountId: number,
  closes: string,
  charge: { amount: string; category_id: number; note?: string | null },
) => api<StatementCheck>(path(accountId, closes, '/resolve'), { method: 'POST', body: { choice: 'charge', ...charge } });

/** REC-29. A confirmed plan's payment was billed at a different amount - this payment and later ones change. */
export const changeInstallmentPayment = (accountId: number, closes: string, ruleId: number, amount: string) =>
  api<StatementCheck>(path(accountId, closes, '/resolve'), {
    method: 'POST',
    body: { choice: 'installment_change', rule_id: ruleId, amount },
  });

/** REC-29. The bank added interest to this plan's payments - confirms its terms and corrects the posted ones. */
export const confirmInstallmentInterest = (accountId: number, closes: string, ruleId: number, amount: string) =>
  api<StatementCheck>(path(accountId, closes, '/resolve'), {
    method: 'POST',
    body: { choice: 'installment_interest', rule_id: ruleId, amount },
  });

/** The bank posted this purchase on the next statement. Its budget period does not move. */
export const markPostedNext = (accountId: number, closes: string, transactionId: number) =>
  api<StatementCheck>(path(accountId, closes, '/resolve'), {
    method: 'POST',
    body: { choice: 'posted_next', transaction_id: transactionId },
  });
