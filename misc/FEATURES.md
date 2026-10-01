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
| 1. Security & Access | `SEC` | 27 | 0 | 5 | 0 | 32 |
| 2. Accounts | `ACC` | 28 | 0 | 3 | 0 | 31 |
| 3. Categories | `CAT` | 8 | 0 | 0 | 0 | 8 |
| 4. Transactions | `TXN` | 21 | 0 | 2 | 0 | 23 |
| 5. Budgets & Allowance | `BUD` | 16 | 0 | 1 | 0 | 17 |
| 6. Calendar | `CAL` | 7 | 0 | 0 | 0 | 7 |
| 7. Stats & Reports | `STA` | 12 | 0 | 0 | 0 | 12 |
| 8. Recurring, Installments & Projection | `REC` | 30 | 0 | 1 | 0 | 31 |
| 9. Subscriptions | `SUB` | 9 | 0 | 0 | 0 | 9 |
| 10. Savings Goals | `GOA` | 11 | 0 | 0 | 0 | 11 |
| 11. Data In/Out | `DAT` | 16 | 2 | 2 | 0 | 20 |
| 12. Settings & UX | `UX` | 15 | 2 | 3 | 0 | 20 |
| **Total** | | **200** | **4** | **17** | **0** | **220** |

The AI companion (2026-09-30) has its own list, `AI-01` to `AI-67`, in
[AI/FEATURES.md](AI/FEATURES.md); it is not counted above.

> **2026-09-14 — the recovery phrase is out.** SEC-14/15/16/20/22 moved to ❌
> Out and two features came in: password reset by email (SEC-30) and an
> offline copy of `.env` kept by the server owner (SEC-31). §13 records why.

