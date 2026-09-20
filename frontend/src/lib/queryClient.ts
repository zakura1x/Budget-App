/**
 * The one query client (misc/UX_RESPONSIVENESS_PLAN.md §2.1, D1).
 *
 * It holds what the API returned, in PAGE MEMORY ONLY. Nothing here is ever
 * persisted: no `persistQueryClient`, no storage persister, no IndexedDB
 * (SEC-29 - this browser origin is shared with QUOT, and every API response
 * is `Cache-Control: no-store`). `clear()` runs the moment the app locks or
 * signs out (App.tsx), so a decrypted figure never outlives the DEK in the
 * page any more than it does in the server's session keyring.
 *
 * Several of React Query's defaults have to be turned OFF, because
 * `lib/api.ts` and `useCatchUp` already own the behaviour they duplicate.
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // api.ts owns the ONE shared silent refresh on 401 and the
      // SESSION_LOCKED / SESSION_REVOKED events. Automatic retries would fire
      // repeat requests at a locked or revoked session before our own handler
      // ran, and two refreshes with the same token look like a replay (SEC-06).
      retry: false,
      // Stale-while-revalidate (D2): a screen paints its cached figures at
      // once and refetches quietly behind them. Per-key overrides in queryKeys.ts.
      staleTime: 30_000,
      // How long an unmounted screen's data is kept. A tab switch and back is
      // well inside this, which is the whole point.
      gcTime: 5 * 60_000,
      // A resume within staleTime costs nothing; past it, the figures are
      // refreshed for a new day. useCatchUp still owns posting what fell due.
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      // Screens keep showing their own inline error strips; nothing throws
      // into an error boundary and blanks a page that has good data on it.
      throwOnError: false,
    },
  },
});

/**
 * Dev-only peek at what is cached, for checking that a lock really empties it:
 * `__ZBDGT_CACHE()` in the console. Stripped from the production bundle.
 */
if (import.meta.env.DEV && typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__ZBDGT_CACHE = () =>
    queryClient.getQueryCache().getAll().map((q) => q.queryKey);
}
