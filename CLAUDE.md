# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal budget / spending tracker (FastAPI + React 19 PWA) that stores its
data in a **shared company SQL Server** (`P8_NOAH_AI`, schema `ZBDGT`). Because
the database is not trusted, **every financial field is encrypted in-process
with AES-256-GCM before it is written**. That single constraint drives nearly
every design decision in the repo — read `misc/ARCHITECTURE.md` §5 before
touching anything under `app/core/crypto/` or `app/db/repositories/`.

Deployed under IIS at `/ZBDGT` on the same host as a sibling app (QUOT), whose
conventions this project deliberately mirrors.

## Reference docs (already written, keep them in sync)

| File | What it holds |
|---|---|
| `misc/ARCHITECTURE_OVERVIEW.md` | The visual tour — mermaid diagrams of every flow. Start here. |
| `misc/ARCHITECTURE.md` | The same system in full detail, numbered §1–§14. Code comments cite these section numbers. |
| `misc/FEATURES.md` | Feature-by-feature scope with IDs (`TXN-01`, `BUD-06`, `SEC-14`…) referenced throughout the code. |
| `misc/phases.md` | Build order, phase by phase, and what is actually done. |
| `misc/ROADMAP.md` | Everything not built yet — deferred rows plus new ideas, with reserved IDs, as Phases 11–15. Tick it when one ships. |
| `misc/how-to-run.txt` | Setup, recovery, and backup runbook. |
| `misc/DEPLOY.md` | Deploying to IIS: the release zip, first deploy, every update, rollback, troubleshooting. |
| `misc/ARCHITECTURE_REVIEW.html` | The 2026-10-12 architecture review: six deepening candidates, before/after, and what was built. |

## Commands

```bash
# Backend (venv at .venv, Python 3.11)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
#   App    http://localhost:8000/ZBDGT
#   Health http://localhost:8000/ZBDGT/api/v1/health
#   Docs   http://localhost:8000/ZBDGT/api/v1/docs   (only when DEBUG=True)

# Tests
pytest                                  # all, ~30 s
pytest -m "not slow"                    # quick pass (what .vscode/settings.json uses)
pytest tests/test_crypto.py -v          # never skip these
pytest tests/test_repository.py::test_name -v   # single test
pytest tests/test_crypto_performance.py -s      # prints the benchmark number

# Tests marked `db` reach the real SQL Server and are skipped unless asked:
ZBDGT_DB_TESTS=1 pytest tests/test_db_mssql.py -s      # bash
$env:ZBDGT_DB_TESTS=1; pytest tests/test_db_mssql.py   # powershell

ruff check app tests                    # lint (no config file; defaults)

# Migrations — alembic.ini has NO sqlalchemy.url on purpose; alembic/env.py
# builds the connection from .env through the app's own engine factory.
alembic upgrade head
alembic revision --autogenerate -m "message"

# Frontend (Node local only — the server has no Node, ever)
cd frontend
npm run dev        # http://localhost:5173/ZBDGT/ — proxies /ZBDGT/api to :8000
npm run build      # tsc --noEmit, then Vite -> ../app/web/static/dist/
npm run typecheck
npm test           # vitest, src/tests/ — the caching layer only, no DOM
npm run test:watch
```

Scripts that exist today (many more are referenced in `misc/how-to-run.txt` but
belong to later phases): `bootstrap_user.py` (create the first account from the
CLI), `decrypt_query.py` (read your own rows; needs the master key),
`benchmark_fetch.py` (read-only cold-load timing — the number that decides
ARCHITECTURE §5.7), `generate_keys.py [--fill]`, `generate_int_tables.py`,
`seed_categories.py --user-id N [--dry-run]` (the default category set, CAT-07),
`backup.py` / `restore.py` / `verify_backup.py` (Phase 8a),
`rotate_keys.py --status | --new-key | --rewrap [--dry-run]` (master-key
rotation; runbook in `misc/how-to-run.txt`), `verify_integrity.py [--user-id N]
[--json]` (read-only drift check) and `env_fingerprint.py [FILE] [--compare OTHER]`
(SEC-31, reads files only).

Develop against `:5173` (hot reload) with uvicorn running alongside it on
`:8000`, or every API call fails.

## Non-negotiable invariants

These are enforced by code and tests. Breaking one is a data-loss bug, not a
style issue.

1. **Encryption happens in exactly one layer.** `app/db/repositories/` is the
   only place `encrypt`/`decrypt` is called. Services receive and return fully
   decrypted plaintext objects and hold a `UserCipher`, never a key. Endpoints
   do HTTP only. Never encrypt in a service or an endpoint.
2. **The two-step insert.** A row's `id` is part of its AAD, so it must exist
   before the payload can be sealed: `INSERT` a `PLACEHOLDER` payload → flush
   for the identity id → seal → `UPDATE`, all in one transaction. This lives
   once, in `EncryptedRepository.create()` — do not reimplement it per table.
3. **AAD format is `ZBDGT.{table}:{row_id}:{user_id}:v{key_version}`**, where
   `ZBDGT` is a hardcoded constant, *not* `settings.DB_SCHEMA` (restore into
   the scratch schema depends on this). Changing the format makes every stored
   row undecryptable.
4. **No nonce parameter, anywhere.** `envelope.encrypt()` always draws 12 fresh
   OS bytes. Do not add a way for a caller to supply one.
5. **Money is `Decimal`, never `float`.** `user_cipher.dumps_payload()` walks
   every payload and raises on a float before sealing.
