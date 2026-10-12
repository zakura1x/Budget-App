# BUDGET APP — System Architecture

> **Looking for the diagrams and the end-to-end flow?**
> [ARCHITECTURE_OVERVIEW.md](ARCHITECTURE_OVERVIEW.md) is the visual tour of this
> same system. **Looking for what to build, in order?** [phases.md](phases.md).
> **Looking for what it does, feature by feature?** [FEATURES.md](FEATURES.md) —
> and if you change a scope decision there, §14 of that file says what has to
> move in here.

**Personal Budget & Spending Tracker**
FastAPI · SQL Server (schema `ZBDGT`) · React 19 + Vite · AES-256-GCM at rest

This document is the map. Phase 1 (the crypto core, the database layer and the
frontend shell) was built on 2026-09-11, and the sections it touches describe
the code as it exists; everything later is still design. `misc/phases.md` is
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
| `account_service` | Cash, debit, credit, savings, investment, lent, borrowed and member accounts (with a `subtype` label), plus the one hidden untracked-cash account (ACC-39); balances; credit statement cycles, the bill left to pay, available credit and your own per-cycle spending limit; bills typed from a card's own app and what is due now (ACC-35); cash on hand and net worth (ACC-36); the interest terms an account earns on (ACC-37) and the cashback it usually pays (ACC-38) |
| `installment_conversion` | REC-34: a purchase on a card or loan turned into an installment plan and back. The purchase is hidden and linked both ways, so nothing counts twice; the plan is an ordinary recurring rule. Imports `recurring_service` and `transaction_service`; only its endpoints import it |
| `interest_service` | ACC-37: the daily savings interest a bank pays, credited day by day as ordinary income. A catch-up, like the recurring engine (§4.6); the arithmetic itself is pure, in `app/core/utils/interest.py`, and shared with the projection. Imports `transaction_service`; nothing imports it |
| `statement_service` | Checks a card statement against the bank's total and applies what you say the difference was (§4.4). Writes only through `transaction_service` and `recurring_service`; nothing imports it |
| `category_service` | Categories and sub-categories, icons, colours, ordering |
| `transaction_service` | Expense/income/transfer/adjustment CRUD; the write path. Also the cashback pair (TXN-22): a purchase and the income row that credits it, written, edited and deleted together |
| `budget_service/` | Periods, per-category allocations, **daily allowance** |
| `recurring_service` | Rule expansion — daily/weekly/monthly/custom. The one engine behind standard rules, subscriptions and installments |
| `subscription_service` | Your recurring merchant charges (Netflix, gym). A **view over** `recurring_rules`, never a second expansion engine |
| `projection_service` | The months ahead: salary, bills, installments, card statements and typed card bills laid out from the rules (§4.5). **Read-only** — it never posts a transaction |
| `stats_service` | Every chart series; all aggregation, since SQL cannot. One overview per range: category shares from splits, trend, comparison, merchants, accounts, tags and the forecast. Transfers, balance adjustments and revaluations never count |
| `calendar_service` | Day-by-day spending heatmap, shaded against the budget per day (or a typical day) |
| `tag_service` | Tags (name, colour). Transactions carry `tag_ids`, checked on write; deleting a tag removes its id from every transaction in the same commit |
| `goal_service` | Savings goals and progress |
| `import_export_service` | CSV in and out, encrypted attachments |
| `budget_app_import_service` | DAT-21: the "Budget" phone app's `.xlsx` backup, read in memory (zip sizes capped, any DOCTYPE refused), previewed, then written through `transaction_service.import_entries`. Today's balances are typed and land in the opening balances; it never writes a balance adjustment |
| `audit_service` | Records who changed what, with encrypted detail |

---

## 4. Data model