> **2026-09-28 — what comes next is in [ROADMAP.md](ROADMAP.md).** Every 🟡
> Deferred row below, plus thirteen new features with reserved IDs (TXN-24/25,
> BUD-17, CAL-07, REC-35, GOA-09..12, ACC-41, STA-12, SEC-32), ordered into Phases
> 11–15. A new ID gets its row here the day it is built. **Phase 11 built the
> same day:** TXN-24, TXN-25, BUD-17, GOA-05, SUB-07, STA-10. **Phase 12 too:** CAL-06,
> CAL-07, REC-27, REC-35. **Phase 13 too:** GOA-09, GOA-10, GOA-11, GOA-12. **Phase 14:** ACC-41, STA-12,
> SEC-32, SEC-12. **Phase 15:** UX-14 only (the user's choice; the rest wait).

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
| SEC-11 | Key rotation script | ✅ v1 | 9 | **Built 2026-09-15.** `scripts/rotate_keys.py --status / --new-key / --rewrap`, each with `--dry-run`. Resumable, one commit per account; the old key is retired, never deleted, so older backups still open. Paired with `verify_integrity.py` and `env_fingerprint.py` (SEC-31) |
| SEC-12 | **Biometric unlock (WebAuthn / Face ID)** | ✅ v1 | 14 | **Built 2026-09-28.** A passkey - Face ID, a fingerprint, Windows Hello - unlocks the LOCK SCREEN of a session already signed in, instead of the PIN. It is the PIN's equal: it only decides, and the DEK comes back through the same `_reunlock`, unwrapped with the master key - never a second way to a key. **Hand-rolled on `cryptography`** (the user's choice: no WebAuthn library in the venv QUOT shares): attestation *none*, ES256 or RS256, a single-use 2-minute challenge in process memory, origin = `APP_PUBLIC_URL`, the user VERIFIED (not just present), and a counter that goes backwards is refused. Adding one asks for the password; up to 5; removed from *Signed-in devices*. Public keys only, on `users.passkeys`. Off until `BIOMETRIC_WEBAUTHN_ENABLED=True`. `auth_service/passkey_service.py` |
| SEC-13 | Backup UI in Settings | ✅ v1 | 8a | **Promoted from deferred.** The full backup (DAT-06) needs a button, not just a script — a backup you have to open a terminal for is one you will not take |
| SEC-14 | ~~12-word recovery phrase~~ | ❌ Out | — | **Removed 2026-09-14** (built in Phase 1). Replaced by an offline copy of `.env` kept by the server owner (SEC-31). The phrase asked every user to keep paper safe against a loss only the server side can cause. See §13 and ARCHITECTURE.md §5.2.1. Code and database columns removed the same day |
| SEC-15 | ~~Recovery flow — phrase restores access and resets the password~~ | ❌ Out | — | **Removed 2026-09-14** with SEC-14. A forgotten password is reset by an emailed link (SEC-30); a lost `.env` is restored from the offline copy (SEC-31) |
| SEC-16 | ~~Re-view the recovery phrase in Settings~~ | ❌ Out | — | **Removed 2026-09-14** with SEC-14. It was never built: the words were not stored, so there was nothing to show (§13-A) |
| SEC-17 | **Multiple independent user accounts** | ✅ v1 | 2 | **DECIDED.** Each user gets their own data and their own DEK. Already the shape of the schema — every table is user-scoped from day one. See §16 |
| SEC-18 | **No admin can read another user's data** | ✅ v1 | 2 | Structural, not a policy. There is no key that opens everything, so there is no super-user who could read your rows. An admin can create and disable accounts; they can never decrypt one. An admin cannot reset another user's password either: a reset link goes only to the account's own email (SEC-30). Outside the app, whoever holds `.env` and the database can read everything (ARCHITECTURE.md §5.1) |
| SEC-19 | **Registration requires a code you control** | ✅ v1 | 2 | **DECIDED.** `REGISTRATION_CODE` in `.env`. No code, no account. Change it any time to invalidate every outstanding invitation at once — it is reusable until you change it |
| SEC-20 | ~~Per-user recovery phrase~~ | ❌ Out | — | **Removed 2026-09-14** with SEC-14. Each user still has their own DEK (SEC-10) |
| SEC-21 | **Account deletion is a full cascade** | ✅ v1 | 8b | Deleting a user destroys their rows, attachments, DEK and its wrapped copy. Irreversible, audited, and requires typing the account name — there is no undo and no backup on our side |
| SEC-22 | ~~Regenerate the recovery phrase~~ | ❌ Out | — | **Removed 2026-09-14** with SEC-14. Built in 8b, removed the same day. DEK rotation (SEC-23) stays |
| SEC-23 | **Full DEK rotation** — the real revoke | ✅ v1 | 9 | Generates a *new* DEK, re-encrypts every row under it, and wraps it under the master key. The only thing that actually revokes access if your key may already have been unwrapped. Slow, and correspondingly rare. Built early, in 8b. See §17 |
| SEC-24 | Password change and DEK rotation end other sessions | ✅ v1 | 8b | Revokes every refresh-token family but the current one. If you are acting because of a compromise, leaving other sessions alive defeats the point. A password reset by email (SEC-30) ends all of them |
| SEC-25 | Registration attempts are rate-limited hard | ✅ v1 | 2 | The code is the *only* gate on signup, so it must not be brute-forceable. 5 attempts per hour per IP, constant-time comparison, every failure audited |
| SEC-26 | `MAX_USERS` cap enforced at registration | ✅ v1 | 2 | A second backstop if the code ever leaks — a leaked code cannot create unlimited accounts |
| SEC-27 | A server restart looks like an auto-lock | ✅ v1 | 2 | IIS stops the app after 20 idle minutes and restarts it on deploy, emptying the in-memory keys. The next request shows the PIN screen instead of an error, then unlocks and re-warms. Nobody is logged out |
| SEC-28 | Session cookies scoped to `/ZBDGT` | ✅ v1 | 2 | `Path=/ZBDGT`, named `zbdgt_*`. The host is shared with QUOT and other apps: an unscoped cookie would be sent to all of them, and a common name could overwrite QUOT's |
| SEC-29 | Nothing decrypted is stored in the browser | ✅ v1 | 8b | No figures in `localStorage`, IndexedDB or the service-worker cache, and caches are cleared on lock and logout. Every app on the host can read that storage |
| SEC-30 | **Password reset by email** | ✅ v1 | 9 | **Added and built 2026-09-14**, replacing the reset half of SEC-15 (chosen over an admin-issued code, so nobody types a code). "Forgot your password?" mails a one-time link to the address typed, if it has an account — the answer is identical either way. The token rides in the URL fragment (never reaches the server's logs), only its SHA-256 is stored, it works once for 30 minutes, a newer request replaces it, and the link's origin is `APP_PUBLIC_URL`, never the Host header. Using it signs in, ends every other session and touches no data. Sent through the SMTP settings in `.env`. Honest limit: whoever controls the mailbox controls the account |
| SEC-31 | **Offline copy of `.env`, kept by the server owner** | ✅ v1 | 9 | **Added 2026-09-14**, replacing SEC-14 as the answer to "what if `.env` is lost". The whole file, in at least two places, off the server and apart from the backup files; refreshed the same day any key changes; compared with the server through a non-secret fingerprint (`scripts/env_fingerprint.py`). Losing `.env` and every copy loses every account at once. Runbook: how-to-run.txt |
| SEC-32 | **Sign-in activity and open sessions** | ✅ v1 | 14 | **Built 2026-09-28.** Settings → *Signed-in devices*: every session live now - a coarse device label (*Chrome on Android*) parsed from the User-Agent at sign-in and never the raw string (`refresh_tokens.device_label`, migration `20260928_0004`; older sessions say *Unknown device*), when it signed in and was last used - each with *Sign out*, plus *Sign out everywhere else*; both revoke through session_service (`revoke_reason = user`), so the keyring entry goes too. And the last 30 days of sign-ins, unlocks and resets, right or wrong, from `login_attempts`: IPs are only ever stored hashed, so the most it says is *this network*. A session is named to the client by a handle, never its session id. Shape A tables only. `auth_service/activity_service.py`, `GET /auth/activity` |

---

## 2. Accounts

> iOS app: *"Manage credit, debit, mutual funds, and stock accounts in one place"*

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| ACC-01 | Multiple accounts | ✅ v1 | 3 | Unlimited |
| ACC-02 | Account types: cash, debit, credit, savings | ✅ v1 | 3 | Since 2026-09-15 also investment, **lent**, **borrowed** (ACC-31) and **member** (ACC-32), each picked from the Add Account list (ACC-33) |
| ACC-03 | Opening balance | ✅ v1 | 3 | Set when the account is created. Later corrections go through the balance edit (ACC-27, ACC-28) |
| ACC-04 | Running balance | ✅ v1 | 3 | Computed in Python — SQL cannot sum ciphertext |
| ACC-05 | Colour + icon per account | ✅ v1 | 3 | |
| ACC-06 | Archive (never hard-delete) | ✅ v1 | 3 | History depends on the account existing |
| ACC-07 | Per-account currency | ❌ Out | — | **DECIDED: single currency.** Removed entirely — no currency field on accounts or transactions |
| ACC-08 | Investment accounts (stocks, mutual funds) | ✅ v1 | 3 | **DECIDED: a value you type.** No holdings, no units, no price feed. **Money you MOVE in or out still counts (fixed 2026-09-16, user: a transfer into a fund was logged and the balance stood still).** The balance is the value last typed PLUS every transfer since that day: what the fund is worth is typed, but a contribution is real money, not market movement. Contributions on or before the day of a valuation are already inside the figure typed, so typing a new value resets the base and nothing is ever counted twice. The account page says which is which — *"₱100,000.00 last valued · ₱5,000.00 moved in since"* |
| ACC-09 | **Credit card statement cycle & due date** | ✅ v1 | 3 | **Pulled into v1.** Statement closing day + payment due day per credit account. Derives the current statement period and its balance |
| ACC-10 | Bank / open-banking sync | ❌ Out | — | Permanently. Manual entry only — a bank aggregator on a company server is not a defensible idea |
| ACC-11 | Multi-currency conversion | ❌ Out | — | **DECIDED: PHP only.** No FX source, no rate history, no conversion. Removes the ambiguity that was flagged in ARCHITECTURE.md §12 |
| ACC-12 | ~~Investment revaluation is **not** income~~ **An investment's value asks like any balance** | ✅ v1 | 3 → 10 | **Changed 2026-09-18** (user: "in investment accounts the system did not ask for the unrecorded gain/loss, I was just able to edit the value"). Editing an investment shows *Value today*; a new figure asks the ACC-28 question - record an **unrecorded gain or loss** (an adjustment, counted in Stats as its own row) or **fix the starting value** (moves the last typed valuation, or the opening value, and keeps no record). The separate *Record value* box is gone; valuations typed before stay the base (ACC-13), and an adjustment on a valuation's own day still counts. Was: a valuation change, excluded from stats |
| ACC-13 | Dated valuation history on investment accounts | ✅ v1 | 3 | Each value you type is appended with its date, not overwritten, and shown on the investment account itself. Investments do not count in cash on hand (ACC-18), so this history feeds no total |
| ACC-14 | Credit limit & available credit | ✅ v1 | 3 | `available = limit − current balance − unpaid installment remainder`. The bank blocks the whole installment amount, so leaving it out would overstate what you can spend (REC-14) **Shown as ‘Left to spend’ since 2026-09-16** on the card's tile, its page banner and its details card, with what the plans hold back said out loud |
| ACC-15 | Payment-due alert | ✅ v1 | 5 | In-app, `CREDIT_DUE_ALERT_DAYS` ahead (default 5). Same in-session model as the budget alerts — no push (BUD-16). Shown on Home. Built to clear only when the whole card is at zero; ACC-20 changes that to "this statement is paid" |
| ACC-16 | Statement period ≠ budget period | ✅ v1 | 3 | A card closing on the 20th has nothing to do with a budget starting on the 1st. Two independent cycles; sharing `date_utils` but never the same dates |
| ACC-17 | **Cash on hand** — the one total | ✅ v1 | 3 | **DECIDED.** *"What is in my pockets."* The sum of every account that counts (ACC-18). **Deliberately not net worth:** nothing you own (a motorcycle, a phone) and nothing you will owe later (unpaid installments) is part of it |
| ACC-18 | "Count in cash on hand" switch per account | ✅ v1 | 3 | Defaults: cash, debit, savings **on** · credit card **on** — what you have already spent on it is subtracted · investment **off** · lent and borrowed **off**, member card **on** (ACC-31/32). Change any of them in the account's settings |
| ACC-19 | **Statement amount due** | ✅ v1 | 5b | *"₱12,300 due Oct 6."* What the card owed at the moment the statement closed, the same figure a bank statement shows. Derived from postings, never stored. The app never calculates interest or fees; they come in through the statement check (ACC-24) |
| ACC-20 | **Bill reminder clears when that statement is paid** | ✅ v1 | 5b | Left to pay = statement amount − payments and refunds into the card since it closed, never below zero. Refunds count — decided 2026-09-14. A part payment shows *"₱7,300 left, due Oct 6"*. Paying in full clears the reminder even while new purchases build up on the next statement. See §21 |
| ACC-21 | **Your own spending limit per card** | ✅ v1 | 5b | **DECIDED: per statement cycle.** Optional, e.g. ₱10,000 from the 17th to the 16th, so what you spend against it is what next month's bill will be. Separate from the bank's credit limit (ACC-14). Counts purchases minus refunds, including recurring and installment charges; payments and balance adjustments never count |
| ACC-22 | Card-limit alerts: approaching, pace, over | ✅ v1 | 5b | The budget's rules on the card's cycle: `warn` at `ALERT_WARN_THRESHOLD_PCT` (80%), `warn` when spending runs ahead of the cycle, `danger` at 100%. Home banner, tab badge, colour on the card. Over replaces the other two. No push (BUD-16) |
| ACC-23 | "Left on this card" in the add sheet | ✅ v1 | 5b | Pick a card with a limit and the sheet shows *"₱1,200 left on BPI Card this cycle"*, updating as you type. It warns and never blocks the save |
| ACC-24 | **Check the statement against the bank** | ✅ v1 | 5b | When a statement closes, the card asks for the bank's total. **One number, not every line.** The app shows its own figure beside it and the difference. A match is marked ✅ Checked. The bank's figure is kept on the card per statement; the difference is recalculated every time, never stored. See §21 |
| ACC-25 | **Explain a difference** | ✅ v1 | 5b | Choices: **a one-time fee or interest** (posts to Financial › Bank fees or Interest on the closing date) · **a purchase I forgot** (add sheet, amount filled in) · **posted on the next statement** (ACC-26) · **leave it** (stays visible on the card). One difference can be split across several choices. Installment interest joins the list in Phase 7 (REC-29). The app suggests and never decides, and a *lower* bank total is never offered as interest |
| ACC-26 | Purchases the bank posts late | ✅ v1 | 5b | Purchases in the card's **posting delay** before closing are marked *"may be on next statement"*. **Per card since 2026-09-14:** set when the card is added (a new card starts at 3 days, `CARD_POSTING_LAG_DAYS`) and editable any time, 0–10, because every bank posts at its own speed. If the bank did post one later, one tap moves it to the next statement and that cycle's limit. **The budget keeps the purchase date** |
| ACC-27 | **Edit the current balance** | ✅ v1 | 5b | On an existing cash, debit, savings or credit account, the sheet shows the **current balance** (for a card, **amount owed**) instead of the opening balance. **Since 2026-09-16 a card with a credit limit shows both ‘Amount owed’ and ‘Left to spend’** - type either and the other follows (limit less the plans still to bill); both save as the same balance. Saving a different figure asks first (ACC-28). Investment accounts keep their valuations (ACC-13) |
| ACC-28 | **Ask before recording the difference** | ✅ v1 | 5b | *"Wallet: ₱2,450.00 → ₱2,100.00. Difference −₱350.00."* Choices: **record as a balance adjustment** (recommended) · **fix the opening balance instead** · **cancel**. Nothing is recorded without a tap. See §22 |
| ACC-29 | **Balance adjustment — unrecorded loss or gain** | ✅ v1 | 5b | A transaction of type `adjustment`, dated today, on that account only. It moves the balance and cash on hand. **DECIDED 2026-09-14: the budget stays the same.** Neither a loss nor a gain touches the budget, the daily allowance or a card's limit, because the app does not know what the money was. Own ledger label. **Stats counts them since 2026-09-18** (user's choice: own rows, counted): a loss is spending and a gain is income, each its own *Unrecorded loss* / *Unrecorded gain* row in By Category, in the totals, trend, comparison and per-account figures; merchants and tags stay purchases only, and the totals line says they are included. Delete to undo; never edited |
| ACC-31 | **Borrow / lend accounts** | ✅ v1 | 10 | Added 2026-09-15 (user, after sample_ui/). **Lent** — money someone owes you: a positive balance, lent out and paid back by transfer (*Lend more* / *Paid back*). **Borrowed** — money you owe a person, and **Loan** (a bank, car or salary loan) as its subtype: a negative balance shown as *"You owe ₱45,000"*, typed as a positive amount, brought down by transfers into it (*Pay back*). Interest on a loan is an expense. Both are **off** cash on hand by default: money lent is not in your pockets until it returns, and a debt is money owed later, as ACC-17 already treats installments. No schedule, no interest engine — a loan with fixed payments is a recurring transfer (REC) | **The From / To side the page does not know starts BLANK (2026-09-20, user:** *"is it possible that the default is blank... it is much better to be default than picking the last-used"*): *Lend more*, *Paid back*, *Borrow more* and *Pay back* fill only the loan's own side, and Save stays disabled until the other is chosen - a guessed account here is a withdrawal from an account you never picked. Every other transfer keeps its guess. Leaving that row blank means the money came from, or went back into, cash you don't track (ACC-39)
| ACC-32 | **Member accounts** | ✅ v1 | 10 | Added 2026-09-15. Membership, transport (Beep), school and other prepaid cards: a balance you top up by transfer and spend from like cash. **On** cash on hand by default — it is prepaid money you will spend |
| ACC-33 | **Add Account list and subtype** | ✅ v1 | 10 | Added 2026-09-15. New accounts start from a list grouped Debit · Credit · Borrow/Lend · Invest · Member account (Debit card, Cash, Bank account, E-wallet, PayPal, Other debit · Credit card, Other credit account · Lent, Borrowed, Loan · Savings, Stock, Fund, Crypto, Real estate, Precious metal · Membership, Transport card, School card, Other member card). The entry is kept as the account's `subtype`, shown as its label. A label only — the TYPE decides every rule |
| ACC-34 | **A card's plans and monthly payment** | ✅ v1 | 10 | Added 2026-09-15 (user, after importing cards with a balance and no plans). On a credit card's page: its installment plans and repeating charges with *+ Add* and edit in place; ~~Does it balance?~~ **removed 2026-09-16 (user)**: comparing the app with the bank is Check statement's job (ACC-24), correcting what the card owes is the account sheet's (ACC-27/28), the banner already shows owed with plans beside what is billed (REC-14), and on a card with typed bills it could only agree with itself; **You pay it each month** — the recurring transfer into the card and, from GET /projection's items (dates from the one occurrences() engine), the card's owed month by month for 12 months and the month it is paid off. **The month it is paid off starts from what the account really owes (fixed 2026-09-21, user: a ₱185,000 motorcycle one payment in said *paid off by September 2026*):** the balance AND the plans not billed yet (REC-14, `owedWithPlans`), where it used to read the balance alone - only ₱5,000 of that loan had been billed. A plan's own charges are skipped in the walk, because they are that figure being billed rather than new debt |
| ACC-35 | **A card's bills, typed from its own app** | ✅ v1 | 10 | Added 2026-09-15 (user, from SPayLater's *My Bills*: "Sep ₱7,754.49 due 15 Oct, Oct ₱4,120.80 due 15 Nov…"). On a credit card's page, type the unpaid bills — due date and amount — instead of every purchase behind them. **Changes ACC-17 for that card:** cash on hand subtracts only what is **due now** (overdue bills + the next one), not the card's whole balance; the balance itself, the limit and net worth are untouched. What is paid is derived, never ticked: payments and refunds into the card from the day the list was saved settle bills oldest first. Saving replaces the list and restarts that count, as a paid bill leaves the card app's Unpaid tab. The payment reminder (ACC-15/20) follows the bills. `POST /accounts/{id}/bills` (not PUT: IIS WebDAV refuses PUT with 405); an ordinary edit keeps them; an empty list removes them. **Plans are part of the bills:** every installment payment and repeating charge on the card is added to a bill (from the one occurrences() schedule), except where that bill fell due before the list was saved. **Which bill depends on what the charge is (fixed 2026-09-16, user: a payment dated 15 Oct was landing on the 15 Nov bill):** an INSTALLMENT payment's date is the day the bank bills it, so it joins the first bill falling due on or after that day - past the last typed bill it keeps that bill's day of the month; any other charge is a purchase, billed with the statement cycle it falls in, which falls due the month after. Months ahead asks the question the same way, so nothing is counted twice; a charge that never ends is counted only as far as the last typed bill. Editing starts from the typed part, so a plan is never typed in twice. The Cash on hand banner links to Months ahead. **Months ahead lists the bills already in cash on hand (fixed 2026-09-16, user: the next bills "are not reflected"):** the overdue bills and the one due now are shown in the month they fall due as *already set aside*, with no effect on the figures, because today's cash on hand - where every month starts - holds them already. **Months ahead follows the bills:** each later bill is taken on its own due date, in the month it is due (changed 2026-09-19, user: November's bill showed in October - it used to be taken the day after the bill before it; each month now says what Home will hold back at its end, `bills_held`) — the typed part as *card bills* on top of the budget, the plan part as a fixed charge — and a card charge already inside a bill is not counted again **Purchases recorded after the list (added 2026-09-17**, user: "the added expense transaction did not add to the bills payment for the next month"): a one-off purchase recorded after the list was saved, and dated on or after that day, joins the bill of the statement it posts in - a new bill line when no bill was typed for that due date - shown as *incl. ₱X new purchases*. The bank's posted-on day (ACC-26) decides the statement. Anything recorded before the save was already in the card's app, so it is never added twice; a saved list names the purchases and plans it covers (`bills_cover_transactions`, `bills_cover_rules`). **The same goes for plans** (fixed 2026-09-17, user: SPayLater's typed ₱8,280.76 showed as ₱8,296.09): a plan created before the list was saved is already in the card app's figures and adds nothing; only a plan created later adds its payments. The bill editor now starts from each bill's full unpaid amount. Payments settle the typed part, then new purchases, then plans; Months ahead takes new purchases with the typed bills. **Bills add up to what the card owes, and open (2026-09-19**, user: the bills and the owed figure did not match, and a bill could not be opened): below the bills, *Not on a bill yet* = owed with plans - bills left + repeating charges on the bills not charged yet (`not_on_bill`, `bills_not_charged`) - usually payments the card's app lists only later; shown, never put on a bill (D1-a), and *Card owes* repeats the tile. Tapping a bill opens its lines (`Bill.lines`): the typed figure, purchases and plan payments added on top, what the typed figure already holds (greyed, never added), and the payments that settled it, oldest bill first; a line opens its transaction or plan. A saved list also names the payments dated that day (`bills_cover_payments`): one made before the list was typed is not applied a second time. |
| ACC-36 | **Net worth, one tap from cash on hand** | ✅ v1 | 10 | Added 2026-09-15 (user: "a grand total so I don't overspend"). **Reverses the "not net worth" half of ACC-17 as a second view, not a replacement:** the headline on the Accounts tab flips between cash on hand and net worth — every active account at full value (savings, investments, money lent) less every debt in full (cards, loans, installments not billed yet), with assets and liabilities. The choice is kept in memory only. **Each account has its own "Count in net worth" switch** (on by default, separate from ACC-18's cash-on-hand switch), so an account can be left out of the grand total |
| ACC-37 | **Daily savings interest** | ✅ v1 | 10 | Added 2026-09-16 (user, from MariBank's and SeaBank's help pages). A cash, debit, savings or member account can earn a rate a year, in **bands** — 3.25% up to ₱1,000,000 and 3.75% above it — charged on **yesterday's closing balance** and credited early the next morning, dated that day, **net of the 20% withholding tax**, exactly as the banks do. **DECIDED (user, 2026-09-16): one entry per day**, so the app's balance matches the bank's every day rather than drifting until a monthly sweep; and **the net only** is credited, because that is what the bank actually deposits — the gross and the tax are shown on the account, never posted. Interest **compounds**: a day's credit is part of that day's closing balance. **Nothing under ₱0.01 is credited and nothing is lost** — the fraction is carried (`carry`) until it reaches a centavo. **Today's entry is posted on today's first open** (user, 2026-09-17: "my MariBank added 2.58 at 1:00am"): it is paid on yesterday's closed balance, so it never changes with the next thing you type; today's own balance is paid tomorrow. The first entry is the day after interest starts. There is no scheduler on the server, so `POST /accounts/interest/accrue` is a catch-up called on every open beside the recurring one (REC-05): it posts what is owed up to today, moves `credited_through` in the SAME commit, and a second call changes nothing. An entry you delete is never written back; changing a rate never rewrites what was already credited. Turning it on can fill in up to a year backwards. The arithmetic is pure, in `app/core/utils/interest.py`, and shared with **Months ahead**, which adds one estimated interest month at today's balance (REC-21). A card, a loan and an investment are all excluded: their interest is a charge (REC-29), an expense (ACC-31) or a valuation (ACC-12) |
| ACC-38 | **The cashback an account usually pays** | ✅ v1 | 10 | Added 2026-09-16 (user). A rate and the income category it lands in, kept on the account you spend FROM. A **suggestion only**: it fills the cashback field in on a purchase (TXN-22) — "Cashback ₱20.00" on a 2% card — and is never applied to anything by itself, so no figure anywhere is derived from it. No monthly cap (not built; type the amount instead) |
| ACC-39 | **Cash you don't track ("my wallet")** | ✅ v1 | 9 | Added 2026-09-20 (user, on lending: *"the money is coming from my wallet, and I don't create any account for my wallet, and I don't want to create one because I consider my wallet as spent money already"*). A loan's transfer (ACC-31) may come **from my wallet**, or be paid back **into** it. The money has to have two ends - a transfer is two legs - so the app keeps **one hidden account** for it, made on the server the first time a loan is saved from it (`POST /accounts/untracked`, get-or-create) and never shown again: not on the Accounts tab, not in a picker, not in cash on hand, not in net worth, not in Stats (it only ever holds transfer legs). Its balance only falls and nothing reads it. So lending ₱500 from the wallet raises what Juan owes by ₱500 and changes **no** balance, budget, allowance or day total - which is what "already spent" means. `hidden` is server-owned: it is not part of any request payload, and an edit of the account keeps it. **Blank IS the answer (2026-09-20, user: “if the user did not pick anything from the From options, it will automatically recognize that it comes from My wallet”):** there is no wallet chip to find. On a loan's transfer the side the page does not know starts empty, Save is enabled with it empty, and a line under the row says where the money is coming from or going back to. Lending out of a pocket is the normal case, so it costs no taps; naming an account is the exception, one tap on a chip, and tapping that chip again clears it back to the wallet. Only the side OPPOSITE a lent or borrowed account may be blank - everywhere else the money really did leave, or land in, an account you track, and a forgotten chip would be a mistake rather than an answer. An entry already on the wallet opens with that side blank again |
| ACC-40 | **A loan bills like a card** | ✅ v1 | 9 | Added 2026-09-21 (user: *"is it possible to make the rules in borrowed and loans the same in credit cards - because in credit cards it deducts it in cash on hand the monthly dues, and in credit card it shows the bills per month"*). A card's bills are TYPED from its own app because the statement is the bank's (ACC-35); a **loan's are DERIVED**, because the installment plan on it already carries the schedule. Every scheduled payment money has not covered is a bill on its own day (`AccountView.dues`, from `recurring_service.plans_owed` - one pass that also answers REC-14's unbilled remainder, since the account list asks for both). **`due_now` is the card's rule exactly** - everything overdue plus the next one - and once the account's *Count in cash on hand* switch is on, that is what the headline holds back instead of the whole debt: ₱50,000 in the bank with ₱185,000 owed reads ₱40,000, not −₱135,000. The switch still starts OFF (ACC-31), so nothing changes until it is turned on. **What you OWE, the balance and net worth are untouched** - they count the plan in full, as REC-14 says. The loan's page shows **Bills** above its plans: the next six payments with their due dates, what is due now, and how many are left. **Months ahead treats them as bills too**: the ones cash on hand already holds are shown as set aside, every later one leaves on its due date, the plan's own charges are dropped so the same money is not counted twice, and the transfer that pays it is neutral between two counted accounts - the same bargain a card's typed bills have had since 2026-09-16 |
| ACC-41 | **Check a cash, debit, savings or member account against the bank** | ✅ v1 | 14 | **Built 2026-09-28.** What ACC-24 does for a card, for every other account you can read a balance for: type the bank's (or the wallet's) balance for the end of a day, and the account's page shows the app's balance for that day (`balance_on`) and the difference - **one number, not every line**. A match reads *✓ Checked 27 Sep*; older than a month it says so. A difference offers **A transaction I forgot** (the add sheet on that day, the amount and direction filled in) or **Record it as an adjustment** - ACC-28's own path through `update_account`, today's balance moved by the difference, never a new writer - or leave it, and it stays on the page. Only the bank's figure is kept (`balance_checks`, one per day, 24 at most); the difference is worked out on every read, and a balance adjustment dated after the day answers it. `account_service.check_balance`, `POST /accounts/{id}/balance-check`. No per-transaction *cleared* ticks (the roadmap's default) |
| ACC-30 | **Audit trail only when accepted** | ✅ v1 | 5b | Accepting writes a `BALANCE_ADJUST` audit entry: before, after, difference and an optional note, encrypted under your key like every audit detail. Fixing the opening balance or cancelling writes no adjustment and no balance entry |

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
| TXN-01 | **Quick add: two taps and a number** | ✅ v1 | 4 | Bottom sheet, custom numpad, amount pre-focused. The single most important interaction. **The account row is GONE when the screen that opened the sheet already named it (2026-09-20, user: "it should already know which account it was being used - I think it is redundant", then "is it possible to just remove the paid from part"):** the + on SeaBank's own page shows no account row and no label - it is for SeaBank, and repeating that is a line you read past. To choose an account, open the sheet from the [+] in the tab bar, which names nothing and shows the full row. An edit always shows the row (there the account is part of what you came to change) and a transfer's two rows are untouched. **The extras are ICON buttons (same day, user: "add note, split, cashback does not feel like a button - it's like a text in the design", then "make those smaller or maybe just make those an icons"):** Add note, Tags, Split, Installments and Cashback are 44px outlined tiles on a hard shadow that sink when pressed (`SheetAction`, the neo-brutalist `press`), each carrying its name as `aria-label` and `title`. Text survives only where it is a figure or a sentence: the cashback SUGGESTION (ACC-38) sits beside its icon, and *Repeat last entry* and *Add a line* keep their words. **A transfer hides the side the page already knows too (same day):** *Lend more* and *Pay back* show only the From row, *Paid back* and *Borrow more* only the To row - a picker for the account whose page you are standing on is the same redundancy. Change the hidden side's value and its row comes back, because then it is a choice again. **The way OUT of each extra is now the same visible tile** (`tone="quiet"`, a × icon in calmer ink): remove the note - which had NO way back at all before, once opened it stayed - clear the tags, *Don't split*, remove the cashback. They were bare grey words (user: "the buttons of close or remove of that data is not much visible") |
| TXN-02 | Expense entries | ✅ v1 | 4 | |
| TXN-03 | Income entries | ✅ v1 | 4 | |
| TXN-04 | Transfers between accounts | ✅ v1 | 4 | Linked pair; must never count as spending |
| TXN-05 | Category + sub-category assignment | ✅ v1 | 4 | Main chips, most-used first; its sub-categories appear under it, optional. The recurring / installment sheet picks the same way (2026-09-16, user: the whole list at once is unusable after an import) |
| TXN-06 | Account assignment | ✅ v1 | 4 | |
| TXN-07 | Date (defaults to today) | ✅ v1 | 4 | |
| TXN-08 | Merchant / payee | ✅ v1 | 4 | Encrypted |
| TXN-09 | Free-text notes | ✅ v1 | 4 | Encrypted |
| TXN-10 | Tags | ✅ v1 | 6 | Stored as ids inside the transaction payload. **Moved to Phase 6 (2026-09-14):** the ids have been kept, empty, since Phase 4; Phase 6 adds managing them, choosing them in the add sheet, a ledger filter and spending by tag |
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
| TXN-22 | **Cashback on a purchase** | ✅ v1 | 10 | Added 2026-09-16 (user: "some of my purchase has cashback… based on percentage or the user can just input it"). Typed on the entry, or offered from the account's usual rate (ACC-38). **DECIDED (user, 2026-09-16): it is its own credit, not a discount** — the purchase keeps its full amount, so **spending stats stay gross**, and the money back is an income row in the category you choose. **DECIDED: you pick the account and the day** — the same card that day by default, which is what a wallet does; a card that pays at the end of the cycle gets its own date. A date later than the purchase files the credit on that day; like every dated entry in this app it counts in the balance straight away, so there is no "pending" state. The two rows are a linked pair like a transfer's legs (`cashback_id` / `cashback_of`): written, edited and deleted together, in one commit. Removing the cashback removes the credit; deleting the credit leaves the purchase claiming nothing. Cashback can never be more than what was spent, and only a purchase earns it. **Neither the category nor the account is asked for any more (2026-09-20, user: "it is already default that the category should be Cash Back and the account should be the bank account we are in - there is no need to put those in"):** the category is the account's own rule (ACC-38) or the income category plainly meant for it - Cashback, Rebates, Refunds - and the account is the one the purchase was made on, which is what a card actually does. The sheet says where it lands in the line under the amount rather than asking. Both are defaults, and the credit is an ordinary income row, so moving it afterwards is an ordinary edit. The category picker comes back ONLY when there is nothing sensible to guess, because a silent answer would otherwise file the money under something like Salary; Save then waits for it. The date stays - a card that pays at the end of its cycle needs it |
| TXN-23 | **Look at an entry before editing it** | ✅ v1 | 9 | Added 2026-09-20 (user: "if I click a data it should not show as the edit already page - I want a preview of the data first and a button if the user wants to edit", after the read-only balance-adjustment view). Tapping a transaction ANYWHERE it is listed - the account page's trail, Home's recent list, a calendar day - opens a READ-ONLY preview (`TransactionPreview`, `uiStore.preview`): the amount signed for that account, the date, the account (a transfer as *from → to*), every split with its category and note, tags, the note, the bank's posted-on day (ACC-26), the savings-interest day (ACC-37), when it was recorded, the receipt to look at (TXN-15), the plan behind a posted payment (opens it, REC-04) and the cashback row it is joined to (TXN-22, opens that entry's preview). **Edit** opens the sheet the tap used to open; **Delete** asks twice, because a row is tapped by accident far more easily than the editor was opened - and it is a BUTTON: an outlined tile in red ink, turning solid red for the second tap (2026-09-21, user: "I can't delete the payment I did for this month" - as red words beside a filled Edit it read as a label, so a plan payment made while trying the button looked impossible to take back; it always was, from either leg, `test_a_payment_can_be_taken_back`). A balance adjustment (ACC-29) keeps its own wording and has no Edit. The Ledger keeps swipe-to-edit - already a deliberate action - and a pending (optimistic) row opens nothing until the server has answered. |
| TXN-24 | **Merchant, and merchants remembered** | ✅ v1 | 11 | **Built 2026-09-28.** The add sheet had no merchant field at all - merchants came only from imports and plans. **A Merchant tile beside Add note (user's choice, 2026-09-28)** opens the field, focused. Typing offers the merchants used before (this kind only, most used first; `GET /transactions/merchants`, from the working set - merchant is encrypted, so never SQL); picking one fills the category its LATEST entry was filed under - **only when no category is chosen yet**, so a suggestion never overrides you. Names match as a person reads them: case and runs of spaces do not make two shops. A split entry suggests no category, an archived category is never suggested, and a cashback credit is not a merchant of its own. An edit now sends the merchant back, so saving an imported or recurring entry no longer wipes it |
| TXN-25 | **Recently deleted, and Undo** | ✅ v1 | 11 | **Built 2026-09-28.** After any delete - the preview, the sheet, a ledger swipe - a toast says *"Deleted ₱150.00 · Jollibee · Undo"* for six seconds; **More → Recently deleted** keeps the last 30 days, newest first, with Restore. Both bring back everything that went: a transfer's other leg, a purchase's cashback; a credit deleted on its own rejoins its purchase. Only what DELETE removed is listed - `delete_transaction` stamps `deleted_at` - so a purchase hidden by an installment conversion (REC-34), a plan's charges removed by converting back, and a credit taken away by an edit never appear. **Refused, with the reason shown, when a restore would contradict what happened since:** its account is archived or gone, a category it was filed under was deleted, it was money paid ON a plan (REC-32 - pay it again from the plan), the plan that posted it is gone, that charge or that day's interest has been recorded again since. Tags deleted meanwhile are dropped. `GET /transactions/deleted`, `POST /transactions/{id}/restore` |

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
| BUD-13 | **Copy last period's budget** | ✅ v1 | 5 | **Pulled into v1.** Start a new period from the previous one's allocations instead of retyping every category. You will want this by month two. **Confirmed 2026-09-14: no button** — allocations stay in force from period to period, so there is nothing to copy |
| BUD-14 | Approaching-budget warning | ✅ v1 | 5 | Fires at `ALERT_WARN_THRESHOLD_PCT` (default 80%) of the period budget |
| BUD-15 | **Pace alert** — spending faster than the period is elapsing | ✅ v1 | 5 | Day 10 of 30 with 60% spent. More useful than a fixed threshold, because it warns you while there is still time to act |
| BUD-16 | Web push notifications | ❌ Out | — | **DECIDED: no push.** It would need a background sender that decrypts to know your budget state — a service holding keys outside a user session, weakening ARCHITECTURE.md §5.5. Every alert above is computed inside your own session instead |
| BUD-17 | **Suggested budget from your recent spending** | ✅ v1 | 11 | **Built 2026-09-28** (user: *"an auto budget feature that already suggests a budget based on your last month/s data"*). *Suggest from my spending* on Budget, and *Start from my spending* on Home with no budget yet, works out a total and an amount per category from the last 1, 3 or 6 FINISHED periods - exactly what the budget counts, sub-categories rolled into their main - for the period the budget applies to now. **Decided by the user:** it SUGGESTS and never sets anything (*Use this* fills the Plan editor; Save saves); the typical figure is the **median**, the average shown beside it; every line **rounds up** to a step chosen in Settings (₱1/10/50/100/500/1,000, default ₱100). Scheduled bills, subscriptions and installments are the **floor**; a category spent in fewer than half the periods joins the unassigned buffer; one budgeted with no recent spending is kept. Over the usual income it says so and offers *Fit to my income*; *5% / 10% less* trims above the floor only. **The reminder:** in the first 3 days of a period (weekly: once a month), after 3 finished periods, when the suggested TOTAL is more than 15% from the budget either way, Home shows *"Your spending has changed"* - *Review budget* opens the suggestion, *Not now* is kept in the budget on the server until the next period; a Settings switch (on by default) turns it off. `budget_service/suggest.py` (pure), `GET /budgets/suggestion`, `POST /budgets/suggestion/dismiss` |

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
| CAL-07 | **Upcoming bills and charges on the calendar** | ✅ v1 | 12 | **Built 2026-09-28.** Days after today show what is SCHEDULED - repeating charges and income, subscriptions, installment payments, card bills and loan dues - outlined dashed, from the Months ahead projection (the one schedule, `occurrences()`), so the two never disagree. A cell shows what leaves cash on hand that day - each item's `effect`: a plan's charge on an uncounted loan, or a card payment between counted accounts, is listed but moves nothing - and the header says *"₱X scheduled"* BESIDE what was spent, never added to it (CAL-05 stays what was actually spent). A future day's sheet lists the items; each opens its plan, a bill its account |
| CAL-06 | Week and year calendar views | ✅ v1 | 12 | **Built 2026-09-28.** A Week · Month · Year switch on the calendar. **Week:** its seven days, each with its entries (and, ahead of today, what is scheduled - CAL-07); an empty day offers to add one on it. **Year:** twelve small heatmaps from one `GET /calendar/{year}`, each month exactly as `calendar_service.month` gives it, so a day's shade and a month's total never differ between views - tap a month to open it. The arrows move by a week, a month or a year |

---

## 7. Stats & Reports

> iOS app: *"Stats & Charts – Understand your spending patterns with insightful visuals"*

Every figure here is Python over the decrypted working set. SQL computes none of
it — see ARCHITECTURE.md §4.3.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| STA-01 | Category breakdown (donut) | ✅ v1 | 6 | Balance adjustments are their own row since 2026-09-18 (ACC-29) |
| STA-02 | Drill into sub-categories | ✅ v1 | 6 | Tap a slice |
| STA-03 | Spending trend over time (line) | ✅ v1 | 6 | |
| STA-04 | Month-over-month comparison | ✅ v1 | 6 | |
| STA-05 | Income vs expense | ✅ v1 | 6 | |
| STA-06 | Top merchants | ✅ v1 | 6 | |
| STA-07 | Average daily spend | ✅ v1 | 6 | |
| STA-08 | Per-account breakdown | ✅ v1 | 6 | |
| STA-09 | Custom date range on every chart | ✅ v1 | 6 | |
| STA-10 | Cash on hand over time | ✅ v1 | 11 | **Built 2026-09-28.** Renamed from "net worth over time". A line on Stats under *Over time*: cash on hand at the end of each trend bucket (the day, week or month), up to today and never after it - the months ahead are REC-21's, from the rules. It is the **plain balances** of the accounts counted in cash on hand **today** (ACC-18 - a switch's history is not kept), an investment read through its valuations (ACC-12). What today's headline holds back - a card's typed bills (ACC-35), a loan's dues (ACC-40), money set aside for goals (GOA-08) - cannot be told for a past day, so it is left out and the card says so. `account_service.balance_on` / `cash_history`; `Overview.cash_on_hand` |
| STA-11 | **Forecast / projected period-end** | ✅ v1 | 6 | **Pulled into v1.** "At this rate you finish the month at ₱43,200." Runs off the same trend data as STA-03, so it is a calculation and a chart line, not new plumbing. Current period only, from past spending — the months ahead, from your rules, are REC-21 |
| STA-12 | **Monthly review** | ✅ v1 | 14 | **Built 2026-09-28.** A finished period looked back on - a budget period when there is a budget, else a calendar month - from Stats (*Review this period*) and offered on Home in the first 5 days of the next one, until *Not now* (kept in the preferences, `review_dismissed_for`). Spent against the period before, what came in and what was left; the budget's result and carry-over (only for a period the budget covered); the three categories that moved most, a stopped one included; the three biggest purchases; plans and subscriptions that started, were paid off, cancelled or changed price; cashback and savings interest; cash on hand at the start and the end (STA-10's plain balances). **Net worth is left out**: typed card bills carry no date, so a past net worth could not be rebuilt honestly. Derived, nothing stored. `stats_service.review`, `GET /stats/review`, `/review/offer`, `POST /review/dismiss` |

