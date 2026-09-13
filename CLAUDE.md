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
| `misc/how-to-run.txt` | Setup, recovery, deploy, and backup runbook. |

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
```

Scripts that exist today (many more are referenced in `misc/how-to-run.txt` but
belong to later phases): `bootstrap_user.py` (create the first account from the
CLI), `decrypt_query.py` (read your own rows; needs the master key),
`benchmark_fetch.py` (read-only cold-load timing — the number that decides
ARCHITECTURE §5.7), `generate_keys.py [--fill]`, `generate_int_tables.py`,
`seed_categories.py --user-id N [--dry-run]` (the default category set, CAT-07).

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
   the server only ever does `git pull` + restart.
10. **Nothing from the API is persisted in browser storage** (localStorage,
    IndexedDB, Cache API) — the browser origin is shared with other company
    apps (SEC-29).

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
  `login_attempts`, `audit_log`.
- **Shape B — encrypted (`EncryptedRowMixin`):** the other eleven tables. Only
  `id`, `user_id`, `key_version`, `is_deleted` and the row timestamps are
  plaintext; everything else is one `VARBINARY(MAX)` JSON blob. The only index
  a Shape B table can usefully have is `(user_id, is_deleted)`.

Consequences worth internalising: SQL cannot filter, sum or join on anything
inside a payload, so **all arithmetic happens in Python over a warm in-memory
cache loaded once at login**. References inside payloads (`category_id`,
`account_id`, `splits[]`) are real relationships with **no foreign key
possible** — the service layer owns that integrity (a planned
`scripts/verify_integrity.py` is to check for drift in Phase 9).

`row_created` is the insert timestamp, not the transaction date; `txn_date`
lives inside the ciphertext.

### Key hierarchy

```
BUDGET_MASTER_KEY (.env)  ──HKDF──▶ wrapping key ──▶ users.dek_wrapped
12-word BIP-39 phrase     ──────────────────────▶ users.dek_wrapped_recovery
                                                        │
                                              per-user DEK (32 bytes)
                                                        │
                                        every Shape B row this user owns
```

Two independent ways in; losing one is recoverable, losing both is permanent by
design. The recovery wrap uses `key_version = 0`, which a master key can never
be (config enforces 1–255). There is **no admin key** — nobody, the admin
included, can decrypt another user's rows.

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
  named secrets and any 12+ BIP-39-word run from messages, args and tracebacks.
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
  variants (light/dark is a variable swap), and `ok`/`warn`/`danger` mean money
  state and nothing else.
- **Type, spacing and radii come from `tailwind.config.js`** — use `text-body`,
  `p-tap`, `rounded-card`; don't introduce `text-[15px]` or a new font.
- **Mobile-first, 390px baseline.** Unprefixed utilities are the phone layout;
  `sm:`/`md:` only widen it inside `max-w-app`.
- Any visual change means `npm run build` and committing
  `app/web/static/dist/` (invariant 9).

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

Phases 1–4 are built: crypto core, recovery phrase, database layer and
migration, frontend shell, the whole sign-in / lock / recovery flow
(2026-09-11), accounts + categories and transactions (2026-09-13) —
340 passing tests across 26 files. Mounted: `auth`, `health`,
`settings`, `accounts`, `categories`, `transactions`.

**The working set is live** (`app/core/crypto/working_set.py`). Every read of
transactions goes through `TransactionRepository.cached()`, and writes reach
it only after COMMIT — a rollback drops the user's entry instead. The session
keyring notifies it whenever a DEK is dropped (lock, logout, idle expiry,
sweep), so decrypted rows never outlive their key. Never mutate a cached
`Record.data`; build a new dict. Tests start from an empty working set via an
autouse fixture in `tests/conftest.py`.

Two things Phase 4 left open on purpose: tags (TXN-10) are stored as an empty
`tag_ids` with no management, and the POST response carries account balances
and cash on hand but not yet the budget status (Phase 5).

Phase 5 (budgets and the daily allowance) is next — everything from there on
is a plan, not an observation, so check `misc/phases.md` before assuming a
service, endpoint or script exists.