6. **User scoping is structural.** `UserCipher` knows its `user_id`; no
   repository method takes a user id, so no call can pass the wrong one.
7. **One uvicorn worker.** Session keys and the decrypted working set live in
   process memory. A second worker would serve stale data and see unlocked
   users as locked. `web.config` enforces this.
8. **A missing, short or malformed master key aborts startup** at import of
   `app/core/config.py`. Never add a fallback that lets it boot and write
   plaintext.
9. **`app/web/static/dist/` is committed on purpose** and `.gitattributes`
   marks it `-text`. Rebuild and commit it whenever frontend source changes;
   the server has no npm. Deploys are COPIED, not pulled (there is no git
   remote): `scripts/make_release.py` zips the last commit, and `misc/DEPLOY.md`
   says which server folders to replace and which (`.env`, `uploads/`,
   `backups/`, `logs/`) never to touch.
10. **Nothing from the API is persisted in browser storage** (localStorage,
    IndexedDB, Cache API) — the browser origin is shared with other company
    apps (SEC-29). The ONE exception, the user's decision on 2026-09-16: the
    `zbdgt_theme` cookie holds the word light or dark so a lock screen opened
    after the app was closed keeps the chosen theme (UX-05). It is written by
    `pwa.applyTheme`, cleared on sign-out, and the shell echoes only those two
    words into `<html>`. Do not grow it into a second preference - the colour
    palette (2026-09-18) is deliberately NOT in it, so sign-in and a reopened
    lock screen show the classic palette.

## Architecture

### Request path

IIS (`httpPlatformHandler`) → uvicorn (1 worker) → FastAPI. Middleware,
outermost first: CORS (dev only) → SecurityHeaders → RateLimit → Logging →
Auth. Starlette makes the *last* added middleware the outermost, so
`app/main.py` adds them in reverse of that order.

Three route families: `/ZBDGT/api/v1/*` (JSON), `/ZBDGT/static/*` (the bundle),
and a catch-all SPA fallback that renders the Jinja shell so a refresh on any
client-side route works. The shell reads `dist/.vite/manifest.json` at request
time (re-read on mtime change) to inject the hashed bundle filenames, so a
fresh `npm run build` is picked up without restarting uvicorn.

### Auth: attach vs. enforce

`AuthMiddleware` **never blocks** — it attaches identity and lets everything
through, so a failed request is still audited. Enforcement lives in
`app/core/deps.py`, at two levels:

- `get_session_context` — signed in (valid access cookie, active user, live
  token family). Being *locked* is fine here.
- `get_unlocked_context` — the above **plus** the DEK is in the session
  keyring; yields a `UserCipher`. Every endpoint touching financial data
  depends on this one.

An empty keyring means **locked, never an error** (SEC-27): IIS idle-stops the
process after 20 minutes while cookies stay valid, and the PIN brings the key
back. Auto-lock is enforced server-side in `SessionKeyring`, not just by a
browser timer.

### Data model: two table shapes

- **Shape A — operational, readable, indexed:** `users`, `refresh_tokens`,
  `login_attempts`, `audit_log`, `assistant_usage` (the AI companion's daily
  counts - never content, 2026-09-30).
