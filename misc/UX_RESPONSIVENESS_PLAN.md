# Tab switching, caching and "did that save?" — findings and plan

Written 2026-09-20, from two things you noticed:

1. **Every tab switch looks like a reload.** Skeletons flash, figures blink,
   the screen you left is rebuilt from nothing when you come back.
2. **Some writes do not reach the rest of the app** until you leave the screen
   and come back — you want a save to land everywhere, at once, without a tab
   switch being the refresh button.

Part 1 is what is actually happening (measured from the code, not guessed).
Part 2 is the design that fixes it. Part 3 is the write-by-write audit you
asked for, with the four real bugs it turned up. Part 4 is the build order.

Part 3's fixes were built on 2026-09-20 (step 0); the caching work in Part 2 is
still to come. Each row below says where it stands.

---

## Status — decided 2026-09-20 · **steps 0–2 built 2026-09-20**

- **Step 0** — `lib/invalidate.ts` and every stale-after-write fix in Part 3.
- **Step 1** — `@tanstack/react-query` 5.103.1, `lib/queryClient.ts`,
  `lib/queryKeys.ts`, the provider in `main.tsx`, `queryClient.clear()` on lock.
- **Step 2** — `useLookups` (accounts, categories, tags) reads the cache, and
  `ledgerStore`'s `Outcome` paths invalidate it.
- **Step 3** — the screens: Home's category grid, Accounts, AccountDetail,
  Calendar (grid, month list, day sheet), Stats, Recurring, Projection, Goals,
  Categories, Tags, Budget, More, plus `AccountPlans`, `AccountPayments` and
  `CardPayments`.
- **Step 4** — `ledgerStore` and `budgetStore` skip a fetch that is still
  fresh (60 s), and every write forces them past it.
- **Step 5** — prefetch on tab press, the lookups warmed at unlock, the lazy
  chunks warmed on idle.
- **Step 6** — scroll memory per route, and D7's hairline.
- **Step 7** — partly: `dist/` is rebuilt and the version counter is down to
  one reader, but it cannot go until the account trail moves (see below).
- **Step 8** (found in the log, not in the original plan) — the SHEETS. They
  were never in step 3's list and each fetched its own copies on open: the add
  sheet asked for accounts, categories and tags on every tap of [+], the
  preview fetched the whole rule list to open one plan, and the account and
  statement sheets refetched categories. They read the cache now, through
  `ensure*` in `lib/prefetch.ts`. Also fixed there: prefetch-on-press raced the
  screen's own mount and fetched the two hand-rolled stores twice - they now
  share one in-flight request, as a query does. (`BillSheet` was the fifth
  sheet, found by grep rather than by the log: same whole-rule-list fetch as
  the preview.)

**What is left, and why**, is in §4.3. Measured cost of the dependency: the main chunk
went from 162.21 KB to 174.17 KB gzipped, **+11.96 KB**.

| # | Question | Answer | Result |
|---|---|---|---|
| **D1** | How do we cache? | **B** | Add `@tanstack/react-query`. Not a UI dependency, so the "no UI deps" rule in CLAUDE.md is untouched. It must be configured *against* several of its defaults — see §2.1. |
| **D2** | Freshness policy | **A** | Stale-while-revalidate: the cached figure paints instantly, a background refetch runs if it is older than its `staleTime`, the swap is silent. Self-heals a missed invalidation. |
| **D3** | Tab model | **A** | Screens still unmount; their data comes from the cache and their scroll position is remembered. No always-mounted tabs. |
| **D4** | A single `GET /bootstrap`? | **A** | Later, if the numbers still ask for it once the cache is in. |
| **D5** | Prefetch | **A** | Both: data prefetched on tab press, lazy chunks warmed on idle. |
| **D6** | The `ledgerStore.version` counter | **A** | `afterWrite()` keeps bumping it during the migration; it is deleted in the last step, once every screen is on the cache. |
| **D7** | Background-refresh cue | **A** | Silent for 400 ms, then a 2 px accent line under the header. |
| **D8** | Order of work | **A** | Part 3's stale-after-write fixes land first, as their own commit, on top of correct invalidation. |
| **D9** | Do `ledgerStore` / `budgetStore` move to React Query? | **No** | They stay hand-rolled. Both already survive a tab switch, and they own the two delicate flows — the pending row (`addPending`/`failPending`) and the `Outcome` merge (`applyOutcome`/`acceptOutcome`). React Query takes the 15 screens that refetch on mount; `afterWrite()` reloads these two. Revisit `useInfiniteQuery` for the ledger and account trails only if paging turns out to matter in use. |

