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
import { centavos, fromCentavos } from './money';
import { localToday } from './transactions';

/** lent / borrowed (ACC-31) and member (ACC-32) since 2026-09-15. */
export type AccountType = 'cash' | 'debit' | 'credit' | 'savings' | 'investment' | 'lent' | 'borrowed' | 'member';

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
  /** ACC-26 - this card's window for "may be on next statement". */
  posting_lag_days: number;
}

/**
 * ACC-35 - one line of a bill (2026-09-19). 'typed' is the card app's own figure; 'purchase' and
 * 'plan' are added on top of it; 'inside_typed' is already inside the typed figure - shown, never
 * added; 'payment' is money into the card that settled this bill, oldest bill first.
 */
export interface BillLine {
  kind: 'typed' | 'purchase' | 'plan' | 'inside_typed' | 'payment';
  amount: string;
  on: string | null;
  name: string | null;
  transaction_id: number | null;
  rule_id: number | null;
  category_id: number | null;
}

/** ACC-35 - one bill typed from the card's own app; what is paid of it is derived. */
export interface Bill {
  due: string;
  /** typed + from_purchases + from_plans */
  amount: string;
  paid: string;
  left: string;
  overdue: boolean;
  /** What was typed from the card's app for this due date (0.00 for a date only a plan bills). */
  typed: string;
  /** Installment payments and repeating charges on this card that land on this bill. */
  from_plans: string;
  /** What is still unpaid of the typed part - what an edit starts from. */
  typed_left: string;
  /** Purchases recorded on the card after the list was saved, on this bill's statement. */
  from_purchases: string;
  purchases_left: string;
  /** Repeating charges on this bill not charged yet - on the bill, not yet in what the card owes. */
  not_charged: string;
  lines: BillLine[];
}

export interface Credit {
  /** ACC-35. Empty unless the bills were typed. */
  bills: Bill[];
  bills_left: string;
  /** Overdue bills + the next one; null without bills. Cash on hand subtracts this, not the balance. */
  due_now: string | null;
  /**
   * What the card owes that no bill lists yet (2026-09-19): owed_with_plans - bills_left +
   * bills_not_charged. Null without bills; negative when the bills hold more than the card owes.
   */
  not_on_bill: string | null;
  bills_not_charged: string;
  limit: string | null;
  statement_closing_day: number;
  payment_due_day: number;
  period_start: string;
  period_closes: string;
  payment_due: string;
  due_for_statement_closing: string;
  period_spend: string;
  /** What is ON the card now - what a payment would clear. */
  owed: string;
  unpaid_installments: string;
  /** REC-14 - owed plus what the plans have still to bill: what the card's own app calls your balance. */
  owed_with_plans: string;
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
  posting_lag_days: number;
}

export interface Valuation {
  on: string;
  value: string;
  note: string | null;
}

/** ACC-37 - one tier of a savings rate; `up_to` is empty on the top band. */
export interface InterestBand {
  up_to: string | null;
  /** Per cent a year, as a string: "3.2500". */
  rate: string;
}

/**
 * ACC-37 - what an account earns while the money sits there, plus what that is
 * worth at today's balance. `per_day` and `per_year` are net of tax and come
 * from the server, which uses the same arithmetic as the daily credits.
 */
