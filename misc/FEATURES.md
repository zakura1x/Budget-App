# BUDGET APP — Feature Catalogue

> The decision document. [ARCHITECTURE.md](ARCHITECTURE.md) describes how the
> system is built; this describes **what it does**, feature by feature, with a
> scope decision against each one.
>
> **How to use this file:** change a `Status` cell, then read §14 — it maps each
> decision onto the part of the architecture that has to move. Feature IDs are
> stable; quote them (`TXN-04`, `BUD-07`) when asking for a change.

**Source app**: [Budget App — Spending Tracker](https://apps.apple.com/us/app/budget-app-spending-tracker/id1525179720) (iOS, id1525179720)

---

## Status legend

| Status | Meaning |
|---|---|
| ✅ **v1** | In scope. Built in the phase named. |
| 🟡 **Deferred** | Wanted, but not in v1. Architecture leaves room for it. |
| ❌ **Out** | Deliberately not built. Reason given. |
| ❓ **Decide** | Needs your call before the phase starts. **None open — every decision is settled in §13.** |

## Summary

| Group | Prefix | ✅ v1 | 🟡 Deferred | ❌ Out | ❓ Decide | Total |
|---|---|---|---|---|---|---|
| 1. Security & Access | `SEC` | 28 | 1 | 0 | 0 | 29 |
| 2. Accounts | `ACC` | 15 | 0 | 3 | 0 | 18 |
| 3. Categories | `CAT` | 8 | 0 | 0 | 0 | 8 |
| 4. Transactions | `TXN` | 19 | 0 | 2 | 0 | 21 |
| 5. Budgets & Allowance | `BUD` | 15 | 0 | 1 | 0 | 16 |
| 6. Calendar | `CAL` | 5 | 1 | 0 | 0 | 6 |
| 7. Stats & Reports | `STA` | 10 | 1 | 0 | 0 | 11 |
| 8. Recurring & Installments | `REC` | 17 | 0 | 1 | 0 | 18 |
| 9. Subscriptions | `SUB` | 8 | 1 | 0 | 0 | 9 |
| 10. Savings Goals | `GOA` | 6 | 1 | 0 | 0 | 7 |
| 11. Data In/Out | `DAT` | 16 | 2 | 2 | 0 | 20 |
| 12. Settings & UX | `UX` | 14 | 3 | 3 | 0 | 20 |
| **Total** | | **161** | **10** | **12** | **0** | **183** |

**All decisions are closed** — §13 records what was chosen and why. Four new
second-order questions came out of those choices; each has a working default
built into the docs, listed at the end of §13.

> **On the iOS app's paywall:** every feature that app charges for — unlimited
> categories, unlimited accounts, full stats, widgets — is simply included here.
> There is no monetisation, so there is no free tier to design around. Where a
> feature is missing below it is because it is genuinely hard or genuinely
> unwanted, never because it was premium.

---

## 1. Security & Access

Not in the iOS app in this form — this group exists because the data lives on a
shared company database. See ARCHITECTURE.md §5.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| SEC-01 | Email + password login | ✅ v1 | 2 | bcrypt cost 12, 12-char minimum |
| SEC-02 | Registration is never open | ✅ v1 | 2 | Gated by a code you set in `.env` (SEC-19). Open signup on a shared company host is a bad idea whether you have one user or five |
| SEC-03 | Account lockout after failed attempts | ✅ v1 | 2 | 5 attempts → 15 min |
| SEC-04 | JWT access token in HttpOnly cookie | ✅ v1 | 2 | 30 min, `SameSite=Lax` |
| SEC-05 | Refresh token rotation | ✅ v1 | 2 | New token each refresh, old invalidated |
| SEC-06 | Token reuse detection → family revocation | ✅ v1 | 2 | Replayed token ends every session |
| SEC-07 | 6-digit PIN lock | ✅ v1 | 2 | The Face ID equivalent. Guards the **session**, never the data |
| SEC-08 | Auto-lock on idle | ✅ v1 | 2 | 5 min; drops the DEK *and* the cache |
| SEC-09 | Full-row encryption of all financial data | ✅ v1 | 1 | AES-256-GCM. The defining constraint of the whole system |
| SEC-10 | Per-user DEK, envelope-wrapped | ✅ v1 | 1 | Makes rotation affordable |
| SEC-11 | Key rotation script | ✅ v1 | 9 | Resumable, dry-run first |
| SEC-12 | Biometric unlock (WebAuthn / Face ID) | 🟡 Deferred | 9 | `BIOMETRIC_WEBAUTHN_ENABLED=False`. Works on iOS Safari as a passkey; adds a dependency and a fallback path |
| SEC-13 | Backup UI in Settings | ✅ v1 | 8a | **Promoted from deferred.** The full backup (DAT-06) needs a button, not just a script — a backup you have to open a terminal for is one you will not take |
| SEC-14 | **12-word recovery phrase** | ✅ v1 | 1 | **DECIDED.** BIP-39 mnemonic wraps a second copy of your DEK, so losing `.env` is survivable. Shown once at registration. See ARCHITECTURE.md §5.5 |
| SEC-15 | Recovery flow — phrase restores access *and* resets the password | ✅ v1 | 2 | Without the reset, you would hold the key but have no way to log in |
| SEC-16 | Re-view the recovery phrase in Settings | ✅ v1 | 8b | Behind a password re-prompt. See §13-A — flag if you would rather it be shown once, ever |
| SEC-17 | **Multiple independent user accounts** | ✅ v1 | 2 | **DECIDED.** Each user gets their own data and their own DEK. Already the shape of the schema — every table is user-scoped from day one. See §16 |
| SEC-18 | **No admin can read another user's data** | ✅ v1 | 2 | Structural, not a policy. There is no key that opens everything, so there is no super-user who could read your rows. An admin can create and disable accounts; they can never decrypt one |
| SEC-19 | **Registration requires a code you control** | ✅ v1 | 2 | **DECIDED.** `REGISTRATION_CODE` in `.env`. No code, no account. Change it any time to invalidate every outstanding invitation at once — it is reusable until you change it |
| SEC-20 | Per-user recovery phrase | ✅ v1 | 2 | Each user gets their own. Yours cannot recover anyone else's account |
| SEC-21 | **Account deletion is a full cascade** | ✅ v1 | 8b | Deleting a user destroys their rows, attachments, DEK and both wrapped copies. Irreversible, audited, and requires typing the account name — there is no undo and no backup on our side |
| SEC-22 | **Regenerate the recovery phrase** | ✅ v1 | 8b | New 12 words, DEK re-wrapped, **old phrase stops working instantly**. Fast — one row update, no data re-encrypted. Gated behind a password re-prompt. See §17 for what this does and does not fix |
| SEC-23 | **Full DEK rotation** — the real revoke | ✅ v1 | 9 | Generates a *new* DEK and re-encrypts every row under it. The only thing that actually revokes access if your key may already have been used. Slow, and correspondingly rare. See §17 |
| SEC-24 | Rotating either one ends other sessions | ✅ v1 | 8b | Revokes every refresh-token family but the current one. If you are rotating because of a compromise, leaving other sessions alive defeats the point |
| SEC-25 | Registration attempts are rate-limited hard | ✅ v1 | 2 | The code is the *only* gate on signup, so it must not be brute-forceable. 5 attempts per hour per IP, constant-time comparison, every failure audited |
| SEC-26 | `MAX_USERS` cap enforced at registration | ✅ v1 | 2 | A second backstop if the code ever leaks — a leaked code cannot create unlimited accounts |
| SEC-27 | A server restart looks like an auto-lock | ✅ v1 | 2 | IIS stops the app after 20 idle minutes and restarts it on deploy, emptying the in-memory keys. The next request shows the PIN screen instead of an error, then unlocks and re-warms. Nobody is logged out |
| SEC-28 | Session cookies scoped to `/ZBDGT` | ✅ v1 | 2 | `Path=/ZBDGT`, named `zbdgt_*`. The host is shared with QUOT and other apps: an unscoped cookie would be sent to all of them, and a common name could overwrite QUOT's |
| SEC-29 | Nothing decrypted is stored in the browser | ✅ v1 | 8b | No figures in `localStorage`, IndexedDB or the service-worker cache, and caches are cleared on lock and logout. Every app on the host can read that storage |

---

## 2. Accounts

> iOS app: *"Manage credit, debit, mutual funds, and stock accounts in one place"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| ACC-01 | Multiple accounts | ✅ v1 | 3 | Unlimited |
| ACC-02 | Account types: cash, debit, credit, savings | ✅ v1 | 3 | |
| ACC-03 | Opening balance | ✅ v1 | 3 | |
| ACC-04 | Running balance | ✅ v1 | 3 | Computed in Python — SQL cannot sum ciphertext |
| ACC-05 | Colour + icon per account | ✅ v1 | 3 | |
| ACC-06 | Archive (never hard-delete) | ✅ v1 | 3 | History depends on the account existing |
| ACC-07 | Per-account currency | ❌ Out | — | **DECIDED: single currency.** Removed entirely — no currency field on accounts or transactions |
| ACC-08 | Investment accounts (stocks, mutual funds) | ✅ v1 | 3 | **DECIDED: a value you type.** No holdings, no units, no price feed |
| ACC-09 | **Credit card statement cycle & due date** | ✅ v1 | 3 | **Pulled into v1.** Statement closing day + payment due day per credit account. Derives the current statement period and its balance |
| ACC-10 | Bank / open-banking sync | ❌ Out | — | Permanently. Manual entry only — a bank aggregator on a company server is not a defensible idea |
| ACC-11 | Multi-currency conversion | ❌ Out | — | **DECIDED: PHP only.** No FX source, no rate history, no conversion. Removes the ambiguity that was flagged in ARCHITECTURE.md §12 |
| ACC-12 | Investment revaluation is **not** income | ✅ v1 | 3 | Updating a stock account ₱100k → ₱105k records a valuation change, excluded from income and spending stats. Otherwise market noise pollutes your spending reports |
| ACC-13 | Dated valuation history on investment accounts | ✅ v1 | 3 | Each value you type is appended with its date, not overwritten, and shown on the investment account itself. Investments do not count in cash on hand (ACC-18), so this history feeds no total |
| ACC-14 | Credit limit & available credit | ✅ v1 | 3 | `available = limit − current balance − unpaid installment remainder`. The bank blocks the whole installment amount, so leaving it out would overstate what you can spend (REC-14) |
| ACC-15 | Payment-due alert | ✅ v1 | 5 | In-app, `CREDIT_DUE_ALERT_DAYS` ahead (default 5). Same in-session model as the budget alerts — no push (BUD-16) |
| ACC-16 | Statement period ≠ budget period | ✅ v1 | 3 | A card closing on the 20th has nothing to do with a budget starting on the 1st. Two independent cycles; sharing `date_utils` but never the same dates |
| ACC-17 | **Cash on hand** — the one total | ✅ v1 | 3 | **DECIDED.** *"What is in my pockets."* The sum of every account that counts (ACC-18). **Deliberately not net worth:** nothing you own (a motorcycle, a phone) and nothing you will owe later (unpaid installments) is part of it |
| ACC-18 | "Count in cash on hand" switch per account | ✅ v1 | 3 | Defaults: cash, debit, savings **on** · credit card **on** — what you have already spent on it is subtracted · investment **off**. Change any of them in the account's settings |

---

## 3. Categories

> iOS app: *"Set budget for categories & sub-categories"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| CAT-01 | Unlimited categories | ✅ v1 | 3 | Premium in the iOS app; free here |
| CAT-02 | Sub-categories (one level) | ✅ v1 | 3 | Deeper nesting adds UI cost for little gain |
| CAT-03 | Expense vs income categories | ✅ v1 | 3 | |
| CAT-04 | Icon picker | ✅ v1 | 3 | |
| CAT-05 | Colour per category | ✅ v1 | 3 | Same colour everywhere — ledger, pie, budget bars |
| CAT-06 | Custom sort order, drag to reorder | ✅ v1 | 3 | Long-press to lift; touch-friendly |
| CAT-07 | Sensible default category set | ✅ v1 | 3 | `seed_categories.py` |
| CAT-08 | Safe delete — reassign, never orphan | ✅ v1 | 3 | No FK can protect this; the service must |

---

## 4. Transactions

The core of the app. TXN-01 is the feature everything else exists to support.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| TXN-01 | **Quick add: two taps and a number** | ✅ v1 | 4 | Bottom sheet, custom numpad, amount pre-focused. The single most important interaction |
| TXN-02 | Expense entries | ✅ v1 | 4 | |
| TXN-03 | Income entries | ✅ v1 | 4 | |
| TXN-04 | Transfers between accounts | ✅ v1 | 4 | Linked pair; must never count as spending |
| TXN-05 | Category + sub-category assignment | ✅ v1 | 4 | Chips, most-used first |
| TXN-06 | Account assignment | ✅ v1 | 4 | |
| TXN-07 | Date (defaults to today) | ✅ v1 | 4 | |
| TXN-08 | Merchant / payee | ✅ v1 | 4 | Encrypted |
| TXN-09 | Free-text notes | ✅ v1 | 4 | Encrypted |
| TXN-10 | Tags | ✅ v1 | 4 | Stored as ids inside the transaction payload |
| TXN-11 | Ledger grouped by day, with subtotals | ✅ v1 | 4 | Sticky date headers |
| TXN-12 | Search across merchant and notes | ✅ v1 | 4 | Substring, in memory — encrypted fields can't be searched in SQL |
| TXN-13 | Filter by category, account, date, type | ✅ v1 | 4 | All in Python over the warm cache |
| TXN-14 | Edit and soft-delete | ✅ v1 | 4 | Soft only, so the audit trail stays honest |
| TXN-15 | Receipt photo attachment | ✅ v1 | 8a | File itself AES-GCM encrypted on disk |
| TXN-16 | **Split across categories** | ✅ v1 | 4 | **DECIDED.** One ₱3,500 supermarket run → ₱2,800 groceries + ₱700 household. **Every** transaction carries a `splits` array; a simple one is a single-element split, so stats has exactly one code path. See ARCHITECTURE.md §4.2 |
| TXN-17 | **Repeat last entry** | ✅ v1 | 4 | **Pulled into v1.** One tap duplicates your most recent transaction, date defaulted to today. Cheap, and it is the second-most-used action after TXN-01 |
| TXN-18 | **Receipt scanning / OCR** | ❌ Out | — | The iOS app does this with on-device AI. Server-side OCR means an image leaving the encryption boundary. See §13 |
| TXN-19 | Voice entry | ❌ Out | — | Same objection as TXN-18, plus a speech service dependency |
| TXN-20 | Split validation — total must equal the sum of parts | ✅ v1 | 4 | Decimal-exact, enforced in the service. A ₱0.01 drift here silently corrupts every report |
| TXN-21 | Per-split note | ✅ v1 | 4 | |

---

## 5. Budgets & Daily Allowance

> iOS app: *"Set budget for categories & sub-categories on a weekly, monthly, or custom basis"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| BUD-01 | Weekly budget period | ✅ v1 | 5 | |
| BUD-02 | Monthly budget period | ✅ v1 | 5 | Default |
| BUD-03 | Custom period length | ✅ v1 | 5 | |
| BUD-04 | Custom month start day | ✅ v1 | 5 | Payday budgeting — e.g. the 25th |
| BUD-05 | Custom week start day | ✅ v1 | 5 | |
| BUD-06 | **Daily allowance** | ✅ v1 | 5 | *"You can spend ₱612 today."* The number the app exists for |
| BUD-07 | Allowance mode: remaining ÷ days left | ✅ v1 | 5 | Default. Self-correcting after an overspend |
| BUD-08 | Allowance mode: fixed daily | ✅ v1 | 5 | `DAILY_ALLOWANCE_MODE` |
| BUD-09 | Per-category budget allocations | ✅ v1 | 5 | |
| BUD-10 | Over-budget detection + colour states | ✅ v1 | 5 | Green → amber → red |
| BUD-11 | Carry over unspent to next period | ✅ v1 | 5 | **Now a Settings toggle, default OFF** — so you no longer have to decide up front. Symmetric when on: a surplus rolls forward, and so does an overspend. §13-B explains it with numbers |
| BUD-12 | **In-app over-budget alerts** | ✅ v1 | 5 | **DECIDED: in-app only.** Banner on Home, badge on the tab bar, red on the offending category |
| BUD-13 | **Copy last period's budget** | ✅ v1 | 5 | **Pulled into v1.** Start a new period from the previous one's allocations instead of retyping every category. You will want this by month two |
| BUD-14 | Approaching-budget warning | ✅ v1 | 5 | Fires at `ALERT_WARN_THRESHOLD_PCT` (default 80%) of the period budget |
| BUD-15 | **Pace alert** — spending faster than the period is elapsing | ✅ v1 | 5 | Day 10 of 30 with 60% spent. More useful than a fixed threshold, because it warns you while there is still time to act |
| BUD-16 | Web push notifications | ❌ Out | — | **DECIDED: no push.** It would need a background sender that decrypts to know your budget state — a service holding keys outside a user session, weakening ARCHITECTURE.md §5.5. Every alert above is computed inside your own session instead |

---

## 6. Calendar

> iOS app: *"Budget Calendar – Visualize your day-to-day spending on a calendar view"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| CAL-01 | Month grid with spending heatmap | ✅ v1 | 6 | Intensity buckets by daily total |
| CAL-02 | Swipe between months | ✅ v1 | 6 | |
| CAL-03 | Tap a day → that day's transactions | ✅ v1 | 6 | Bottom sheet |
| CAL-04 | Daily totals on each cell | ✅ v1 | 6 | |
| CAL-05 | Month total in the header | ✅ v1 | 6 | |
| CAL-06 | Week and year calendar views | 🟡 Deferred | — | Month view covers the actual use |

---

## 7. Stats & Reports

> iOS app: *"Stats & Charts – Understand your spending patterns with insightful visuals"*

Every figure here is Python over the decrypted working set. SQL computes none of
it — see ARCHITECTURE.md §4.3.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| STA-01 | Category breakdown (donut) | ✅ v1 | 6 | |
| STA-02 | Drill into sub-categories | ✅ v1 | 6 | Tap a slice |
| STA-03 | Spending trend over time (line) | ✅ v1 | 6 | |
| STA-04 | Month-over-month comparison | ✅ v1 | 6 | |
| STA-05 | Income vs expense | ✅ v1 | 6 | |
| STA-06 | Top merchants | ✅ v1 | 6 | |
| STA-07 | Average daily spend | ✅ v1 | 6 | |
| STA-08 | Per-account breakdown | ✅ v1 | 6 | |
| STA-09 | Custom date range on every chart | ✅ v1 | 6 | |
| STA-10 | Cash on hand over time | 🟡 Deferred | — | Renamed from "net worth over time". Now simple: the running balance of the counted accounts, built from transactions already stored, with no typed valuations involved |
| STA-11 | **Forecast / projected period-end** | ✅ v1 | 6 | **Pulled into v1.** "At this rate you finish the month at ₱43,200." Runs off the same trend data as STA-03, so it is a calculation and a chart line, not new plumbing |

---

## 8. Recurring Transactions & Installments

> iOS app: *"Set recurring transactions on a daily, weekly, monthly, or custom basis"*

REC-08 to REC-18 add **installment plans** — something bought on terms and paid
monthly, like a motorcycle at ₱5,000 × 36. An installment is a recurring rule
that also knows the total, so it can tell you what is left and when you finish.
How it affects cash on hand is explained in §19.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| REC-01 | Daily / weekly / monthly / yearly rules | ✅ v1 | 7 | |
| REC-02 | Custom interval (every N periods) | ✅ v1 | 7 | |
| REC-03 | Rule = template transaction + schedule | ✅ v1 | 7 | |
| REC-04 | Auto-expansion on the due date | ✅ v1 | 7 | Reduces the daily allowance the day it charges |
| REC-05 | Catch-up for missed days | ✅ v1 | 7 | Runs at login; **must be idempotent** — double-charging is the obvious bug |
| REC-06 | End conditions: never / after N / until date | ✅ v1 | 7 | |
| REC-07 | Pause and resume | ✅ v1 | 7 | |
| REC-08 | **Installment plans** | ✅ v1 | 7 | **DECIDED.** A motorcycle at ₱5,000 × 36 months. An installment is a recurring rule with `kind = installment` — same one-engine rule as subscriptions (SUB-00), never a second system |
| REC-09 | Installment details: total, number of payments, amount, start | ✅ v1 | 7 | ₱180,000 · 36 · ₱5,000 · Sept 2026. Stored in the rule's encrypted payload — no new table |
| REC-10 | **Remaining balance, payments left, payoff date** | ✅ v1 | 7 | *"₱125,000 left · 11 of 36 paid · done Aug 2029."* **Derived from the payments actually posted**, never stored as its own counter — same reason as GOA-07: a stored number drifts |
| REC-11 | Each payment counts as spending | ✅ v1 | 7 | ₱5,000 hits your budget and daily allowance on the due date, like any expense |
| REC-12 | **Never posts the full price up front** | ✅ v1 | 7 | Your account balances drop ₱5,000 a month, never ₱180,000 on day one. This is the *cash view* — see §19 |
| REC-13 | Early payoff | ✅ v1 | 7 | Pay the remaining balance in one go; the plan closes and generates nothing further |
| REC-14 | **Credit-card installments** ("0% for 36 months") | ✅ v1 | 7 | The monthly amount posts to the card each month, not the full price. But **available credit** still subtracts the whole unpaid remainder, because the bank blocks it (ACC-14) |
| REC-15 | Skip a payment | ✅ v1 | 7 | Balance unchanged, payoff date moves one period later. You still owe it — skipping must never make debt disappear |
| REC-16 | Final payment absorbs rounding | ✅ v1 | 7 | ₱100,000 ÷ 36 is ₱2,777.77…; the last payment is adjusted so the total is exact to the centavo |
| REC-17 | Total still owed across all plans | ✅ v1 | 7 | One figure on the Installments screen: everything you have committed to but not yet paid |
| REC-18 | Asset-and-debt net-worth view | ❌ Out | — | **DECIDED: cash view only.** Nothing you own is part of any total. The motorcycle never exists in the app as an asset — only its payments do. See §19 |

---

## 9. Subscriptions

> iOS app: subscription manager to identify and track recurring service charges

**To be unambiguous: this is about *your* recurring merchant charges** — Netflix,
Spotify, gym membership, iCloud. The "where is my money quietly leaking"
feature. It has nothing to do with paid tiers or billing for this app; there are
none, and there is nothing to monetise.

### How this relates to Recurring (§8) — one engine, not two

A subscription **is** a recurring rule with extra metadata. It is not a parallel
system:

```
recurring_rules            <- THE ENGINE. Schedule + template + expansion.
  ├── kind = standard       an ordinary recurring transaction
  │                         (rent, salary, utilities)
  ├── kind = subscription   ALSO carries: service name, billing cycle,
  │                         reminder lead days, cancellation URL,
  │                         price-change history
  └── kind = installment    ALSO carries: total, number of payments,
                            per-payment amount (REC-08..17)
```

**Only `recurring_service` ever creates transactions.** The Subscriptions screen
is a filtered view over the same rules, plus its own extra fields.

This matters: two systems both expanding Netflix into a transaction would
**charge you twice**, and you would not notice until a month-end total looked
wrong. One engine makes that bug impossible rather than merely unlikely.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| SUB-00 | A subscription is a flagged recurring rule | ✅ v1 | 7 | **One expansion path.** Never a second system that also writes transactions |
| SUB-01 | Track subscriptions: merchant, amount, cycle | ✅ v1 | 7 | |
| SUB-02 | Next charge date | ✅ v1 | 7 | |
| SUB-03 | Auto-detect repeating merchant+amount | ✅ v1 | 7 | Scans past transactions and *proposes* a rule. One-tap confirm creates a flagged recurring rule — it never silently starts charging you |
| SUB-04 | Upcoming charges timeline | ✅ v1 | 7 | |
| SUB-05 | Monthly subscription total | ✅ v1 | 7 | And its share of the budget |
| SUB-06 | Reminder lead days | ✅ v1 | 7 | Shown in-app on next open — no push (BUD-16) |
| SUB-07 | Cancellation tracking | 🟡 Deferred | — | |
| SUB-08 | Price-change history | ✅ v1 | 7 | Streaming services raise prices quietly. Recording the old amount when you edit it is nearly free, and it is the thing you actually want to see |

---

## 10. Savings Goals

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| GOA-01 | Named goal with target amount | ✅ v1 | 8b | |
| GOA-02 | Progress tracking | ✅ v1 | 8b | |
| GOA-03 | Target date | ✅ v1 | 8b | |
| GOA-04 | Link to an account | ✅ v1 | 8b | |
| GOA-05 | Required-per-month calculation | 🟡 Deferred | — | |
| GOA-06 | **Contributions are real transfers** | ✅ v1 | 8b | **DECIDED: goals are in.** Putting ₱5,000 toward a goal writes an actual transfer into the linked account, so goal progress and account balance can never disagree. See §13-C |
| GOA-07 | Goal progress never contradicts the account | ✅ v1 | 8b | Progress is *derived* from the linked account's transfers, not stored as its own number |

---

## 11. Data In / Out

> iOS app: *"Export & Import – Export your data as CSV or import from other CSV files"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| DAT-01 | CSV export | ✅ v1 | 8a | Streamed, never staged on disk |
| DAT-02 | **Plaintext warning on export** | ✅ v1 | 8a | The one place data leaves the encryption boundary on purpose. Warn every time |
| DAT-03 | CSV import with column mapping | ✅ v1 | 8a | |
| DAT-04 | Import dry-run preview | ✅ v1 | 8a | |
| DAT-05 | Duplicate detection on import | ✅ v1 | 8a | |
| DAT-06 | **Encrypted full backup** (`.budgetbak`) | ✅ v1 | 8a | **Every table, not just transactions.** Still ciphertext, so it is safe on a USB stick or in cloud storage. The real "the database is not my only copy" answer |
| DAT-07 | Restore from backup | ✅ v1 | 8a | **Rehearse this.** An untested backup is not a backup |
| DAT-08 | **Automatic backup, triggered by use** | ✅ v1 | 8a | 5 minutes after your last change, plus at login if the newest backup is over 24 hours old. **Not on a clock:** IIS stops the app after 20 idle minutes, so a 02:00 schedule would rarely fire. Data only changes while the app is in use, so this misses nothing. See §15 |
| DAT-09 | PDF / Excel export | 🟡 Deferred | — | CSV covers the need |
| DAT-10 | Cloud sync across devices | ❌ Out | — | The company DB *is* the sync point — every device hits the same server. Nothing to build |
| DAT-11 | **Splits round-trip through CSV** | ✅ v1 | 8a | One row per split, sharing a `txn_id` plus a `split_index`, so an export re-imports identically. See §13-D |
| DAT-12 | Full-fidelity export — *every* entity | ✅ v1 | 8a | Accounts, categories, budgets, allocations, transactions, splits, recurring, subscriptions, goals, tags, preferences, attachments. CSV alone covered only transactions, which would have restored your ledger into an empty shell |
| DAT-13 | **ID remapping on import** | ✅ v1 | 8a | The hard part. AAD binds ciphertext to its row `id` (ARCHITECTURE.md §5.3), so a restore that changes identity values would break every payload. See §15 |
| DAT-14 | Round-trip fidelity test | ✅ v1 | 8a | export → wipe → import → export again, and the two must match semantically. This is the test that *proves* portability |
| DAT-15 | Import modes: fresh / merge / verify | ✅ v1 | 8a | `verify` restores into a scratch schema and diffs, without touching live data |
| DAT-16 | Backup restorable with the **recovery phrase alone** | ✅ v1 | 8a | The file carries both wrapped DEKs, so it is a genuinely standalone artifact — a new server, an empty database, and 12 words is enough |
| DAT-17 | Attachments included in the backup | ✅ v1 | 8a | Receipt images, still encrypted. A backup missing them is not a full backup |
| DAT-18 | Plaintext full archive (JSON + all CSVs) | ❌ Out | — | **DECIDED: not built.** You chose encrypted-only for backups. Per-transaction CSV export (DAT-01) remains for Excel and for moving to another app — so the encryption boundary keeps exactly one deliberate, warned opening rather than two |
| DAT-19 | Attachments stored per-user | ✅ v1 | 8a | `uploads/<user_id>/<id>.enc`. The single-user layout would have let two users' receipts collide |
| DAT-20 | Nightly server backup via Windows Task Scheduler | 🟡 Deferred | 9 | Optional, for a copy that does not depend on anyone using the app. Possible because writing a backup needs no key. Someone with admin rights on the server has to create the task |

---

## 12. Settings & Mobile Experience

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| UX-01 | **Mobile-first, 390 px baseline** | ✅ v1 | 1 | Desktop is a widened phone layout, never a separate design |
| UX-02 | Bottom tab bar, `[+]` centre and raised | ✅ v1 | 1 | Home · Calendar · [+] · Stats · More |
| UX-03 | Custom numpad, no OS keyboard | ✅ v1 | 4 | |
| UX-04 | Bottom sheets throughout | ✅ v1 | 1 | |
| UX-05 | Light / dark / system theme | ✅ v1 | 8b | |
| UX-06 | Soft calm palette, matching the source app | ✅ v1 | 1 | |
| UX-07 | Safe-area insets (notch, home indicator) | ✅ v1 | 1 | |
| UX-08 | 44 px minimum touch targets | ✅ v1 | 1 | |
| UX-09 | Installable PWA, standalone, own icon | ✅ v1 | 8b | Add to Home Screen |
| UX-10 | Offline shell — **the app only, never your figures** | ✅ v1 | 8b | **Changed.** Offline, the app opens and says it is offline, but shows no balances. Browser storage is shared by every app on `delca.noahapplication.com`, so figures kept there would outlive logout and be readable by other apps' scripts. See ARCHITECTURE.md §10.3 |
| UX-11 | Currency display — **PHP, fixed** | ✅ v1 | 8b | Single currency (ACC-11). No picker; `₱` and PHP grouping are formatting constants |
| UX-12 | "About your encryption" screen | ✅ v1 | 8b | What is protected, what is not, plain language |
| UX-13 | Offline writes with sync-on-reconnect | 🟡 Deferred | 9 | Genuinely hard — merging offline edits into an encrypted store |
| UX-14 | Haptics | 🟡 Deferred | — | Vibration API; weak on iOS Safari |
| UX-15 | Multi-language (iOS app has 11) | 🟡 Deferred | — | English only in v1 |
| UX-16 | Home-screen widgets | ❌ Out | — | Native iOS capability. A PWA cannot provide it |
| UX-17 | Siri Shortcuts one-tap entry | ❌ Out | — | Native. Nearest equivalent is a home-screen bookmark straight to the add sheet |
| UX-18 | **Shared budgets / collaboration** | ❌ Out | — | **Still out, and now precisely scoped.** Multiple *independent* users are in (SEC-17); two people sharing *one* budget is a different problem — Bob mathematically cannot read Alice's rows. §16 sketches exactly what it would take (~2–3 weeks, adds public-key crypto) if you ever want it |
| UX-19 | Over-budget banner + tab-bar badge | ✅ v1 | 5 | The visible half of BUD-12/14/15 |
| UX-20 | Admin screen — create / disable / delete accounts | ✅ v1 | 8b | Management only. Deliberately cannot show another user's financial data (SEC-18) |

---

## 13. Decisions — settled, and what they changed

All seven original questions are now closed.

| ID | Decision | What it changed |
|---|---|---|
| **GOA-06** | ✅ **Yes — savings goals** | Kept in Phase 8, and tightened: contributions are real transfers, so progress cannot drift from the account balance |
| **ACC-08** | ✅ **A value you type** | Investment accounts are a manually-updated number. No holdings table, no price feed, nothing leaves the encryption boundary |
| **ACC-11** | ✅ **PHP only** | Currency removed from accounts and transactions entirely. No FX source, no rate history. **Closes the ambiguity flagged in ARCHITECTURE.md §12** |
| **BUD-11** | ↔️ **Promoted to a Settings toggle** | You did not need to decide. It is now a per-user preference, default off. §13-B below explains what it does |
| **BUD-12** | ✅ **In-app alerts, no push** | Alerts are computed in your own session and rendered as a banner + badge. **Preserves §5.5** — no background service ever holds your keys |
| **SEC-14** | ✅ **Yes — 12-word recovery phrase** | New `dek_wrapped_recovery` column, a BIP-39 dependency, and a recovery flow. Added to Phase 1 (the wrap) and Phase 2 (the flow). **This was the right call to make now** — it cannot be retrofitted to rows already encrypted without your key |
| **TXN-16** | ✅ **Yes — split transactions** | Transaction payload gains a `splits` array. Locked in *before* Phase 4, so no migration. Ripples into stats, budgets, category delete, and CSV |

Two more settled in the second round:

| ID | Decision | What it changed |
|---|---|---|
| **DAT-06/12** | ✅ **Full encrypted backup, every entity** | CSV alone only round-tripped transactions — a "restore" would have rebuilt your ledger into an empty shell. Now every table, plus attachments, in one encrypted file. Pulled forward to Phase 8, and DAT-08 (automatic, triggered by use) promoted out of deferred |
| **SEC-17** | ✅ **Multiple independent users** | Nearly free — every table was already user-scoped with a per-user DEK. Config flag + registration policy. §16 covers what it costs |
| **DAT-18** | ❌ **No plaintext full archive** | You chose encrypted-only. Per-transaction CSV export (DAT-01) stays for Excel, so **the encryption boundary keeps exactly one deliberate opening instead of two.** Better posture than what I originally proposed |
| **REC-08** | ✅ **Installment plans, cash view** | A third kind of recurring rule, so it shares the one expansion engine. Payments reduce your balances ₱5,000 a month and never the full price at once. The remaining debt shows on the installment card, not in any total. §19 compares the two views |
| **ACC-17** | ✅ **Cash on hand, not net worth** | *"I only need what is in my pockets."* The headline number counts money in the accounts you choose (ACC-18) and nothing else — no assets, no future payments. The asset-and-debt view (REC-18) is out, and "net worth over time" became "cash on hand over time" (STA-10) |
| **UX-18** | ❌ **Still no shared budgets** | Two people on *one* budget is a different problem from two people with *separate* data. §16 sketches the ~2–3 week design if you ever want it |

---

### §13-B — What "carry over" actually means

The one you asked about. Concretely, with a ₱10,000 weekly budget:

| | Week 1 | Week 2 starts with |
|---|---|---|
| You spend ₱7,000 (₱3,000 left over) | | |
| **Carry-over OFF** *(default)* | ₱10,000 budget | **₱10,000** — the leftover ₱3,000 is forgotten |
| **Carry-over ON** | ₱10,000 budget | **₱13,000** — the ₱3,000 rolls forward |
| You spend ₱12,000 (₱2,000 over) | | |
| **Carry-over OFF** | ₱10,000 budget | **₱10,000** — a clean slate |
| **Carry-over ON** | ₱10,000 budget | **₱8,000** — the overspend follows you |

**OFF** means each period is a fresh start. Simple, forgiving, and it keeps the
daily allowance easy to reason about — but a good week earns you nothing, and a
bad one costs you nothing.

**ON** makes the budget behave like a running balance across the whole month.
More honest, and better if your real goal is a monthly total rather than a
weekly rhythm. The risk is a bad week compounding into a punishing next one.

It is **symmetric** when on — surpluses and overspends both carry. A
positive-only version would drift upward forever and stop meaning anything.

Default is **OFF**, and it is a toggle in Settings, so you can try both without
a code change. My suggestion: run OFF for the first month, and switch it on only
if you find yourself wanting the weeks to add up to a monthly figure.

---

### New questions raised by your decisions

Four second-order questions. **None of them blocks anything** — I have picked a
default for each and built it into the docs. Flag any you would rather flip.

| Ref | Question | What I assumed, and why |
|---|---|---|
| **§13-A** | Should the **recovery phrase be re-viewable** in Settings, or shown exactly once at registration? | **Re-viewable, behind a password re-prompt** (SEC-16). Once-only is marginally safer — a phrase that cannot be displayed cannot be shoulder-surfed from a live session — but for a personal app the far likelier disaster is *losing the paper*. If you would rather it be shown once and never again, say so |
| **§13-C** | When you put ₱5,000 toward a savings goal, is that a **real transfer** or just a number on the goal? | **A real transfer** into the linked account (GOA-06). If it were only a number, your goal could say ₱50,000 saved while the account holds ₱30,000 — the classic budgeting-app inconsistency. Cost: you must have a savings account to have a goal |
| **§13-D** | How do **splits survive a CSV export**? | **One row per split**, sharing a `txn_id` and carrying a `split_index` (DAT-11). Exports re-import identically. Trade-off: the row count no longer equals the transaction count, which can surprise you in Excel |
| **§13-E** | Does updating an **investment balance** count as income? | **No** (ACC-12). A stock account moving ₱100k → ₱105k is a valuation change, recorded on the account and excluded from income and spending stats. Otherwise market swings would pollute every spending report you own |

---

## 14. How a change here changes the architecture

The point of this file. If you move a Status, this is what moves with it.

**Adding a field to an existing entity** — cheap. The payload is JSON inside one
encrypted blob, so there is no `ALTER TABLE` and no migration. Update the
Pydantic payload schema, handle the field being absent on older rows, done.
*This is the one genuine upside of full-row encryption.*

**Adding a new entity** — a new Shape B table (`id`, `user_id`, `key_version`,
`payload`, `is_deleted`, timestamps), a repository, a service, endpoints, a
screen. Roughly 2–3 days each. GOA-* is exactly this shape.

**Anything needing search or aggregation** — remember that SQL can do neither.
It lands in `stats_service` as Python over the working set. Fine at personal
scale; §5.7 of ARCHITECTURE.md is the escape hatch if the dataset outgrows it.

**Anything sending data outside the process** — OCR (TXN-18), voice (TXN-19),
FX rates (ACC-11), price feeds (ACC-08), push payloads (BUD-16). Each one is a
hole in the encryption boundary. Your decisions closed every one of these: no FX
source, no price feed, no push sender. **The encryption boundary now has exactly
one deliberate opening — CSV export (DAT-02)** — and it warns you every time.

**Multiple independent users (SEC-17) — now in, and it was nearly free**,
because every table was user-scoped with a per-user DEK from Phase 1. **Shared
budgets (UX-18) remain out**, and the distinction matters: separate users is a
config flag; two people editing *one* budget needs public-key crypto so a shared
key can be wrapped to someone whose DEK you do not know. That is a redesign of
§5, not a feature. §16 has the sketch.

**Backup and restore (§15)** — the awkward part is not the encryption, it is
that AAD binds ciphertext to its row `id`, so a restore that renumbers rows
breaks every payload. Export and import therefore both re-encrypt, and the
importer has to remap every cross-reference buried inside the ciphertext. Any
new entity you add later must be added to that remapping table too, or it will
restore as a silent orphan.

**Push notifications (BUD-16) — now closed, and worth recording why.** A push
sender must know you are over budget *while you are not using the app*, which
means decrypting your data outside your session, which means a background
service holding your keys. That would undo the guarantee in §5.5. The in-app
alerts you chose (BUD-12/14/15) compute the same figures inside your own
session, where the key already legitimately is. Same information, no new
exposure — this was the better answer, not just the cheaper one.

**Recovery phrase (SEC-14) — the one change that adds an attack surface.** It
creates a *second* complete path to your data. `dek_wrapped_recovery` sits in
the same database as `dek_wrapped`, so a DBA now sees two wrapped keys instead
of one — both still useless without either your `.env` or your phrase. The real
change is physical: **the paper you write those 12 words on is now equivalent to
the master key.** Treat it that way. In exchange, the single largest risk in the
project — losing `.env` and everything with it — stops being fatal.

---

## 15. Full backup & restore — so the company DB is not your only copy

**Decided: encrypted-only.** The backup is ciphertext from end to end, which
means you can put it on a USB stick, in Google Drive, on a personal laptop —
anywhere — and it leaks nothing to whoever finds it. It never opens the
encryption boundary.

### What is in the file

```
budget-2026-09-08T1422.budgetbak        (a zip container)
├── manifest.json          PLAINTEXT — format version, app version,
│                          key_version, timestamp, row counts, checksums.
│                          Deliberately readable so a restore tool can
│                          validate the file before asking for your key.
├── keys.enc               your dek_wrapped AND dek_wrapped_recovery
├── accounts.enc
├── categories.enc
├── tags.enc
├── budgets.enc
├── budget_allocations.enc
├── transactions.enc       including every split
├── recurring_rules.enc
├── subscriptions.enc
├── savings_goals.enc
├── user_preferences.enc
└── attachments/
    └── <id>.enc           receipt images, still encrypted
```

Because `keys.enc` carries both wrapped DEKs, the file is **standalone**: a new
server, an empty database, and either your `.env` master key *or* your 12 words
is enough to get everything back (DAT-16).

### The problem that makes this non-trivial

AAD binds every ciphertext to its own row `id` (ARCHITECTURE.md §5.3) — that is
what stops a DBA swapping your ₱5 coffee over your ₱50,000 rent. But it means a
restore **cannot simply reload rows**: a fresh database assigns new identity
values, and a payload moved to a new `id` fails to authenticate.

So only the import re-encrypts:

```
EXPORT — no key needed               IMPORT — needs your key
──────────────────────               ───────────────────────
copy each row exactly as stored      unwrap your DEK (.env or 12 words)
  (ciphertext + its id,              rebuild each row's ORIGINAL AAD
   user_id, key_version)             decrypt → INSERT, get NEW id
                                     re-encrypt with AAD = NEW id
```

**Writing a backup decrypts nothing and needs no key.** That is what lets it run
automatically without anyone logged in.

### When backups happen

Never at a fixed time. IIS stops this app after 20 idle minutes, so a 02:00
schedule would only fire if someone happened to be using the app at 02:00.
Instead (DAT-08):

- **5 minutes after your last change.** IIS keeps the app alive for 20 minutes
  after a request, so this always fires first.
- **At login**, if the newest backup is over 24 hours old, as a safety net.
- **"Back up now"** in Settings, whenever you like.

Your data only changes while someone is using the app, so this misses nothing.

### ID remapping (DAT-13) — where the bugs will be

Every cross-reference lives *inside* ciphertext, so no foreign key can help. The
importer builds an `export_id → new_id` map per entity type and rewrites:

- `transactions.account_id`, `transactions.splits[].category_id`
- `transactions.tag_ids[]`, `recurring_id`, `attachment_id`
- `categories.parent_id` (parents must be inserted before children)
- `budget_allocations.budget_id` and `.category_id`
- `savings_goals.account_id`
- `recurring_rules` template: `.account_id`, `.splits[].category_id`, `.tag_ids[]`
- `subscriptions.recurring_rule_id`

> The last two were missing from the original list. Every recurring rule — rent,
> subscriptions, installments — would have restored still pointing at the old
> account and category ids, then quietly posted payments to the wrong place.

Insert order is therefore fixed: **accounts → categories (parents first) → tags
→ budgets → allocations → recurring → subscriptions → goals → transactions →
attachments.** Get it wrong and you get silent orphans that nothing will catch.

### Import modes (DAT-15)

| Mode | Does |
|---|---|
| `fresh` | Target must be empty for this user. Straight restore |
| `merge` | Adds to existing data, skipping duplicates by content hash |
| `verify` | Restores into a scratch schema and diffs. **Touches nothing live** |

`verify` is how you make backup-testing a habit rather than an act of courage.

### The test that proves it works (DAT-14)

> export → restore into an empty database → export again → **the two exports
> must be semantically identical.** Same entities, same values, same
> relationships. Row ids may differ; nothing else may.

Until that passes, you do not have portability, you have a file.

---

## 16. Multiple users

**Decided: separate users, no sharing.** Worth being clear about what that does
and does not give you.

### What you get, and why it was nearly free

Every table has been user-scoped since Phase 1 — `user_id` on every row, a
per-user DEK, blind-indexed login. Multi-user is not a feature bolted on; it is
the shape the schema already had. Enabling it is a config flag plus a
registration policy.

```
Alice                          Bob
  │                             │
Alice DEK                     Bob DEK
  │                             │
  ▼                             ▼
rows WHERE user_id = 1     rows WHERE user_id = 2
```

**Bob cannot read Alice's data — not by policy, by cryptography.** Their DEKs
are unrelated 32-byte keys. This has a consequence worth stating plainly:

> **There is no admin who can read your data (SEC-18).** An administrator can
> create, disable and delete accounts. They cannot decrypt one, because no key
> exists that opens everything — and adding one would undo the entire design.
> If you forget your password *and* lose your recovery phrase, nobody can help
> you. That is the correct behaviour here, not a gap.

### What it costs

| Concern | Effect |
|---|---|
| Working-set cache | Memory is now N users × their data. `CACHE_MAX_USERS` bounds it (default 8, LRU) |
| `--workers 1` | Still required — the cache is per-process. Fine for a handful of users; this design does not scale to hundreds, and does not need to |
| Key rotation | `rotate_keys.py` must iterate every user's DEK, not just yours |
| Backups | Per-user. Writing one needs no key, but restoring needs that user's key, so each file belongs to one user |

### What you did *not* get: shared budgets (UX-18)

Two people seeing **one** budget is a genuinely different problem, and it is
worth recording what it would take, in case you want it later.

The blocker: Alice cannot wrap a shared key *to* Bob, because she does not know
Bob's DEK — and should not. Symmetric keys alone cannot express "share with".
The fix is standard but structural:

```
give every user an X25519 keypair
  (private key encrypted under their own DEK)

Alice generates a Budget Encryption Key (BEK) for the shared budget
  ├── wraps BEK to Alice's public key  ─┐
  └── wraps BEK to Bob's public key    ─┴─► budget_key_grants table

rows in that budget encrypt under the BEK, not a personal DEK
  └── so each row needs a `key_scope` saying which key opens it
```

Roughly 2–3 weeks, and it changes §5 of the architecture rather than adding to
it. The ugliest part is **revocation**: removing Bob means rotating the BEK and
re-encrypting that budget's rows, because Bob has already seen the old key and
you cannot un-see a key.

Not built. Cleanly possible later.

---

## 17. Rotating keys after a compromise

You asked for the ability to refresh a recovery phrase you think is compromised.
That exists (SEC-22) — but it only solves half the problem, and the half it does
not solve is the one that matters if something has actually gone wrong. Both
capabilities are built; use the right one.

### The two operations

| | **SEC-22 — Regenerate phrase** | **SEC-23 — Rotate the DEK** |
|---|---|---|
| Changes | The recovery *wrap* only | **The data key itself** |
| Data re-encrypted | None | **Every row you own** |
| Speed | Instant — one row update | Seconds to a minute |
| Old phrase | Stops working immediately | Stops working immediately |
| **Anyone who already has your DEK** | **Still has it. Still reads everything.** | **Locked out** |
| Use when | The paper is lost, or you stored it somewhere you regret — but you do not believe anyone used it | You believe someone **used** the phrase, or otherwise obtained your key |

### Why the difference exists

The phrase does not protect your data. It **unwraps the key** that protects your
data. So if someone read your twelve words and used them, they now hold a copy
of your DEK — a 32-byte value they can keep forever. Changing the phrase after
that is like changing the lock while the intruder walks around with a copy of
the key already cut.

```
Regenerate phrase (SEC-22)          Rotate DEK (SEC-23)
──────────────────────────          ───────────────────
new words → new recovery key        NEW DEK generated
     ↓                                   ↓
re-wrap the SAME DEK                decrypt every row with old DEK
     ↓                              re-encrypt every row with new DEK
dek_wrapped_recovery updated             ↓
                                    re-wrap under master key AND
old phrase: dead                    a fresh phrase
old DEK:    UNCHANGED  ←── the gap        ↓
                                    old phrase: dead
                                    old DEK:    now useless
```

### How rotation works

Row `id`s do not change, so AAD stays valid — it is a straight
decrypt-with-old, encrypt-with-new for every row. At personal scale (~10k rows)
this runs in **a single database transaction**: it either completes or nothing
changed. No half-rotated state, no `dek_version` column, no resume logic.

Both operations require a password re-prompt, are audited, and end every other
session (SEC-24) — leaving a stolen session alive would defeat the purpose.

### What neither can undo

If someone already **exported and kept your data**, no key operation reaches it.

The same goes for **your own older backups.** A `.budgetbak` written before a
rotation still carries the old wrapped keys, so it still opens with the old
phrase. After rotating because of a compromise, take a fresh backup and delete
the older files.
Rotation stops future reads, not copies already taken. Worth knowing before you
rely on it, because "I rotated the key" can feel more complete than it is.

---

## 18. Feature parity with the source app

An honest scorecard against the iOS original.

| iOS app feature | Here |
|---|---|
| Budgets: weekly / monthly / custom, per category & sub-category | ✅ Full parity |
| Recurring transactions, daily → custom | ✅ Full parity |
| Budget calendar | ✅ Full parity |
| Stats & charts | ✅ Full parity, plus custom date ranges |
| Multiple accounts (credit, debit) | ✅ Full parity |
| Investment accounts (stocks, mutual funds) | ⚠️ Deliberately partial — a typed balance, not holdings (ACC-08) |
| Split a transaction across categories | ✅ Full parity |
| Subscription manager | ✅ Full parity, plus auto-detection |
| CSV export & import | ✅ Full parity |
| Cloud sync | ✅ Inherent — one server, every device |
| **Full encrypted backup + restore** | ✅ Beyond the source app (§15) |
| **Installment plans with payoff tracking** | ✅ Beyond the source app (§19) |
| Unlimited categories (premium there) | ✅ Free here |
| Receipt scanning (AI) | ❌ Out — image would leave the encryption boundary |
| Voice entry | ❌ Out — same reason |
| Widgets & Siri Shortcuts | ❌ Out — native-only capability |
| Shared budgeting / shared ledger | ❌ Out — needs public-key crypto (§16) |
| Multiple user accounts | ✅ Separate, private, per-user keys (SEC-17) |
| Multi-currency | ⚠️ Deliberately dropped — PHP only (ACC-11) |
| 11 languages | 🟡 English only in v1 |
| **Not in the iOS app** | |
| Full-row encryption on a shared database | ✅ The reason this project exists |
| Password + PIN + key rotation | ✅ |
| 12-word recovery phrase | ✅ (SEC-14) |
| Savings goals | ✅ |
| Pace alert — spending faster than time is passing | ✅ (BUD-15) |

**Summary:** near-total parity on everything that is budgeting. The gaps are all
either native-iOS capabilities a web app cannot have, or features that would
require your financial data to leave the encryption boundary — which is the one
thing this build exists to prevent.

---

## 19. Cash on hand — why it is not net worth

**Decided: cash view, for everything.** *"I don't want the things I have to be
part of my net worth. I only need what is in my pockets."*

So the app's headline number is **cash on hand**: the money in the accounts you
choose to count (ACC-17, ACC-18). It is deliberately not called net worth,
because net worth normally includes what you own, and yours does not.

| Counts | Does not count |
|---|---|
| Cash, debit and savings accounts | Things you own — a motorcycle, a phone, a laptop |
| What you have already spent on a credit card (subtracted) | The unpaid remainder of an installment (it is future money) |
| Any account you switch on (ACC-18) | Investment accounts, unless you switch them on |

### The motorcycle, in cash on hand

₱180,000, paid ₱5,000 × 36 months.

| | Day you buy | After 1 month | After 12 months | After 36 months |
|---|---|---|---|---|
| Change in cash on hand | ₱0 | −₱5,000 | −₱60,000 | −₱180,000 |
| Still owed — on the installment card, **not** in cash on hand | ₱180,000 | ₱175,000 | ₱120,000 | ₱0 |

Cash on hand goes down ₱5,000 a month, never ₱180,000 at once, and the
motorcycle never appears as something you own.

**The one thing to keep an eye on:** after month one, cash on hand says you are
₱5,000 lighter — but you have signed up for ₱175,000 more. That debt is real, so
it stays visible on the installment card (REC-10), and the Installments screen
totals everything you still owe (REC-17). It just is not inside the pocket number.

### What was not chosen, for the record

The **asset-and-debt view** would count the motorcycle as something you own and
the loan as something you owe:

| | Day you buy | After 1 month | After 12 months | After 36 months |
|---|---|---|---|---|
| Change in net worth | ₱0 | ₱0 | −₱30,000 | −₱70,000 |

There, buying and paying change nothing; only the motorcycle losing value does.
It answers *"what am I worth"* rather than *"what is in my pockets"*, and it
means guessing what your belongings are worth and keeping that guess updated. It
is out (REC-18).

### Two defaults worth knowing about

Both follow from "what is in my pockets", and both are a switch on the account
(ACC-18) if you see it differently:

- **Credit cards count, as money already gone.** Spend ₱3,000 on a card and cash
  on hand drops by ₱3,000 now, not when you pay the bill. The purchase has
  happened; leaving it out would show you ₱3,000 you do not really have. Future
  installment payments are different — they have not happened yet, so they stay
  out.
- **Investments do not count.** Stocks and mutual funds are not in your pocket,
  and their value is a number you type (ACC-08). Switch an investment account on
  if you want it included.