---

## Part 1 — Why every tab feels like a refresh

### 1.1 Each screen owns its data, and a tab switch destroys it

`AppTabs` renders one `<Routes>`; switching tabs unmounts the old screen. Every
screen holds its data in local `useState` and fetches it in a mount effect:

```tsx
const [data, setData] = useState<AccountList | null>(null);
useEffect(() => { void load(controller.signal); }, [load, version]);   // Accounts.tsx:147
```

So the data dies with the component and is fetched again on return — always from
zero, always with a skeleton. The two exceptions (`ledgerStore`, `budgetStore`)
are module-level zustand stores that *do* survive a tab switch, which is
precisely why Home feels better than Stats or Recurring.

### 1.2 What one tab switch actually costs

Counted from the mount effects, per visit:

| Tab | Requests on every entry |
|---|---|
| Home | `GET /transactions` (conditionally) · `GET /budgets/current` · `/accounts` · `/categories` · `/tags` — **up to 5** |
| Accounts | `/accounts` · `/goals` — **2** |
| Calendar | `/calendar/{y}/{m}` · `/transactions?from,to` (month list) · `/accounts` · `/categories` · `/tags` — **5** (+1 when a day sheet opens) |
| Stats | `/stats/overview` · `/accounts` · `/categories` · `/tags` — **4** |
| Recurring | `/recurring` · `/recurring/subscriptions` · `/recurring/detected` · `/accounts` · `/categories` · `/tags` — **6** |
| Projection | `/recurring/projection` · `/recurring/cards` · `/accounts` · `/categories` · `/tags` — **5** |
| Account detail | `/accounts` · `/transactions?account=` · `/goals` · plans · `/accounts` + `/categories` + `/tags` again — **7** |

Three of those repeat on nearly every screen: `useLookups` re-fetches accounts,
categories and tags on every mount so a transaction row can print a name and a
colour. They change a handful of times a month.

### 1.3 The same call twice, in the same mount

`AccountDetail` calls `listAccounts()` in `loadAccount` **and** `useLookups`
calls `listAccounts()` in the same render — two identical in-flight requests for
one screen. `/accounts` is not a cheap endpoint: `account_service.list_accounts`
derives every card's bills and statement, plan remainders, goal set-asides and
investment valuations over all postings. Nothing dedupes them, in `lib/api.ts`
or anywhere else.

### 1.4 No HTTP cache is available — by design

`SecurityHeaders` sets `Cache-Control: no-store` on every API response, and
`lib/api.ts` sends `cache: 'no-store'`. That is correct (SEC-29: the browser
origin is shared with QUOT) and it means **the only cache we are allowed is
JavaScript memory that dies with the page** — which is what this plan builds.
It also rules out ETag/304: a conditional request needs a stored copy.

### 1.5 Screens that deliberately blank themselves

- `Calendar` → `MonthList`: `setPage(null)` before every fetch, so stepping a
  month, *and every write anywhere*, blanks the list to a skeleton.
- `Calendar` → `DaySheet`: `setRows(null)` on every `version` change, so adding
  an entry from the open day sheet flashes the sheet empty before redrawing it.
- `Calendar` grid: keeps `data` but only renders it when the month matches, so
  swiping months is a blank grid each time — including months you just looked at.

Stats and Projection already keep their old data while refetching. They are the
model; the rest should match.

### 1.6 The lazy chunks load on the first tap

Stats, Recurring, Projection, Goals, Backup, Admin and AboutEncryption are
`lazy()` (App.tsx). The first tap on Stats downloads recharts *and then* starts
its requests, behind the `Suspense` skeleton. Nothing warms them.

### 1.7 Scroll position is lost

Every return to a tab starts at the top. Half of "it reloaded everything" is
this, not the data.

### 1.8 Secondary costs

- `useLookups` rebuilds three `Map`s on **every render** of every consumer
  (`new Map(accounts.map(...))` in the return statement) — not memoized.
- The API budget is 200 requests/minute per account (`RATE_LIMIT_REQUESTS`).
  Five requests per tab switch plus a write-storm of refetches is not close to
  it today, but it is the same pressure the cache removes.

---

## Part 2 — The design

Five pieces. Each one is independently useful; together they make a tab switch
paint from memory and touch the network only when something actually changed.

### 2.1 The query client, and the defaults we must override (D1 = B)