export interface Interest {
  bands: InterestBand[];
  basis: number;
  tax_rate: string;
  category_id: number | null;
  started: string;
  /** Never today: a day's interest is earned on its closing balance. */
  credited_through: string;
  per_day: string;
  per_year: string;
  /** The fraction of a centavo still owed - more places than money. */
  carry: string;
}

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  /** ACC-33 - "e-wallet", "loan", "crypto"; a label, never a rule. */
  subtype: string | null;
  opening_balance: string;
  balance: string;
  colour: string;
  icon: string;
  archived: boolean;
  counts_in_cash_on_hand: boolean;
  /** ACC-36 - on unless turned off; only net worth reads it. */
  counts_in_net_worth: boolean;
  sort_order: number;
  note: string | null;
  credit: Credit | null;
  valuations: Valuation[];
  current_value: string | null;
  /** What it adds to cash on hand when counted: the balance, or minus a card's bill due now. */
  cash_amount: string;
  /** ACC-37 - null on a card, an investment, or any account that earns nothing. */
  interest: Interest | null;
  /** ACC-38 - what this account usually pays back, to fill the add sheet in (TXN-22). */
  cashback: CashbackRule | null;
  /**
   * REC-14 - what this account's installment plans have still to charge. Money
   * you already owe, on a card or a loan alike, before any charge has posted.
   * The balance never includes it; what you OWE and net worth do.
   */
  plans_unbilled: string;
  /** GOA-08 - earmarked for savings goals; the balance is unchanged. */
  set_aside: string;
  /** Balance less set_aside - what cash on hand counts - or null when nothing is set aside. */
  available: string | null;
  /**
   * ACC-39 - untracked cash, the wallet. The app owns this one account: it is
   * never listed, never picked and never counted. `visible()` takes it out of
   * every list; only a loan's From / To row offers it, by name.
   */
  hidden: boolean;
}

/**
 * ACC-39. Every account a list, a picker or a total may show - the wallet is
 * not one of them. `accountById` (useLookups) deliberately still holds it, so
 * a transaction row that points at it can still show a name.
 */
export const visible = (accounts: Account[]) => accounts.filter((a) => !a.hidden);

/** ACC-39. The wallet, if it has been made yet. */
export const untracked = (accounts: Account[]) => accounts.find((a) => a.hidden) ?? null;

/**
 * ACC-39. What a From or To chip holds until the wallet exists: the sheet
 * resolves it to a real id on save, so nothing creates an account by a tap
 * that is never saved. Negative, like a pending row's id, so it can never
 * collide with an account's.
 */
export const UNTRACKED_ID = -1;

/** ACC-38 - a suggestion for the add sheet, never a total in its own right. */
export interface CashbackRule {
  /** Per cent of what you spend, as a string: "2.0000". */
  rate: string;
  category_id: number | null;
}

export interface CashOnHand {
  total: string;
  account_ids: number[];
  excluded_ids: number[];
}

/** ACC-36 - every active account at full value, all debts in full. */
export interface NetWorth {
  total: string;
  assets: string;
  liabilities: string;
}

export interface AccountList {
  accounts: Account[];
  cash_on_hand: CashOnHand;
  net_worth: NetWorth;
}

/** ACC-28. What to do with the difference between a typed balance and the account's own. */
export type BalanceAction = 'adjust' | 'fix_opening';

export interface AccountDraft {
  name: string;
  type: AccountType;
  subtype?: string | null;
  /** Set when creating an account; an edit changes the current balance instead. */
  opening_balance?: string;
  colour?: string;
  icon?: string;
  counts_in_cash_on_hand?: boolean;
  counts_in_net_worth?: boolean;
  note?: string | null;
  statement_closing_day?: number;
  payment_due_day?: number;
  credit_limit?: string | null;
  spending_limit?: string | null;
  /** ACC-26. Days this bank can take to post a purchase, 0-10; a new card starts at 3. */
  posting_lag_days?: number;
  /** ACC-27. The balance you typed on an existing account - signed, so a card you owe on is negative. */
  balance?: string;
  balance_action?: BalanceAction;
  balance_note?: string | null;
  /**
   * ACC-37. Left out, an edit keeps the account's interest; sent as null it
   * turns it off and leaves everything already credited alone. `started` is
   * read only the first time - after that the day it began is fixed.
   */
  interest?: InterestDraft | null;
  /** ACC-38. Same rule: left out keeps it, null removes it. */
  cashback?: { rate: string; category_id: number } | null;
}

export interface InterestDraft {
  bands: { up_to: string | null; rate: string }[];
  basis?: number;
  tax_rate?: string;
  category_id: number;
  started?: string;
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
  lent: 'Lent',
  borrowed: 'Borrowed',
  member: 'Member card',
};

/** What each type is for, in the words someone setting one up would use. */
export const TYPE_HINT: Record<AccountType, string> = {
  cash: 'Money in your pocket',
  debit: 'An everyday bank account',
  credit: 'Billed monthly, paid later',
  savings: 'Money set aside',
  investment: 'A value you type in yourself',
  lent: 'Money someone owes you',
  borrowed: 'Money you owe someone',
  member: 'A prepaid or member card',
};

