# BUDGET APP — Roadmap: what comes after Phase 10

> **The tracker for everything not built yet.** Added 2026-09-28 (user: "add it
> to a file so we can remember it if this feature is already built").
> [FEATURES.md](FEATURES.md) is the catalogue of what the app does and holds the
> 🟡 Deferred rows; this file takes those rows, adds the new ideas, and puts them
> all in build order as Phases 11–15. When a feature is built, tick it here AND
> move its row in FEATURES.md to ✅ (new IDs get a FEATURES.md row the day they
> are built, with the user's words, the way every other row has them).
>
> Feature IDs continue the FEATURES.md numbering and are reserved here — quote
> them in code comments like any other ID.

## Status legend

| Mark | Meaning |
|---|---|
| ⬜ | Not started |
| 🔨 | In progress |
| ✅ | Built — write the date and the commit beside it |
| ⏸️ | Parked — a decision or someone else is needed first (reason given) |

**Sizes** are rough: **S** ≈ a day, **M** ≈ 2–4 days, **L** ≈ a week or more.

**Before Phase 11:** Phase 9's checklist in [phases.md](phases.md) still has
open items that protect the data itself — a backup restored once, a `.env`
restore rehearsed, master-key rotation rehearsed on a copy, the IIS deploy, and
a second place for automatic backups. None of the features below blocks them,
but a feature is worth little if the data behind it cannot be recovered.

---

## Summary

| ID | Feature | Source | Phase | Size | Status |
|---|---|---|---|---|---|
| **TXN-24** | Merchant memory — suggest merchant, pre-pick its category | new (#2) | 11 | S | ✅ 2026-09-28 |
| **TXN-25** | Recently deleted, and Undo after a delete | new (#3) | 11 | M | ✅ 2026-09-28 |
| **BUD-17** | Suggested budget from your recent spending | new (2026-09-28) | 11 | M | ✅ 2026-09-28 |
| **GOA-05** | Required-per-month for a goal | deferred | 11 | S | ✅ 2026-09-28 |
| **SUB-07** | Cancellation tracking | deferred | 11 | S | ✅ 2026-09-28 |
| **STA-10** | Cash on hand over time | deferred | 11 | S | ✅ 2026-09-28 |
| **CAL-07** | Upcoming bills and charges on the calendar | new (#4) | 12 | M | ⬜ |
| **REC-27** | What-if: try a plan before committing | deferred | 12 | M | ⬜ |
| **REC-35** | Debt payoff planner (snowball vs avalanche) | new (#5) | 12 | M | ⬜ |
| **CAL-06** | Week and year calendar views | deferred | 12 | M | ⬜ |
| **GOA-09** | Sinking funds for once-a-year costs | new (#6) | 13 | M | ⬜ |
| **GOA-10** | Emergency-fund cover ("X months") | new (#7) | 13 | S | ⬜ |
| **GOA-11** | Emergency-fund advisor — rule-based target | new (#7) | 13 | M | ⬜ |
| **GOA-12** | Payday prompt — set money aside when income lands | new (#8) | 13 | M | ⬜ |
| **ACC-41** | Check a debit / savings account against the bank | new (#9) | 14 | M | ⬜ |
| **STA-12** | Monthly review | new (#12) | 14 | M | ⬜ |
| **SEC-32** | Sign-in activity and open sessions | new (#11) | 14 | M | ⬜ |
| **SEC-12** | Biometric unlock (WebAuthn / Face ID) | deferred | 14 | L | ⬜ |
| **DAT-09** | PDF / Excel export | deferred | 15 | M | ⏸️ |
| **DAT-20** | Nightly server backup via Task Scheduler | deferred | 15 | S | ⏸️ |
| **UX-13** | Offline writes with sync-on-reconnect | deferred | 15 | L | ⏸️ |
| **UX-14** | Haptics | deferred | 15 | S | ⬜ |
| **UX-15** | Multi-language | deferred | 15 | L | ⬜ |

**Deliberately NOT on this list** (still ❌ Out in FEATURES.md, for the reasons
written there): push notifications (BUD-16), bank sync (ACC-10), receipt OCR and
voice entry (TXN-18/19), multi-currency (ACC-07/11), shared budgets (UX-18),
widgets and Siri (UX-16/17), a plaintext full archive (DAT-18).

---

## 📦 PHASE 11: Quick wins over data the app already has

### 🎯 Objective: Six features built from data the app already has — no new table

> **✅ Built 2026-09-28** — all six, 87 new backend tests (846 in all, 0 failed),
> checked in the browser on a local in-memory copy. FEATURES.md has each row.
> Where the build differed from the plan below:
> - **TXN-24:** the add sheet had NO merchant field; the user chose a
>   **Merchant tile** beside Add note (over learning from notes). Editing an
>   entry used to wipe its merchant - the sheet now sends it back.
> - **TXN-25:** a plan payment (REC-32) is refused, not routed through
>   recurring_service. A restore is refused with its reason for an archived
>   account and a deleted category too. Nothing is purged after 30 days - the
>   list just stops showing it.
> - **SUB-07:** "saved" leaves out any occurrence that DID post, so a
>   cancellation entered late never claims money that was really spent.
> - **STA-10:** plain balances, as recommended - the card says so.

| ID | Feature | Status |
|---|---|---|
| TXN-24 | Merchant memory | ✅ 2026-09-28 |
| TXN-25 | Recently deleted + Undo | ✅ 2026-09-28 |
| BUD-17 | Suggested budget | ✅ 2026-09-28 |
| GOA-05 | Required-per-month | ✅ 2026-09-28 |
| SUB-07 | Cancellation tracking | ✅ 2026-09-28 |
| STA-10 | Cash on hand over time | ✅ 2026-09-28 |

### TXN-24 · Merchant memory
Typing a merchant offers the ones you have used before (most-used first), and
picking one pre-selects the category — and sub-category — you used with it LAST
time. Two taps become one on the entries you make every week.

- **Server:** `GET /transactions/merchants` — built from
  `transaction_service.views()` over the working set: normalised name (trimmed,
  case-folded, inner spaces collapsed) → display spelling, count, last category
  id, last account id. Merchant is encrypted (TXN-08), so this can only ever be
  Python over the cache, never SQL.
- **Client:** its own key in `lib/queryKeys.ts`; lives in the query cache only
  (invariant 10 — never persisted). Reloaded by `afterWrite(...MONEY)`.
- **Rules:** a suggestion never overwrites a category the user already picked;
  a split entry suggests nothing (which split would it be?). Also offered on the
  CSV import mapping (DAT-03) as the category for unmapped rows.
- **Tests:** normalisation, "last used wins over most used", archived category
  is never suggested.

### TXN-25 · Recently deleted, and Undo
Deleting is already a soft delete (TXN-14), and `TransactionRepository.undelete()`
already exists — what is missing is a way back in the UI.

- **Undo:** after Delete in `TransactionPreview`, a toast with *Undo* for a few
  seconds. Undo calls the same restore endpoint.
- **Recently deleted:** More → *Recently deleted* — the last 30 days, newest
  first, each with *Restore*. `GET /transactions/deleted`,
  `POST /transactions/{id}/restore`, through `transaction_service` so the
  working set is updated after COMMIT like every other write, and `afterWrite(...MONEY)`.
- **Traps to design for, each needs a test:**
  - A transaction HIDDEN by an installment conversion (REC-34, `converted_to`)
    is not "deleted" and must never be listed or restored here — *Convert back*
    is its only way back.
  - Pairs come back together: both legs of a transfer, and a cashback pair
    (TXN-22), in one commit.
  - A plan payment (REC-32) whose extra part lives in the plan's `prepayments`:
    restoring the transfer alone would leave the plan disagreeing with it.
    Either restore through `recurring_service` or refuse with a reason.
  - A recurring or interest entry carries `recurring_on` / `interest_on`, so the
    catch-up will not post it a second time — restoring it is safe; test it.
  - A balance adjustment (ACC-29) restores with an audit entry, like its delete.
- **Open question:** purge after 30 days, or keep forever and only *list* 30?
  (Default: keep — soft delete exists so the audit trail stays honest.)

### BUD-17 · Suggested budget from your recent spending
Added 2026-09-28 (user: *"an auto budget feature that already suggests a budget
based on your last month/s data"*). *Suggest from my spending* on the Budget
screen — and on the empty state when there is no budget yet — fills in a
total and an allocation per category from the last finished periods. You look
it over, change anything, and save. **It suggests; it never sets a budget on its
own**, the same ask-first bargain as ACC-28 and the cashback suggestion (ACC-38).

**What it reads** — exactly what the budget itself counts, so the suggestion and
the progress bars can never disagree:

- The **expense splits** of the last **1, 3 or 6 FINISHED periods** (default 3),
  cut on the budget's own rhythm (`budget_period()`: monthly from the month
  start day, weekly, or custom). No budget yet → the user's Settings defaults,
  as `create_budget` already does. The current, unfinished period is never used.
- Income, transfers and balance adjustments are not spending here either
  (ACC-29), so they are left out. Recurring and installment payments ARE
  spending (REC-11) and count.
- Sub-category spending rolls up into its main category, because an allocation
  on a parent covers its children (`_category_progress`).

**The rules** (to confirm with the user before building):

| Rule | What it does |
|---|---|
| **Typical spend** | The **median** per period for each main category, so one big purchase does not set next month's budget (decided 2026-09-28). With only 1 period chosen, that period's figure. The average is shown beside it on each line, for comparison only |
| **Already scheduled is the floor** | Never below what recurring charges, subscriptions and installment payments will charge that category next period (from `occurrences()` — budget_service reaches `recurring_service` through a lazy import, as it already must) |
| **Occasional categories** | Spent in fewer than half the periods → not given an allocation of their own; its median goes into the unallocated buffer and the line says *"only 1 of 3 months"*. Yearly costs belong in a sinking fund (GOA-09), and the line says so |
| **Rounded up** | Each allocation rounded UP to **the step chosen in Settings** (decided 2026-09-28) — budgets are round numbers, and rounding down would start you over. A new preference, `budget_round_step`, one of ₱1 · ₱10 · ₱50 · ₱100 · ₱500 · ₱1,000, **default ₱100**; ₱1 means round to the peso only. Validated in `preferences_service` beside `budget_period`, encrypted like every preference, loaded into `preferencesStore` after unlock (never in the browser). The Suggest screen can change it for one suggestion without saving it |
| **Total** | Sum of the allocations + the unallocated buffer (the median of spending in categories with no allocation), rounded up the same way |
| **Existing allocations** | A category you already budget with no spending in the window is KEPT at its amount, marked *"no spending in 3 months — keep or remove?"* — you put it there for a reason |
| **Income check** | If the total is more than your median income over the same periods, say so, and offer *Fit to my income*: scale the categories above their scheduled floor down until it fits. Never touches the floor |
| **Optional trim** | *Spend 5% / 10% less*, the same scaling, never below the floor |

**What the screen shows:** each category with its last periods side by side
(*₱4,200 · ₱3,900 · ₱5,100*), the suggestion, and one reason (*"median of 3
months"*, *"₱1,200 already scheduled"*, *"only 1 of 3 months"*), next to what
is budgeted now. Every line is editable before saving.

**How it is built:**

- A pure module, `app/services/budget_service/suggest.py`, beside
  `allowance.py` and `carry_over.py`: plain inputs (spends, the category tree,
  the periods, the scheduled floor per category, income per period) → a
  suggestion with a reason per line. Tested directly, one test per rule.
- `GET /budgets/suggestion?periods=3&today=…` (the client's `today`, as every
  budget endpoint takes) returns the preview and **writes nothing**. Its own key
  in `lib/queryKeys.ts`; never persisted.
- **Save goes through the existing writers**, `create_budget` /
  `update_budget` with `allocations` — never a new one. So the amount history
  behaves as it does today: the new amount applies from today, a finished
  period is never rewritten, and carry-over (BUD-11) is untouched.
  `afterWrite(...)` with the budget group after saving.
- Money is `Decimal` throughout; the median of an even count is the mean of
  the middle two, quantised to the centavo before rounding up.

**Not enough history:** less than one finished period → the button explains
why and offers nothing. Fewer periods than chosen → it uses what exists and
says *"based on 2 months"*.

**Decided (user, 2026-09-28):**

1. **Suggest only.** There is no auto-adjust mode: the budget never changes
   without a tap, like every other figure in the app.
2. **Median**, with the average shown beside it for comparison.
3. **The rounding step is a Settings preference** (`budget_round_step`,
   default ₱100) — see *Rounded up* above.

4. **The period-start reminder is in, with a switch** (user, 2026-09-28 —
   option 1 plus option 3's switch). It only OPENS the suggestion, so it keeps
   "suggest only":

   > **Your spending has changed**
   > Your last 3 months averaged ₱35,500 · your budget is ₱30,000
   > **[Review budget]** **[Not now]**

   | Rule | Value |
   |---|---|
   | Compares | The suggested TOTAL with the budget in force — never category by category (the suggestion screen shows those) |
   | Fires when | They differ by more than **15%, either way** — a budget too loose is wrong too |
   | Needs | **3 finished periods** of history, so one odd month cannot trigger it |
   | When | The first **3 days** of a new period, then it goes away by itself. A **weekly** budget is checked once a month, not every week |
   | Where | Home, beside the other alerts: computed in-session on open, never pushed (BUD-12, BUD-16). No badge on the tab bar — it is advice, not an alert about money |
   | *Review budget* | Opens the suggestion screen filled in; nothing is saved until Save there |
   | *Not now* | Hides it until the next period. Remembered ON THE SERVER, in the budget's payload (`suggestion_dismissed_for`: the period's start date) — invariant 10 forbids browser storage, and it also means dismissing on the phone hides it on the PC |
   | **Switch** | Settings → *Remind me when my spending changes*, a new preference `budget_suggestion_nudge`, **on by default**. Off → never shown; the button still works |

   Built as a pure check beside `alerts.py` (plain inputs: the suggested
   total, the amount in force, the period, how many periods of history, the
   dismissed-for date), tested for each row above — including that a
   dismissal for the last period does not hide this one.

Goes with STA-12 (the monthly review can end with *Adjust next month's
budget*) and shares its per-period, per-category spending with GOA-10/11's
*essential monthly spending* — build that helper once.

### GOA-05 · Required-per-month
*"₱4,200 a month to reach ₱50,000 by June."* `(target − set aside) ÷ months
left`, rounded UP to the centavo, shown on the goal's card. With no target date,
nothing is shown. Pure function, used again by GOA-09, GOA-11 and GOA-12.

### SUB-07 · Cancellation tracking
*Cancel* on a subscription ends the rule (REC-06 end date), keeps it listed
under *Cancelled* with the date, and shows *"saved ₱1,650 since March"* — the
charges that would have posted since, from `occurrences()` (never its own date
logic). An optional *remind me to cancel by* date shows on Home in-app (SUB-06
model — no push).

### STA-10 · Cash on hand over time
A line on Stats: the running balance of the accounts counted in cash on hand
(ACC-18), rebuilt from postings already stored. **Uses the switches as they are
TODAY** (say so under the chart — history of a switch is not kept). Card bills
(ACC-35) and loan dues (ACC-40) make "cash amount" differ from "balance" — pick
one and label it; recommendation: plain balances of counted accounts, because a
past day's typed-bill state cannot be reconstructed.

---

## 📦 PHASE 12: Looking ahead

### 🎯 Objective: The schedule the app already knows, shown where you plan

| ID | Feature | Status |
|---|---|---|
| CAL-07 | Upcoming on the calendar | ⬜ |
| REC-27 | What-if | ⬜ |
| REC-35 | Debt payoff planner | ⬜ |
| CAL-06 | Week and year views | ⬜ |

### CAL-07 · Upcoming bills and charges on the calendar
Days after today show what is scheduled, faded: recurring charges and income,
subscriptions, installment payments, card bills (ACC-35) and loan dues (ACC-40).
Tapping a future day lists them; each opens its plan.

- **One schedule:** the items come from `GET /projection` (already in the query
  cache for Months ahead), which reads `occurrences()`. `calendar_service` must
  NOT import `projection_service` — "projection_service is imported by nothing"
  (CLAUDE.md). Overlay on the client, or have the endpoint layer combine the two.
- Future days never add to the month total in the header (CAL-05), which stays
  what was actually spent; show *"₱X scheduled"* beside it.

### REC-27 · What-if
*"Can I afford a phone at ₱3,000 × 12?"* Months ahead gets *Try a plan*: the
same rule sheet, but nothing is saved — the unsaved rule is sent to a
`POST /projection/what-if` that runs the projection with it added and returns
both versions. Show the difference month by month and the new lowest point
(REC-24). Writes nothing, ever; *Save this plan* hands off to the normal create.

### REC-35 · Debt payoff planner
Every card, loan and borrowed account side by side, with an extra amount a month
you could pay: when each is cleared and the order to pay them in.

- **Snowball** — smallest balance first. Needs nothing new.
- **Avalanche** — highest interest first. Needs an optional **annual rate** on a
  card / loan account (a new payload field, a RATE: four places,
  `toRateString`, never money helpers). Without rates, only snowball is offered.
- Installment plans keep their fixed schedule; extra money on a plan means REC-32
  (lower or shorten), and the planner says which it assumed.
- Pure function (`app/core/utils/payoff.py`, like `interest.py`), writes
  nothing, starts from `owedWithPlans` — the same figure ACC-34 fixed on 2026-09-21.
- The app still never calculates a card's real interest (ACC-19): the planner's
  interest is an estimate from the rate you typed, and says so.

### CAL-06 · Week and year views
Week: seven days with each day's entries listed. Year: twelve small month
heatmaps with month totals. Same `transaction_service.views()` rules as the
month (expense and income splits only).

---

## 📦 PHASE 13: Money set aside, and a safety net

### 🎯 Objective: Goals that plan ahead, built on GOA-08's set-aside money

| ID | Feature | Status |
|---|---|---|
| GOA-09 | Sinking funds | ⬜ |
| GOA-10 | Emergency-fund cover | ⬜ |
| GOA-11 | Emergency-fund advisor | ⬜ |
| GOA-12 | Payday prompt | ⬜ |

### GOA-09 · Sinking funds
For costs that come once a year — insurance, vehicle registration, school fees,
Christmas. A goal with `kind: sinking`, an amount, a due date and *repeats
yearly*. It shows what to set aside each month (GOA-05) and whether this month's
part is done. When the cost is paid, *Use it* releases the money (GOA-08) and a
repeating fund starts again for next year.

- **Can follow a rule:** link it to a yearly recurring rule and its amount and
  date follow that rule's next occurrence (from `occurrences()`). Offer to create
  one for every yearly rule that has none.
- Set-aside only, like GOA-08: no transaction, the balance never moves, cash on
  hand counts only what is available.

### GOA-10 · Emergency-fund cover
One figure: *"Your emergency money lasts 2.4 months."*
`emergency money ÷ essential monthly spending`.

- **Emergency money:** a goal marked *emergency fund* if one exists (what it has
  set aside), otherwise cash on hand. Open question: allow both, with a switch?
- **Essential monthly spending** — defined once and shared with GOA-11: the
  average over the last 6 full months of committed outgoings (recurring bills,
  subscriptions, installment and loan payments) plus spending in categories
  flagged **essential**. Needs a new `essential` flag on a category (a payload
  field, no migration); the default set (CAT-07) marks rent, utilities,
  groceries, transport, health and education. No flags set → 70% of average
  spending, and the screen says it is guessing.
- Shown on the Accounts tab beside cash on hand, coloured by GOA-11's target.

### GOA-11 · Emergency-fund advisor (rule-based)
**Suggests how big your emergency fund should be, and explains every reason.**
Rule-based on purpose, not an AI model: no figure may leave the encryption
boundary (§5), rules can be tested to the centavo, and each suggestion can say
exactly *why*.

**Inputs.** Derived from the working set:

| Input | How |
|---|---|
| Essential monthly spending `E` | GOA-10's definition |
| Income swing | coefficient of variation of monthly income, last 12 full months |
| Income sources | distinct income categories / income rules seen in the last 6 months |
| Months with no income | count in the last 12 |
| Debt load | monthly dues (card `due_now`, loan dues, installment payments) ÷ average income |

Plus three questions, asked once and kept as encrypted preferences:
work type (regular employee / contractual or project-based / self-employed or
freelance), dependents (0 / 1–2 / 3+), and earners in the household (1 / 2+).

**Rules** (a starting point to confirm with the user before building):

| Rule | Months |
|---|---|
| Base: regular employee | 3 |
| Base: contractual / project-based | 6 |
| Base: self-employed / freelance | 6 |
| Income swings more than 25% month to month | +1 |
| …more than 50% | +2 (instead of +1) |
| Only one income source | +1 |
| A month with no income in the last 12 | +1 |
| Dependents 1–2 / 3+ | +1 / +2 |
| Two or more earners in the household | −1 |
| Debt payments above 30% of income | +1 |
| **Clamp** | **3 to 12** |

**Output:** *"Aim for 6 months — ₱108,000 (₱18,000 of essentials a month).
You have ₱43,200 (2.4 months)."* Below it, every rule that fired, in one line
each, and *"₱5,400 a month reaches it in 12 months"* (GOA-05). A button creates
or updates the emergency-fund goal with that target — never on its own.

- **Pure function** in `app/core/utils/` (like `interest.py`): plain inputs in, a
  target, a month count and the list of fired rules out. Table-driven tests, one
  per rule, plus the clamp.
- **Wording:** a guide, not financial advice — say so once on the screen.
- Too little history (under 3 months of income) → the base rule only, and it
  says why.

### GOA-12 · Payday prompt
When income lands (a recurring salary posting, or an income entry above a
threshold you set), Home shows a card: *"₱25,000 arrived. Set some aside?"* with
a split pre-filled from each goal's GOA-05 monthly need (sinking funds and the
emergency fund first). One tap sets each part aside through `goal_service.add_money`.

- **Suggests, never moves on its own** — the same bargain as the cashback
  suggestion (ACC-38).
- **"Already answered" must be stored on the server** (invariant 10 forbids
  browser storage): a `set_aside_prompted` marker on the income transaction's
  payload, or a list in preferences. Open question — the payload is simpler and
  goes with the entry if it is deleted.
- Never more than is available (GOA-08's rule), and never on a transfer.

---

## 📦 PHASE 14: Checking, reviewing, and securing

### 🎯 Objective: Trust the numbers, look back on a month, and see who is signed in

| ID | Feature | Status |
|---|---|---|
| ACC-41 | Check a debit / savings account | ⬜ |
| STA-12 | Monthly review | ⬜ |
| SEC-32 | Sign-in activity | ⬜ |
| SEC-12 | Biometric unlock | ⬜ |

### ACC-41 · Check a debit or savings account against the bank
What ACC-24 does for a card, for every other account: type the bank's balance
for a day, the app shows its own closing balance for that day and the
difference. **One number, not every line.** A match is ✅ Checked with the date.

- A difference offers: **a transaction I forgot** (add sheet, amount filled in),
  **record as a balance adjustment** — through the ONE existing path,
  `account_service.update_account` after `BALANCE_DIFFERS` (ACC-28), never a new
  writer — or **leave it** (stays visible on the account).
- Checks are kept as a dated list in the account's payload (`balance_checks`);
  the difference is recalculated every time, never stored. Add the field to
  `backup_service/references.py` only if it ever holds an id.
- Account page shows *"Last checked 12 Sep ✅"*; an old check goes stale after
  a month. Open question: add per-transaction *cleared* ticks later? (Default: no.)

### STA-12 · Monthly review
A screen for a finished month, reached from Stats and offered on Home in the
first days of a new month:

- Budget result: under / over, by how much, and the carry-over if on (BUD-11).
- The three categories that changed most against the month before.
- New subscriptions and price changes (SUB-08), plans that started or finished.
- Biggest purchases, cashback earned (TXN-22), interest earned (ACC-37).
- Cash on hand at the start and the end (STA-10's series).
- Net worth change only if it can be rebuilt honestly — investment values are
  dated (ACC-13), typed card bills are not; otherwise leave it out.

All from `stats_service` over the working set; nothing stored.

### SEC-32 · Sign-in activity and open sessions
Settings → Security: the devices signed in now, and recent sign-ins.

- **Open sessions** = live refresh-token families: when it started, when it was
  last used, and a device label (*"Chrome on Android"*). **Needs a new column**
  `device_label` on `refresh_tokens` (Shape A, Alembic migration) — a coarse
  label parsed from the User-Agent at sign-in, never the raw string. Existing
  sessions show *"Unknown device"*.
- **Sign this device out** revokes that family (`revoke_reason = user`), the same
  mechanism SEC-24 uses; *Sign out everywhere else* revokes all but the current.
- **Recent sign-ins** — successes and failures from `login_attempts` / the audit
  log. IPs are stored only as hashes, so the most the screen can say is *"same
  network as now"* or *"a different network"*; do not start storing raw IPs.
- Nothing financial is involved; this reads Shape A tables only.

### SEC-12 · Biometric unlock (WebAuthn / Face ID)
Unlock the lock screen with a passkey instead of typing the PIN. Already
sketched: `BIOMETRIC_WEBAUTHN_ENABLED=False`. Adds a server dependency (a
WebAuthn library) — a decision for the user, like any dependency. It must bring
the key back through the SAME path the PIN does (SEC-27 — read
`auth_service/pin_service.py` first) and must never become a second way to
unwrap a DEK. The PIN always stays as the fallback.

---

## 📦 PHASE 15: Larger or optional — needs a decision first

| ID | Feature | Status | What has to happen first |
|---|---|---|---|
| DAT-09 | PDF / Excel export | ⏸️ | A second deliberate opening in the encryption boundary; DAT-18 chose to keep exactly one. Needs the user's decision, and DAT-02's warning every time |
| DAT-20 | Nightly backup via Windows Task Scheduler | ⏸️ | Someone with admin rights on the server must create the task. Writing a backup needs no key, so the script side is small |
| UX-13 | Offline writes, synced on reconnect | ⏸️ | Queuing a write in the browser means storing it there, which invariant 10 / SEC-29 forbids. Blocked unless that decision changes |
| UX-14 | Haptics | ⬜ | Nothing — `navigator.vibrate` on Android; iOS Safari ignores it |
| UX-15 | Multi-language | ⬜ | Every string pulled out of the components first; large, and English-only has been fine |

---

## When a feature here is built

1. Tick it in the Summary AND in its phase table: ✅ with the date and commit.
2. Add or move its row in [FEATURES.md](FEATURES.md) (a new ID gets its first
   row, marked ✅ v1 with the phase), and update the Summary counts there.
3. Add the phase to [phases.md](phases.md)'s deliverables checklist.
4. If it touches a payload reference, `backup_service/references.py` (CLAUDE.md,
   *Backup*). If it changes the frontend, `npm run build` and commit
   `app/web/static/dist/` (invariant 9).