---

## 8. Recurring Transactions, Installments & Projection

> iOS app: *"Set recurring transactions on a daily, weekly, monthly, or custom basis"*

REC-08 to REC-18 add **installment plans** — something bought on terms and paid
monthly, like a motorcycle at ₱5,000 × 36. An installment is a recurring rule
that also knows the total, so it can tell you what is left and when you finish.
How it affects cash on hand is explained in §19.

REC-19 to REC-27 add **projection** — your salary, bills, subscriptions and
card installments laid out over the coming months, so you can see what each
month will look like before it arrives. It reads the same rules the engine
expands and never writes anything. §20 walks through it with numbers.

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
| REC-09 | Installment details: total, number of payments, amount, start | ✅ v1 | 7 | ₱180,000 · 36 · ₱5,000 · Sept 2026. Stored in the rule's encrypted payload — no new table. **The total is what the bank bills, interest included.** Enter the price and let the first statement supply the interest (REC-28, REC-29), or enter both if you already know them (REC-30) |
| REC-10 | **Remaining balance, payments left, payoff date** | ✅ v1 | 7 | *"₱125,000 left · 11 of 36 paid · done Aug 2029."* **Derived from the payments actually posted**, never stored as its own counter — same reason as GOA-07: a stored number drifts |
| REC-11 | Each payment counts as spending | ✅ v1 | 7 | ₱5,000 hits your budget and daily allowance on the due date, like any expense |
| REC-12 | **Never posts the full price up front** | ✅ v1 | 7 | Your account balances drop ₱5,000 a month, never ₱180,000 on day one. This is the *cash view* — see §19 |
| REC-13 | Early payoff | ✅ v1 | 7 | Pay the remaining balance in one go; the plan closes and generates nothing further |
| REC-14 | **Installments** ("0% for 36 months") | ✅ v1 | 7 | The monthly amount posts each month, not the full price, so the budget and the daily allowance see ₱2,000 a month and not ₱12,000 at once. **What you OWE counts the whole plan from day one (fixed 2026-09-16, user: "it does not show the charges").** A plan is a debt the moment you take it: the card's page and tile show `owed_with_plans` — ₱12,000, split as "₱0.00 billed · ₱12,000.00 of plans still to bill" — and a loan or borrowed account adds `plans_unbilled` to what it says you owe. Net worth (ACC-36) counts it on any account; **cash on hand never does** (ACC-17), and the balance itself stays the ledger's own sum. Available credit is unchanged (ACC-14). **A plan shows on the account it runs on**, not only on Recurring: a credit card lists its plans inside the payments card, and every other account gets the same list (`AccountPlans`) — before the fix an installment on a loan appeared nowhere but the Recurring page. **And it can be paid there:** the monthly payment (`AccountPayments`, a recurring transfer in, with the payoff month) is on every account you owe on, not only cards — a plan on a loan could not be paid any other way (2026-09-16) |
| REC-15 | Skip a payment | ✅ v1 | 7 | Balance unchanged, payoff date moves one period later. You still owe it — skipping must never make debt disappear |
| REC-16 | Final payment absorbs rounding | ✅ v1 | 7 | ₱100,000 ÷ 36 is ₱2,777.77…; the last payment is adjusted so the total is exact to the centavo |
| REC-17 | Total still owed across all plans | ✅ v1 | 7 | One figure on the Installments screen: everything you have committed to but not yet paid |
| REC-18 | Asset-and-debt net-worth view | ❌ Out | — | **Superseded 2026-09-15 by ACC-36**, which adds net worth as a SECOND view (a flip on the Accounts headline), never as the headline. What stays out is the asset side: **DECIDED: cash view only.** Nothing you own is part of any total. The motorcycle never exists in the app as an asset — only its payments do. See §19 |
| REC-19 | **Semi-monthly schedule** (twice a month) | ✅ v1 | 7 | Paid on the 15th and the 30th, the usual Philippine payroll. Two days per month, not "every 2 weeks" — those drift apart. A day past month-end clamps to the last day, so "30th" is Feb 28 |
| REC-20 | **Scheduled amount change** | ✅ v1 | 7 | *"Salary goes to ₱48,000 from January."* A dated amount history on the rule, like the budget's. Expansion and projection both use the amount in effect on each occurrence date; posted transactions are never rewritten. Subscription price rises (SUB-08) record into the same history |
| REC-21 | **Month-by-month projection** | ✅ v1 | 7 | Next 12 months by default (3 / 6 / 12). Each month: income due, committed outgoings, the rest of the budget, and **projected cash on hand at month end**, carried forward into the next month. See §20 |
| REC-22 | Projection uses the expansion schedule and writes nothing | ✅ v1 | 7 | **One schedule, two readers.** `recurring_service` exposes the occurrence calculation; expansion posts it, projection only reads it. A separate forecast calendar could disagree with what actually posts — the same bug SUB-00 prevents. Nothing is stored and nothing is posted early |
| REC-23 | Committed vs budgeted spending | ✅ v1 | 7 | A month's projected spending is **the larger of your budget and your committed outgoings**, because recurring charges already count against the budget (REC-11). A month where committed charges alone exceed the budget is flagged as overcommitted |
| REC-24 | **Lowest point in each month** | ✅ v1 | 7 | Rent on the 1st and salary on the 15th can take you below zero mid-month even when the month ends positive. Shows the low point and its date, in `danger` when below zero |
| REC-25 | **Credit-card look-ahead** | ✅ v1 | 7 | Per card, the next 6 statements (ACC-09 cycle): every installment payment, subscription and recurring charge landing on each one, the statement total, and its due date. *"April statement: ₱7,150 — due May 5."* Stops at an installment's final payment (REC-16). On a card with a spending limit (ACC-21), each statement also shows how much of the limit recurring charges already use **A card with typed bills (ACC-35) shows those bills instead** (2026-09-19, D8-a) - the same figures and lines as its Bills section, each opening what it is made of. |
| REC-26 | Tap a month → every projected item | ✅ v1 | 7 | Dated list of occurrences, grouped by account, with the rule each came from. Paused rules (REC-07) are shown dimmed and left out of the totals |
| REC-27 | What-if: try a plan before committing | ✅ v1 | 12 | **Built 2026-09-28.** *"Can I afford a phone at ₱3,000 × 12?"* Months ahead offers *Try a plan* - an installment, a subscription, or a bill or income - in the ordinary rule sheet, whose button reads *See what it does*. The unsaved plan is checked exactly as a new rule would be and expanded through THE schedule (`recurring_service.trial`, rule id -1), and `POST /projection/what-if` returns the months with and without it. Every month then says what it does: the end figure's change and whether it takes the lowest point below zero - or, when the plan fits inside the budget (REC-23: fixed charges count inside it), *"Fits in your budget — ₱3,000 less of it left for everything else"*. *Save this plan* is the ordinary create; *Stop trying* puts it back. Nothing is written |
| REC-28 | **Installment from price and months only** | ✅ v1 | 7 | *"₱40,000 phone, 6 months, on BPI Card."* You rarely know the interest at the shop. Payments are **provisional** at price ÷ months (₱6,666.67) and the plan shows *"Terms not confirmed"* until the first statement. Budget, projection and card limit use the provisional amount meanwhile |
| REC-29 | **Confirm the terms from the first statement** | ✅ v1 | 7 | A new choice in the statement check (ACC-25): **interest on this installment**. It is suggested when exactly one unconfirmed plan is on that statement; otherwise you pick the plan. ₱400 → the plan becomes ₱7,066.67 × 6, ₱2,400 interest. **Every payment already posted is corrected to carry its ₱400**, on its own day, so it matches the bank's line — a plan confirmed after two or three bills ends at exactly zero too (fixed 2026-09-15; before, only one payment's interest was added). Payments 2–6, the remaining balance, the projection and the look-ahead all recalculate. **A later bill that differs** — higher or lower — is a second choice, *the payment changed*: the plan carries the new interest from that payment on (its dated `interest_changes`, like REC-20), the posted payments from there are corrected, earlier ones stay as billed, and the price never changes (built 2026-09-15) |
| REC-31 | **Recurring from the + button** | ✅ v1 | 10 | Added 2026-09-15 (user). The add sheet's fourth choice, *Recurring*, offers a bill or income, a subscription, an installment, or a credit card payment (a monthly transfer into a card, prefilled) — each opens the same rule sheet as More → Recurring, already on the account the sheet was opened for |
| REC-32 | **Paying a plan, and extra payments** | ✅ v1 | 10 | Added 2026-09-16 (user, a ₱185,000 motorcycle over 37 × ₱5,000 on a loan from a person: "every time the user pays, the system will ask if this would reduce the monthly payment, or keep the monthly payment and the later payments will be deducted"). **Pay** on any plan, and **Pay back** on a loan that carries one, record money paid ON THE PLAN: a transfer from the account you pay out of into the plan's account, carrying the plan's id, so the plan says what you have paid and what is left - "₱5,000.00 a month · 34 to go · ₱15,000.00 paid · ₱170,000.00", which is exactly "You owe". A payment covers what is DUE first (every payment dated on or before it not yet covered; with nothing due, the next payment, paid early). **Anything above that is extra, and the app asks** - with both outcomes worked out by the server: **lower the monthly payment** (same count, ₱4,722.22 × 36) or **keep it and finish sooner** (the last payments disappear: 34 payments, done two months earlier). Nothing is written until one is chosen (409 PREPAYMENT_CHOICE, the same ask-first pattern as ACC-28). The extra is charged at once to the plan's category, so the budget sees it that day and the schedule, the budget and what you owe move together; the plan still charges exactly its price. Extra payments live in the plan (`prepayments`) and are applied inside the one schedule (`recurring_service.installment_plan`), so bills and Months ahead follow. Paying everything left closes the plan without asking; more than is left is refused; terms are fixed once an extra payment exists. A plain transfer into the account is NOT counted against a plan - use Pay |
| REC-33 | **Pay a repeating charge now** | ✅ v1 | 10 | Added 2026-09-16 (user: Spotify is paid monthly from GCash and a normal account had no Pay the way a card's plan does). **Pay** beside a repeating charge on any account the money leaves itself (not a card - a card's charges are paid through its bill) records the rule's NEXT occurrence now, after one confirmation. It carries that occurrence's date, so the catch-up does not charge it again on its day and the rule's next date moves on by itself; it is dated the day paid, or its own day when that has already come. One occurrence per tap. Installments use REC-32; income and paused rules are refused |
| REC-34 | **Pay a purchase in installments** | ✅ v1 | 10 | Added 2026-09-18 (user: "modify the expense in a credit account and split it into 3 months, or depending on the payment plan - an expense that can be moved to an installment plan"). Every recommendation accepted. On a **credit card or a loan** only (elsewhere the money already left): the add sheet's **Installments** saves a new purchase as a plan, and an expense already recorded can be **converted** from its sheet - months (3/6/12/24/other), first payment (default: the bill the purchase belongs to; a loan: a month later), optional interest or fee, and a server-worked preview. **The purchase BECOMES the plan (option A)**: it is hidden (soft-deleted, linked both ways - `from_transaction` / `converted_to`) so nothing counts twice; the budget sees one payment a month (REC-14), what you owe does not move (plans_unbilled), payments already due post at once, a split purchase keeps its proportions on every payment (`category_shares`), its receipt shows on the plan, cashback already received stays its own income, and a typed bill list that held the purchase holds the plan (ACC-35). A purchase on a closed statement is allowed, with a warning. **Convert back to one purchase** removes the plan and the payments it posted and restores the purchase as it was; money paid on the plan stays. `installment_conversion`; `POST /recurring/installments/preview`, `/recurring/installments`, `/recurring/installments/from/{id}`, `/recurring/{id}/revert` |
| REC-35 | **Debt payoff planner** | ✅ v1 | 12 | **Built 2026-09-28.** More → *Pay off debts*: every card and borrowed account that owes something (what its page says you owe, plans still to bill included), with an extra amount a month you could pay. **Smallest first** (snowball) and, once a rate is typed, **Dearest first** (avalanche); a cleared debt's payment rolls on to the next; each shows when it is cleared, the debt-free month against paying as you do now, and the interest - an ESTIMATE, since the app never calculates a card's real interest (ACC-19). A debt's payment is its repeating transfer in, else its installments' next payment, and can be typed for a try (never stored). **Decided by the user:** the rate is typed **as the bank shows it** - *Interest it charges* on a card or loan, per month or per year (`debt_rate`, stored a year) - and extra money on an installment plan **finishes it sooner**. Pure arithmetic in `app/core/utils/payoff.py`; `payoff_service`; `POST /projection/payoff`. Nothing is written |
| REC-30 | **Price and interest split on every payment** | ✅ v1 | 7 | ₱7,066.67 posts as **₱6,666.67** in the purchase's category and **₱400** in Financial › Interest — two splits (TXN-16). The bill and the card limit see one ₱7,066.67; Stats shows what the interest cost you. Also used when you enter known interest up front. A 0% plan posts a single split |

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
| SUB-07 | Cancellation tracking | ✅ v1 | 11 | **Built 2026-09-28.** In a subscription's sheet: **I cancelled this subscription** (on a day - today by default) ENDS the rule that day, so nothing charges after it; a charge already posted after it (a cancellation entered late) is real money and stays. It moves to a **Cancelled** list with what it has **saved** since - its schedule replayed through `occurrences()` as if it had carried on, less any occurrence that did post. **Resume** restarts it from today, never the months it was cancelled (the catch-up marker moves up), and an edit cannot restart it by clearing the end date. **Remind me to cancel by** a day (a free trial) raises `subscription_cancel_by` on Home within its reminder days - in-app like SUB-06, and only a reminder. Written by `recurring_service` (cancel / resume / set_cancel_by), which owns the rule; `POST /subscriptions/{id}/cancel`, `/resume`, `/cancel-by` |
| SUB-08 | Price-change history | ✅ v1 | 7 | Streaming services raise prices quietly. Recording the old amount when you edit it is nearly free, and it is the thing you actually want to see |