export const TYPE_ICON: Record<AccountType, string> = {
  cash: 'cash',
  debit: 'card',
  credit: 'credit-card',
  savings: 'piggy-bank',
  investment: 'chart',
  lent: 'hand-coin',
  borrowed: 'hand-owe',
  member: 'badge',
};

/**
 * Accounts whose balance is money you OWE, shown as a positive "owed" figure:
 * a card, and a loan or money borrowed (ACC-31). Stored balances stay signed.
 */
export const isOwed = (type: AccountType) => type === 'credit' || type === 'borrowed';

/**
 * REC-14. What an account owes INCLUDING installments not billed yet - the
 * figure a card's own app shows. A plan you take out is money owed from the
 * day you take it, even though the first charge has not posted.
 */
export function owedWithPlans(account: Account): string {
  if (account.credit) return account.credit.owed_with_plans;
  // A debt is stored as a minus, so what you owe is the balance turned round,
  // and a plan not billed yet is owed on top of it.
  return fromCentavos(-centavos(account.balance) + centavos(account.plans_unbilled));
}

/** The same account's own balance, shown the way its type means it. */
export const shownFigure = (account: Account): string =>
  isOwed(account.type) ? owedWithPlans(account) : account.balance;

export interface AccountKind {
  subtype: string;
  label: string;
  hint: string;
  type: AccountType;
  icon: string;
  example: string;
}

/**
 * The Add Account list (after sample_ui/, 2026-09-15): every entry is one of
 * the account types with its own label and icon, stored as `subtype` (ACC-33).
 */
export const ACCOUNT_KINDS: { group: string; items: AccountKind[] }[] = [
  {
    group: 'Debit',
    items: [
      { subtype: 'debit-card', label: 'Debit card', hint: 'A card that spends from your bank', type: 'debit', icon: 'card', example: 'BPI Debit' },
      { subtype: 'cash', label: 'Cash', hint: 'Money in your pocket', type: 'cash', icon: 'cash', example: 'Wallet' },
      { subtype: 'bank', label: 'Bank account', hint: 'Savings or payroll account you spend from', type: 'debit', icon: 'bank', example: 'BDO Savings' },
      { subtype: 'e-wallet', label: 'E-wallet', hint: 'GCash, Maya, ShopeePay…', type: 'debit', icon: 'wallet', example: 'GCash' },
      { subtype: 'paypal', label: 'PayPal', hint: 'Online balance', type: 'debit', icon: 'globe', example: 'PayPal' },
      { subtype: 'other-debit', label: 'Other debit account', hint: 'Anything else you spend from', type: 'debit', icon: 'piggy-bank', example: 'Coins jar' },
    ],
  },
  {
    group: 'Credit',
    items: [
      { subtype: 'credit-card', label: 'Credit card', hint: 'Billed monthly, paid later', type: 'credit', icon: 'credit-card', example: 'BPI Gold' },
      { subtype: 'other-credit', label: 'Other credit account', hint: 'SPayLater, Home Credit, buy now pay later', type: 'credit', icon: 'card', example: 'SPayLater' },
    ],
  },
  {
    group: 'Borrow / Lend',
    items: [
      { subtype: 'lent', label: 'Lent', hint: 'Money someone owes you', type: 'lent', icon: 'hand-coin', example: 'Juan' },
      { subtype: 'borrowed', label: 'Borrowed', hint: 'Money you owe a person', type: 'borrowed', icon: 'hand-owe', example: 'Tita Grace' },
      { subtype: 'loan', label: 'Loan', hint: 'A bank, car or salary loan', type: 'borrowed', icon: 'contract', example: 'SSS salary loan' },
    ],
  },
  {
    group: 'Invest',
    items: [
      { subtype: 'savings', label: 'Savings', hint: 'Money set aside', type: 'savings', icon: 'piggy-bank', example: 'Emergency fund' },
      { subtype: 'stock', label: 'Stock', hint: 'A value you type in yourself', type: 'investment', icon: 'chart', example: 'COL Financial' },
      { subtype: 'fund', label: 'Fund', hint: 'Mutual fund, UITF, Pag-IBIG MP2', type: 'investment', icon: 'trend', example: 'Pag-IBIG MP2' },
      { subtype: 'crypto', label: 'Crypto currencies', hint: 'A value you type in yourself', type: 'investment', icon: 'crypto', example: 'Coins.ph' },
      { subtype: 'real-estate', label: 'Real estate', hint: 'A lot, a house, a condo', type: 'investment', icon: 'home', example: 'Condo unit' },
      { subtype: 'precious-metal', label: 'Precious metal', hint: 'Gold and silver', type: 'investment', icon: 'coins', example: 'Gold' },
    ],
  },
  {
    group: 'Member account',
    items: [
      { subtype: 'membership', label: 'Membership', hint: 'Store and loyalty cards with a balance', type: 'member', icon: 'badge', example: 'SM Advantage' },
      { subtype: 'transport-card', label: 'Transport card', hint: 'Beep and other fare cards', type: 'member', icon: 'bus', example: 'Beep card' },
      { subtype: 'school-card', label: 'School card', hint: 'Campus ID with load', type: 'member', icon: 'graduation', example: 'School ID' },
      { subtype: 'other-member', label: 'Other member card', hint: 'Any other prepaid card', type: 'member', icon: 'id-card', example: 'Gym card' },
    ],
  },
];

