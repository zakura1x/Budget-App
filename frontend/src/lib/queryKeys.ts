/**
 * Every cache key in one place (misc/archive/UX_RESPONSIVENESS_PLAN.md §2.3), and the
 * map from "what a write touched" to the keys that go stale with it.
 *
 * A key CARRIES THE CLIENT'S `today` wherever the endpoint takes one. Almost
 * all of them do (`/accounts?today=`, `/recurring?today=`, `/goals?today=`,
 * `/projection?today=`, `/stats/overview?today=`): the server answers "as of"
 * that day, so a response cached yesterday is a wrong figure, not an old one.
 * Keying on the date means midnight changes the key and the answer is fetched
 * again by itself.
 *
 * Not here, on purpose (plan D9): the ledger's rows, the account trails and the
 * budget STATUS. Those stay in `ledgerStore` / `budgetStore`, which already
 * survive a tab switch and own the pending row and the `Outcome` merge;
 * `afterWrite` reloads them in the same breath as it invalidates these keys.
 */
import { queryClient } from './queryClient';
import type { Range } from './stats';
import { localToday } from './transactions';

export const keys = {
  accounts: () => ['accounts', localToday()] as const,
  categories: () => ['categories'] as const,
  tags: () => ['tags'] as const,
  goals: () => ['goals', localToday()] as const,
  /** Phase 13 - under `goals`, so a goal or a set-aside refreshes them; the emergency advice reads money too. */
  yearlyBills: () => ['goals', 'yearly-bills', localToday()] as const,
  emergency: () => ['goals', 'emergency', localToday()] as const,
  payday: () => ['goals', 'payday', localToday()] as const,
  /** GET /budgets - the budget's shape and allocations, the Budget screen's editor. */
  budgetShape: () => ['budget', 'shape', localToday()] as const,
  /** BUD-17 - under `budget`, so a saved budget or a posted entry asks for it again. */
  suggestion: (periods: number, step: number | undefined, trim: number, fit: boolean) =>
    ['budget', 'suggestion', localToday(), periods, step ?? 'setting', trim, fit] as const,
  calendar: (year: number, month: number) => ['calendar', year, month] as const,
  /** CAL-06 - under `calendar`, so every write that moves money refreshes it. */
  calendarYear: (year: number) => ['calendar', 'year', year] as const,
  /**
   * A dated slice of the ledger - the calendar's month list and its day sheet.
   * The LEDGER itself and an account's trail are not queries (plan D9): they
   * page by cursor and carry the pending row. These two ask for one range and
   * show what comes back, so they cache like anything else.
   */
  transactionsIn: (from: string, to: string) => ['transactions', 'range', from, to] as const,
  /** TXN-24/25 - under `transactions`, so every write that touches an entry refreshes them too. */
  merchants: () => ['transactions', 'merchants'] as const,
  deleted: () => ['transactions', 'deleted'] as const,
  stats: (range: Range) =>
    ['stats', localToday(), 'span' in range ? range.span : 'custom',
      'span' in range ? range.on : range.from, 'span' in range ? '' : range.to] as const,
  rules: (kind?: string) => ['rules', localToday(), kind ?? 'all'] as const,
  subscriptions: () => ['subscriptions', localToday()] as const,
  detected: () => ['detected', localToday()] as const,
  projection: (months: 3 | 6 | 12) => ['projection', localToday(), months] as const,
  /** REC-35 - under `projection`, so a payment, a plan or a balance refreshes it. */
  payoff: (extra: string, payments: string) => ['projection', 'payoff', localToday(), extra, payments] as const,
  /** REC-27 - an unsaved plan's what-if, keyed by the plan itself. */
  whatIf: (months: 3 | 6 | 12, draft: string) => ['projection', 'what-if', localToday(), months, draft] as const,
  /** STA-12 - under `stats`, so every write that moves money refreshes the review too. */
  review: (on?: string) => ['stats', 'review', localToday(), on ?? 'last'] as const,
  reviewOffer: () => ['stats', 'review-offer', localToday()] as const,
  /** SEC-12/32 - the Security activity screen: sessions, sign-ins, passkeys. */
  activity: () => ['security', 'activity'] as const,
  cardLookahead: () => ['cards', 'lookahead', localToday()] as const,
  statement: (accountId: number, closes: string) => ['statement', accountId, closes] as const,
  health: () => ['health'] as const,
  /** misc/AI - may this user ask, opted in, questions left today. Never a conversation: that is assistantStore. */
  assistantStatus: () => ['assistant', 'status'] as const,
};

/** How long each answer stays fresh before a background refetch (plan §2.3). */
export const STALE = {
  lookups: 5 * 60_000, // accounts, goals - a write invalidates them anyway
  taxonomy: 30 * 60_000, // categories, tags - renamed a handful of times a month
  derived: 5 * 60_000, // calendar, stats, rules, projection
  shape: 30 * 60_000, // the budget's own structure
  statement: 30_000, // a card's closed statement, while its sheet is open
  health: 60_000,
  assistant: 60_000, // the questions-left count moves with every question, which invalidates it
} as const;

/**
 * What each group of a write invalidates. React Query matches a key by PREFIX,
 * so `['budget']` covers every budget key and `['stats']` every range.
 *
 * `transactions`, `budget` and `preferences` also reach the three hand-rolled
 * stores - that part lives in `afterWrite` (lib/invalidate.ts), because the
 * stores are not queries.
 */
export const GROUP_KEYS = {
  transactions: [['transactions']],
  accounts: [['accounts']],
  categories: [['categories']],
  tags: [['tags']],
  goals: [['goals']],
  budget: [['budget']],
  calendar: [['calendar']],
  stats: [['stats']],
  rules: [['rules'], ['subscriptions'], ['detected']],
  projection: [['projection'], ['cards']],
  statements: [['statement']],
  preferences: [],
  security: [['security']], // SEC-12/32 - nothing here shows money
  assistant: [['assistant']], // misc/AI - an opt-in or a question asked; never money
} as const satisfies Record<string, readonly (readonly unknown[])[]>;

export type Group = keyof typeof GROUP_KEYS;

/**
 * Everything that shows money - what a write reaches when in doubt. A posted
 * transaction lands in all of these: the ledger, the balances, the allowance,
 * the calendar day, the stats slice, a plan's remaining, the months ahead.
 */
export const MONEY: readonly Group[] = [
  'transactions',
  'accounts',
  'budget',
  'calendar',
  'stats',
  'rules',
  'projection',
  'goals',
  'statements',
];

/** A restore or an import replaces the lot, preferences and lookups included. */
export const EVERYTHING: readonly Group[] = [...MONEY, 'categories', 'tags', 'preferences'];

/**
 * Mark every cached answer that depended on these groups as stale. React Query
 * matches by prefix, so one entry covers every key under it; a query no screen
 * is watching is dropped rather than refetched.
 *
 * Components call `afterWrite` (lib/invalidate.ts), never this. It is exported
 * for the two places that CANNOT import that file without a cycle, because it
 * imports them: `ledgerStore.applyOutcome` and `removeIds`, which already do
 * the rest of the job themselves.
 */
export function invalidateGroups(groups: Iterable<Group>): void {
  for (const group of new Set(groups)) {
    for (const key of GROUP_KEYS[group]) void queryClient.invalidateQueries({ queryKey: key });
  }
}