Everything lives in the **`ZBDGT` schema** of the shared SQL Server database.
Seventeen tables, in two shapes (`assistant_usage` since 2026-09-30, `assistant_threads` since
2026-10-01 - both the AI companion's, §15).

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
- `splits` is never empty. A balance adjustment carries exactly one split with
  `category_id: null`, the one split without a category (§4.4).

There is no `currency` field. The app is PHP-only by decision (FEATURES.md
ACC-11), so currency is a formatting constant, not data.

`row_created` is the server's insert timestamp, not the transaction date. That
distinction matters: `row_created` leaks only *when you used the app*, which is
unavoidable, while `txn_date` — which leaks your actual financial timeline —
stays inside the ciphertext.

### 4.2 The seventeen tables

| Shape | Table | Holds |
|---|---|---|
| A | `users` | `email_bidx`, `profile_enc` (email + display name, sealed under the user's own DEK), `password_hash`, `key_version`, `dek_wrapped`, `pin_hash`, lockout state. (`dek_wrapped_recovery` was dropped on 2026-09-14, §5.2.1) |
| A | `refresh_tokens` | Hashed token, family id, parent id, expiry, revocation |
| A | `login_attempts` | `kind` (login / pin / register / reset; `recovery` on rows from before 2026-09-14), `email_bidx`, success flag, keyed hash of the IP, timestamp |
| A | `audit_log` | user_id, action, entity, entity_id, encrypted detail blob |
| A | `assistant_usage` | The AI companion's counts per user per day: questions, model calls, tokens, template fallbacks. Never a question, reply or figure (misc/AI ARCHITECTURE §7, migration `20260930_0005`) |
| B | `accounts` | name, type, opening balance, colour, archived, `counts_in_cash_on_hand`, manual value (investment), statement/due day + credit limit + optional own `spending_limit` + `statement_checks` — the bank's total per statement (credit) |
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
| B | `assistant_threads` | A saved AI companion conversation: title, dates, the questions and replies. Only for a user who chose to keep conversations (misc/AI A6, migration `20261001_0006`) |

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

**But what you OWE counts the whole plan from the day you take it** (fixed
2026-09-16). A plan is a debt whether or not a charge has posted, so
`AccountView.plans_unbilled` carries the unbilled remainder on EVERY account
type and `CreditView.owed_with_plans` is `owed + unpaid_installments` - what
the card's own app calls your balance. Three figures stay out of it on
purpose: `balance` (the ledger's own sum), `owed` (what a payment would clear,
which the reminder and the statement check read) and cash on hand (ACC-17,
which never counts what you will owe later). Net worth counts it, on a card
and on a loan alike.

**A plan can be paid on the plan itself** (REC-32, 2026-09-16). A payment is
a transfer from the account you pay out of into the plan's account, carrying
the plan's id with no occurrence date - so `InstallmentStatus` can report the
plan in MONEY terms (`money_paid`, `left_to_pay`) beside its CHARGES (`paid`,
`remaining`), and the catch-up can never mistake it for a payment it posted.
What is due is covered first; an extra part is the user's to direct, and is
asked for before anything is written (409 `PREPAYMENT_CHOICE`):

```
lower    same number of payments, what is left spread over them
shorten  same payment, the last ones taken away (the new last one reduced)
```

Each extra payment is stored on the plan (`prepayments`: on, after, amount,
mode) and charged at once, so the budget sees it that day. It is applied
INSIDE the one schedule - `installment_plan()` builds the plan's payments from
its terms, then its interest changes, then each extra payment in order, and
`occurrences()` reads those rows - so bills, Months ahead and the catch-up all
follow without knowing extra payments exist. Price and interest each stay
exact to the centavo: an extra comes off the price first.

**Moving a start earlier reopens the catch-up** (fixed 2026-09-16). A plan
created with a later start and corrected to an earlier one kept its
`posted_through` marker, so the payments in between could never post.
`update_rule` now pulls the marker back to the new start (at most a year), and
expansion's check of dates already posted stops anything doubling up.

**The headline number is cash on hand** (ACC-17): the sum of what each account
whose payload has `counts_in_cash_on_hand = true` adds — its balance
(`AccountView.cash_amount`). Defaults by type are cash, debit, savings, credit
and member on; investment, lent and borrowed off (ACC-18/31/32). An installment's
unpaid remainder is never subtracted — it shows on the installment card instead.
So cash on hand drops ₱5,000 a month for the motorcycle, never ₱180,000 at once.

**A card with typed bills** (ACC-35, added 2026-09-15) adds `-due_now` instead
of its balance: the overdue bills plus the next one, as its own app lists them
(`bills` + `bills_from` in the account payload, written only by
`account_service.set_bills`). What is paid of each bill is derived — payments
into the card since the list was saved, oldest bill first — and the plan
charges on the card are added to a bill. WHICH bill depends on what the charge
is: an installment payment's date is the day the bank bills it, so it joins the
first bill due on or after that day; anything else is a purchase and takes the
statement route, falling due the month after (fixed 2026-09-16).
`projection_service._lands_on_bill` asks the question exactly the same way, or
a payment would be counted both inside a bill and on its own day.

**Cash the user does not track has one hidden account** (ACC-39, added
2026-09-20). Money lent out of a wallet that was never an account still needs
two ends, because a transfer is two legs (§4.2) and a one-legged posting would
have to be an adjustment - which Stats would read as income (§4.8). So
`account_service.untracked_cash()` get-or-creates a single account with
`hidden` set: out of every list and picker (the client filters it once, in
`useLookups`), out of cash on hand and out of net worth, whatever its own
switches say. It only ever holds transfer legs, so Stats never sees it either.
`hidden` is not part of `AccountIn` - only that function writes it - and
`_clean` carries it through an edit. The client never offers it as a chip: on a
loan's transfer, an EMPTY side means the wallet (`fromIsWallet` / `toIsWallet`
in TransactionSheet), the draft leaves with a sentinel id, and `save` turns
that into the real account - creating it on the server if this is the first
one. Every other transfer must still name both ends.

**A loan bills like a card** (ACC-40, added 2026-09-21). A credit card's
bills are typed from its own app; a loan's are derived, because the plan on it
IS the schedule. `recurring_service.plans_owed()` walks the rules once and
answers both questions - what is still to be BILLED (REC-14, the figure a
card's limit holds back) and what of the SCHEDULE money has not covered - and
`account_service._dues_view` turns the second into `AccountView.dues` for a
borrowed account. `due_now` follows ACC-35 exactly (everything overdue plus the
next one) and takes the place of the balance in `cash_amount`, so a counted
loan holds back what is due rather than the whole debt. Everything else -
`balance`, what it says you owe, net worth - still counts the plan in full.
`projection_service._bill_items` emits the dues the same way it emits a card's
bills, and `project()` drops the plan's own charges on such an account, or the
same money would leave twice.

**Net worth sits beside it, never instead of it** (ACC-36, added 2026-09-15 at
the user's request): every active account with its own
`counts_in_net_worth` switch on, at full balance, less every debt in full —
card balances, loans, and installments not yet billed (`account_service.net_worth`).
The Accounts tab flips between the two.

**Credit-card installments** post the monthly amount to the card each month.
`available credit` still subtracts the whole unpaid remainder, because the bank
blocks it from your limit on day one. That remainder is derived per card from
the open plans (`recurring_service.plans_owed`), never stored on the
account.

**Posted occurrences carry `recurring_id` and `recurring_on`** (the occurrence
date; null for a payment against a plan, such as its confirmed interest or an
early payoff). Catch-up posts what is dated after the rule's `posted_through`
and not already present as that pair, then advances `posted_through` in the
same commit - so it is idempotent, and a charge the user deleted is not posted
again.

**Card bills (FEATURES.md ACC-19, ACC-20)** are derived from postings, never
stored:

```
statement amount = what the card owed at the close of that statement
left to pay      = max(0, statement amount − payments and refunds into the card since the close)
card_due alert   = left to pay > 0  and  due within CREDIT_DUE_ALERT_DAYS
```

The alert keys on *left to pay*, not on the card's whole balance. Keyed on the
balance, as first built in Phase 5, it kept warning after the bill was paid
whenever new purchases sat on the next statement.

**Your own spending limit (ACC-21, ACC-22)** is an optional `spending_limit` in
the account payload, separate from the bank's `credit_limit`. It needs no
migration. It is measured over the **open statement period**: purchases minus
refunds posted to the card, including recurring and installment charges,
excluding payments, transfers and balance adjustments. The check reuses the budget's rules in
`budget_service/alerts.py`, with the same `ALERT_WARN_THRESHOLD_PCT` and pace
tolerance, applied to the statement period instead of the budget period.
`card_limit_over` replaces `card_limit_approaching` and `card_limit_pace` for
that card, just as `over` does for the budget. Nothing is ever blocked, and a
purchase still counts once, against the budget period of its own date (ACC-16).

**The statement check (ACC-24..26)** is the one number the user types at
billing. The bank's total is appended to the card's payload as
`statement_checks: [{closes, bank_total}]`, the same append-only shape as the
valuation history (ACC-13), with no migration. The difference is derived on
every read, never stored:

```
difference = bank_total − statement amount (the app's)
```

Every resolution is an ordinary transaction, so once it posts the difference
recomputes to zero and nothing else needs updating:

| Choice | Writes |
|---|---|
| One-time fee or interest | An expense on the card, dated the closing date, in Financial › Bank fees or Interest |
| Interest on this installment (REC-29) | The plan's terms updated, and its payments already posted corrected to carry the interest (`transaction_service.reprice_recurring`, their price split untouched) |
| The installment payment changed (REC-29) | The plan's `interest_changes` gains the new interest from that payment on; posted payments from there are corrected the same way |
| A purchase I forgot | Whatever the add sheet saves |
| Posted on the next statement | `card_posted_on` on the purchase |

**Statement membership and the card limit use `card_posted_on` when it is set,
otherwise `txn_date`. The budget always uses `txn_date`.** That is the whole
effect of a late posting: it moves between statements, never between budget
periods. A lower bank total is never offered as interest.

**Installment terms** can arrive after the purchase (REC-28..30):

```json
{ "kind": "installment", "price": "40000.00", "payments": 6,
  "terms": "provisional", "amount": "6666.67", "start": "2026-09-20" }

// after the first statement confirms ₱400 a month:
{ "kind": "installment", "price": "40000.00", "interest": "2400.00",
  "total": "42400.00", "payments": 6, "terms": "confirmed",
  "amount": "7066.67", "start": "2026-09-20" }
```

A provisional plan's `total` is its `price`. Each payment posts two splits:
`price ÷ payments` in the purchase's category and `interest ÷ payments` in
Financial › Interest. Each split's last payment absorbs its own rounding
(REC-16), so both the price and the interest come out exact. Zero interest
posts one split. The remaining balance stays derived, as above: the ₱400 posted
for payment 1 carries the plan's `recurring_id`, so it counts as paid.

**Balance adjustments (FEATURES.md ACC-27..30).** A balance is never stored, so
"set the balance to X" has to be recorded as *something*. The edit sheet sends
the typed balance alongside the account fields. `account_service` compares it
with the derived balance, and if they differ it saves nothing and returns
`409 BALANCE_DIFFERS` carrying the difference. The client asks the user, then
resubmits with one choice (cancel never reaches the server):

| `balance_action` | Writes |
|---|---|
| `adjust` | An `adjustment` transaction dated today for the difference, plus `audit_service.BALANCE_ADJUST` with `{before, after, difference, note}`. Both happen in the same database transaction as the account update |
| `fix_opening` | `opening_balance += difference`. No adjustment and no `BALANCE_ADJUST` |

The ordinary `UPDATE` audit entry (name and type, no amounts) is written on
every save either way, as it is today.

`adjustment` joins `expense`, `income` and `transfer` in `transaction_service.TYPES`.
It posts to one account with one uncategorised split. **Balances, cash on hand
and the statement amount include it; the budget, the allowance, stats and the
card limit exclude it by type** — confirmed by the user on 2026-09-14. Every
place that filters on type has to be checked when it lands. Deleting is the only undo (soft, audited); `update`
refuses an adjustment, because its audit entry already recorded the before and
after.

### 4.5 Projection — the months ahead

Projection (FEATURES.md REC-19..27, §20) lays salary, bills, subscriptions and
installments over the next months. **It adds no table and stores nothing.** It
runs on request, in the user's session, over rules already in the working set.

**One schedule, two readers.** `recurring_service` exposes a pure function,
`occurrences(rule, start, end)`, that returns dated amounts. It handles
frequency, semi-monthly days (REC-19), end conditions, skips, the amount history
(REC-20) and the installment's rounding-absorbing final payment (REC-16).
Expansion posts what it returns up to today. `projection_service` reads what it
returns after today. There is no second calendar that could disagree with what
actually posts.

```
recurring_service.occurrences()  ──┬──▶ expansion  (≤ today)  → transactions
                                   └──▶ projection (> today)  → a response, never a row
```

The amount history is a dated list inside the rule's encrypted payload. Like
every payload field, it needs no migration; a rule without one uses its single
`amount`.

**Per month**, starting from today's cash on hand (ACC-17):

```
income     = income occurrences into counted accounts
committed  = expense occurrences on counted accounts (cards included, §19)
bills      = typed card bills entering cash on hand this month (ACC-35)
spending   = max(budget for the month, committed)     REC-23
closing    = opening + income − spending − bills      → next month's opening
low point  = lowest running balance over the dated occurrences,   REC-24
             with (spending − committed) set aside on day 1
```

- The **current month** uses what is left of the current budget period, not the
  full budget, plus the occurrences still to come after today.
- A **"month"** is the budget month when the budget is monthly, which respects a
  custom start day (BUD-04). Weekly and custom budgets are pro-rated by days
  into calendar months, rounded to the centavo with `Decimal`.
- **Carry-over is ignored.** The projection assumes you spend exactly the
  budget, so there is nothing to carry.
- **Transfers** follow ACC-18. Between two counted accounts they change nothing;
  into an uncounted one they reduce cash on hand.
- **Typed card bills** (ACC-35). Cash on hand already holds the bill due now;
  each later bill enters the day after the bill before it falls due. Its typed
  part is `bills`, taken on top of the budget (past purchases); its plan part is
  a fixed charge (`committed`) on that day. A card charge that lands on one of
  these bills is not counted again on the day it posts.

**Credit-card look-ahead (REC-25)** groups each card's occurrences by statement
period, using the same `date_utils` statement cycle as ACC-09. A card charge
reduces projected cash on hand on the day it posts, not when the bill is paid.
The bill is shown as *"₱7,150 due May 5"* but never subtracted again, because
paying it is a transfer between two counted accounts.

Like the budget endpoints, `GET /api/v1/projection` and
`GET /api/v1/projection/cards` take the client's `today`. Nothing from either
response is cached in the browser (SEC-29). `projection_service` imports
`recurring_service`, `account_service` and `budget_service`, and none of them
imports it back.

### 4.6 Daily savings interest (ACC-37)

The banks this app is used with (SeaBank, MariBank) work interest out on
**yesterday's closing balance** and credit it early the next morning (MariBank:
1:00 am), dated that morning, so an account's real
history holds one small income entry per day. `interest_service` reproduces
that history rather than approximating it, which is what keeps the app's
balance equal to the bank's on any given day.

```
for each day from max(started + 1, credited_through + 1) to TODAY:
    base   = the account's closing balance the day before
    gross  = the slice of base in each band x rate / 100 / 365
    net    = gross x (1 - withholding tax)
    carry += net                       <- kept to eight places
    credit = carry truncated to the centavo; carry -= credit
```

Four rules hold this together:

- **An entry dated d pays for d - 1.** Yesterday's balance is closed, so
  today's entry posts on today's first open, as the bank's does; today's own
  balance is paid tomorrow, so typing a transaction never changes a posted
  entry. (Until 2026-09-17 the app waited a day - the user's MariBank credits
  at 1:00 am.)
- **The credit compounds.** Interest posted on a day is part of that day's
  closing balance, so the next day earns on it.
- **Sub-centavo interest is carried, never rounded.** `carry` holds what is
  still owed and pays out on the first day it reaches ₱0.01 — nothing is
  invented and nothing is lost.
- **Net only.** What is credited is what the bank deposits; the gross and the
  20% tax are shown on the account page and never posted (ACC-37).

There is no scheduler on this server — IIS idle-stops the process (§7) — so
`POST /accounts/interest/accrue` is a **catch-up**, safe on every open, exactly
like `POST /recurring/expand`. Every posting and every account's
`credited_through` marker move in ONE commit, so the marker and the rows can
never disagree and a deleted entry is never written back. Each entry carries
`interest_on`, which is what makes a second run a no-op.

The arithmetic is pure and lives in `app/core/utils/interest.py`, shared with
`projection_service` so the months ahead and the days behind can never use two
different formulas — the same discipline as `recurring_service.occurrences()`.

### 4.7 Cashback (TXN-22)

A purchase that pays something back keeps its **full amount**: spending stays
gross, and the money that comes back is an income row of its own, in the
category the user picks, on the account and day the user picks. The two are a
linked pair, like a transfer's legs — the purchase carries `cashback` (what,
where, when) and `cashback_id`; the credit carries `cashback_of` — and they are
written, edited and deleted in one commit by `transaction_service`.

The reason it is a pair and not a discount is the balance: cards pay cashback
days later, and a purchase quietly reduced by ₱20 would leave the app's balance
disagreeing with the card's until the money arrives. An account's usual rate
(ACC-38) only fills the field in; nothing is derived from it afterwards, so a
rate that changes later cannot rewrite what was recorded.

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
BUDGET_MASTER_KEY
(.env on the server, plus the owner's offline copy — never in the database)
        │
        │ HKDF-SHA256, info="budget:dek-wrap:v{ver}"
        ▼
   wrapping key
        │
        │ AES-256-GCM
        ▼
  users.dek_wrapped
        │
        ▼
  user DEK (32 bytes)
  unwrapped at login, memory only
        │
        │  AES-256-GCM per row
        ▼
  transactions.payload
```

Why the indirection? Two reasons.

**Rotation stays survivable.** Rotating the master key rewraps **one row per
user** — a few milliseconds — instead of decrypting and re-encrypting every
transaction you have ever recorded. Rotation you can afford to perform is
rotation that actually happens.

**A password never touches the data.** The password authenticates you; it does
not wrap the key. Changing it, or resetting it by email (FEATURES SEC-30), updates one
hash and no ciphertext.

### 5.2.1 Losing `.env` — the offline copy

**Decided 2026-09-14: there is no recovery phrase.** Phases 1–2 built a second
wrap of every DEK under a 12-word BIP-39 phrase (`users.dek_wrapped_recovery`),
so that losing `.env` would be survivable. It was removed from the code the same
day (FEATURES SEC-14). The reasoning:

- Only the server side can lose `.env`. The phrase made every *user* keep
  insurance, on paper, against a failure none of them could cause or prevent.
- One offline copy of `.env` insures every account at once and asks users for
  nothing.
- The phrase was a second complete path to the data: each sheet of paper was
  exactly as sensitive as the master key.

What replaces it is operational, not cryptographic: the server owner keeps an
**offline copy of the whole `.env`** (FEATURES SEC-31).

| Secret in `.env` | Lost without a copy |
|---|---|
| `BUDGET_MASTER_KEY` | No DEK unwraps. **Every row of every user is unreadable** |
| `BUDGET_RETIRED_KEYS` | Backups and wraps from before a master-key rotation are unreadable |
| `BUDGET_BLIND_INDEX_PEPPER` | No email finds its account, so nobody signs in until a script rebuilds every index from `profile_enc` (possible, because the master key still opens each DEK) |
| `PIN_PEPPER`, `JWT_SECRET_KEY`, `SESSION_SECRET` | Everyone is signed out and PINs are set again. Nothing is lost |

Rules for the copy (the runbook is `how-to-run.txt`):

- **The whole file, in at least two places**, none of them the app server or
  the repository.
- **Never beside the `.budgetbak` files.** A backup is safe anywhere on its own
  (§12); a backup plus the copy is the data.
- **Refreshed the same day any key changes** — `generate_keys.py`,
  `rotate_keys.py`. A stale copy cannot open what was wrapped under a newer key.
- **Checked, not trusted.** `scripts/env_fingerprint.py` prints a short SHA-256
  fingerprint of each random key, and `--compare` checks every setting of two
  files - passwords included - printing only same / different. Admin → status
  shows the same fingerprints for the keys the running app loaded. Passwords
  are never fingerprinted for display: a short hash of a guessable value can be
  checked against guesses.

**What this costs, stated plainly.** Losing `.env` *and* every copy destroys
every account at once, where the phrase made that loss survivable per user. And
whoever holds `.env` and can reach the database can read every account. That
was already true (§5.1 puts the app server out of scope), but a second door is
gone, and the burden sits entirely with the server owner.

**A forgotten password is reset by an emailed link** (SEC-30, built
2026-09-14), since the recovery flow is what used to do it:

```
/forgot  email typed ──► blind index ──► active account?
                         (same 202 answer either way; 3 mails/address/hour)
             yes ──► token = 32 random bytes
                     users.reset_token_hash = SHA-256(token), expires in 30 min
                     mail to the typed address, AFTER the response:
                     {APP_PUBLIC_URL}{BASE_URL}/reset#token=...
/reset   fragment read by the page, wiped from the address bar
         POST /auth/reset-password {token, password}
             ──► hash matches, not expired ──► new bcrypt hash, token cleared,
                 every session ended, signed in, audited
```

- The address mailed is the one typed. It matched the blind index, so it is
  the account's email; nothing is decrypted to send it.
- The token is in the **fragment**, which a browser never sends to the server,
  so it cannot land in the IIS access log. Only its hash is stored.
- The link's origin is `APP_PUBLIC_URL`, never the request's `Host` header:
  otherwise anyone could make the app mail a real user a link to their site.
- No ciphertext changes: the password never wrapped the DEK.
- The email carries nothing from the budget. SMTP settings live in `.env`;
  an empty `SMTP_HOST` turns the feature off.

The honest cost: **the mailbox is now part of the account.** Whoever can read
a user's email can reset their password and, signed in, read their budget.

**Removed from the code on 2026-09-14:**
- The sign-up words screen (`RecoveryPhraseSetup`).
- `/auth/recover`, `RecoveryPhraseEnter` and `recovery_service`.
- `security_service.regenerate_phrase` and the "New recovery words" row.
- The recovery wrap in `provisioning.py` and in DEK rotation.
- Phrase unlock in `restore_service` and in `restore.py --phrase`.
- `crypto/recovery.py`, `lib/bip39.ts` and the `mnemonic` dependency, with their tests.
- `users.dek_wrapped_recovery` and `recovery_created_at`, dropped by migration
  `20260914_0002` (applied to ZBDGT the same day).

Backups written before then still carry the recovery wrap, and the reader
ignores it. Key version 0 stays reserved, so such a wrap can never be taken for
a master-key wrap.

### 5.2.2 Rotating after a suspected compromise

Two operations exist, and the difference between them is the whole point.

**Rotate the master key** (`scripts/rotate_keys.py`) — a new key in `.env`,
every user's *same* DEK re-wrapped under it, the old key kept in
`BUDGET_RETIRED_KEYS` so older backups still open. Milliseconds per user, no
data touched. Three steps: `--new-key` (writes `.env`), restart the app,
`--rewrap` (one commit per account, resumable). Sign-in also re-wraps a DEK
still under a retired version.

Two version numbers must not be confused. The **wrap's** version is the
`key_ver` byte of `users.dek_wrapped`, and rotation moves it.
`users.key_version` is the version `profile_enc` was sealed under - part of
that ciphertext's AAD - and only a DEK rotation, which re-seals the profile,
changes it. Until 2026-09-15 the sign-in re-wrap overwrote `users.key_version`,
which would have made every profile unreadable after the first real rotation;
`tests/test_key_rotation.py` now guards it.

**Rotate the DEK (SEC-23)** — a *new* DEK, with every row decrypted under the old
one and re-encrypted under the new one, then wrapped under the master key.

The distinction matters because **the master key does not protect your data; it
unwraps the key that does.** Someone who held `.env` and the `users` table could
unwrap your DEK — a 32-byte value they keep forever. Rotating the master key
after that changes the lock while they walk away with a cut key. Only SEC-23
actually revokes them. After a leaked `.env`: rotate the master key first, so
no new DEK is wrapped under the leaked key, then every user's DEK, then replace
the offline copy.

Rotation is cheaper here than it sounds: row `id`s do not change, so AAD stays
valid and it is a straight decrypt-old / encrypt-new per row. At personal scale
it runs in **one database transaction** — it completes or nothing changed, so
there is no half-rotated state to reason about and no `dek_version` column.

DEK rotation requires a password re-prompt, is audited, and revokes every other
session (SEC-24); master-key rotation is a script the server owner runs, dry run
first. Neither reaches data someone already exported and kept.

**As built (Phase 8b, `auth_service/security_service.py`).** Rotation re-seals
every Shape B row, every audit detail, the sealed profile and every receipt
file (`rotation_repository.py`); receipts are written beside the originals and
swapped in only after COMMIT, so a failed rotation changes nothing. The current
session is re-keyed in place and every other ends. Rotation also writes a fresh
backup and deletes the account's older server-side backups, because an older
backup opens the old DEK.
**FEATURES §13-A is closed as moot.** The phrase was never re-viewable, because
the words were never stored, and the phrase itself is being removed.

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
> place this awkwardness lives, shared by all twelve data tables.
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
| **Offline copy of `.env`** | **The owner's password manager + encrypted USB, off the server, apart from backups** | Replaced the same day any key changes |
| Wrapping key | Derived on demand, never stored | One call |
| `dek_wrapped` | `users` table | Until rotation |
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

- **Bottom tab bar**, thumb-reachable: Home · Accounts · **[+]** · Calendar · More
  (2026-09-15; was Home · Calendar · [+] · Stats · More). The `[+]` is centre,
  raised, and larger than the rest — it is the action the app exists for.
  Accounts is a tab because editing one should never be a trip through More;
  Stats sits behind a Calendar | Stats switch at the top of both screens, each
  still its own route. The look is neo-brutalist (2026-09-18, replacing the
  lavender look of `sample_ui/`): outlined tiles on hard offset shadows, 8px
  corners, amounts and labels in a self-hosted mono face, a floating pill bar.
  Four colour palettes (classic, candy, lime, mono), each light and dark — all
  tokens in `theme.css`, picked by `data-palette` and `data-theme` on `<html>`.
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

  As built: `app/web/static/sw.js` is hand-written and committed (Vite does not
  touch it) and served at `/ZBDGT/sw.js` with `Service-Worker-Allowed: /ZBDGT/`
  and a worker CSP of `default-src 'self'` — a worker runs under its own
  script's CSP, and `'none'` would stop it fetching anything. It caches the
  shell network-first and the hashed bundle cache-first, and returns before any
  cache is consulted for `/api/`. `/ZBDGT/manifest.webmanifest` is served by
  the web router; icons are PNGs drawn by `scripts/generate_icons.py` and
  committed. The page clears `zbdgt-*` caches on lock and sign-out, and shows
  an offline screen with no figures while the browser reports no connection.

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
app adds are `argon2-cffi`, `mnemonic` (removed with the recovery phrase in
Phase 9) and `pillow`, plus `hypothesis` and `ruff`
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
| `keys.enc` | `dek_wrapped`, under the master key version in the manifest. Files written before 2026-09-14 also carry `dek_wrapped_recovery`, which the reader ignores |
| `<table>.enc` | One entry per data table: every row exactly as stored — the ciphertext plus its `id`, `user_id` and `key_version` |
| `attachments/<id>.enc` | Receipt images, still encrypted |

The manifest is deliberately readable so a restore tool can validate the file —
version, completeness, corruption — before asking for a key. It contains counts
and hashes, never values.

Because `keys.enc` carries the wrapped DEK, **the file is standalone** wherever
the same master key exists: a new server, an empty database, and the offline
`.env` copy (§5.2.1) are enough. That is what makes it a real second copy rather
than a dump that only works against the machine that produced it. Keep the file
and the `.env` copy apart: each is harmless alone, and together they are the
data.

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
copy each row exactly as stored:      unwrap the DEK (master key)
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
rows it copies, and it opens with the same key: the master key, current or
retired.

An earlier version of this design decrypted on export and re-encrypted under a
backup key derived from the DEK. That required a key to be present for every
backup and bought nothing.

### 12.3 ID remapping — where the bugs will be

Every cross-reference lives *inside* ciphertext, so the database cannot help.
The importer builds an `export_id → new_id` map per entity and rewrites every
reference listed in **one place**, `app/services/backup_service/references.py`:

- `transactions.account_id`, `.counter_account_id`, `.splits[].category_id`,
  `.tag_ids[]`, `.recurring_id`, `.pair_id`, `.attachment_id`
- `categories.parent_id`
- `budget_allocations.budget_id`, `.category_id`
- `savings_goals.account_id`
- `recurring_rules.account_id`, `.counter_account_id`, `.category_id`,
  `.interest_category_id`, `.tag_ids[]`
- `subscriptions.recurring_rule_id`
- `attachments.transaction_id`

The recurring and subscription lines were missing from the first version of
this list, and the transfer, installment-interest and receipt references from
the second; building it found them. Without them a rule restores still
pointing at the old account and posts to the wrong place, and a transfer's legs
lose each other.

Insert order is fixed by those dependencies:

```
accounts → categories → tags → budgets → budget_allocations
  → recurring_rules → subscriptions → savings_goals → user_preferences
  → transactions → attachments
```

A reference to a table at or after a row's own position — a category's parent,
a transfer's other leg, a transaction's receipt — is **deferred**: the row is
inserted with it cleared and it is filled in once every row exists, inside the
same database transaction. Rows are inserted in their original id order within
each table, so their relative order survives and two exports compare position
by position. A reference that resolves to nothing aborts the restore before
commit.

Get it wrong and you get silent orphans that no constraint will catch. **Any new
entity or reference added later must be added to that map**; a test fails if
the insert order stops covering every encrypted table.

### 12.4 Modes and proof

| Mode | Behaviour |
|---|---|
| `fresh` | Target account must hold no data (its preferences excepted) |
| `merge` | Adds to existing, skipping rows whose content is already there; one budget and one preferences row per account, so an existing one is kept |
| `verify` | A dry restore in memory: every row opened, every reference resolved, the result compared with the live data. **Writes nothing** |

`verify` is what makes testing backups routine instead of frightening. It was
first planned as a restore into a scratch schema; done in memory it proves the
same things without extra database rights or anything to clean up.

**A restore always targets an existing account.** On a new server you put the
offline `.env` copy in place and sign up first, which gives the account its own
DEK. The backup's rows are opened with the key they were made under and
re-sealed under the target's. Which path may open a backup:

| Path | Allowed for |
|---|---|
| The app's Restore screen | Only the signed-in account's **own** backup: the file's user id and `email_bidx` must match |
| `scripts/restore.py`, run on the server | Any backup whose master key (current or retired) is in `.env` |

Without the first rule a stolen `.budgetbak` plus any login on the server would
turn the app into a decryption oracle for it. The script is not bound by it,
because whoever holds `.env` can read everything anyway (§5.1). A restore onto a
new server therefore always goes through the script: the new account's user id
differs from the file's.

Backups written before 2026-09-14 also carry a recovery wrap; nothing reads it
any more (§5.2.1).

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

### 13.2 No administrator can read your data in the app

Worth stating explicitly, because it is unusual and it is deliberate:

> An admin can create, disable and delete accounts. They **cannot decrypt an
> account** from the app, and cannot reset anyone's password: a reset link goes
> only to the account's own email (FEATURES SEC-30), so whoever controls that
> mailbox is the one who can.

Be precise about the limit. There is no admin *role* that decrypts, but the
master key opens every DEK, so whoever holds `.env` and can reach the database
(the server owner) can read everything (§5.1). With the recovery phrase gone
(§5.2.1) there is no per-user secret that stands outside that. If `.env` and
every offline copy are lost, nobody can recover anyone's data.

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
- **`.env` is the single point of failure** (§5.2.1). The recovery phrase was
  removed on 2026-09-14, so the offline copy is the only protection against
  losing `.env`, and a loss takes every account at once. Check the copy by
  fingerprint; do not trust it.
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

---

## 15. The AI companion

Built 2026-09-30 to 2026-10-01 and documented in full in `misc/AI/`
(README, ARCHITECTURE, FEATURES, PHASES). What the rest of the system needs to
know:

- **It is a reader.** `/assistant/ask` answers a question about the user's own
  money by calling the same services the screens call (`budget_service`,
  `stats_service`, `projection_service`, `safety_service` ...) and handing the
  model finished, formatted figures. The model words the answer; it never
  computes a figure, never reads the database and never writes. Every reply
  is checked (`assistant_service/verifier.py`) and replaced by the app's own
  sentence if any number in it is not in the figures.
- **"Can I afford it?" is decided by rules** (`app/core/utils/affordability.py`)
  over the Months ahead cash line (§4.5); the model explains the verdict.
- **The model is IBM watsonx.ai**, reached the way STWRD reaches it: the API
  key is fetched from the company IAM service at run time and held in memory
  only (`app/ai/`). `AI_ENABLED=False` loads and calls nothing. What leaves
  the server is the question and the figures that answer it (§5's boundary
  has one deliberate opening here, which the user opts in to).
- **Two tables.** `assistant_usage` (Shape A) counts questions, model calls,
  tokens and fallbacks per user per day - never content. `assistant_threads`
  (Shape B) holds a conversation only if the user chose to keep conversations;
  by default a conversation lives in process memory and is dropped with the
  DEK, like the working set (§5.5).
- **One worker still holds.** The model wait runs in a pool thread; at most
  `AI_MAX_CONCURRENT_CALLS` are in flight and others wait
  `AI_QUEUE_WAIT_SECONDS` for a place. `scripts/ai_load.py` measures what
  questions do to the rest of the app.
- **Nothing is logged** but counts, the skill and `elapsed_ms` - never a
  question or a reply.
