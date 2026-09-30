/**
 * Accounts, categories and tags by id - what a transaction row needs to show a
 * name and a colour instead of a number.
 *
 * These three are the most fetched answers in the app: seventeen screens and
 * components ask for them, and before the cache every one of them fetched its
 * own copy on every mount (plan §1.2/§1.3). They now come from the query cache
 * (misc/archive/UX_RESPONSIVENESS_PLAN.md §2.2), so the whole app shares one copy of
 * each, a second screen needing them costs nothing, and a write refreshes them
 * through `afterWrite` rather than through a counter.
 *
 * Still page memory only, still dropped on lock (SEC-29) - `queryClient.clear()`
 * in App.tsx.
 */
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { listAccounts, visible, type Account } from '../lib/accounts';
import { flatten, listCategories, type Category } from '../lib/categories';
import { keys, STALE } from '../lib/queryKeys';
import { listTags, type Tag } from '../lib/tags';

export interface Lookups {
  /** ACC-39: the wallet is not here. `accountById` still holds it, so a row pointing at it has a name. */
  accounts: Account[];
  tree: Category[];
  tags: Tag[];
  accountById: Map<number, Account>;
  categoryById: Map<number, Category>;
  tagById: Map<number, Tag>;
  ready: boolean;
}

// Stable identities, so a screen waiting on its first fetch does not rebuild
// the maps below on every render.
const NO_ACCOUNTS: Account[] = [];
const NO_CATEGORIES: Category[] = [];
const NO_TAGS: Tag[] = [];

export function useLookups(): Lookups {
  const accountsQuery = useQuery({
    queryKey: keys.accounts(),
    queryFn: ({ signal }) => listAccounts(signal),
    staleTime: STALE.lookups,
  });
  const treeQuery = useQuery({
    queryKey: keys.categories(),
    queryFn: ({ signal }) => listCategories(signal),
    staleTime: STALE.taxonomy,
  });
  const tagsQuery = useQuery({
    queryKey: keys.tags(),
    queryFn: ({ signal }) => listTags(signal),
    staleTime: STALE.taxonomy,
  });

  // A screen that fails to load these still draws: the rows fall back to plain
  // labels, and the screen's own data reports its own errors.
  const all = accountsQuery.data?.accounts ?? NO_ACCOUNTS;
  const tree = treeQuery.data ?? NO_CATEGORIES;
  const tags = tagsQuery.data ?? NO_TAGS;
  const ready = accountsQuery.isSuccess && treeQuery.isSuccess && tagsQuery.isSuccess;

  // Rebuilt only when an answer actually changes. React Query keeps the same
  // object identity across a refetch that returned the same data, so a quiet
  // background refresh does not re-render every row on the screen.
  return useMemo(
    () => ({
      // ACC-39. Filtered ONCE, here, rather than in the seventeen places that
      // ask: a picker that offered the wallet would let money be moved into
      // cash the user does not track.
      accounts: visible(all),
      tree,
      tags,
      accountById: new Map(all.map((a) => [a.id, a])),
      categoryById: new Map(flatten(tree).map((c) => [c.id, c])),
      tagById: new Map(tags.map((t) => [t.id, t])),
      ready,
    }),
    [all, tree, tags, ready],
  );
}
