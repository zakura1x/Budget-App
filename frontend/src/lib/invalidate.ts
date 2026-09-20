/**
 * What a write touched, said once (misc/UX_RESPONSIVENESS_PLAN.md §2.4).
 *
 * Before this, every sheet that wrote something bumped `ledgerStore.version`
 * by hand and trusted the screens keyed on it to refetch. That signal does
 * reach those screens - but NOT `ledgerStore.items` or `budgetStore.status`,
 * which reload only when something calls their `load()`. Eleven call sites
 * bumped the counter and stopped there, so a plan payment, a typed balance, a
 * renamed category or a new receipt could stay invisible on Home for the rest
 * of the session.
 *
 * The rule: a component never invalidates by hand. It calls `afterWrite()` and
 * names what the write touched; this file decides what that means.
 *
 * Step 7 of the plan deletes the version counter (D6); nothing at a call site
 * changes when it goes - that is the point of routing them all through one
 * function.
 */
import { invalidateGroups, type Group } from './queryKeys';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';

// The vocabulary itself lives in queryKeys.ts beside the keys each group
// stands for - the stores import it from there, and cannot import this file.
export { EVERYTHING, MONEY, type Group } from './queryKeys';

/**
 * Tell the app a write landed, and what it touched.
 *
 * `afterWrite('tags', 'transactions')` - a deleted tag; the server stripped its
 * id from every transaction, so the rows in memory are stale too.
 * `afterWrite(...MONEY)` - anything that posted, moved or repriced money.
 */
export function afterWrite(...groups: Group[]): void {
  const touched = new Set<Group>(groups);
  invalidateGroups(touched);

  // The two stores React Query will not own (plan D9). They hold the ledger's
  // rows and the budget status, and the version bump below never reloads them.
  // Both are FORCED: each skips a fetch that is still fresh, and a write is
  // exactly the thing that makes "fresh" wrong.
  if (touched.has('transactions')) void useLedgerStore.getState().load(undefined, { force: true });
  // `load(null)` is the current period on purpose: after a write that moved
  // money, the figure worth showing is today's. Browsing another period is
  // only protected from being yanked on the Outcome path (`acceptOutcome`).
  if (touched.has('budget')) void useBudgetStore.getState().load(null, { force: true });

  // Down to ONE consumer: the account page's trail, the last list that is
  // neither a query nor the ledger store (plan D9 - it pages by cursor and the
  // Month view walks every page). It goes when that moves to `useInfiniteQuery`.
  useLedgerStore.setState((s) => ({ version: s.version + 1 }));
}
