# BUDGET APP — System Architecture

> **Looking for the diagrams and the end-to-end flow?**
> [ARCHITECTURE_OVERVIEW.md](ARCHITECTURE_OVERVIEW.md) is the visual tour of this
> same system. **Looking for what to build, in order?** [phases.txt](phases.txt).
> **Looking for what it does, feature by feature?** [FEATURES.md](FEATURES.md) —
> and if you change a scope decision there, §14 of that file says what has to
> move in here.

**Personal Budget & Spending Tracker**
FastAPI · SQL Server (schema `ZBDGT`) · React 19 + Vite · AES-256-GCM at rest

This document is the map. Phase 1 (the crypto core, the database layer and the
frontend shell) was built on 2026-09-11, and the sections it touches describe
the code as it exists; everything later is still design. `misc/phases.txt` is
the build log and is where defects and debt get tracked.

---

## 1. What the system does

A personal budget tracker for a small number of independent users, modelled
feature-for-feature on
[Budget App — Spending Tracker](https://apps.apple.com/us/app/budget-app-spending-tracker/id1525179720)
for iOS. You set a budget for a period, log what you spend against categories,
and the app tells you the one number that actually changes behaviour: **how much
you can still spend today.**

Around that sit the supporting features: a spending calendar, per-category stats,
multiple accounts, recurring transactions, a subscription manager, and CSV
import/export.

Two things make this different from the App Store original, and both are
deliberate:

**It runs on a company database.** Storage is a SQL Server instance shared with
roughly ninety other applications, which means DBAs, backup operators and
anyone with a `db_datareader` grant can read every table on it. So *every field
of personal financial data is encrypted by the application before it is sent,
and decrypted only in this process*. The database stores ciphertext it cannot
interpret. Section 5 is the whole design and is the most important section here.

**It is a web app that has to feel like the iOS one.** Mobile-first React,
served as a static bundle by the same FastAPI process that serves the API.
Section 3 explains how React gets there without npm ever running on the server.

The path a peso takes through the system:

```
open app ──► PIN / login ──► DEK unwrapped into memory
                                    │
                                    ▼
                    working set decrypted and cached
                                    │
                                    ▼
   tap [+] ──► amount, category, account ──► encrypt ──► INSERT ciphertext
                                    │
                                    ▼
              cache updated in place, budget recomputed in Python
                                    │
                                    ▼
        home screen: remaining, daily allowance, progress ring
                                    │
                                    ▼
              calendar heatmap · category stats · CSV export
```

---

## 2. Runtime shape

One FastAPI process serves three things from the same codebase:

| Surface | Prefix | Returns | Lives in |
|---|---|---|---|
| **JSON API** | `/ZBDGT/api/v1` | Pydantic-validated JSON | `app/api/v1/` |
| **SPA shell** | `/ZBDGT` | One Jinja2 HTML file | `app/web/` |
| **Static bundle** | `/ZBDGT/static` | Built React JS/CSS, PWA assets | `app/web/static/` |

Unlike QUOT, there is no per-page server rendering. Jinja renders exactly one
template — `index.html`, the SPA shell — and everything after that is React
talking to `/api/v1`. Jinja earns its place by injecting the CSP nonce, the
hashed bundle filenames, and the PWA manifest link; that is all it does.

`/` redirects to `/ZBDGT`. The `BASE_URL` prefix exists for the same reason it
does in QUOT: the app is deployed as one IIS application among many on a shared
host, launched by httpPlatformHandler, with the path forwarded unchanged and no
rewrite rule.

**Startup** (`app/main.py` lifespan), in this order and for this reason:

1. Configure logging — with the redaction filter installed *first*, so nothing
   that follows can log a plaintext amount.
2. Load and validate the master key. **Refuse to start** if `BUDGET_MASTER_KEY`
   is missing, malformed, or not 32 bytes. A budget app that silently falls back
   to storing plaintext is worse than one that will not boot.
3. Verify the database connection and that schema `ZBDGT` exists.
4. Mount static files, the API router, and the SPA fallback route.

**Middleware**, outermost first:
`CORS → SecurityHeaders → RateLimit → Logging → Auth`.

`AuthMiddleware` attaches identity when a valid token is present and lets
everything through; enforcement lives in the `get_current_user` dependency. Same
split as QUOT, same reason — a failed login still gets audited with its IP.

---

## 3. Layers

```
app/
├── main.py                  FastAPI app, middleware stack, lifespan, health
│
├── api/v1/
│   ├── router.py            mounts every endpoint module
│   ├── endpoints/           HTTP concerns only — auth, validation, status
│   └── schemas/             Pydantic request/response contracts
│
├── web/
│   ├── router.py            SPA shell, manifest, service worker, fallback
│   ├── static/dist/         the committed React build output
│   └── templates/index.html the only server-rendered file
│
├── services/                ALL business logic
├── db/
│   ├── models/              SQLAlchemy ORM, schema ZBDGT
│   ├── repositories/        query construction, no business rules
│   └── session.py           session factory + session_scope()
│
└── core/
    ├── crypto/              ★ key management, cipher, blind index, cache
    ├── middleware/          cors, security headers, rate limit, logging, auth
    ├── config.py            settings, with hard fail on a bad master key
    └── deps.py              get_current_user, get_dek, get_working_set
```

The rule the code follows, inherited from QUOT: **endpoints do not touch the
database and repositories do not make decisions.** An endpoint validates and
delegates; a service decides; a repository queries.

This project adds one rule of its own, and it is absolute:

> **Nothing outside `app/core/crypto/` and `app/db/repositories/` ever sees a
> ciphertext, and nothing outside those two ever sees a raw key.**
>
> Repositories hand services fully decrypted domain objects and accept fully
> populated ones back. A service author should never have to remember to
> encrypt something — that is exactly the kind of thing people forget once, in
> one field, and never notice.

### The services

| Service | Responsibility |
|---|---|
| *(no service)* | Key handling lives in `app/core/crypto/`. Its façade is `UserCipher`: repositories are handed one, services pass it along, and neither ever holds a key |
| `auth_service/` | Login, JWT issue/refresh, lockout, PIN, password rules |
| `account_service` | Cash, debit, credit, savings, investment accounts; balances; credit statement cycles and available credit |
| `category_service` | Categories and sub-categories, icons, colours, ordering |
| `transaction_service` | Expense/income/transfer CRUD; the write path |
| `budget_service/` | Periods, per-category allocations, **daily allowance** |
| `recurring_service` | Rule expansion — daily/weekly/monthly/custom. The one engine behind standard rules, subscriptions and installments |
| `subscription_service` | Your recurring merchant charges (Netflix, gym). A **view over** `recurring_rules`, never a second expansion engine |
| `stats_service` | Every chart series; all aggregation, since SQL cannot |
| `calendar_service` | Day-by-day spending heatmap |
| `goal_service` | Savings goals and progress |
| `import_export_service` | CSV in and out, encrypted attachments |
| `audit_service` | Records who changed what, with encrypted detail |

---

## 4. Data model

Everything lives in the **`ZBDGT` schema** of the shared SQL Server database.
Fifteen tables, in two shapes.

### 4.1 The two table shapes

**Shape A — operational tables.** No personal financial data, so they hold
ordinary columns the database can index and query normally.

**Shape B — data tables.** Every one of them looks like this:

```sql
CREATE TABLE ZBDGT.transactions (
    id           BIGINT IDENTITY(1,1) PRIMARY KEY,   -- plaintext, surrogate
    user_id      INT           NOT NULL,             -- plaintext, the only filter
    key_version  TINYINT       NOT NULL,             -- which master key wrapped the DEK
    payload      VARBINARY(MAX) NOT NULL,            -- ENCRYPTED: everything else
    is_deleted   BIT           NOT NULL DEFAULT 0,   -- plaintext, soft delete
    row_created  DATETIME2     NOT NULL,             -- server clock, NOT the txn date
    row_updated  DATETIME2     NOT NULL,
    INDEX IX_transactions_user (user_id, is_deleted)
);
```

Note what is *not* there: no `amount`, no `txn_date`, no `category_id`, no
`merchant`. All of it is inside `payload`, which decrypts to:

```json
{
  "txn_date":    "2026-09-08",
  "type":        "expense",
  "amount":      "3500.00",
  "account_id":  3,
  "merchant":    "SM Supermarket",
  "notes":       "weekly run",
  "splits": [
    { "category_id": 11, "amount": "2800.00", "note": "groceries" },
    { "category_id": 19, "amount": "700.00",  "note": "household" }
  ],
  "tag_ids":     [2, 7],
  "recurring_id": null,
  "attachment_id": null
}
```

**Every transaction carries a `splits` array — including simple ones.** A single
-category purchase is a one-element split. The alternative (a `category_id`
field *or* a `splits` array) would mean every stats query, every budget
calculation and every category-delete check has two code paths, and one of them
would eventually be wrong. One shape, one path.

Two invariants the service enforces, because the database cannot:

- `amount` equals the sum of `splits[].amount`, **Decimal-exact**. A one-centavo
  drift here silently corrupts every report downstream.
- `splits` is never empty.

There is no `currency` field. The app is PHP-only by decision (FEATURES.md
ACC-11), so currency is a formatting constant, not data.

`row_created` is the server's insert timestamp, not the transaction date. That
distinction matters: `row_created` leaks only *when you used the app*, which is
unavoidable, while `txn_date` — which leaks your actual financial timeline —
stays inside the ciphertext.

### 4.2 The fifteen tables

| Shape | Table | Holds |
|---|---|---|
| A | `users` | `email_bidx`, `profile_enc` (email + display name, sealed under the user's own DEK), `password_hash`, `key_version`, `dek_wrapped`, **`dek_wrapped_recovery`**, `pin_hash`, lockout state |
| A | `refresh_tokens` | Hashed token, family id, parent id, expiry, revocation |
| A | `login_attempts` | `kind` (login / pin / recovery / register), `email_bidx`, success flag, keyed hash of the IP, timestamp |
| A | `audit_log` | user_id, action, entity, entity_id, encrypted detail blob |
| B | `accounts` | name, type, opening balance, colour, archived, `counts_in_cash_on_hand`, manual value (investment), statement/due day + credit limit (credit) |
| B | `categories` | name, parent_id, icon, colour, kind, sort order |
| B | `budgets` | period type, start day, amount, carry-over flag, active range |
| B | `budget_allocations` | budget_id, category_id, allocated amount |
| B | `transactions` | as above |
| B | `recurring_rules` | template transaction, frequency, interval, next run, end, `kind` (`standard` / `subscription` / `installment`), installment terms. **The only thing that expands into transactions** |
| B | `subscriptions` | Subscription-only metadata for a flagged `recurring_rule`: service name, reminder lead days, cancellation URL, price history. **Does not carry its own schedule** |
| B | `savings_goals` | name, target, current, target date, linked account |
| B | `tags` | name, colour |
| B | `attachments` | filename, mime, size, on-disk ref (file itself encrypted) |
| B | `user_preferences` | theme, week start, month start day, **carry-over toggle**, alert thresholds |

### 4.3 The cost of Shape B, stated plainly

You chose full-row encryption, so these consequences are real and permanent
features of the design, not bugs to be fixed later:

- **There are no foreign keys between data tables.** `category_id` lives inside
  a ciphertext — now nested inside a `splits` array, one level deeper still.
  The database cannot constrain what it cannot read. Referential integrity is
  enforced in the service layer, and `scripts/verify_integrity.py` exists to
  catch drift. Note that deleting a category must now walk every split of every
  transaction, not just a top-level field.
- **There are no useful indexes.** `(user_id, is_deleted)` is the only one
  possible. Every query is that index scan plus decryption.
- **SQL can compute nothing.** No `SUM`, no `GROUP BY category`, no
  `WHERE txn_date BETWEEN`. Every figure in the app is Python arithmetic over
  decrypted rows. This is why `stats_service` exists as a first-class service.
- **The database's own tooling is blind to your data.** No SSMS reporting, no
  ad-hoc query to check something quickly. `scripts/decrypt_query.py` is the
  only window in, and it needs the master key.

Section 5.6 covers what this costs in milliseconds, and section 5.7 covers the
escape hatch if it ever stops being acceptable.

### 4.4 Installments, and cash on hand

An installment (a motorcycle at ₱5,000 × 36) is a `recurring_rule` with
`kind = installment`, and its terms live in the rule's encrypted payload:

```json
{ "kind": "installment", "total": "180000.00",
  "payments": 36, "amount": "5000.00", "start": "2026-09-15" }
```

No new table: adding fields to an encrypted payload needs no migration
(FEATURES.md §14).

**The remaining balance is derived, never stored.** It is `total − sum of the
payments actually posted against this rule`, computed from the working set. A
stored counter would drift the first time a payment is edited, skipped or
deleted, and the database could not catch it.

Payments behave like any recurring expense: they reduce the account and the
daily allowance on the due date. The full price is never posted up front.

**The app has no net worth figure.** Its headline number is **cash on hand**
(ACC-17): the sum of the balances of accounts whose payload has
`counts_in_cash_on_hand = true`. Defaults by type are cash, debit, savings and
credit on, investment off (ACC-18). Nothing you own is modelled as an asset, and
an installment's unpaid remainder is never subtracted — it shows on the
installment card instead. So cash on hand drops ₱5,000 a month for the
motorcycle, never ₱180,000 at once. The asset-and-debt alternative is out
(REC-18); FEATURES.md §19 records why.

**Credit-card installments** post the monthly amount to the card each month.
`available credit` still subtracts the whole unpaid remainder, because the bank
blocks it from your limit on day one.

---

## 5. Encryption — the core of this application

### 5.1 The threat being defended against

Be precise about this, because it determines every decision below.

**In scope:** a person with legitimate SQL access to the company database — a
DBA, a backup operator, an auditor, a colleague with a broad read grant, or
anyone who obtains a copy of a backup file. They can `SELECT *` on any table and
restore any backup. They must learn nothing about your finances.

**Out of scope, and worth being honest about:** anyone with administrative
access to the *application server* while the app is running. They can read
`.env`, and they can read process memory where the DEK and the decrypted working
set live. Encryption at the application layer cannot defend against the machine
that does the decrypting. If the app server and the database are administered by
the same people, this design buys you less than it appears to.

### 5.2 Envelope encryption

The master key never encrypts a row. It wraps a per-user Data Encryption Key,
and the DEK encrypts rows.

```
BUDGET_MASTER_KEY                    12-word recovery phrase
(.env, never in the database)        (paper, never anywhere digital)
        │                                        │
        │ HKDF-SHA256                            │ BIP-39 → seed
        │ info="budget:dek-wrap:v{ver}"          │ → HKDF-SHA256
        ▼                                        ▼
   wrapping key                            recovery key
        │                                        │
        │ AES-256-GCM                            │ AES-256-GCM
        ▼                                        ▼
  users.dek_wrapped                users.dek_wrapped_recovery
        │                                        │
        └──────────────┬─────────────────────────┘
                       │  either one opens it
                       ▼
              user DEK (32 bytes)
              unwrapped at login, memory only
                       │
                       │  AES-256-GCM per row
                       ▼
              transactions.payload
```

Why the indirection, when there is only one user? Two reasons.

**Rotation stays survivable.** Rotating the master key rewraps **one row per
user** — a few milliseconds — instead of decrypting and re-encrypting every
transaction you have ever recorded. Rotation you can afford to perform is
rotation that actually happens.

**Two independent keys can open the same data.** The DEK is wrapped twice, under
two unrelated keys. Lose `.env` and the recovery phrase still opens it; lose the
phrase and `.env` still does. Neither wrapped copy is useful on its own, and a
DBA holding both learns nothing.

### 5.2.1 The recovery phrase

A 12-word BIP-39 mnemonic (128 bits of entropy), generated at registration and
displayed once, with an explicit acknowledgement before you can continue.

```
phrase ──► BIP-39 seed (PBKDF2-HMAC-SHA512, 2048 rounds)
       ──► HKDF-SHA256, info="budget:recovery-wrap"
       ──► 32-byte recovery key ──► unwraps dek_wrapped_recovery
```

The recovery flow does two things, and it needs both to be useful: it unwraps
your DEK **and** it authorises a password reset. A phrase that recovered the key
but left you unable to log in would be an ornament.

Be clear-eyed about what this costs. It is a **second complete path to your
data**. The database now holds two wrapped keys instead of one — both still
inert without `.env` or the phrase — but the paper those twelve words are
written on is now exactly as sensitive as the master key. Store it the way you
would store the master key, which is to say: not on this machine, not in this
repository, and not in the same place as your `.env` backup.

In exchange, the single largest risk in the project stops being fatal.

**Recovering with no `.env` at all.** Losing `.env` loses the blind-index
pepper as well as the master key, and a new pepper computes different
indexes, so an email address can no longer find its user row. The phrase finds
it instead: its derived key is tried against each user's
`dek_wrapped_recovery`, and only the owner's authenticates (the slow PBKDF2
step runs once; each try after it is one 62-byte AES-GCM open). The recovered
DEK then opens `users.profile_enc`, which holds the email, so the email index is
rebuilt under the new pepper and `dek_wrapped` under the new master key.
`tests/test_recovery.py::test_total_env_loss_recover_by_phrase_alone` does
exactly this.

### 5.2.2 Rotating after a suspected compromise

Two operations exist, and the difference between them is the whole point.

**Regenerate the phrase (SEC-22)** — new twelve words, the *same* DEK re-wrapped
under a new recovery key. One row update, instant, no data touched. The old
phrase dies immediately.

**Rotate the DEK (SEC-23)** — a *new* DEK, with every row decrypted under the old
one and re-encrypted under the new one, then wrapped under both the master key
and a fresh phrase.

The distinction matters because **the phrase does not protect your data; it
unwraps the key that does.** If someone read your twelve words and used them,
they hold a copy of your DEK — a 32-byte value they keep forever. Regenerating
the phrase after that changes the lock while they walk away with a cut key. Only
SEC-23 actually revokes them.

Rotation is cheaper here than it sounds: row `id`s do not change, so AAD stays
valid and it is a straight decrypt-old / encrypt-new per row. At personal scale
it runs in **one database transaction** — it completes or nothing changed, so
there is no half-rotated state to reason about and no `dek_version` column.

Both require a password re-prompt, are audited, and revoke every other session
(SEC-24). Neither reaches data someone already exported and kept.

### 5.3 The ciphertext envelope

Every `payload` column is one byte string laid out like this:

```
┌────────┬─────────────┬─────────────┬──────────────────┬──────────┐
│ fmt(1) │ key_ver (1) │ nonce (12)  │ ciphertext (n)   │ tag (16) │
└────────┴─────────────┴─────────────┴──────────────────┴──────────┘
   0x01     e.g. 0x01     random per      AES-256-GCM      GCM auth
                          encryption
```

- **`fmt`** lets the envelope format itself change later without guesswork.
- **`nonce`** is 12 fresh random bytes for *every single encryption*. Reusing a
  nonce under the same key is the one mistake that breaks GCM catastrophically —
  it leaks the XOR of both plaintexts and the authentication key. `envelope.encrypt()`
  therefore never accepts a caller-supplied nonce. There is no parameter for it.
- **`tag`** is what makes this *authenticated* encryption. A DBA who flips a byte
  in your ciphertext gets a decryption failure, not a corrupted balance.
- **The header is authenticated too.** `fmt` and `key_ver` are prepended to the
  associated data, so rewriting `key_ver` fails exactly like flipping a
  ciphertext byte.

**Associated Data** binds each ciphertext to its own row:

```python
aad = f"ZBDGT.{table}:{row_id}:{user_id}:v{key_version}".encode()
```

`ZBDGT` there is a constant namespace, not the configured `DB_SCHEMA`: a restore
into the scratch schema `ZBDGT_VERIFY` (§12.4) must rebuild the same AAD, or
verify mode could never decrypt a row.

Without this, someone with write access could copy the ciphertext from a ₱5.00
coffee over a ₱50,000.00 rent payment. They cannot read either one, but they can
swap them, and the app would decrypt the result happily. With AAD bound to the
row id, the swapped ciphertext fails to authenticate. This is why
`BUDGET_AAD_BIND_ROW=True` is not optional in practice.

> One consequence: a row's `id` must exist before its payload can be encrypted.
> Inserts are therefore two-step — insert with a placeholder payload to obtain
> the identity value, then encrypt with the real AAD and update, inside one
> transaction. `EncryptedRepository.create()` (`app/db/repositories/`) is the only
> place this awkwardness lives, shared by all eleven data tables.
>
> The column type `EncryptedPayload` backs this up: it refuses to write anything
> that is not a sealed envelope, so a dict, a string or JSON bytes assigned to a
> payload column fails the flush instead of landing in the database as plaintext.

### 5.4 The one field that cannot be encrypted this way

Login needs to find your user row from an email address, before any key has been
unwrapped. A randomly-nonced ciphertext is different every time, so it cannot be
searched. Something has to give.

The answer is a **blind index**: a deterministic HMAC stored alongside the
encrypted email.

```python
email_bidx = hmac_sha256(key=BUDGET_BLIND_INDEX_PEPPER,
                         msg=email.strip().lower()).hexdigest()   # CHAR(64)
```

The lookup is `WHERE email_bidx = ?`. What this leaks to a DBA: that two rows
have the same email, and — if they can guess your email address and they have
the pepper — that a given row is yours. Without the pepper, which lives only in
`.env`, it is an opaque 64-character hash.

This is the single deliberate exception to full-row encryption in the system.
It is confined to `users.email_bidx` and nothing else. No transaction field
gets a blind index, because none of them needs to be found before login.

### 5.5 Where keys live, and for how long

| Secret | Lives in | Lifetime |
|---|---|---|
| `BUDGET_MASTER_KEY` | `.env` on disk | Until rotated |
| **Recovery phrase** | **Paper, off this machine** | Forever — it never expires |
| Wrapping key | Derived on demand, never stored | One call |
| Recovery key | Derived on demand during recovery only | One call |
| `dek_wrapped` | `users` table | Until rotation |
| `dek_wrapped_recovery` | `users` table | Until the phrase is regenerated |
| **User DEK (plaintext)** | **Process memory only** | Session, then zeroed |
| Working set (decrypted) | Process memory only | `CACHE_TTL_SECONDS` |

The DEK is unwrapped at login and held in a session-scoped keyring. It is never
written to disk, never logged, never serialised into a JWT, and never returned
by any endpoint. On logout, session expiry, or PIN lock, the keyring entry and
the cached working set are dropped together.

A logging filter in `app/core/logging_config.py` redacts anything matching the
key and payload patterns, as a second line of defence for the day someone adds a
well-meaning `logger.debug(transaction)`.

### 5.6 What this costs

**Measured 2026-09-11** by `tests/test_crypto_performance.py` (10,000 realistic
transactions, seeded through the real repository): a cold load from **SQLite**
takes **224 ms** median, of which **decrypt + parse is 123 ms**. SQLite's fetch is
local and nearly free, so 123 ms is the CPU cost of the design.

**Against SQL Server from the development PC** the same cold load took
**2,346 ms** — over the line — with decrypt + parse still only 140 ms. Diagnosis
put the rest on the link between that PC and the database (14 ms round trip,
~12 Mbit/s over the internet): 10,000 bare ids came back in 39 ms, the same rows
with 250-byte payloads in ~1.75 s, whether or not the column was `MAX`.
Production runs beside the database, so the §5.7 go/no-go is taken from
`scripts/benchmark_fetch.py` run **on the app server** (read-only; it generates
its own rows).

The original estimate, kept for comparison:

For a personal dataset of **10,000 transactions** (roughly five years of heavy
daily use), a cold load is:

| Step | Estimate |
|---|---|
| Fetch 10,000 rows over ODBC | 200–400 ms |
| AES-256-GCM decrypt, ~200-byte payloads, AES-NI | 20–40 ms |
| JSON parse + object construction (`orjson`) | 60–120 ms |
| **Cold total** | **≈ 0.3–0.6 s** |
| Warm (cache hit) | < 1 ms |

That happens **once per session**, warmed at login while the user is still
looking at the unlock screen. Every screen afterwards reads the in-memory
working set. A month's stats over a warm cache is a Python loop over a few
hundred dicts — microseconds.

The cache is per-user, TTL-bounded (`CACHE_TTL_SECONDS=900`), write-through on
every mutation, and dropped on lock. At personal scale this is comfortable. It
would not be at organisational scale, which is the next section.

### 5.7 The escape hatch

If the dataset ever outgrows the working-set model — tens of thousands of rows,
or multiple real users — the migration path is already designed, and it is a
partial retreat from full encryption rather than a rewrite:

Add plaintext **bucket columns** to `transactions`: `period_key CHAR(7)`
(`'2026-09'`) and `category_id INT`. Now SQL can filter by month and group by
category, and only the matching rows get decrypted. Amounts stay encrypted, so
totals are still computed in Python, but over hundreds of rows instead of
thousands.

The cost is honest: a DBA would then see which months you were active and how
many transactions fell in each category. That is a real disclosure, which is why
it is not the starting point. `scripts/add_bucket_columns.py` is a Phase 9
deliverable — written, tested, and left unrun.

---

## 6. Authentication and session security

Login is layered, and each layer guards something different:

| Layer | Guards | Mechanism |
|---|---|---|
| Password | The account | bcrypt, cost 12, 12-char minimum |
| Lockout | Brute force | 5 attempts → 15-minute account lock |
| JWT access token | API calls | HS256, 30 min, `HttpOnly` cookie |
| Refresh token | Session continuity | Rotating, hashed, family-revoked on reuse |
| PIN | The *unattended screen* | 6 digits, bcrypt + pepper, 5-min auto-lock |
| DEK | **The data itself** | Unwrapped in memory, dropped on lock |

**Refresh token rotation** works as it should: each refresh issues a new token
and invalidates the old one. If an already-used token is presented, the entire
token family is revoked immediately — that is the signature of a stolen token
being replayed, and the correct response is to end every session.

**The PIN is not a second password, and it must not be mistaken for one.** It
re-locks a session that is already authenticated, the way Face ID does on the
iOS app. It never touches the DEK derivation, so a 6-digit PIN never becomes the
thing standing between an attacker and your data — a 6-digit secret has a
million possibilities, which is nothing to an offline attack. Failing the PIN
drops the in-memory keys and forces a full password login.

**A process restart looks exactly like an auto-lock.** IIS stops the app after
20 idle minutes, recycles it periodically, and restarts it on every deploy
(§10.1). Each time, the in-memory keys and working sets are gone while the
session cookies are still valid. The app treats an empty keyring as *locked*,
not as an error: the next request answers "locked", the PIN screen appears,
and after the PIN the server unwraps the DEK again with the master key and
re-warms the cache. Auto-lock fires after 5 minutes and idle shutdown after
20, so in practice the user was already locked (SEC-27).

**As built (Phase 2).** The session id *is* the refresh-token family id, and
the keyring is keyed by it. The access JWT sits in `zbdgt_session`
(`Path=/ZBDGT`); the refresh token in `zbdgt_refresh`, whose path is narrower
still (`/ZBDGT/api/v1/auth`), so no ordinary request carries it. Every request
checks its family is still alive, so a sign-out ends a 30-minute access token
at once. Locked is a first-class state: `/auth/me` answers `locked: true` and
omits the email, which lives under the DEK. Unlock is by PIN or by password,
and both make the server unwrap the DEK with the master key. Five wrong PINs
end the session. Lockouts are counted from `login_attempts`, so an email with
no account locks exactly like one with an account and reveals nothing. Every
state-changing API request must carry `X-Requested-With: fetch`: `SameSite=Lax`
does not protect against the other `*.noahapplication.com` apps, which count as
same-site.

---

## 7. The frontend, and how React gets built without npm on the server

React source lives in `frontend/`. It is **never built on the server**. The
server has no Node runtime, no npm, and no build step, and this is a permanent
constraint of the deployment, not a temporary state.

```
YOUR MACHINE                          THE SERVER
────────────                          ──────────
frontend/src/**/*.tsx
        │
        │  npm run build          (Vite — local only)
        ▼
app/web/static/dist/          ──►    FastAPI StaticFiles
  ├── index-a1b2c3d4.js               serves these bytes.
  ├── index-e5f6g7h8.css              Never runs Node.
  ├── manifest.webmanifest            Never runs npm.
  └── sw.js
        │
        └── committed to git ─────────────┘
```

`app/web/static/dist/` is **deliberately committed**, and `.gitignore` says so at
the point where it would otherwise be excluded. Deployment is `git pull` plus a
process restart.

The one moving part this creates is filename hashing. Vite emits
`index-[hash].js`, so the shell template cannot hard-code it. On startup the app
reads `dist/.vite/manifest.json` and passes the current filenames into the Jinja
context, so `index.html` always points at the bundle that is actually present.

**Development** runs the Vite dev server on `:5173` with HMR, proxying
`/ZBDGT/api` to uvicorn on `:8000`. **Production** is the built bundle only.
`CORS_ORIGINS` exists solely to make the dev proxy work; in production the API
and the bundle share an origin and CORS is irrelevant.

### Mobile-first, as a constraint rather than an aspiration

The design target is a 390 px iPhone viewport. Desktop is a widened version of
the phone layout, never a separate design.

- **Bottom tab bar**, thumb-reachable: Home · Calendar · **[+]** · Stats · More.
  The `[+]` is centre, raised, and larger than the rest — it is the action the
  app exists for.
- **Add-transaction is a bottom sheet with a numpad**, not a form with a text
  input. It opens with the amount field focused and the numpad already up.
  Two taps and a number should complete an entry.
- Touch targets ≥ 44 px. Safe-area insets respected. No hover-dependent
  affordances anywhere.
- **PWA**: installable to the home screen, standalone display, own icon and
  splash. A service worker caches the app shell so it opens instantly, but
  **never your figures**: offline, the app says it is offline instead of showing
  balances (§10.3). Writes require connectivity in v1, and queued
  offline writes are a Phase 9 item, deliberately deferred because merging
  offline edits into an encrypted store is genuinely hard.

---

## 8. Cross-cutting concerns

**Config** — `app/core/config.py`, Pydantic `BaseSettings`. Validators enforce
that the master key is present and exactly 32 bytes when base64-decoded, and
that the pepper is set. Both raise at import time. The app does not start
misconfigured.

**Errors** — one exception hierarchy in `app/core/exceptions.py`, one handler
that maps it to RFC 7807 problem responses. `DecryptionError` is special-cased:
it is logged with the row id and *never* returns detail to the client, because
decryption failure detail is an oracle.

**Rate limiting** — in-process sliding window, 200 req/min generally, 10 per
5 min on the login endpoint.

**Security headers** — `Content-Security-Policy` with a per-request nonce (no
`unsafe-inline`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`. **No HSTS:** it is a host-wide header, and this
app shares its host with other applications (§10.3).

**Audit** — every mutation writes to `audit_log`. The action verb and entity are
plaintext so the log is useful; the detail blob is encrypted so the log is not a
side channel that leaks the very amounts the main tables protect.

**Logging** — stdlib `logging`, as in QUOT, JSON lines to `logs/app.jsonl`. The
redaction filter from §5.5 is attached to every handler before that handler is
added, and uvicorn's own handlers are re-routed through it, with query strings
stripped from access-log lines. It removes amounts, keys, emails, recovery
phrases and named secrets. It cannot recognise free text, so exception messages
carry row ids, never payload values.

**Caching** — every API response carries `Cache-Control: no-store`. The
browser's HTTP cache is origin-wide storage on a shared host (§10.3).

---

## 9. Database schema management

Alembic, same as QUOT, with one addition: migrations touching a Shape B table
must never attempt a data transform in SQL, because SQL cannot read the data.
Such migrations pair a schema step with a Python backfill script in `scripts/`
that opens the master key, decrypts, transforms, and re-encrypts.

```bash
# Fresh install
alembic upgrade head
python scripts/bootstrap_user.py      # creates the account, generates its DEK
python scripts/seed_categories.py     # default category set, encrypted on write
```

Migrations live in `alembic/versions/`. `scripts/int_tables.sql` holds the raw
DDL for reference, mirroring the QUOT convention.

---

## 10. Deployment

IIS + httpPlatformHandler, following QUOT's `web.config`: the shared
`FAST-PYTHON` virtual environment, uvicorn launched as a child process, the path
forwarded unchanged with no rewrite rule, and `BASE_URL=/ZBDGT` and
`API_PREFIX=/ZBDGT/api/v1` set as environment variables. The IIS application
is named `ZBDGT`, which is also the database schema name. They are separate
settings that happen to share a name.

Where this app's `web.config` differs from QUOT's, and why:

1. **One worker.** QUOT runs two. This app can't: the decrypted working set and
   the session keys live in process memory, so a second worker would serve
   stale balances and see users as locked who are unlocked on the other one.
2. **No secrets in `web.config`.** It is committed. The master key, pepper, JWT
   secret, registration code and database password come from `.env` in the
   application folder, which is copied to the server by hand and never
   committed.
3. **Security headers come from the app, not IIS.** QUOT sets them in IIS.
   Here the middleware sends a per-request CSP nonce and `X-Frame-Options:
   DENY` (§8). Setting them in both places would duplicate each header, and
   QUOT's `SAMEORIGIN` next to the app's `DENY` is a conflict browsers resolve
   inconsistently.
4. **`SESSION_COOKIE_SECURE=true`.** Production is HTTPS, on the same host as
   QUOT (`https://delca.noahapplication.com/ZBDGT`), so the session cookie is sent over TLS only.
5. **`applicationInitialization`** points at `/ZBDGT/api/v1/health`, which
   reports database reachability and *whether the master key loaded*, without
   revealing anything about the key.

### 10.1 Idle shutdown, and how the app is shaped around it

IIS stops the process after the app-pool idle timeout (20 minutes by default)
and starts it again on the next request. Keeping it always running was declined
for QUOT on 2026-09-10 because of memory on a server running ~90 applications.
This app assumes the same constraint and does not ask for an exception.

| Consequence | How the design handles it |
|---|---|
| **A job scheduled for 02:00 only fires if someone is using the app at 02:00** | Nothing is scheduled for a time when the app may be stopped. Recurring payments, installments and subscription reminders catch up at login (REC-05); alerts are computed when you open the app |
| **Scheduled backups would rarely happen** | Backups are triggered by use (§12.6). The one timer, a 5-minute delay after your last change, always falls inside the 20 minutes IIS keeps the app alive after a request |
| **A restart empties memory**: the working set and every session's DEK are gone | A restart behaves exactly like an auto-lock (§6). The next request gets "locked", the PIN screen appears, and the app unlocks and re-warms. Nobody is logged out and nobody sees an error |
| **The first request after a stop is slower** | It pays the process start plus the cold decrypt (§5.6), roughly a second |

### 10.2 The shared virtual environment

Production runs in `C:\inetpub\wwwroot\FAST-PYTHON\.venv`, the same venv QUOT
uses, so installing `requirements.txt` there changes packages QUOT also depends
on. Wherever the two files overlap, this app's minimum versions match QUOT's
floors, so nothing here forces an upgrade QUOT didn't ask for. The packages this
app adds are `argon2-cffi`, `mnemonic` and `pillow`, plus `hypothesis` and `ruff`
for development. Preview the effect before installing with
`pip install -r requirements.txt --dry-run`.

### 10.3 Sharing a host with other applications

Production is `https://delca.noahapplication.com/ZBDGT`, on the same host as QUOT and the other
applications. To a browser, every app on that host is one **origin**, and some
browser features work per origin, not per path.

| Browser feature | Scoped to | What this app does |
|---|---|---|
| Cookies | A path, if one is set | Session and refresh cookies set `Path=/ZBDGT` and are named `zbdgt_*`, so they go only to this app and never overwrite QUOT's (SEC-28) |
| HSTS | The whole host | **Not sent.** It would change how browsers treat every app on the host. That is the host owner's call, not this app's |
| `localStorage`, IndexedDB, Cache Storage | The whole origin | **Never used for your data.** Any app's script on the host can read them. The service worker caches the app shell only, and caches are cleared on lock and logout (SEC-29). Offline, the app says it is offline instead of showing balances (UX-10) |
| Same-origin requests | The whole origin | **Cannot be prevented.** See below |

**The remaining risk, stated plainly.** Because every app on the host shares one
origin, a cross-site-scripting bug in *any* of them could send requests to
`/ZBDGT/api/v1` with your session while you are logged in, and read the
answers. Cookie paths don't stop that, and neither does `SameSite`. What limits
it: the 5-minute auto-lock (a locked session returns no data), this app's own
CSP, and nothing decrypted ever being stored in the browser.

This doesn't touch the risk the app was built for; the database side is fully
covered either way. The only complete fix is an origin of its own, such as a
subdomain like `zbdgt.noahapplication.com`. Worth asking the platform team
about if it's easy, but it blocks nothing.

---

## 11. Repository layout outside `app/`

| Path | Contains |
|---|---|
| `frontend/` | React source. Built locally; `node_modules/` never deployed |
| `alembic/` | Migrations |
| `scripts/` | DDL, seeds, key rotation, integrity check, decrypt-query tool |
| `tests/` | pytest; `test_crypto.py` is the one that must never be skipped |
| `misc/` | This document, the overview, the phase plan, the file tree |
| `uploads/` | Encrypted receipt files (gitignored) |
| `backups/` | Encrypted exports (gitignored — they are as sensitive as the DB) |
| `logs/` | Runtime logs (gitignored) |

---

## 12. Backup and restore

The company database must not be the only place your data exists. It is shared
infrastructure you do not control — a restore from someone else's mistake, a
decommissioned server, a migration you were not consulted about. So the app owns
a complete, portable, **encrypted** copy of itself.

### 12.1 The file

`budget-<timestamp>.budgetbak`, a zip container:

| Entry | Contents |
|---|---|
| `manifest.json` | **Plaintext** — format version, app version, key version, timestamp, per-table row counts, checksums |
| `keys.enc` | `dek_wrapped` **and** `dek_wrapped_recovery` |
| `<table>.enc` | One entry per data table: every row exactly as stored — the ciphertext plus its `id`, `user_id` and `key_version` |
| `attachments/<id>.enc` | Receipt images, still encrypted |

The manifest is deliberately readable so a restore tool can validate the file —
version, completeness, corruption — before asking for a key. It contains counts
and hashes, never values.

Because `keys.enc` carries both wrapped DEKs, **the file is standalone**: a new
server, an empty database, and either `.env` or your twelve words is enough.
That is what makes it a real second copy rather than a dump that only works
against the machine that produced it.

### 12.2 Only the import re-encrypts

AAD binds every ciphertext to its row `id`, together with the user and the key
version (§5.3). That is what stops a DBA swapping your ₱5 coffee over your
₱50,000 rent. It also means a restore can't simply reload rows: a fresh database
assigns new identity values, and a payload moved to a new `id` fails to
authenticate.

The fix only involves the import side:

```
EXPORT — needs no key                 IMPORT — needs your key
─────────────────────                 ───────────────────────
copy each row exactly as stored:      unwrap the DEK (master key or phrase)
  id, user_id, key_version,           for each entry:
  payload (ciphertext, untouched)       rebuild the ORIGINAL AAD from the
copy keys.enc and attachments             stored id, user_id, key_version
                                        decrypt
                                        INSERT → obtain a NEW id
                                        re-encrypt with AAD = new id
```

The file keeps each row's original `id`, `user_id` and `key_version` next to its
ciphertext. The database already shows that metadata in plaintext, and it is
everything the importer needs to rebuild the original AAD.

Because **writing a backup needs no key**, it can run with nobody logged in
(§12.6). Nothing is decrypted to write the file, so it is exactly as safe as the
rows it copies, and it opens with the same two keys: the master key or the
recovery phrase.

An earlier version of this design decrypted on export and re-encrypted under a
backup key derived from the DEK. That required a key to be present for every
backup and bought nothing.

### 12.3 ID remapping — where the bugs will be

Every cross-reference lives *inside* ciphertext, so the database cannot help.
The importer builds an `export_id → new_id` map per entity and rewrites:

- `transactions.account_id`, `.splits[].category_id`, `.tag_ids[]`,
  `.recurring_id`, `.attachment_id`
- `categories.parent_id`
- `budget_allocations.budget_id`, `.category_id`
- `savings_goals.account_id`
- `recurring_rules` template: `.account_id`, `.splits[].category_id`, `.tag_ids[]`
- `subscriptions.recurring_rule_id`

The last two were missing from the first version of this list. Without them,
every recurring rule would restore still pointing at the old account and
category ids and then post payments to the wrong place.

Insert order is fixed by those dependencies:

```
accounts → categories (parents before children) → tags → budgets
  → budget_allocations → recurring_rules → subscriptions
  → savings_goals → transactions → attachments
```

Get it wrong and you get silent orphans that no constraint will catch. **Any new
entity added later must be added to this map**, or it will restore broken.

### 12.4 Modes and proof

| Mode | Behaviour |
|---|---|
| `fresh` | Target must be empty for this user |
| `merge` | Adds to existing, skipping duplicates by content hash |
| `verify` | Restores into a scratch schema and diffs. Touches nothing live |

`verify` is what makes testing backups routine instead of frightening.

The acceptance test, and it is not optional:

> **export → restore into an empty database → export again → the two must be
> semantically identical.** Same entities, values and relationships. Row ids may
> differ; nothing else may.

Until that passes you have a file, not a backup.

### 12.5 What deliberately is *not* here

There is **no plaintext full archive**. Per-transaction CSV export (for Excel,
or for moving to another app) remains, with its warning, and that is the single
deliberate opening in the encryption boundary. Backups never open it at all.

---

### 12.6 When backups happen

Not on a schedule. IIS stops this app after 20 idle minutes (§10.1), so a job
set for 02:00 would only fire if someone happened to be using the app at 02:00.
Backups are triggered by use instead:

| Trigger | Does |
|---|---|
| **5 minutes after your last change** | Writes one. IIS keeps the process alive for 20 minutes after a request, so the delay always fires before an idle stop |
| **Login** | Writes one if your newest backup is older than `BACKUP_INTERVAL_HOURS` (24) — a safety net for a delay lost to a recycle |
| **"Back up now"** in Settings | Writes one immediately (SEC-13) |

This works because **your data only changes while someone is using the app.**
Recurring payments and installments are posted by the login catch-up, not in the
background, so backing up after changes captures every change.

For a copy that doesn't depend on anyone using the app, the server can run
`scripts/backup.py` from Windows Task Scheduler (DAT-20). It needs database
access and no key, because writing a backup decrypts nothing. Someone with admin
rights on the server has to create that task.

Backups stay per user: writing one needs no key, but restoring it needs that
user's key, so each file belongs to one user.

---

## 13. Multiple users

The app supports **multiple independent users**. It does not support two people
sharing one budget, and the difference is cryptographic rather than political.

### 13.1 Why it was nearly free

Every table has carried `user_id` and a per-user DEK since Phase 1. Multi-user
is the shape the schema already had, not a feature bolted on:

```
Alice                            Bob
  │                               │
Alice DEK                       Bob DEK      (unrelated 32-byte keys)
  │                               │
  ▼                               ▼
rows WHERE user_id = 1      rows WHERE user_id = 2
```

Enabling it is a config flag plus a registration policy. **Registration is gated
by a code you set in `.env`** (`REGISTRATION_CODE`): no code, no account. The
code is reusable until you change it, and changing it invalidates every
outstanding invitation at once. Because that code is the only gate on signup,
registration attempts are rate-limited hard, compared in constant time, audited
on failure, and additionally capped by `MAX_USERS`.

### 13.2 There is no administrator who can read your data

Worth stating explicitly, because it is unusual and it is deliberate:

> An admin can create, disable and delete accounts. They **cannot decrypt one.**
> No key exists that opens everything, and adding one would defeat the entire
> design. If a user forgets their password *and* loses their recovery phrase,
> nobody — including you — can recover their data.

That is the correct behaviour for this system, not a missing feature.

### 13.3 What it costs

| Concern | Effect |
|---|---|
| Working-set cache | Memory becomes N users × their data. `CACHE_MAX_USERS` bounds it (default 8, LRU eviction) |
| `--workers 1` | Still required — the cache is per-process. Fine for a handful of users; this does not scale to hundreds and does not need to |
| Key rotation | `rotate_keys.py` iterates every user's DEK |
| Backups | Per-user. Writing one needs no key, but restoring needs that user's key, so each file belongs to one user |
| Rate limiting | Per-account, not per-IP |

### 13.4 Shared budgets, and what they would take

Not built. Recorded so the option stays open.

The blocker: Alice cannot wrap a shared key *to* Bob, because she does not know
Bob's DEK and should not. Symmetric keys alone cannot express "share with". The
fix is standard but structural:

```
every user gets an X25519 keypair
  (private key encrypted under their own DEK)

Alice creates a Budget Encryption Key (BEK) for the shared budget
  ├─ wraps BEK to Alice's public key ─┐
  └─ wraps BEK to Bob's public key   ─┴─► budget_key_grants

rows in that budget encrypt under the BEK, not a personal DEK
  └─ every row needs a `key_scope` naming which key opens it
```

Roughly 2–3 weeks, and it modifies §5 rather than extending it. The ugliest part
is **revocation**: removing Bob means rotating the BEK and re-encrypting that
budget's rows, because he has already seen the old key and a key cannot be
un-seen.

---

## 14. Known state

Phases 1 and 2 are built (2026-09-11): the crypto core, the database layer,
the migration, the frontend shell, and sign-up / sign-in / lock / recovery,
with 212 passing tests. Schema `ZBDGT` and its fifteen tables exist on
P8_NOAH_AI, the SQL Server tests pass there, and the tables are empty. Everything
from Phase 3 on is still design. The things most likely to need revision:

- **§5.6 is measured except where it matters most.** CPU: 123-140 ms for
  10,000 rows. From the dev PC the fetch is network-bound (2.3 s total). The
  deciding figure is `scripts/benchmark_fetch.py` on the app server; if that
  exceeds ~1.5 s, §5.7 stops being a contingency and becomes the plan.
- **The two-step insert in §5.3** is the ugliest part of the design. If it
  proves error-prone in practice, the alternative is binding AAD to a
  client-generated UUID instead of the identity column — which removes the
  round-trip at the cost of a second key column.
- **Offline writes are deferred**, and the deferral is real. Do not let the PWA
  shell imply offline capability it does not have.
- ~~**Multi-currency is modelled but not converted.**~~ **Closed.** The app is
  PHP-only (FEATURES.md ACC-11). Currency is a formatting constant; there is no
  currency field on accounts or transactions, no FX source, and no mixed-currency
  arithmetic to get wrong.
- **Splits make the category-integrity problem one level deeper.** `category_id`
  now lives inside an array inside the ciphertext. `verify_integrity.py` and the
  category-delete path must both walk splits, and a bug in either is invisible
  to the database. Test these specifically.
- **The recovery phrase is a second attack surface**, accepted deliberately
  (§5.2.1). The paper it is written on is equivalent to the master key.
- **The backup importer's ID remapping (§12.3) is the highest-risk code in the
  project.** Every cross-reference it misses becomes a silent orphan that no
  database constraint can catch, and you will not find out until a restore. The
  round-trip test in §12.4 is the only thing standing between you and that.
- **Multi-user raises the memory ceiling**, since each active user holds a
  decrypted working set. `CACHE_MAX_USERS` bounds it, but with one worker and
  several heavy users this is the first thing that will hurt.
- **The app uses QUOT's database login** (same server, same database). If that
  login's password is ever changed on the platform, update both `.env` files.
- **It shares a browser origin with every other app on
  `delca.noahapplication.com`** (§10.3). A scripting bug in any of them could
  use a logged-in session. Only a subdomain removes that entirely.