---

## 10. Savings Goals

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| GOA-01 | Named goal with target amount | ✅ v1 | 8b | |
| GOA-02 | Progress tracking | ✅ v1 | 8b | **Shown where the accounts are (2026-09-16, user):** a foldable *Savings goals* section on the Accounts tab - saved of target, the bar, what is left and by when, with the total saved - and the goal's card, with *Add money*, on the page of the account it lives in. Tapping a goal on the Accounts tab opens that account. The Goals screen under More is unchanged; all three share `components/GoalSheets.tsx` |
| GOA-03 | Target date | ✅ v1 | 8b | |
| GOA-04 | Link to an account | ✅ v1 | 8b | |
| GOA-05 | Required-per-month calculation | ✅ v1 | 11 | **Built 2026-09-28.** *"₱3,000.00 a month for 7 months to be on time."* What is left over the months to the target date, counting THIS month and the target's own, rounded UP to the centavo so the last month is never short; a target later this month asks for all of it now. Nothing with no date or nothing left; a date that has passed says so instead. `goal_service.monthly_need` - pure, and meant to be shared by the goals Phase 13 builds on it |
| GOA-06 | ~~Contributions are real transfers~~ **Replaced by GOA-08 on 2026-09-16** | ✅ v1 | 8b | **DECIDED: goals are in.** Putting ₱5,000 toward a goal writes an actual transfer into the linked account, so goal progress and account balance can never disagree. See §13-C |
| GOA-07 | Goal progress never contradicts the account | ✅ v1 | 8b | Progress is *derived*, never stored as its own number - since GOA-08 from the goal's own dated set-aside entries, and a goal whose account balance falls below what its goals hold says so (`short_by`) instead of pretending |
| GOA-08 | **Goals set money aside inside their account** | ✅ v1 | 10 | Added 2026-09-16 (user: "when I press add money it deducts my spending available for that account, but the balance should remain the same as I want to check it matches my bank"). *Add money* earmarks part of the account's balance for the goal and *Use it* releases it; **nothing moves** - no transaction, the balance still matches the bank. What is set aside comes off the account's **available** money and, **decided by the user, off cash on hand** (and so Months ahead); net worth still counts it. Several goals may share one account, each holding only its part; no more than is available can be set aside, and no more than a goal holds can be used. Deleting a goal releases what it held; a goal holding money cannot move to another account. **Existing goals start at ₱0 set aside** (user's choice). Add money / Use it on the Accounts tab, the account's page (banner: *₱X set aside for goals · ₱Y available*) and the Goals screen. `POST /goals/{id}/add` and `/use`; the old `/contribute` transfer is gone |
| GOA-09 | **Sinking funds** | ✅ v1 | 13 | **Built 2026-09-28.** A goal has a kind: *saving*, *sinking* or *emergency*. A sinking fund can repeat **every year** (its date rolls on) or **follow a yearly bill** (`rule_id`, an expense rule), taking its target and date from the bill's next occurrence through `recurring_service.occurrences()`. The Goals screen lists *Bills that come once a year* that no goal follows yet, each with *Set aside for it*. Every dated goal shows *"This month: X of Y set aside ✓ done"*, measured from where it stood when the month began. `GET /goals/yearly-bills` |
| GOA-10 | **Emergency-fund cover** | ✅ v1 | 13 | **Built 2026-09-28.** *"Emergency money lasts 1.2 months"* on the Accounts tab and More → *Emergency fund*. Emergency money is the goal marked emergency fund, else cash on hand (**user's choice**), and the screen says which. Essential spending is the average of the last 6 full months over categories marked **Essential** - pre-marked by name (rent, bills, food, transport, health, education…), with a switch on each category that overrides the name (**user's choice**) - plus every repeating bill and plan payment; with none, 70% of spending, and it says so. `safety_service`, `app/core/utils/emergency.py` |
| GOA-11 | **Emergency-fund advisor (rule-based)** | ✅ v1 | 13 | **Built 2026-09-28.** A target in months from rules, never a model: base 3 (employed) / 6 (self-employed or irregular), +1/+2 for income that swings over 25%/50%, +1 for a single income source, +1 for a month with no income, +1 when debt payments pass 30% of income, +1/+2 for dependents, −1 for two or more earners, clamped 3–12. Three questions (work, dependents, earners) are preferences; every rule that fired is listed with its months. Under 3 months of history only the base applies. *"Make ₱X its target"* sets or creates the emergency fund. `GET /goals/emergency` |
| GOA-12 | **Payday prompt** | ✅ v1 | 13 | **Built 2026-09-28.** When income of at least the Settings amount lands (default ₱5,000, *Never* to turn off - **user's choice**; cashback never counts), Home offers each goal its part of this month - emergency fund first, then sinking funds, then the rest - capped by what came in and what each account has available; every amount can be changed. *Set aside* is one commit; it and *Not now* are both kept on the income (`set_aside_prompted`), so it is never asked twice, on any device. `GET /goals/payday`, `POST /goals/payday/{id}` and `/dismiss` |

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
| DAT-16 | Backup restorable on a **new server** with the offline `.env` copy | ✅ v1 | 8a | **Changed 2026-09-14** (was: with the recovery phrase alone). `keys.enc` carries the DEK wrapped under the master key, so the file is standalone wherever that key exists: put the offline `.env` in place, sign up, and run `scripts/restore.py`. Inside the app a backup opens only for its own account. Keep the file and the `.env` copy apart — together they are the data |
| DAT-17 | Attachments included in the backup | ✅ v1 | 8a | Receipt images, still encrypted. A backup missing them is not a full backup |
| DAT-18 | Plaintext full archive (JSON + all CSVs) | ❌ Out | — | **DECIDED: not built.** You chose encrypted-only for backups. Per-transaction CSV export (DAT-01) remains for Excel and for moving to another app — so the encryption boundary keeps exactly one deliberate, warned opening rather than two |
| DAT-19 | Attachments stored per-user | ✅ v1 | 8a | `uploads/<user_id>/<id>.enc`. The single-user layout would have let two users' receipts collide |
| DAT-21 | **Import from the Budget phone app** (.xlsx) | ✅ v1 | 10 | Added 2026-09-15 (user). More → Backup & data → *Import from Budget App*. Reads that app's `com.budget.portable-xlsx` backup in memory (never stored; zip size capped, any DOCTYPE refused). Accounts (type 0 → credit card, "not in assets" → savings off cash on hand), categories and sub-categories (archived ones archived again), expenses, income, refunds (income in *Refunds*), fees (expense in *Fees*), transfers, and borrow/lend people as Lent/Borrowed accounts (ACC-31) with every record paid from or into an account as a transfer. **Today's balance per account is typed by the user** and set through the opening balance, because that app's balance adjustments and account-less loan records do not add up to its own balances (checked against its screens); a person's loan is prefilled with what they still owe. Balance adjustments are never written (ACC-29). Matched by name, duplicates skipped (DAT-05), so importing a later export adds only what is new. A card with no statement day in the file gets closing day 1 — check it after import |
| DAT-20 | Nightly server backup via Windows Task Scheduler | 🟡 Deferred | 9 | Optional, for a copy that does not depend on anyone using the app. Possible because writing a backup needs no key. Someone with admin rights on the server has to create the task |

---

## 12. Settings & Mobile Experience

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| UX-01 | **Mobile-first, 390 px baseline** | ✅ v1 | 1 | Desktop is a widened phone layout, never a separate design |
| UX-02 | Bottom tab bar, `[+]` centre and raised | ✅ v1 | 1 | Home · Accounts · [+] · Calendar · More (2026-09-15; Stats behind a Calendar \| Stats switch) |
| UX-03 | Custom numpad, no OS keyboard | ✅ v1 | 4 | |
| UX-04 | Bottom sheets throughout | ✅ v1 | 1 | |
| UX-05 | Light / dark / system theme, and a colour palette | ✅ v1 | 8b | **Four palettes (2026-09-18, user):** classic, candy, lime, mono - each with a light and a dark, picked separately in Settings; money colours are the same in all of them. The palette is an encrypted preference only, never in the cookie, so sign-in and a reopened lock screen show classic. **The lock screen keeps it (fixed 2026-09-16, user).** Locking no longer drops the theme; signing out still does. And, by the user's decision, the light/dark word is remembered in one cookie (`zbdgt_theme`, path /ZBDGT, SameSite=Strict) so an app reopened while locked opens in it - the rest of the preferences are encrypted and cannot be read before unlock. The shell writes `data-theme` from the cookie only when it says light or dark; "system" and sign-out delete it. The one exception to SEC-29 |
| UX-06 | Soft calm palette, matching the source app | ✅ v1 | 1 | |
| UX-07 | Safe-area insets (notch, home indicator) | ✅ v1 | 1 | |
| UX-08 | 44 px minimum touch targets | ✅ v1 | 1 | |
| UX-09 | Installable PWA, standalone, own icon | ✅ v1 | 8b | Add to Home Screen |
| UX-10 | Offline shell — **the app only, never your figures** | ✅ v1 | 8b | **Changed.** Offline, the app opens and says it is offline, but shows no balances. Browser storage is shared by every app on `delca.noahapplication.com`, so figures kept there would outlive logout and be readable by other apps' scripts. See ARCHITECTURE.md §10.3 |
| UX-11 | Currency display — **PHP, fixed** | ✅ v1 | 8b | Single currency (ACC-11). No picker; `₱` and PHP grouping are formatting constants |
| UX-12 | "About your encryption" screen | ✅ v1 | 8b | What is protected, what is not, plain language |
| UX-13 | Offline writes with sync-on-reconnect | 🟡 Deferred | 9 | Genuinely hard — merging offline edits into an encrypted store |
| UX-14 | **Haptics** | ✅ v1 | 15 | **Built 2026-09-28.** A short vibration on a number-pad key, an entry saved or repeated, an entry deleted and a wrong PIN (`lib/haptics.ts`, `buzz`). `navigator.vibrate` - Android only; iOS Safari has no vibration for web pages and is left alone. *Vibrate on taps* in Settings → Appearance, on by default, kept with the other preferences on the server (`haptics`) |
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
| **SEC-14** | ↩️ **Reversed 2026-09-14 — no recovery phrase; an offline `.env` copy instead** | First decided *yes* and built in Phases 1–2 as a second DEK wrap under 12 BIP-39 words. Reversed because only the server side can lose `.env`, so the insurance belongs with the server owner (SEC-31), not on every user's paper. What moves: sign-up loses the words screen, recovery and "New recovery words" go, backups need only the master key, and a forgotten password is reset by an emailed link (SEC-30). The trade: losing `.env` and every copy is fatal for every account at once. The phrase was removed from the code and the database the same day, and the email reset was built with it |
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

Four second-order questions. **Confirmed 2026-09-14: all four kept as written
below.**

| Ref | Question | What I assumed, and why |
|---|---|---|
| **§13-A** | ~~Should the recovery phrase be re-viewable in Settings, or shown exactly once?~~ | **Closed as moot, 2026-09-14.** The build (8b) could not re-show it, because the words were never stored, and the phrase itself has since been removed (SEC-14) |
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

**Recovery phrase (SEC-14) — added, then removed on 2026-09-14.** It was a
*second* complete path to your data, and it made a sheet of paper as sensitive
as the master key for every user who wrote one down. It is replaced by an
offline copy of `.env` that the server owner keeps (SEC-31). What moves with it:
one wrapped key per user instead of two, no recovery flow, a password reset by
email (SEC-30), and backups that open with the master key alone.
What it costs: `.env` is now a single point of failure. Lose it and every copy,
and every account is gone at once, so the copy has to be real, current and
checked.

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
├── keys.enc               your dek_wrapped (under the master key)
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

Because `keys.enc` carries the wrapped DEK, the file is **standalone** wherever
the same master key exists: a new server, an empty database, and the offline
`.env` copy are enough to get everything back (DAT-16). Keep the file and that
copy apart. Each is harmless alone; together they are your data.

### The problem that makes this non-trivial

AAD binds every ciphertext to its own row `id` (ARCHITECTURE.md §5.3) — that is
what stops a DBA swapping your ₱5 coffee over your ₱50,000 rent. But it means a
restore **cannot simply reload rows**: a fresh database assigns new identity
values, and a payload moved to a new `id` fails to authenticate.

So only the import re-encrypts:

```
EXPORT — no key needed               IMPORT — needs your key
──────────────────────               ───────────────────────
copy each row exactly as stored      unwrap your DEK (.env master key)
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

> **There is no admin who can read your data in the app (SEC-18).** An
> administrator can create, disable and delete accounts. They cannot decrypt an
> account from the app, or reset its password: a reset link goes only to the
> account's own email (SEC-30), so the mailbox is what guards it. Outside the app, whoever holds `.env` and the
> database — the server owner — can read everything; with no per-user recovery
> secret, that is the honest shape of the design. If `.env` and every offline
> copy are lost, nobody can help anyone. That is the correct behaviour here,
> not a gap.

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

This section used to compare regenerating the recovery phrase (SEC-22) with
rotating the DEK (SEC-23). The phrase was removed on 2026-09-14, but the lesson
carries over unchanged to the key that remains: re-wrapping a key does not
revoke anyone who already unwrapped it.

### The two operations

| | **Rotate the master key** (`scripts/rotate_keys.py`) | **SEC-23 — Rotate the DEK** |
|---|---|---|
| Changes | The *wrap* on every user's DEK | **The data key itself** |
| Data re-encrypted | None | **Every row you own** |
| Speed | Milliseconds per user | Seconds to a minute |
| Run by | The server owner | You, from Settings |
| **Anyone who already unwrapped your DEK** | **Still has it. Still reads everything.** | **Locked out** |
| Use when | A copy of `.env` went somewhere you regret, but nobody could also reach the database or a backup | Someone may have held `.env` **and** the database or a backup — so may have unwrapped your key |

### Why the difference exists

The master key does not protect your data. It **unwraps the key** that protects
your data. Someone who held `.env` and a copy of the `users` table could unwrap
your DEK — a 32-byte value they can keep forever. Rotating the master key after
that is like changing the lock while the intruder walks around with a copy of
the key already cut.

```
Rotate master key                   Rotate DEK (SEC-23)
─────────────────                   ───────────────────
new master key in .env              NEW DEK generated
     ↓                                   ↓
re-wrap the SAME DEK                decrypt every row with old DEK
     ↓                              re-encrypt every row with new DEK
dek_wrapped updated                      ↓
old key → BUDGET_RETIRED_KEYS       re-wrap under the master key
old DEK:    UNCHANGED  ←── the gap        ↓
                                    old DEK:    now useless
```

After a real leak of `.env`, do **both, in this order**: rotate the master key
first, so no new DEK is wrapped under the leaked key, then rotate every user's
DEK. Then make a fresh offline copy and destroy the old ones.

### How rotation works

Row `id`s do not change, so AAD stays valid — it is a straight
decrypt-with-old, encrypt-with-new for every row. At personal scale (~10k rows)
this runs in **a single database transaction**: it either completes or nothing
changed. No half-rotated state, no `dek_version` column, no resume logic.

DEK rotation requires a password re-prompt, is audited, and ends every other
session (SEC-24) — leaving a stolen session alive would defeat the purpose.
Master-key rotation is a script the server owner runs, dry run first.

### What neither can undo

If someone already **exported and kept your data**, no key operation reaches it.

The same goes for **your own older backups.** A `.budgetbak` written before a
rotation still carries the old wrapped key, so it still opens with the old
master key, which stays in `BUDGET_RETIRED_KEYS`. After rotating because of a
compromise, take a fresh backup and delete the older files.
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
| **Month-by-month projection and card look-ahead** | ✅ Beyond the source app (§20) |
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
| Offline `.env` copy and password reset by email, not a recovery phrase | ✅ (SEC-30, SEC-31) |
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

---

## 20. Projection — seeing the months ahead

**Added 2026-09-13.** *"Set a monthly salary that carries into every next month,
so I can see a projection of my budgeting, and the deductions coming from
recurring credit-card payments."*

Most of this already existed. A salary is a recurring income rule (REC-01), and
card installments and subscriptions are recurring rules too (REC-14, SUB-00).
Two things were missing. The rules only ever looked **backwards**: they posted
on the due date, and nothing showed you next month before it arrived. The other
gap was a Philippine payroll: paid on the 15th and 30th, with raises that start
on a future date. REC-19 to REC-27 close both gaps.

### What goes in

| Input | From | Example |
|---|---|---|
| Salary | An income rule, semi-monthly (REC-19) | ₱25,000 on the 15th and 30th, into BDO Payroll |
| Raise | The rule's amount history (REC-20) | ₱27,000 per payday from Jan 1 |
| Bills | Standard expense rules | Rent ₱12,000 on the 1st, from BDO |
| Card charges | Subscription and installment rules on the card | Netflix ₱549 (5th) · phone ₱3,000 × 12, last one Dec 10 · motorcycle ₱5,000 (15th) |
| Everything else you spend | Your budget (§5) | ₱30,000 a month |
| Starting point | Cash on hand today (ACC-17) | ₱5,000 on Oct 1 |

### The month strip (REC-21, REC-23, REC-24)

| | Oct | Nov | Dec | Jan |
|---|---|---|---|---|
| Opening cash on hand | ₱5,000 | ₱25,000 | ₱45,000 | ₱65,000 |
| Salary | +₱50,000 | +₱50,000 | +₱50,000 | **+₱54,000** — the raise |
| Committed (rent, Netflix, phone, motorcycle) | ₱20,549 | ₱20,549 | ₱20,549 | **₱17,549** — phone paid off |
| Rest of the budget | ₱9,451 | ₱9,451 | ₱9,451 | ₱12,451 |
| Spending — the larger of budget and committed | −₱30,000 | −₱30,000 | −₱30,000 | −₱30,000 |
| **Closing cash on hand** | **₱25,000** | **₱45,000** | **₱65,000** | **₱89,000** |
| Lowest point | 🔴 **−₱20,000** · Oct 10 | ₱0 · Nov 10 | ₱20,000 · Dec 10 | ₱40,000 · Jan 5 |

**Why spending is the budget, not budget + committed.** Rent and card charges
already count against your budget when they post (REC-11). Adding them on top
would count them twice. If committed charges ever exceed the budget, the month
uses committed charges and is flagged as overcommitted: your plan no longer fits
your budget.

**Why October goes red while ending at ₱25,000.** Rent lands on the 1st and the
first salary only on the 15th. The low point assumes the flexible part of your
budget (₱9,451) could go any day, so it is set aside at the start of the month.
₱5,000 − ₱9,451 − rent − Netflix − phone = −₱20,000 by the 10th. The month-end
figure alone would never show that.

### The card look-ahead (REC-25)

For a card that closes on the 20th, with payment due on the 5th:

| Statement | Netflix | Phone | Motorcycle | Total | Due |
|---|---|---|---|---|---|
| Oct 21 – Nov 20 | ₱549 | ₱3,000 | ₱5,000 | **₱8,549** | Dec 5 |
| Nov 21 – Dec 20 | ₱549 | ₱3,000 · final | ₱5,000 | **₱8,549** | Jan 5 |
| Dec 21 – Jan 20 | ₱549 | — | ₱5,000 | **₱5,549** | Feb 5 |

The phone drops off after its 12th payment, and nothing is projected past an
installment's end (REC-16).

**The bill is not subtracted from cash on hand a second time.** Card charges
already reduced cash on hand on the day they posted (§19). Paying the bill moves
money from your debit account to the card, both counted, so it changes nothing.
The look-ahead tells you how much needs to be in the debit account by the 5th.

### Rules the projection keeps

- **It never writes.** A projected salary is not a transaction. Only
  `recurring_service` expansion posts, on the due date, as before (REC-22).
- **It cannot disagree with what posts.** Projection and expansion share one
  occurrence function. When November arrives, it posts exactly what the
  projection showed, unless you have changed a rule since.
- **It is computed, not stored.** It is recalculated on every view, inside your
  session, and never kept in the browser (SEC-29). No new table, and nothing
  new for backup or ID remapping (§15).
- **Paused rules** are listed but left out of the totals (REC-26).
- **Bonuses and 13th-month pay** use a yearly rule (REC-01). A single future
  item uses a rule that ends after 1 occurrence (REC-06).

### Decisions — confirmed 2026-09-14

All four kept as proposed.

| Question | Decision, and why |
|---|---|
| Should everyday spending come from the **budget** or from **past spending** (the STA-11 trend)? | **The budget.** It is the number you chose and can change. The trend reflects past mistakes and is noisy before you have three months of history |
| How far ahead? | **12 months**, with 3 and 6 available. A 36-month installment still shows its payoff date on its own card (REC-10) |
| Should the low point set aside the flexible budget on day 1? | **Yes**, the cautious reading. The alternative, spreading it evenly by day, shows a smaller dip that is easier to be surprised by |
| Carry-over (BUD-11) in future months? | **Ignored.** The projection assumes you spend exactly your budget, so there is nothing left to carry |

---

## 21. Credit cards — the bill, and a limit of your own

**Added 2026-09-13.** *"Add a purchase to September, get a statement of what to
pay next month, and set a monthly spending limit on the card so I don't
overspend with it."*

### Decided: purchases stay in the month you make them

A card purchase counts against the budget on its own date, as §19 already said.
A budget that waited for the bill would warn you a month late, after the money
was spent. Budgeting on the due date was considered and not chosen. The card
tracks everything about the bill **next to** the budget instead of moving
purchases into another month.

Purchases still count **once**, against the budget. The card's bill and limit
are views over the same transactions, never a second deduction.

### One card, one cycle

Statement closes on the **16th**, payment due on the **6th**, spending limit
**₱10,000**.

| Date | What happens | Budget | The card shows |
|---|---|---|---|
| Sep 13 | Buy ₱2,000 of groceries on the card | September −₱2,000 | Statement Aug 17 – Sep 16 |
| Sep 16 | Statement closes, card owes ₱12,300 | — | **₱12,300 due Oct 6** (ACC-19) |
| Sep 25 | Pay ₱5,000 from the debit account | — | **₱7,300 left, due Oct 6** (ACC-20) |
| Sep 30 | Day 14 of 30, ₱6,500 spent this cycle | Each purchase counted in September | 🟠 *Spending faster than the cycle is passing* (ACC-22) |
| Oct 1 | Pay the last ₱7,300 | — | ✅ **Paid**, reminder gone, even though the new cycle already holds ₱6,500 |
| Oct 8 | ₱8,000 spent this cycle | Counted in October | 🟠 *80% of your BPI Card limit* |
| Oct 14 | ₱10,000 spent this cycle | Counted in October | 🔴 *BPI Card is at its limit* |
| Oct 16 | Statement closes at ₱10,000 | — | **₱10,000 due Nov 6**. The new cycle starts with the whole ₱10,000 limit |

The pace warning on Sep 30 compares ₱6,500 (65% of the limit) with 14 of 30 days
passed (47%). The gap is more than the 10-point tolerance, so it warns while
half the cycle is still left to adjust.

### Why the statement cycle, not the calendar month

With the limit measured from the 17th to the 16th, **what you have spent
against it is exactly what the next bill will be.** A calendar-month limit would
split one bill across two limits and match neither. The cycle is independent of
the budget period (ACC-16), so a budget starting on the 1st and a card closing
on the 16th each keep their own dates.

### What the limit is not

- **Not the bank's credit limit (ACC-14).** That is what the bank lets you
  spend; this is what you allow yourself. Both show on the card.
- **Not a block.** The app never refuses a purchase you really made, since that
  would only make your records wrong. It warns in the add sheet (ACC-23) and on
  Home.
- **Not a second budget.** A ₱2,000 purchase reduces your September budget and
  counts toward the card's limit. It is one transaction, seen by two checks.
- **Recurring charges count.** Netflix and installment payments land on the bill,
  so they use up the limit. The card look-ahead (REC-25) shows how much of next
  cycle's limit is already committed before you spend anything.

### When the bill arrives — checking it against the bank (ACC-24..26, REC-28..30)

*"I only want to put in the bill, not every line on it."* The app already knows
what should be on the statement, because you entered the purchases on the day
you made them. So you type **one number, the bank's total**, and the app asks
about any difference.

**The phone, bought without knowing the interest.** BPI Card closes on the 16th.

| Date | What happens | The card shows |
|---|---|---|
| Sep 20 | Buy a phone: ₱40,000, 6 months. No interest entered | Plan ₱6,666.67 × 6 · *Terms not confirmed* (REC-28) |
| Sep 17 – Oct 16 | Payment 1 (₱6,666.67) plus ₱12,000 of other purchases | App's statement: ₱18,666.67 |
| Oct 17 | You enter the bank's total: **₱19,066.67** | Difference **+₱400.00** |
| Oct 17 | Suggested: *"Interest on the phone installment?"* → tap | ₱400 Interest posts Oct 16 · plan ₱7,066.67 × 6 · ✅ Checked |
| After | — | ₱35,333.33 left · 1 of 6 paid · payments 2–6 at ₱7,066.67, the last ₱7,066.65 |

From then on every payment posts as ₱6,666.67 Gadgets + ₱400 Interest (REC-30),
and the bill due on Nov 6 matches the bank to the centavo.

**Why the app asks instead of deciding.** One total cannot say *why* it is
different. The same ₱400 could be installment interest, a late fee, a forgotten
purchase, or a purchase the bank posted late. So the app offers the likeliest
reasons and records only what you choose:

| The difference is | Likely cause | Choice |
|---|---|---|
| Higher, and one unconfirmed installment is on this statement | Its interest | **Interest on this installment** (suggested) |
| Higher, no installment involved | Interest, late fee, annual fee | **One-time fee or interest** |
| Higher by a round purchase-like amount | Something not entered | **A purchase I forgot** |
| Lower, close to a purchase from the last 3 days | The bank posted it on the next statement | **Posted on the next statement** (ACC-26) |
| Lower, no recent purchase | A refund not yet entered | **A purchase I forgot**, as a refund. **Never interest** |

A difference can be split, for example ₱400 installment interest plus ₱150 late
fee. "Leave it" is always allowed: the difference stays on the card until
explained, but nothing blocks.

**Decisions — confirmed 2026-09-14.** Also decided that day: a refund made
after the statement closes reduces what is left to pay on it (ACC-20), and the
posting window is each card's own setting.

| Question | Decision, and why |
|---|---|
| Where do interest and fees go? | **Financial › Interest** and **Financial › Bank fees**, which are already in the default categories (CAT-07). You can pick another category |
| What date do they post on? | **The statement's closing date**, so they land on the statement that charged them and count in that budget period |
| How close to closing counts as "may post late"? | **Per card, starting at 3 days** — "Bank posting delay" in the card's settings, 0–10, editable any time. Most Philippine cards post within 1–3 banking days, but some are slower |
| When a second bill shows a different installment amount? | **Ask, and update the plan from that month** (REC-20). Earlier payments are never rewritten |

**Nothing new for backup (§15).** The bank's figures live in the card's
encrypted payload. Every resolution is an ordinary transaction, and the interest
link uses the existing `recurring_id`, which is already remapped.

---

## 22. Balance adjustments — when the app and the real balance disagree

**Added 2026-09-13.** *"When I edit the total amount on a card and save, ask
whether to record it as a loss or a gain, and keep an audit trail only if I
accept."*

### Why this is needed

A balance is never stored. It is the opening balance plus every transaction
(ACC-04). Until now the only editable figure was the opening balance, and
changing it **silently shifts every balance back to the day the account was
opened.** Real balances drift anyway: cash goes missing, an e-wallet fee never
gets entered, a coin jar gets counted.

### What it is called

**Balance adjustment**, shown as **Unrecorded loss** when it lowers the balance
and **Unrecorded gain** when it raises it. "System loss" was considered, but it
reads as if the app lost the money. The difference is really money that moved
without being entered.

### The question on save

The Wallet (cash) account says ₱2,450; you count ₱2,100 and save that.

```
Wallet   ₱2,450.00 → ₱2,100.00
Difference            −₱350.00

[ Record as unrecorded loss ]        recommended
[ Fix the opening balance instead ]
[ Cancel ]
Note (optional): ____________
```

| Choice | Balance | History before today | What is kept |
|---|---|---|---|
| **Record as unrecorded loss** | ₱2,100 from today | Unchanged | A −₱350 adjustment on the ledger, dated today, **plus an audit entry**: before, after, difference, note |
| **Fix the opening balance instead** | ₱2,100 | Every past balance shifts by −₱350 | No adjustment, **no balance audit entry**. Meant for a mistake made when the account was set up |
| **Cancel** | ₱2,450 | Unchanged | Nothing |

**Credit cards** use the same question, with the field reading **amount owed**:
owing more is a loss, owing less is a gain. A difference found on a bill should
go through the statement check (ACC-24) instead, because that can say *what*
the difference was.

### What an adjustment counts toward

**Decided 2026-09-14: the budget stays the same.** (Briefly changed that day
to "a loss counts as spending", then changed back.)

| | Unrecorded loss | Unrecorded gain |
|---|---|---|
| Account balance and cash on hand (ACC-17) | ✅ lowers them | ✅ raises them |
| Budget and daily allowance | ❌ unchanged | ❌ unchanged |
| Spending and income in Stats, the day's totals | ❌ | ❌ |
| A card's spending limit (ACC-21) | ❌ | ❌ |
| The ledger, labelled **Unrecorded loss / gain**, and an **Adjustments** total in Stats | ✅ | ✅ |

**Why the budget stays the same:** the app does not know what the money was,
and counting it as spending would be a guess inside every report. The balance
still tells the truth about what you have. If you later remember the ₱350 was
lunch, delete the adjustment and enter the lunch — then it counts, in Food.

**Undo is delete only** (soft, audited, TXN-14). An adjustment cannot be edited:
its audit entry recorded the before and after, and a changed amount would
contradict it.

### Decisions — confirmed 2026-09-14

| Question | Decision, and why |
|---|---|
| Should an unrecorded loss reduce the budget? | **No — the budget stays the same**, as first proposed. See the table above |
| What date does it post on? | **Today**, the day you noticed. Never backdated |
| The ordinary "account edited" audit entry | **Still written on every save, as today.** It says that the account changed (name and type, no amounts). The trail with the money — before, after, difference — exists only when you accept. Say if even the plain entry should be skipped when you decline |
| Investment accounts? | **Not included.** Typing a new value there is already a dated valuation (ACC-13) |

**Nothing new for backup (§15).** An adjustment is a transaction, so it is
exported, remapped and restored like any other. CSV writes its type as
`adjustment`.