`@tanstack/react-query` v5, one `QueryClient` created in `main.tsx`, provided
above `<App />`. It is memory-only unless a persister plugin is added — **we
never add one** (SEC-29). Four of its defaults have to change, because
`lib/api.ts` and `useCatchUp` already own the behaviour they duplicate:

```ts
// frontend/src/lib/queryClient.ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // api.ts owns the 401 silent refresh and the SESSION_LOCKED event. Three
      // automatic retries would fire three requests at a locked session before
      // our own handler ran, and would look like a replay to the server (SEC-06).
      retry: false,
      staleTime: 30_000,        // per-key overrides in §2.3
      gcTime: 5 * 60_000,       // an unmounted screen's data is kept this long
      refetchOnWindowFocus: true,   // suppressed by staleTime; a quick resume costs nothing
      refetchOnReconnect: true,
      throwOnError: false,      // screens keep showing their inline error strips
    },
  },
});
```

Three more things it gives us that we should use rather than hand-roll:
in-flight **deduplication** by key (this alone kills §1.3), **structural
sharing** (an unchanged refetch keeps referential identity, so the screen does
not re-render at all), and **`AbortSignal` passthrough** — every fetcher in
`lib/*.ts` already takes an optional signal, so they plug straight in.

**Clearing on lock is ours to wire and is the SEC-29 line.**
`queryClient.clear()` goes in the existing `App.tsx` status effect, beside
`resetLedger()` / `resetBudget()`, so lock, idle-lock, sign-out and
`SESSION_REVOKED` all drop every cached figure. Decrypted data must not outlive
the key in the page any more than it does on the server.

### 2.2 What a screen looks like afterwards

```tsx
const { data: accounts, isPending, isFetching } = useQuery({
  queryKey: keys.accounts,
  queryFn: ({ signal }) => listAccounts(signal),
  staleTime: 5 * 60_000,
});
```

Rules, and this is the whole UX change:

