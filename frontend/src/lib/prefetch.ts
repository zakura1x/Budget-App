/**
 * Getting there before the finger does (misc/archive/UX_RESPONSIVENESS_PLAN.md §2.5,
 * step 5).
 *
 * Three moments:
 *   unlock        the answers every screen needs are asked for once, while the
 *                 user is still looking at Home
 *   tab press     `pointerdown` is 80-150 ms before the tab actually changes -
 *                 enough for a warm answer to be there on arrival
 *   idle          the lazy chunks (Stats carries recharts) come down once the
 *                 app is quiet, so the first tap on one does not wait for JS
 *
 * Nothing here forces: every call goes through the same freshness rules as a
 * screen's own, so a prefetch of something fresh costs nothing at all. And
 * nothing here is persisted (SEC-29) - it only fills the same page-memory
 * cache that `queryClient.clear()` empties on lock.
 */
import { listAccounts } from './accounts';
import { listCategories } from './categories';
import { queryClient } from './queryClient';
import { keys, STALE } from './queryKeys';
import { getMonth } from './calendar';
import { listRules } from './recurring';
import { listGoals } from './security';
import { getStatement } from './statements';
import { listTags } from './tags';
import { listMerchants } from './transactions';
import { LAZY_SCREENS } from '../screens/lazy';
import { useBudgetStore } from '../stores/budgetStore';
import { useLedgerStore } from '../stores/ledgerStore';

const prefetch = <T,>(key: readonly unknown[], fn: (signal: AbortSignal) => Promise<T>, staleTime: number) =>
  queryClient.prefetchQuery({ queryKey: key, queryFn: ({ signal }) => fn(signal), staleTime });

/** The three answers almost every screen needs, plus the goals beside them. */
export function warmOnUnlock(): void {
  void prefetch(keys.accounts(), listAccounts, STALE.lookups);
  void prefetch(keys.categories(), listCategories, STALE.taxonomy);
  void prefetch(keys.tags(), listTags, STALE.taxonomy);
  void prefetch(keys.goals(), listGoals, STALE.lookups);
}

/** What the tab about to be tapped will ask for. */
export function prefetchTab(path: string): void {
  if (path === '/') {
    // Home's two figures live in the stores, not the query cache (plan D9);
    // both skip the request when what they hold is still fresh.
    void useLedgerStore.getState().load({});
    void useBudgetStore.getState().load(null);
    return;
  }
  if (path === '/accounts') {
    void prefetch(keys.accounts(), listAccounts, STALE.lookups);
    void prefetch(keys.goals(), listGoals, STALE.lookups);
    return;
  }
  if (path === '/calendar') {
    const now = new Date();
    void prefetch(keys.calendar(now.getFullYear(), now.getMonth() + 1),
      (signal) => getMonth(now.getFullYear(), now.getMonth() + 1, signal), STALE.derived);
  }
  // `/more` is a menu over one cheap /health call; nothing worth warming.
}

/**
 * The same answers, for code that needs them OUTSIDE a render - a sheet that
 * sets itself up when it opens, rather than drawing a list.
 *
 * `ensureQueryData` returns the cached answer when it is still fresh and
 * fetches only when it is not, sharing the request with anything already in
 * flight. The sheets used to fetch their own copies every time they opened:
 * the add sheet alone asked for accounts, categories and tags on every tap of
 * [+], the most used button in the app (seen in logs/app.jsonl, 2026-09-20).
 */
const ensure = <T,>(key: readonly unknown[], fn: (signal: AbortSignal) => Promise<T>, staleTime: number) =>
  queryClient.ensureQueryData({ queryKey: key, queryFn: ({ signal }) => fn(signal), staleTime });

export const ensureAccounts = () => ensure(keys.accounts(), listAccounts, STALE.lookups);
export const ensureCategories = () => ensure(keys.categories(), listCategories, STALE.taxonomy);
export const ensureTags = () => ensure(keys.tags(), listTags, STALE.taxonomy);
export const ensureRules = () => ensure(keys.rules(), (signal) => listRules(undefined, signal), STALE.derived);
/** TXN-24 - the add sheet's merchant suggestions, asked for once and kept until a write changes them. */
export const ensureMerchants = () => ensure(keys.merchants(), listMerchants, STALE.derived);
export const ensureStatement = (accountId: number, closes: string) =>
  ensure(keys.statement(accountId, closes), (signal) => getStatement(accountId, closes, signal), STALE.statement);

/**
 * Pull the lazy chunks down while the app is idle. They are local files served
 * by the same host, so this costs no round trip the user will ever notice -
 * and it is the difference between a tap on Stats drawing and a tap on Stats
 * showing a Suspense skeleton first.
 */
export function warmLazyScreens(): void {
  const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 1500));
  for (const load of LAZY_SCREENS) idle(() => void load().catch(() => undefined));
}