const KIND_BY_SUBTYPE = new Map(ACCOUNT_KINDS.flatMap((g) => g.items).map((k) => [k.subtype, k]));

/** "E-wallet", "Loan", "Transport card" - or the type's own label. */
export const kindLabelOf = (type: AccountType, subtype: string | null | undefined) =>
  (subtype && KIND_BY_SUBTYPE.get(subtype)?.label) || TYPE_LABEL[type];

const today = () => `today=${localToday()}`;

export const listAccounts = (signal?: AbortSignal) => api<AccountList>(`/accounts?${today()}`, { signal });

export const createAccount = (body: AccountDraft) => api<Account>(`/accounts?${today()}`, { method: 'POST', body });

/**
 * ACC-39. The hidden wallet account, made on the server the first time it is
 * needed and returned every time after that. Called only when a loan is saved
 * "from my wallet", never on a tap.
 */
export const untrackedCash = () => api<Account>(`/accounts/untracked?${today()}`, { method: 'POST' });

export const updateAccount = (id: number, body: AccountDraft) =>
  api<Account>(`/accounts/${id}?${today()}`, { method: 'PATCH', body });

export const setArchived = (id: number, archived: boolean) =>
  api<Account>(`/accounts/${id}/archive?${today()}`, { method: 'POST', body: { archived } });

/** ACC-35 - replace a card's bills with the unpaid ones its app shows today; [] removes them. */
export const setBills = (id: number, bills: { due: string; amount: string }[]) =>
  api<Account>(`/accounts/${id}/bills?${today()}`, { method: 'POST', body: { bills } });

/**
 * ACC-37. Post every morning's savings interest credit, today's included, that has not
 * been credited yet. Safe on every open, like expandRecurring: the days
 * already credited are skipped and a second call changes nothing.
 */
export const accrueInterest = () =>
  api<{ posted: number; accounts: number; credited: string; through: string | null; needs_attention: number[] }>(
    `/accounts/interest/accrue?${today()}`, { method: 'POST' },
  );

/**
 * The banks this app is used with, as a one-tap preset (ACC-37). Rates checked
 * 2026-09-16; a bank that changes its rate is edited by hand.
 */
export const INTEREST_PRESETS: { label: string; hint: string; bands: InterestBand[]; tax_rate: string }[] = [
  {
    label: 'SeaBank / MariBank',
    hint: '3.25% a year, 3.75% above ₱1M',
    bands: [{ up_to: '1000000.00', rate: '3.25' }, { up_to: null, rate: '3.75' }],
    tax_rate: '20',
  },
  {
    label: 'GoTyme / Maya',
    hint: 'One rate on the whole balance',
    bands: [{ up_to: null, rate: '4.00' }],
    tax_rate: '20',
  },
];

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