| State | What the screen shows |
|---|---|
| `isPending` (no cached data yet) | the skeleton it shows today — **once per session**, not per visit |
| cached data, fresh | the data, **no request at all** |
| cached data, stale | the data immediately, a background refetch, silent swap (D7's hairline once `isFetching` passes 400 ms) |
| refetch fails | `data` stays, `error` is set — the existing inline error strip appears and a good screen is never blanked |

`enabled: false` covers the idle cases (`DaySheet` with no day chosen). Aborts
are handled by React Query itself, so the `AbortError` checks scattered through
the screens go away.

### 2.3 Query keys

One table, kept in `lib/queryKeys.ts` so a key is never typed twice:

| Key | Endpoint | `staleTime` | Invalidated by |
|---|---|---|---|
| `['accounts',today]` | `GET /accounts` | 5 min | accounts, transactions, rules, goals, statements, bills |
| `['categories']` | `GET /categories` | 30 min | categories |
| `['tags']` | `GET /tags` | 30 min | tags, transactions (a tag delete strips ids) |
| `['goals',today]` | `GET /goals` | 5 min | goals, transactions |
| `['budget','shape',today]` | `GET /budgets` | 30 min | budget |
| `['calendar',year,month]` | `GET /calendar/…` | 5 min | transactions |
| `['stats',today,span,from,to]` | `GET /stats/overview` | 5 min | transactions, accounts (adjustments feed Stats) |
| `['rules',today,kind]` · `['subscriptions',today]` · `['detected',today]` | `GET /recurring…` | 5 min | rules, transactions |
| `['projection',today,months]` · `['cards','lookahead',today]` | `GET /projection`, `/projection/cards` | 5 min | rules, transactions, accounts, bills |
| `['statement',accountId,closes]` | `GET /statements/…` | 30 s | statements, transactions |
| `['health']` | `GET /health` | 60 s | — |

Three things are **not** in this table, all of them D9: the ledger's rows and
the account trails (`ledgerStore`, `AccountDetail`'s own paging), the budget
STATUS (`budgetStore` — only the budget's *shape*, the editor's data, is a
query) and the preferences (`preferencesStore`, loaded once after unlock). If
the ledger ever moves, it enters as `['transactions', filters]` under
`useInfiniteQuery`. `afterWrite` reloads all three stores itself, so a caller
never has to know which data lives where.

**Every key that depends on the client's `today` carries it**, and nearly all of
them do: `/accounts`, `/goals`, `/recurring`, `/projection`, `/stats/overview`
and `/budgets` all take `today` as a query parameter on purpose. A response
cached yesterday is a wrong figure, not an old one — so the date is part of the
key, and midnight changes the key and refetches by itself.

### 2.4 `lib/invalidate.ts` — one place that says what a write touched

Replaced the pattern of `useLedgerStore.setState(s => ({ version: s.version + 1 }))`
sprinkled through eleven files. It is also where D9 is honoured: the hand-rolled
stores are reloaded in the same breath as the query cache, so a caller never has
to remember that transactions live somewhere else.

```ts
export function afterWrite(...groups: Group[]): void {
  const touched = new Set<Group>(groups);
  invalidateGroups(touched);                                        // the query cache
  if (touched.has('transactions')) void useLedgerStore.getState().load();   // D9
  if (touched.has('budget')) void useBudgetStore.getState().load(null);     // D9
  useLedgerStore.setState((s) => ({ version: s.version + 1 }));     // D6: retired in step 7
}
```

`Group`, `MONEY`, `EVERYTHING` and `invalidateGroups` live in `queryKeys.ts`,
beside the keys each group stands for, and `invalidate.ts` re-exports them so no
call site has to know that. The split is not cosmetic: `ledgerStore` must
invalidate too — `applyOutcome` and `removeIds` already hold the new rows and
the new allowance from the write's `Outcome`, but every *other* cached figure a
posted row moves (balances, the calendar day, the stats slice, a plan's
remaining) still has to be asked for again — and `ledgerStore` cannot import
`invalidate.ts`, because `invalidate.ts` imports `ledgerStore`.

The rule, and it should go in CLAUDE.md when this lands: **a component never
invalidates by hand; it calls `afterWrite(...)` and names what it touched.**
`RuleSheet.refreshMoney()` (RuleSheet.tsx:232) is already this idea, done once
correctly — `afterWrite` is that generalised.

A write that already knows the answer should still skip the round trip:
`applyOutcome`/`acceptOutcome` keep merging the `Outcome` a write returns, and
where a query holds the same figure, `queryClient.setQueryData` writes it in
rather than invalidating it.

### 2.5 Feel: prefetch, chunks, scroll

- **Prefetch on press** (D5): `onPointerDown` on each tab in `BottomTabBar`
  calls `queryClient.prefetchQuery` for that tab's primary resource and
  `import()`s its lazy chunk. A finger-down to finger-up is 80–150 ms of free
  head start.
- **Warm the chunks on idle**: after the first paint, `requestIdleCallback` →
  `import('./screens/Stats')` and friends. The bundle is local and already
  committed; this costs nothing but ordering.
- **Warm on unlock**: one `prefetchQuery` each for `accounts`, `categories`,
  `tags` and the current budget status, next to the existing `loadPreferences()`
  in App.tsx, so the first tab you touch after unlocking is already warm.
- **Scroll memory**: `hooks/useScrollMemory.ts` — a module `Map<pathname, y>`,
  restored on mount in a `requestAnimationFrame`, saved on a throttled scroll
  and on unmount, cleared with the cache on lock.
- **Skeleton sweep**: delete every `setX(null)` that precedes a refetch (§1.5),
  and make the remaining skeletons conditional on `data === undefined`.

### 2.6 What this leaves us with

A tab switch on warm data becomes: **zero requests, no skeleton, the scroll
position you left**. A tab switch on stale data: the old figures on screen
instantly, one background request, a silent swap. A write: the figures change
everywhere at once, because `afterWrite` says so.

---

## Part 3 — The write → refresh audit

Every write in the app, what it changes, and what refreshes today. "Version++"
means it bumps `ledgerStore.version`, which makes the screens keyed on it refetch
— but note that **a version bump does not reload `ledgerStore.items` or
`budgetStore.status`**; those two only reload when something calls `load()`
explicitly. That distinction is where the bugs are.

| # | Write | Where | Refreshes now | State |
|---|---|---|---|---|
| 1 | Add / edit / delete transaction, repeat last | `TransactionSheet` | `applyOutcome` / `removeIds`: ledger rows + day totals + budget status from the Outcome, version++ | ✅ correct — the reference |
| 2 | Delete from the preview / the ledger row | `TransactionPreview`, `Ledger` | same path | ✅ |
| 3 | Recurring rule: create, edit, delete, pause, skip, pay off, revert a conversion | `RuleSheet.refreshMoney()` | `afterWrite(...MONEY)` | ✅ — `refreshMoney()` was the idea `afterWrite` generalises |
| 4 | Recurring & interest catch-up | `useCatchUp` | `afterWrite(...MONEY)`, only when something posted | ✅ |
| 5 | Goal add money / use money / edit | `GoalSheets.refreshEverything()` | `afterWrite('accounts', 'goals')` | ✅ writes no transaction (GOA-08), so the ledger and the allowance are left alone |
| 6 | Restore a backup, import CSV / Budget-app xlsx | `Backup`, `BudgetAppImportSheet` | `afterWrite(...EVERYTHING)`, filters reset first | ✅ **fixed 2026-09-20** |
| 7 | **Pay a plan** (REC-32) | `PlanPaymentSheet` | `afterWrite(...MONEY)` | ✅ **fixed 2026-09-20** — was version++ only, so a posted transfer never reached the ledger or budget stores |
| 8 | **Pay the next occurrence early** (REC-33) | `PayNowSheet` | `afterWrite(...MONEY)` | ✅ **fixed 2026-09-20** — same as #7 |
| 9 | **Add / edit / archive an account from the Accounts tab** | `Accounts` → `AccountSheet` | `afterWrite(...MONEY)` | ✅ **fixed 2026-09-20** — had no version bump at all, so an ACC-29 adjustment was invisible everywhere else; both call sites now behave identically |
| 10 | **Category create / edit / delete / reorder** | `Categories` → `CategorySheet` | `afterWrite('categories')`; a delete adds `'transactions','budget','stats'` | ✅ **fixed 2026-09-20** — names and colours now update on every row, grid and slice; reorder too (CAT-05) |
| 11 | **Tag create / edit / delete** | `Tags` → `TagSheet` | `afterWrite('tags')`; a delete adds `'transactions'` | ✅ **fixed 2026-09-20** — `tag_service.delete_tag` strips the id server-side, so the rows reload with it |
| 12 | **Receipt attach / remove** (TXN-15) | `ReceiptControl` | `afterWrite('transactions')` | ✅ **fixed 2026-09-20** — `attachment_id` lives on the row, so the row itself had to reload |
| 13 | Statement check / charge / interest / dispute | `StatementSheet` | `afterWrite(...MONEY)` inside the sheet | ✅ **fixed 2026-09-20** — the `onChanged` prop is gone; it was double-fetching the account page |
| 14 | Typed bill list (ACC-35) | `CardBills` | `afterWrite('accounts', 'budget', 'projection')` | ✅ **fixed 2026-09-20** — the card-due alert is a budget figure and the tab bar's dot |
| 15 | Edit an account from the account page | `AccountDetail` → `AccountSheet` | `afterWrite(...MONEY)` | ✅ **fixed 2026-09-20** — and the duplicate account+trail fetch it was doing is gone |
| 16 | Investment valuation (ACC-08/12) | `AccountSheet` | as #9 / #15, through `updateAccount` | ✅ **fixed 2026-09-20** — both call sites now agree |
| 17 | Budget create / update | `Budget` | `afterWrite('budget', 'stats', 'calendar')` | ✅ **fixed 2026-09-20** |
| 18 | Preferences (theme, palette, week start, auto-lock, budget defaults) | `Settings` | store update + `reloadBudget(null)` | ✅ |
| 19 | Password change, DEK rotation, account deletion | `SecuritySheets` | ends sessions / signs out | ✅ (the App.tsx status effect clears everything) |
| 20 | Admin activate / delete user | `Admin` | local | ✅ (touches no budget data) |

### 3.1 The fix, in one shape (built 2026-09-20)

Each row became one line at its call site:

```ts
await payPlan(rule.id, body);
afterWrite(...MONEY);                              // #7, #8
```
```ts
onSaved={() => afterWrite(...MONEY)}               // #9, #15, #16 — both call sites, one behaviour
```
```ts
afterWrite('categories', 'transactions', 'budget', 'stats');   // #10, a delete
afterWrite('tags', 'transactions');                            // #11, a delete
afterWrite('transactions');                                    // #12
afterWrite('accounts', 'budget', 'projection');                // #14
afterWrite(...EVERYTHING);                                     // #6
```

`afterWrite` is now the only thing that knows what "invalidate transactions"
means — including reloading `ledgerStore` and `budgetStore`, which is the step
eleven call sites used to forget. `ledgerStore.applyOutcome` / `removeIds` keep
their own inline bump: they live inside the store `afterWrite` imports, and they
already do the whole job (rows #1–#2).

### 3.2 One related quirk worth fixing at the same time

`Home`'s mount effect only reloads the ledger when the filters are non-empty or
the list is empty:

```tsx
if (filtered || items.length === 0) void load({});    // Home.tsx
```

That is the deliberate "don't refetch what we already have" instinct this whole
plan generalises — but with no freshness check it is also why a write that skips
`ledger.load()` (rows #7–#14) can leave a stale Recent list on Home for the rest
of the session. Under the same freshness rule it becomes "reload if older than 60 s or
invalidated", which is both faster *and* correct.

---

## Part 4 — Build order

Each step is a commit that leaves the app working.

| Step | Work | How we check it |
|---|---|---|
| **0** ✅ | **Built 2026-09-20.** `lib/invalidate.ts` with `afterWrite` / `MONEY` / `EVERYTHING`; all 11 hand-written version bumps converted; audit rows #6–#17 fixed; `StatementSheet.onChanged` deleted (the version signal already reloads the account page, so it was fetching twice). `npm run typecheck` clean, 742 backend tests pass, `dist/` rebuilt | Walk the checklist in 4.1 by hand, no tab switching allowed |
| **1** ✅ | **Built 2026-09-20.** v5.103.1; `lib/queryClient.ts` with the §2.1 overrides; `lib/queryKeys.ts` (keys, stale times, groups, `invalidateGroups`); provider in `main.tsx`; `queryClient.clear()` in the App.tsx lock/sign-out effect, beside `resetLedger()`. No devtools dependency added — `__ZBDGT_CACHE()` in the console lists the cached keys in dev builds only | Lock the app, call `__ZBDGT_CACHE()`, expect `[]` |
| **2** ✅ | **Built 2026-09-20.** `useLookups` reads three cached queries and memoizes its `Map`s; `ledgerStore.applyOutcome` / `removeIds` call `invalidateGroups(MONEY)`, which is the seam that keeps balances honest once the lookups no longer follow the version counter | Tab switching should drop from 5 requests to 2 on Home, 4→1 on Stats |
| **3** ✅ | **Built 2026-09-20.** All eleven screens plus `CategoryGrid`, `AccountPlans`, `AccountPayments` and `CardPayments`. The §1.5 blanking is gone (`setPage(null)` / `setRows(null)` before a refetch). Screens that fetched the same answer now share one key: `AccountDetail` no longer fetches the account list beside `useLookups` (§1.3), and the rule list is one answer for the Recurring screen, both account cards and the card page | Server log: a second visit to a warm tab makes **zero** requests |
| **4** ✅ | **Built 2026-09-20.** Both stores keep a fetched-at marker (the budget's per period AND per day, since the server answers as of `today`) and skip a request inside 60 s; `afterWrite` and the two `Outcome` paths pass `{ force: true }`, because a write is exactly what makes "fresh" wrong. `acceptOutcome` marks the current period fresh — the status came back with the write, so Home need not ask. Settings forces a reload only for the seven preferences that move a figure, not for the theme, the palette or the auto-lock. Home's mount effect is now an unconditional `load({})`, which also closes §3.2 | Server log: `/budgets/current` once per minute of Home visits, not once per visit |
| **5** ✅ | **Built 2026-09-20.** `lib/prefetch.ts`: `warmOnUnlock` (accounts, categories, tags, goals), `prefetchTab` on the tab bar's `pointerdown`, `warmLazyScreens` on `requestIdleCallback`. `screens/lazy.ts` holds the lazy list once, so App.tsx and the warmer cannot drift. Nothing forces — a prefetch of something fresh costs nothing | First tap on Stats paints without the Suspense skeleton |
| **6** ✅ | **Built 2026-09-20.** `useScrollMemory` restores per route and, where there is no memory, starts at the top — which now has to be explicit: a warm screen keeps its height, so the scroll would otherwise carry across. `RefreshLine` is D7. The skeleton sweep landed with step 3 | Leave Calendar half-scrolled, go to Home, come back — same place |
| **7** ◐ | `dist/` is rebuilt on every step (invariant 9). **The counter stays for now**: it is down from fifteen readers to exactly one — the account page's trail, the last list that is neither a query nor the ledger store, because it pages by cursor and the Month view walks every page. Deleting it means moving that trail to `useInfiniteQuery`, which is the D9 revisit, not this step. It is documented as a single-purpose signal where it is defined and where it is bumped | One reader; `grep "s.version"` finds `AccountDetail.tsx` and nothing else |

Optional **Step 8** (D4): `GET /bootstrap` — accounts + categories + tags +
budget status + goals in one read-only response under `get_unlocked_context`,
composed from the existing services. Decide after Step 5, with real numbers.

### 4.0 What the request log caught that a diff would not

The app writes `logs/app.jsonl`, one line per request with its duration. Three
things showed up there and nowhere else:

1. **Home fetched `/stats/overview` twice on every visit.** The category grid's
   range is its cache key, and Home passed a month range before the budget
   status arrived, then the period range after — two keys, two fetches. Home
   now waits for `loaded`.
2. **Prefetch-on-press doubled the store fetches.** `pointerdown` asked, the
   screen mounted 100 ms later and asked again; neither answer had landed, so
   neither saw the other's freshness marker. Both stores now share one
   in-flight request per key, which is what React Query does for its own.
3. **The sheets were never migrated** (step 8 above) — invisible in a
   screen-by-screen diff, obvious as three requests before every `POST
   /transactions`.

The lesson for the rest of this work: check the log after each step, not just
the types.

### 4.4 The tests (added 2026-09-20)

`npm test` — vitest, 59 tests in `frontend/src/tests/`, no DOM and no component
rendering. They exist because everything this plan added fails *silently*: a
freshness guard that skips a fetch it should have made shows a wrong figure,
not an error. So they count CALLS, not results.

| File | What it holds to account |
|---|---|
| `ledgerStore.test.ts` | fetch once, skip inside the minute, refetch after it, refetch on different filters, always fetch when forced, **share one request between callers that ask together**, run a forced reload *after* the one in flight (so the rows that land last are the ones read after the write), keep the rows when a refresh fails, and drop everything on reset |
| `budgetStore.test.ts` | the same rules per period, plus: a different period always fetches, a new day always fetches (the endpoint answers "as of today"), `acceptOutcome` counts as a fetch, and browsing another period is not yanked back |
| `invalidate.test.ts` | `afterWrite` forces the right store, leaves the other alone, marks the right keys stale by prefix, bumps the version, and `MONEY` vs `EVERYTHING` reach what they should. Also that every `today`-dependent key carries the date |
| `writePaths.test.ts` | reads the source: **any component calling a mutating helper must call `afterWrite`** (or the `Outcome` paths). Two exemptions, each with its reason. This is the test that would have caught the original six bugs, and it fails for a new write until it says what it touched |

Each guard was checked by breaking the code on purpose and confirming the test
failed — including one round where it did *not*, because it matched the
`afterWrite` **import** rather than a call. It matches calls now.

What they do NOT cover: anything that needs a browser. No component renders, so
the scroll memory, the refresh hairline, the prefetch-on-press timing and every
item in §4.1 remain unverified by machine.

### 4.1 The manual checklist (still needs a person)

For each row, do the write and confirm the change appears **without leaving the
screen**, then check the named screens **without a reload**:

1. Add an expense on a card from Home → ring, Recent, Accounts tile, Calendar
   day cell, Stats, the card's bill.
2. Type a different balance on an account from **Accounts** (answer "not
   recorded") → the adjustment shows in Stats' By Category, the ledger, the
   account trail.
3. Rename a category and change its colour → every transaction row, Home's
   grid, Budget's allocation list, Stats' slices.
4. Delete a tag that is on a transaction → the row loses the chip.
5. Attach a receipt, close the preview, reopen it from Home → the receipt is there.
6. Pay a plan (REC-32) and pay an occurrence early (REC-33) → Home's ring,
   Recent, the plan's remaining, the account balance.
7. Resolve a statement with a charge → Accounts tile, Stats, Projection.
8. Save a typed bill list → cash on hand, Home's alert dot, Months ahead.
9. Restore a backup → everything, from an empty cache.
10. Lock, unlock → nothing from before the lock is on screen before its own
    fresh fetch lands.

### 4.3 What is NOT done

| | Why |
|---|---|
| **The account trail on `useInfiniteQuery`** | The D9 revisit, deferred on purpose. It is the last list that fetches on every visit, and the only thing still reading `ledgerStore.version` - so it also blocks step 7's deletion of that counter. It pages by cursor and the Month view walks every page, so it is real work on the account page's core list, not a mechanical migration. |
| **`Backup` and `Admin` screens** | Rare, lazy-loaded, and their data is shared with nothing. Caching them would buy nothing. |
| **`GET /bootstrap`** (D4) | Decided "later, if the numbers ask". They no longer do: unlock is ~10 requests and the lookups are then warm for the session. |
| **The §4.1 checklist** | Never walked. The request log gives partial evidence — the invalidation cascades after a POST and a DELETE look right — but a receipt attach, a category rename and a tag delete have not been seen working. **This is the one piece of unfinished verification, not unfinished building.** |
| **`/projection` at 1.7–1.9 s** | A backend problem. The cache hides it; nothing has fixed it. It is now the slowest call in the app by 3×. |

### 4.2 Before/after

Measured from `logs/app.jsonl` (the request log the app writes itself), old
bundle and new in the same session on 2026-09-20:

| Moment | Before (05:39) | After steps 0–2 (06:33) |
|---|---|---|
| Unlock | 25 requests, with `/categories` ×5, `/tags` ×5, `/accounts` ×5 | 9 requests, each of those once |
| One Accounts visit | 8 | 2 (`/accounts`, `/goals`) |
| `/categories`, `/tags` over 45 s of tab hopping | once per screen mount | **zero** after the first load |

Step 3 took the rest. Measured again at 07:08, over a longer window (32 s vs
27 s) of the same kind of navigation:

| | Old bundle (27 s) | After steps 0–3 (32 s) |
|---|---|---|
| `/accounts` | **21×** @ 401 ms | **1×** |
| `/categories` · `/tags` | 17× each | 1× each |
| `/goals` | 4× | 1× |
| `/stats/overview` | 4× @ 616 ms | 1× |
| Total | **78 requests, 21.7 s of server time** | **25 requests, 7.2 s** |

Both §1.3 and the category-grid race show up as fixed in that log: `/accounts`
appears once at unlock rather than twice, and so does `/stats/overview`.

What remained was the two stores D9 kept out of the cache — `/transactions` ×9
(legitimate: the ledger plus one trail per account page) and `/budgets/current`
×5. The second is what step 4 fixes: at ~600 ms it is the slowest call in the
app, and Home asked for it on every mount.

| | Requests on a warm tab switch | First paint | Scroll |
|---|---|---|---|
| Before | 2–7 | skeleton, every time | top |
| Target | 0 (fresh) / 1 background (stale) | cached figures, no skeleton | remembered |

---

## Part 5 — Invariants this must not break

1. **SEC-29.** The cache is page memory only. No `localStorage`, no IndexedDB,
   no Cache API — which means **no React Query persister plugin, ever**
   (`persistQueryClient`, `createSyncStoragePersister` and friends are
   forbidden: they write the cache to `localStorage` or IndexedDB by design).
   `app/web/static/sw.js` still never caches `/api/`, and `Cache-Control:
   no-store` stays on every API response.
2. **The cache dies with the key.** `queryClient.clear()` goes in the same
   App.tsx effect as `resetLedger()` / `resetBudget()`, so lock, idle-lock,
   sign-out and `SESSION_REVOKED` all drop it — decrypted figures must never
   outlive the session keyring's DEK, in the page any more than on the server.
3. **`retry: false`.** `lib/api.ts` owns the one shared silent refresh and the
   `SESSION_LOCKED` / `SESSION_REVOKED` events; automatic retries would fire
   repeat requests at a locked or revoked session before our handler ran
   (SEC-06). `@tanstack/react-query` is the only dependency this work adds, and
   it is not a UI library — the "no UI deps, no `shadcn init`" rule is untouched.
4. **`today` is the client's** on every budget-shaped endpoint; it belongs in the
   cache key, never assumed from the server.
5. **Money stays a string.** The cache stores exactly the JSON the API returned;
   nothing re-parses or re-quantises on the way in or out.
6. **Rebuild and commit `app/web/static/dist/`** (invariant 9) — every step here
   is frontend source.
7. Keys, fetchers and `afterWrite` groups cite their FEATURES.md ids in comments,
   like the rest of the code.

---

## Part 6 — Risks, and what this plan deliberately does not do

- **A forgotten invalidation is now a visible stale number.** Mitigations: one
  `afterWrite` helper, the table in §2.3, `MONEY` as the default for anything
  money-shaped, and D2's 30–60 s background revalidate as the safety net.
- **Two browser tabs** (desktop) have separate caches; a write in one leaves the
  other stale until its next visibility-change revalidate. Acceptable — the app
  is a phone PWA first, and one uvicorn worker already assumes one live session.
- **Memory.** Bounded by `gcTime` (unmounted data is collected after 5 minutes)
  and cleared on lock. A month of calendar pages is a few hundred KB of JSON at
  most.
- **The dependency.** +11.96 KB gz in the committed `dist/` bundle (measured
  2026-09-20), and its defaults must stay aligned with `lib/api.ts` — §2.1 and
  invariant 3 exist so a future upgrade that changes a default is caught rather
  than absorbed.
- **Not doing:** offline reads (SEC-29 forbids the storage that would need),
  optimistic UI beyond the pending-row insert that already exists, background
  polling, or a service-worker data cache.