- **Shape B — encrypted (`EncryptedRowMixin`):** the other twelve tables
  (`assistant_threads`, the AI companion's kept conversations, since 2026-10-01). Only
  `id`, `user_id`, `key_version`, `is_deleted` and the row timestamps are
  plaintext; everything else is one `VARBINARY(MAX)` JSON blob. The only index
  a Shape B table can usefully have is `(user_id, is_deleted)`.

Consequences worth internalising: SQL cannot filter, sum or join on anything
inside a payload, so **all arithmetic happens in Python over a warm in-memory
cache loaded once at login**. References inside payloads (`category_id`,
`account_id`, `splits[]`) are real relationships with **no foreign key
possible** — the service layer owns that integrity, and
`scripts/verify_integrity.py` (`integrity_service.py`) checks for drift.

`row_created` is the insert timestamp, not the transaction date; `txn_date`
lives inside the ciphertext.

### Key hierarchy

```
BUDGET_MASTER_KEY (.env)  ──HKDF──▶ wrapping key ──▶ users.dek_wrapped
                                                        │
                                              per-user DEK (32 bytes)
                                                        │
                                        every Shape B row this user owns
```

**One way in.** There is no recovery phrase (removed 2026-09-14, migration
`20260914_0002`): a lost `.env` is restored from the server owner's offline
copy (`misc/how-to-run.txt`), and losing `.env` and every copy is permanent for
every account. Key version 0 stays reserved — old backups carry recovery wraps
under it — and config enforces 1–255 for master keys. There is **no admin key**
— nobody, the admin included, can decrypt another user's rows in the app.

**Two version numbers, never interchangeable.** The version of the *wrap* is
the `key_ver` byte of `users.dek_wrapped` (`wrapped_key_version()`); master-key
rotation and the sign-in re-wrap move it. `users.key_version` is the version
`profile_enc` was sealed under — part of its AAD — and only DEK rotation (which
re-seals the profile) may change it. Overwriting it on a re-wrap makes the
profile undecryptable; `tests/test_key_rotation.py` guards this.

`email_bidx = HMAC-SHA256(pepper, normalise(email))` is the single
deterministic value in the schema, and exists only so login can find a row
before any key is unwrapped. Email normalisation is frozen forever once the
first account exists.

## Conventions

- **Errors** are RFC 7807 `application/problem+json` carrying a stable `code`;
  the frontend branches on those codes. `DecryptionError` never returns a
  `detail` — that would be a tampering oracle; the row id goes to the log and
  the client gets a correlation id. Unhandled exception text is never sent to
  the client, DEBUG or not.
- **Logging** installs a redaction filter before any handler exists
  (`app/core/logging_config.py`). It strips money, base64/hex key material,
  and named secrets from messages, args and tracebacks.
  It over-redacts on purpose. Log counts and durations as plain integers
  (`elapsed_ms=412`) — those pass through.
- **Secrets are `SecretStr`**, and a config validation failure never echoes the
  value it rejected.
- **`EncryptedPayload`** (a `TypeDecorator`) refuses to write anything that is
  not a sealed envelope, so assigning a dict or JSON bytes to a payload column
  raises at flush rather than landing as plaintext.
- **Session cookies must be prefixed `zbdgt_`** and scoped to `/ZBDGT`
  (SEC-28) — the browser origin is shared with QUOT.
- The frontend routes all calls through one fetch wrapper (`frontend/src/lib/api.ts`):
  cookie credentials, an `X-Requested-With` CSRF guard, one shared silent
  refresh on `401`, and `SESSION_LOCKED` / `SESSION_REVOKED` dispatched as
  window events the shell listens for.
- **Screens read the query cache, not their own fetch.** `@tanstack/react-query`
  (added 2026-09-20) holds every answer a screen draws from; the keys and stale
  times are in `frontend/src/lib/queryKeys.ts` and nothing keys a query any
  other way. Its defaults are overridden on purpose in `lib/queryClient.ts` -
  `retry: false`, because `api.ts` owns the one silent refresh and the
  SESSION_LOCKED event. **Never add a persister plugin** (`persistQueryClient`
  and friends write the cache to localStorage or IndexedDB, which invariant 10
  forbids), and `queryClient.clear()` stays in the App.tsx lock effect beside
  `resetLedger()`. Code outside a render uses `ensure*` in `lib/prefetch.ts`.
  The ledger's rows, the account trails and the budget status stay hand-rolled
  in their stores - they page by cursor, carry the pending row and merge a
  write's `Outcome` - but they skip a fetch that is still fresh and share one
  in-flight request, the same as a query. `npm test` (vitest, `src/tests/`)
  covers the parts that fail SILENTLY - a guard that skips a fetch it should
  have made shows a wrong figure, not an error - and `writePaths.test.ts` reads
  the source to fail any new write that does not announce itself.
- **A component never invalidates by hand.** After a successful write it calls
  `afterWrite(...groups)` (`frontend/src/lib/invalidate.ts`, 2026-09-20) and
  names what the write touched - `afterWrite(...MONEY)` for anything that
  posted or moved money, `...EVERYTHING` for a restore or an import. That one
  function reloads `ledgerStore` and `budgetStore` and bumps the version every
  screen keys its effect on; bumping `version` at a call site, or calling
  `ledger.load()` there, is how eleven writes used to go missing from Home.
  The rest of the plan it belongs to is `misc/archive/UX_RESPONSIVENESS_PLAN.md`.
- `misc/ARCHITECTURE.md` section numbers and `misc/FEATURES.md` feature IDs are
  cited in code comments; keep new comments doing the same.

### Design skills

Design skills (`frontend-design`, `ui-ux-pro-max`, `ui-styling`, …) are
available and useful for *layout, hierarchy and interaction* decisions on new
screens. They are not permitted to change the foundations:

- **Never run `shadcn init` or add a UI dependency.** The primitives in
  `frontend/src/components/ui/` are hand-rolled on purpose; extend them or add
  a sibling. `recharts` is the only chart library.
- **Colours come from `theme.css` tokens only** — no hex literals, no `dark:`
  variants (light/dark and the four palettes are a variable swap), and
  `ok`/`warn`/`danger` mean money state and nothing else - the same in every
  palette. Accent used as TEXT is `text-accent-ink` (a pink or lime fill is
  not readable as letters); outlines are `stroke`, never `line`.
- **Type, spacing and radii come from `tailwind.config.js`** — use `text-body`,
  `p-tap`, `rounded-card`; don't introduce `text-[15px]` or another font. The
  two faces are the system sans and JetBrains Mono (self-hosted in
  `src/styles/fonts/`, used by `.num` and `.label`).
- **Mobile-first, 390px baseline.** Unprefixed utilities are the phone layout;
  `sm:`/`md:` only widen it inside `max-w-app`.
- Any visual change means `npm run build` and committing
  `app/web/static/dist/` (invariant 9).

The look is NEO-BRUTALIST (2026-09-18, samples in `sample_ui/Neo-Brutalism`):
every tile is an outline plus a hard offset shadow (`shadow-card`; `shadow-edge`
is the outline alone; `.press` is a control that sinks onto its shadow), 8px
corners (the radius scale is replaced, so `rounded-2xl` is 8px too), no
decoration. Four palettes - classic (default), candy, lime, mono - each light
and dark, chosen by `data-palette` (the `palette` preference, `pwa.applyPalette`)
and `data-theme`; `PalettePicker` previews a palette by putting the attribute
on a swatch. Category and account colours are bright fills that carry a BLACK
glyph (`GlyphTile`). The floating pill tab bar stays. Tabs are Home ·
Accounts · [+] · Calendar · More; Stats is reached through `CalendarSwitch`
and keeps its own `/stats` route. Every account is a small tile; a tile
opens `/accounts/:id` (`AccountDetail`) - the account's trail of money in and
out, read from `GET /transactions?account=` and signed per account by
`TransactionRow.moneyIn`. Account types are cash, debit, credit, savings,
investment, lent, borrowed and member (ACC-31/32); `subtype` (ACC-33) is a
label from the Add Account list (`ACCOUNT_KINDS` in `lib/accounts.ts`) and
must never drive a rule. The account-TYPE rules (`OWES`, `LOANS`,
`EARNS_INTEREST`, `GIVES_CASHBACK`, `CHECKABLE`, `COUNTS_IN_CASH_ON_HAND_DEFAULT`)
live once per side - `account_service` and the top of `lib/accounts.ts`, same
names - and `tests/test_account_kinds_parity.py` fails when they disagree;
never spell a type tuple out anywhere else. `isOwed()` is the frontend test for
"show this balance as owed", and what is owed is `AccountView.owed_with_plans`
(REC-14, every OWES account, never below its plans) - read it, never rebuild it
from the balance. A loan's transfer may come from
CASH THE USER DOES NOT TRACK (ACC-39, 2026-09-20): one `hidden` account,
get-or-created by `account_service.untracked_cash()` and by nothing else, kept
out of every list by `visible()` in `lib/accounts.ts` (filtered once, in
`useLookups` - `accountById` still holds it so a row can name it) and out of
cash on hand and net worth whatever its switches say. It is never a chip: on a
lent/borrowed transfer the side the page does not know starts BLANK instead of
guessing the last-used account, and BLANK MEANS THE WALLET - the draft carries
`UNTRACKED_ID` and `save()` resolves it. Only the side opposite a lent or
borrowed account may be left empty. `highlight` (yellow) marks where you are -
today, a chosen period - and never an amount, so it cannot read as `warn`.
Colours also live outside theme.css in three places: the theme-color metas
(both index.html files - the classic ground), the manifest in
`app/web/router.py`, and `scripts/generate_icons.py` (icons are committed
PNGs and keep the indigo brand colour, user 2026-09-18).

## Tests

`tests/conftest.py` sets throwaway keys into the environment **before anything
under `app/` is imported** (env beats `.env` in pydantic-settings), so tests
never use real keys. Repository tests run the production models against
in-memory SQLite with a schema attached under the same name (`ZBDGT`), which is
why `app/db/types.py` gives every column a SQLite variant. Without
`ZBDGT_DB_TESTS=1`, `DB_SERVER` points at an invalid host, so a test that
forgets the fixture fails instead of reaching the company server.

Markers: `db` (real SQL Server, skipped by default), `security` (crypto and
isolation — must never be skipped or xfailed), `slow`.

## Current state

Phases 1–5 are built: crypto core, database layer and
migration, frontend shell, the whole sign-in / lock flow
(2026-09-11); accounts, categories, transactions and budgets (2026-09-13);
card bills, statement check and balance adjustments (Phase 5b, 2026-09-14);
calendar, stats and tags (Phase 6); recurring, subscriptions, installments and
projection (Phase 7); backup, restore, CSV and receipts (Phase 8a); settings,
security, goals, admin and PWA (Phase 8b, all 2026-09-14) — 43 test files.
Mounted: `auth`, `health`, `settings`, `accounts`, `statements`, `categories`,
`tags`, `transactions`, `budgets`, `calendar`, `stats`, `recurring`,
`subscriptions`, `projection`, `attachments`, `backups`, `data`, `goals`,
`security`, `admin`, `assistant` (AI companion, `misc/AI`, A1-A6).

**The working set is live** (`app/core/crypto/working_set.py`). Every read of
transactions goes through `TransactionRepository.cached()`, and writes reach
it only after COMMIT — a rollback drops the user's entry instead. The session
keyring notifies it whenever a DEK is dropped (lock, logout, idle expiry,
sweep), so decrypted rows never outlive their key. Never mutate a cached
`Record.data`; build a new dict. Tests start from an empty working set via an
autouse fixture in `tests/conftest.py`.

**Budgets** (`app/services/budget_service/`): one budget row per user with a
dated amount history; the pure pieces — `allowance.py`, `carry_over.py`,
`alerts.py` — take plain inputs and are tested directly. Every endpoint that
returns budget figures takes the CLIENT's `today` as a query parameter.
Account alerts (card due/limit, `statement_differs`, `subscription_due`) come
from `alerts.account_alerts()` and need no budget: with no budget,
`GET /budgets/current` returns `{"status": null, "alerts": [...]}` from
`budget_service.standalone_alerts`.
`budget_service` imports `transaction_service`; the reverse import is lazy,
inside `transaction_service.outcome()`, to avoid a cycle — keep it that way.

**Cards and balances** (Phase 5b): a card's bill, its spending limit and the
statement check are all DERIVED in `account_service` from postings — only the
bank's typed totals (`statement_checks`) and the `spending_limit` are stored.
`Posting` carries the transaction `kind` and `statement_on`, because a limit
counts purchases, not payments. Two rules to keep:

- A balance adjustment (`type = adjustment`) is written ONLY by
  `account_service.update_account` after a `BALANCE_DIFFERS` answer, together
  with its `BALANCE_ADJUST` audit entry in the same commit. Never let
  `POST /transactions` create one, and never make one editable. It moves
  balances only: no budget, allowance, day total or card limit counts it. Stats
  DOES since 2026-09-18 (user): a loss is spending and a gain is income, as their
  own By Category row (`CategoryShare.unrecorded`). An investment's value is
  typed through the same question (ACC-12 changed the same day).
- Bills typed from a card's own app (ACC-35, payload `bills`/`bills_from`) are
  written ONLY by `account_service.set_bills`. With bills, a card adds
  `-due_now` to cash on hand (`AccountView.cash_amount`, which
  `cash_on_hand()` sums) instead of its balance; what is paid is derived FIFO
  from payments since the list was saved and never stored. Net worth
  (`net_worth()`, ACC-36) always uses full balances plus unbilled installments.
- `card_posted_on` moves a purchase between STATEMENTS only. The budget reads
  `txn_date` and nothing else. `statement_service` writes through
  `transaction_service`, and nothing imports it.

A typed bill list holds everything the card's app knew when it was saved, so
`set_bills` names what it COVERS: `bills_cover_transactions` (purchases on the
card dated on or after that day) and `bills_cover_rules` (every plan on it) -
references in backup_service like any other, left out of a merge key. Anything
else joins the bills: a one-off PURCHASE lands on the bill of the statement it
posts in (`card_posted_on` first), as `Bill.from_purchases` - and so does a
TRANSFER OUT of the card (money sent from it, 2026-10-01), which the bank
bills the same way and `_covered_rows` covers the same way; it uses up the
card's own spending limit too (`_is_purchase`) - and a plan created
later adds its payments as before. Lists saved on 2026-09-17 keep only
`bills_saved_at` (a creation-time comparison), older ones only `bills_from`.
Months ahead takes new purchases with the typed part - money already spent.
The bill editor starts from each bill's full `left`, so saving it unchanged
keeps every total.

Every bill carries its `lines` (typed / purchase / plan / inside_typed / payment),
built in the same pass that adds it up - never assemble them anywhere else.
`CreditView.not_on_bill` is what the card owes that no bill lists (shown, never
placed on a bill), and Months ahead takes each later bill ON ITS DUE DATE, with
`bills_held` saying what Home holds back at a month's end (2026-09-19).

A plan charge joins a card's bills by WHAT IT IS: an installment payment's date
is the day it is billed, so it lands on the first bill due on or after it; any
other recurring charge is a purchase and takes the statement cycle, due the
month after. That rule, and "due now = everything overdue + the next due date"
(cards and loans alike), live ONLY in `app/core/utils/billing.py` (2026-10-12):
`account_service`, `projection_service` and `installment_conversion` all ask
it - never place a charge or sum what is due anywhere else.

`account_service.list_accounts` / `get_account` / `statement` / `update_account`
read every posting themselves; pass `postings=` only to replace them (a test,
or `()` for types and switches only).

A plan can be PAID on the plan (REC-32, `recurring_service.pay_plan`): a
transfer into the plan's account carrying the plan's id and NO `recurring_on`.
What is due is covered first; an extra part answers 409 PREPAYMENT_CHOICE
until the user picks `lower` or `shorten`, is charged at once, and is stored in
`prepayments`. Extra payments are applied inside `installment_plan()`, which
`occurrences()` reads - never adjust a plan's amounts anywhere else.
`InstallmentStatus.paid`/`remaining` are CHARGES; `money_paid`/`left_to_pay`
are MONEY - do not mix them up. On a BORROWED account, money paid in WITHOUT a
plan's id (its monthly payment rule, a transfer from the add sheet) pays its
plans too, oldest scheduled payment first across every plan on it, closed ones
included (`recurring_service._loan_payments`, 2026-09-30); only what is left
after every plan is the loan's own. Never on any other account type. `update_rule` pulls `posted_through` back when
a start moves earlier. A repeating charge's next occurrence can be paid early
(REC-33, `pay_now`): it posts with that occurrence's `recurring_on`, which is
what stops the catch-up charging it again - never post it without one.

A purchase can BECOME an installment plan (REC-34, `installment_conversion`,
2026-09-18) on a card or a loan: from the add sheet or an expense already
recorded. The purchase is hidden (soft-deleted; `converted_to` on it,
`from_transaction` on the rule) - never counted beside its payments - and
`revert` removes the plan and its posted charges and `undelete`s it. A split
purchase keeps its proportions (`category_shares`, applied in
`recurring_service._price_splits`); a bill list that covered the purchase
covers the plan (`Charge.origin`). All of it is references in backup_service.

A LOAN BILLS LIKE A CARD (ACC-40, 2026-09-21): `recurring_service.plans_owed`
walks the rules ONCE and returns both what is still to bill (REC-14) and the
schedule money has not covered; the second becomes `AccountView.dues` on a
borrowed account, whose `due_now` (overdue + the next one, ACC-35's rule)
replaces the balance in `cash_amount`. Net worth, `balance` and what it says
you owe still count the plan in full. `projection_service` emits those dues as
bills and drops the plan's charges on that account, so the money leaves once.

An installment is OWED in full from the day it is taken (REC-14):
`AccountView.plans_unbilled` holds the unbilled remainder on every account
type, and `CreditView.owed_with_plans = owed + unpaid_installments` is what a
card's page and tile show. `balance`, `owed` and cash on hand deliberately do
NOT include it - the reminder, the statement check and ACC-17 each read the
figure they mean. Net worth does, on any account. A plan is listed on the
account it runs on (`AccountPlans`), not only on the Recurring screen.

A savings goal SETS MONEY ASIDE inside its account (GOA-08, 2026-09-16):
`goal_service.add_money` / `use_money` append dated entries to the goal's own
payload and write NO transaction, so the balance never moves. `AccountView.set_aside`
and `available` come from `goal_service.set_aside_by_account` (a lazy import in
account_service, which goal_service imports), and `cash_amount` - so cash on
hand and Months ahead - counts what is available. Net worth still counts the
full balance. Several goals may share an account.

A goal has a KIND (Phase 13, 2026-09-28): saving, sinking or emergency, and at
most one emergency fund. A sinking fund following a yearly bill (`rule_id`, in
references.py) takes its target and date from `recurring_service.occurrences()`
- never its own date logic. The emergency advisor's rules are pure, in
`app/core/utils/emergency.py`; `safety_service` feeds them and is imported only
by its endpoint. "Essential" is `category_service.essential_ids()` - the
category's switch, else its name, else its parent - and nothing else decides
it. The payday prompt (GOA-12) SUGGESTS: `goal_service.set_aside_payday` adds
to the goals and marks the income `set_aside_prompted` in one commit, and only
`transaction_service.mark_set_aside_prompted` writes that marker.

An INVESTMENT account's balance (ACC-08/12) is the value last typed plus every
posting dated AFTER that valuation - money moved in or out is not market
movement, and a transfer into a fund must move it. Postings before the
valuation's day are already inside the typed figure, so a new value resets the
base; on the day itself `Valuation.covers` orders them by when each was
entered (`at` on the value, `row_created` on the posting - fixed 2026-09-19). `AccountView.current_value` stays the typed figure; only `balance` adds
the contributions.

**Interest and cashback** (2026-09-16, ARCHITECTURE §4.6/§4.7):

- Daily savings interest (ACC-37) is credited by `interest_service.accrue()`,
  a CATCH-UP like the recurring engine - `POST /accounts/interest/accrue` is
  called on every open beside `expandRecurring`. An entry dated d pays for the
  CLOSING balance of d - 1, so today's is posted on the first open of the day,
  as the bank credits it in the early morning (the first one the day after
  interest starts). It credits the NET of withholding tax, compounds, and
  carries sub-centavo interest in `carry` until it reaches ₱0.01. Postings and
  each account's `credited_through` marker move in ONE commit, and every entry
  carries `interest_on`, so a second run posts nothing and a deleted entry is
  never written back. The arithmetic is pure, in `app/core/utils/interest.py`,
  and `projection_service` uses the SAME helper - never its own formula.
- Cashback (TXN-22) is a linked pair, not a discount: the purchase keeps its
  full amount (spending stays gross) and the money back is an income row joined
  by `cashback_id` / `cashback_of`. Only `transaction_service` writes it, and
  both rows move, change and go together. An account's usual rate (ACC-38) is a
  suggestion for the sheet and is never applied to anything by itself.
- **A rate is not money.** `money.ts` and `money.py` quantise to two places and
  REFUSE more; rates carry four ("3.2500"). Use `toRateString` to send one,
  `percentOf` to apply one, and the interest helper on the server - never
  `toDecimalString`, `formatPHP` or `splitDecimal` on a rate.

Tapping a transaction opens `TransactionPreview` (TXN-23, `uiStore.preview`),
read-only, and its Edit button opens `TransactionSheet` - the account page, Home
and the calendar day list all do this, and the Ledger keeps swipe-to-edit. Only
the preview and the sheet ever open an entry; a pending row opens neither.

**Calendar, stats and tags** (Phase 6): `stats_service.overview` and
`calendar_service.month` read `transaction_service.views()` - both legs of
every transfer. The calendar counts ONLY expense and income splits; Stats also
counts balance adjustments (an unrecorded loss as spending, a gain as income,
each its own By Category row) and still reports their totals on their own. One `GET /stats/overview` serves the whole Stats
tab. Charts take colours from `hooks/useThemeColours.ts` (recharts needs SVG
attributes, not classes); a category's own stored colour is the slice colour.
Tag ids live in `tag_ids` inside the payload: `transaction_service._tags`
checks them on write (omitted = keep), and `tag_service.delete_tag` strips the
id from every transaction in the same commit.

**The recurring engine** (Phase 7): `recurring_service` is the ONLY code that
turns a schedule into transactions - through `transaction_service.post_recurring`,
which never commits. `occurrences()` is pure and shared by expansion (≤ today)
and `projection_service` (> today); never give projection its own date logic.
Installment remainders, payments made and payoff dates are derived from rows
carrying `recurring_id`, never stored; an installment's total is the sum of
its schedule, which carries later interest changes (`interest_changes`,
REC-29). When a statement confirms or changes a plan's interest, the posted
payments are corrected through `transaction_service.reprice_recurring` - the
only code that edits a posted payment's amount, and it never commits. Import direction: `recurring_service`
imports `transaction_service`; `account_service` and `budget_service` reach it
(and `subscription_service`) only through lazy imports inside functions;
`statement_service` and `projection_service` are imported by nothing.

**Backup** (Phase 8a, `app/services/backup_service/`): writing a `.budgetbak`
reads ciphertext as stored and needs no key; restoring opens rows with the
backup's key and re-seals them through EncryptedRepository under the target
account's. `references.py` is the ONLY list of references inside payloads -
any new table or reference field must be added there (a test checks ORDER
covers every encrypted table). The master key may open only the signed-in
account's own backup; anything else goes through `scripts/restore.py`. EncryptedRepository marks
`session.info[CHANGED_USERS]` on every write, and the scheduler's after-commit
hook turns that into a debounced backup - disabled when ENVIRONMENT=test.
`budget_app_import_service` (DAT-21) imports the Budget phone app's .xlsx
through the same `import_entries` path as the CSV import; it never writes a
balance adjustment - today's balances are typed and land in the opening
balance - and `budget_app_backup/` holds real finances, so it stays gitignored.
Receipts are files at `uploads/<user_id>/<id>.enc`, sealed by
AttachmentRepository under AAD table `attachment_files`. A transfer's two legs
share ONE receipt (`attachment_service._legs`, 2026-09-30) and an edit keeps it;
the preview (TXN-23) attaches one without opening Edit. Uploads are raw
request bodies (no multipart dependency); never put a secret or filename in a
URL - IIS logs query strings.

**Security & PWA** (Phase 8b): password change, DEK rotation (SEC-23) and
account deletion (SEC-21) live in `auth_service/security_service.py`; every one
re-prompts for the password via `confirm_password`, and rotation ends other
sessions and replaces server-side backups. `rotation_repository.py` is where
rows are re-sealed or purged - keep it the only place. There is no recovery
phrase. A forgotten password is reset by an emailed link (SEC-30,
`auth_service/password_reset_service.py` + `email_service.py`): the token rides
in the URL fragment so IIS never logs it, only its SHA-256 is stored, and the
link's origin is `APP_PUBLIC_URL` - never the request's Host header. Nothing
from a budget ever goes into an email, and `email_service` never sends under
ENVIRONMENT=test (messages land in `OUTBOX`). `app/web/static/sw.js` must never cache `/api/`; the
worker is served at `/ZBDGT/sw.js` with its own CSP. Preferences are loaded
into `preferencesStore` after unlock and dropped on lock (theme, week start,
auto-lock); they are never persisted in the browser.

**Phase 11** (2026-09-28, misc/ROADMAP.md) - rules worth keeping:

- **Recently deleted (TXN-25)** lists only rows carrying `deleted_at`, and
  ONLY `transaction_service.delete_transaction` writes it. Every other soft
  delete - an installment conversion (REC-34), a revert's charges, a credit an
  edit took away - is NOT something the user deleted; never stamp one.
  `restore_transaction` brings back the group (`_restore_group`) and refuses
  through `_restore_problem`; a new kind of link between rows must join both.
- **Merchants (TXN-24)** are read from the working set
  (`transaction_service.merchants`); the add sheet only pre-selects a category
  when none is chosen yet.
- **The suggested budget (BUD-17)** reads, never writes: the rules are pure in
  `budget_service/suggest.py`, saving is the ordinary create/update. The
  reminder's dismissal lives in the budget payload
  (`suggestion_dismissed_for`), never in the browser; `status()` computes the
  suggestion only inside `reminder_window`.
- **Cancelling a subscription (SUB-07)** is recurring_service's write
  (`cancel_subscription` / `resume_subscription` / `set_cancel_by`);
  subscription_service only reads. `update_rule` keeps a cancelled one ended.
- **Cash on hand over time (STA-10)** is plain balances of the accounts counted
  TODAY (`account_service.balance_on` / `cash_history`) - never try to rebuild
  bills, dues or set-aside money for a past day.

**Phase 12** (2026-09-28) - rules worth keeping:

- **The calendar's scheduled days (CAL-07)** come from the Months ahead
  projection on the client (`keys.projection(12)`), never a date rule of their
  own; `calendar_service` must not import `projection_service`. Money "going
  out" is an item's `effect`, as Months ahead counts it.
- **A what-if (REC-27)** is `recurring_service.trial` - checked like a new
  rule, expanded through `occurrences()`, rule id `TRIAL_RULE_ID` (-1) - fed to
  `projection_service.project(trial=...)`. It writes nothing; saving is the
  ordinary createRule.
- **The payoff planner (REC-35)** is pure in `app/core/utils/payoff.py` and read
  by `payoff_service`, which nothing but its endpoint imports. `debt_rate` (a
  card's or loan's rate, typed per month or per year) is read ONLY by it - an
  estimate; nothing is ever charged from it. It is a RATE: four places, never
  the money helpers. `/projection/payoff` and `/projection/what-if` are POSTs
  that write nothing (writePaths.test.ts exempts screens/Payoff.tsx for that).

**Phase 14** (2026-09-28) - rules worth keeping:

- **A bank check (ACC-41)** stores only the bank's figure (`balance_checks`);
  the difference is derived on every read (`_balance_check_view`, over
  `balance_on`). Answering it goes through a forgotten transaction or ACC-28's
  own `update_account` question - never a writer of its own.
- **The monthly review (STA-12)** is `stats_service.review`, derived and never
  stored; its Home offer's "Not now" is the `review_dismissed_for` preference.
  No past net worth - typed card bills carry no date.
- **Sessions (SEC-32)** are named to the client by a handle, never the family
  id (it IS the session id); ending one goes through `session_service`, so the
  keyring entry goes with it. `device_label` is a coarse label - never store
  the raw User-Agent, and never a raw IP.
- **A passkey (SEC-12) is the PIN's equal**: `passkey_service.verify` only
  decides, and `auth_service.unlock_with_passkey` unlocks through the same
  `_reunlock`. Never let it derive, wrap or unwrap a key, never let it sign
  in, and keep the challenge single-use. It is hand-rolled on `cryptography`
  on purpose (user, 2026-09-28) - do not swap in a WebAuthn package without
  asking. `users.passkeys` holds PUBLIC keys only.

**The AI companion** (`misc/AI`, A1-A6 2026-09-30 to 10-01) - rules worth keeping:

- **watsonx through the company IAM service**, the way STWRD does it:
  `app/ai/` is STWRD's loader, client and service, copied. The API key lives
  only in process memory. `AI_ENABLED=False` loads and calls nothing, and
  tests never import the SDK (they use a fake model).
- **The model never computes a figure.** A skill
  (`assistant_service/skills/`) calls the service behind a screen and hands
  over finished, formatted facts. `verifier.check` throws away any reply with
  a number that is not in the facts or the question, and the skill's
  template answers instead. A new skill must report the figure its screen
  shows; `test_ai_assistant.py` holds each one to its endpoint. A skill is
  declared ONCE, in `router.SKILL_TABLE` (its ROUTE-prompt line, or None for
  rules-only), and answered in `skills.handlers()`; `test_ai_plumbing.py`
  holds the two together.
- **It never writes financial data.** No `/assistant` route changes it. The
  writes are the `assistant_usage` count (Shape A, counts only) and, for a
  user who chose to keep conversations, their `assistant_threads` row.
- **Question and reply text is never logged** - counts, skill and `elapsed_ms` only.
- **Opt-in** is the server-side `assistant` preference, audited as
  `ASSISTANT_ENABLED` / `ASSISTANT_DISABLED`. Conversations live in
  `assistant_service/memory.py` and `assistantStore`, and both drop on lock.
- **"Can I afford it?" (A3) is decided by rules**, pure in
  `app/core/utils/affordability.py`; the model explains the verdict and may
  not change it. The cash line is Months ahead's own (`skills/afford.timeline`),
  and only the part of a price the budget does not cover is taken off it -
  Months ahead already counts the rest of the period's budget as spent. A
  price comes ONLY from the question's words (`router.find_amount`), never
  from the model.
- **The reply checks** (`verifier.check`): every figure is in the facts; the
  reply does not contradict a verdict; no advice ("you should", an
  instruction); no talk of "the facts"; no month the facts do not name. Any
  failure shows the template.
- **An Explain link names a place, never a figure (A4).** `/ask` takes
  `context` (`screen`, `alert`, `account_id`); `turn.context_intent` checks it
  against its two tables and the user's own visible accounts, and the server
  reads the object itself. `ExplainLink` and `AskTile` draw nothing until the
  user has opted in (`useAssistantOn`).
- **A draft is a button, not a write (A4).** "I spent 250 on lunch" and "help
  me save 50,000 by December" return an action with a `payload`; the client
  opens the ORDINARY sheet pre-filled (`AddPreset`, `GoalSheet preset`, Months
  ahead's what-if) and the user saves. Their fields come from the question's
  words only, no model is called, and the model can never route to `draft`,
  `draft_goal` or `find`. `find` sends the one merchant or bill asked about -
  never a note.
- **A question may wait for a place; a read never waits for the model (A5).**
  `/ask` is a plain `def`, so the model wait sits in a pool thread. The guard
  refuses a user's own second question at once and lets anyone else's wait
  `AI_QUEUE_WAIT_SECONDS` for one of `AI_MAX_CONCURRENT_CALLS` places. The
  Admin line (`GET /assistant/usage`) is counts per day with every account
  summed, and calls nothing. `scripts/ai_load.py` is the load test.
- **Kept conversations are the user's choice and off by default (A6).**
  `assistant_history_days` is 0 (memory only, gone on lock), 30, 90 or 365.
  `assistant_service/history.py` is the only writer of `assistant_threads`;
  it hard-deletes (a deleted conversation must be gone, not hidden) on
  request, on expiry, and when keeping or the assistant is turned off. A saved
  reply keeps no draft button - their ids would not survive a restore, and
  `references.py` lists none for this table.
- **A conversation, not separate questions (2026-10-01).** `router.small_talk`
  answers hello / thanks / ok as skill `chat` with no model call;
  `router.follow_up` continues the previous turn's intent (`Turn.intent`,
  memory only) for "and...", "what about...", "what if...", "why?", replacing
  only the slots the new message names. Never carry from `NOT_CARRIED`
  (drafts, how-to, off-topic, chat).
- `scripts/ai_eval.py` is the gate: the golden questions against the real
  model on in-memory data, with affordability verdicts worked out by hand
  (`AFFORD_WORKING`). Read its replies, not just its percentages - every
  wrong answer so far had true numbers in it.

**Phase 15** (2026-09-28): only UX-14 was chosen. Vibration goes through
`buzz()` in `lib/haptics.ts` and nothing else calls `navigator.vibrate`; it
reads the server-side `haptics` preference, never browser storage.

There is no "copy last period's budget" action,
because allocations persist across periods - confirmed by the user on
2026-09-14, along with every other proposed default in FEATURES.md §13 and
§20-22, plus two changes: refunds after a statement closes reduce what is left
to pay, and each card has its own posting delay.

Phase 9 (hardening, master-key rotation, deploy) is next — everything from there on is a plan,
not an observation, so check `misc/phases.md` before assuming a service,
endpoint or script exists.
