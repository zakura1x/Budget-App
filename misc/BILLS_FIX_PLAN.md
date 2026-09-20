# Card bills & Months ahead — findings and fix plan

Written 2026-09-19, from the three issues reported on credit-card Bills (ACC-35)
and Months ahead (REC-21..26). Each section ends with the decision(s) needed.

## Status — decided and built 2026-09-19

| Decision | Answer | Result |
|---|---|---|
| D1 | A | *Not on a bill yet* row + *Card owes* total in the Bills section, with a tap-to-read explanation. |
| D2 | Yes | The current rule stands: purchases dated before the list are inside the typed bills. They now show on the bill as *already in the card app's figure*. |
| D3 | No | No double count; Aerox TG's unbilled payments are rightly on top of the balance. Nothing to fix. |
| D4 | A | Plans and purchases already in the typed figure are listed, greyed out, and never added. |
| D5 | A | The payments that settled a bill are listed on it (oldest bill first, one payment can split across bills). |
| D6 | B | Cards without typed bills: later, separately. |
| D7 | A | Each bill is taken in the month it is due; each month says what Home will hold back at its end. |
| D8 | A | *Card statements ahead* shows a billed card's bills, each opening its lines. |

Also fixed: a payment made on the day the list was saved, before typing it, is
no longer applied twice (`bills_cover_payments`, registered in backup references).

With D2 = yes and D3 = no, the whole ₱1,889.57 on SPayLater is part A: the
balance holds ₱1,889.57 that no typed bill lists yet. The app now shows it as
*Not on a bill yet*.

**Follow-up question (D3 note, 2026-09-19):** "should the opening balance update
when a purchase is made?" No. The balance is always *opening balance +
every transaction after it*, so a purchase already moves what the card owes, and
changing the opening balance as well would count it twice. The mismatch came from
the opening balance and the bill list being typed from two different screens of
the card's app. A possible follow-up, **D9 (not built)**: when you save a bill list
whose total differs from the card's balance, offer once to *match the balance to
the bills* using the existing balance-adjustment question. Say if you want it.

The figures below were read from your real data (user 20) with a read-only
script that runs the same service code as the card page (rolled back, nothing
written), as of 2026-09-19.

---

## Issue 1 — Bills do not add up to what the card owes

### What you see

| Card | Owed (tile) | All bills left | Gap |
|---|---:|---:|---:|
| Maribank | ₱7,006.77 | ₱7,006.77 | **₱0.00** ✓ |
| SPayLater | ₱19,573.00 | ₱17,683.43 | **₱1,889.57** ✗ |

The tile shows `owed_with_plans` (balance owed + installments not yet billed,
REC-14). The Bills section shows only the bills: what you typed, plus plans
and purchases added after the list was saved. Nothing on the page shows the
difference, so the two numbers look contradictory.

### Where SPayLater's ₱1,889.57 comes from

| Part | Amount | Why it is on no bill |
|---|---:|---|
| **A.** Opening balance the typed bills do not explain | ₱1,522.57 | The opening balance is ₱18,237.00; the four typed bills (15 Oct → 15 Jan) total ₱16,714.43, and ₱46.00 of that is the Aerox TG plan. The card's app probably lists only the next few bills, while its "used" figure also holds payments due **after** 15 Jan 2027. Those later payments are owed but no bill was typed for them. |
| **B.** Two purchases on 17 Sep (₱180 + ₱141) | ₱321.00 | They were dated **before** the list was saved (18 Sep), so `_bills` treats them as already inside the typed bills ("the card's app had it") and drops them. If SPayLater's 15 Oct bill did *not* include them yet, they are missing from the bills. |
| **C.** Aerox TG plan's unbilled payments | ₱46.00 | The plan existed before the list, so its payments are counted **inside the typed bills**, and `unpaid_installments` adds them to the tile as well. If the ₱18,237 opening balance already includes them, the tile counts ₱46 twice. |

Maribank has none of these: its opening balance plus later purchases match the
two typed bills exactly.

### Root cause

The bills and the balance come from two unrelated sources (the card app's
list vs. the ledger), and the page never compares them. Any difference,
whether real (bills not typed yet) or a double count, stays hidden.

### Proposed fix

1. **Add a reconciliation row to the Bills section** so it always adds up to
   the card's owed figure:

   ```
   Due now — counted in cash on hand      ₱8,619.21
   All bills left                         ₱17,683.43
   Not on a bill yet                       ₱1,889.57   ← new, tappable
   ─────────────────────────────────────────────────
   Card owes (same as the tile)           ₱19,573.00
   ```

   Tapping *Not on a bill yet* explains the parts (A/B/C above) in plain
   words. This is derived on every read and never stored, like everything
   else on the bills. Server: `CreditView.unbilled` (+ a breakdown list).
   Client: `CardBills.tsx`.
2. **Fix the two real bugs behind B and C**, depending on your answers below.
3. **One more bug found along the way:** payments into the card are applied
   to the bills when they are dated **on or after** the day the list was saved.
   A payment made *earlier that same day*, before typing the list, is
   already missing from the card app's list and gets applied a second time,
   so the bills come out too low. The fix is the one used for purchases on
   2026-09-17: the saved list names the payments it already reflects
   (`bills_cover_payments`), and only the others settle bills. This change
   also has to be added to `backup_service/references.py`.

### Decisions needed

**D1. How should the unexplained remainder (part A) be handled?**

- **D1-a. Show it as "Not on a bill yet" and leave it there (recommended).** It
  is honest: the app doesn't know which month it falls in. Cash on hand is
  unchanged. Net worth already counts it.
- D1-b. Put it on a bill automatically: add it to the month after the last
  typed bill (16th Feb 2027). That makes the numbers match, but the app would
  be making up a due date.
- D1-c. Treat it as a mismatch to correct: prompt *"Your bills are ₱1,522.57
  less than the card's balance — fix the balance or add a bill"*, using the
  existing balance-adjustment flow.
- D1-a + a "Put it on a bill…" button that lets you choose the due date is
  also possible.

**D2. Did SPayLater's 15 Oct bill (₱8,296.21) already include the 17 Sep
purchases of ₱180 and ₱141?** (part B)

- If **no**, then purchases in the statement cycle that is still open (not
  yet closed) are not on the card app's list yet. The rule should become:
  *a purchase dated before the list is dropped only if its statement had
  already closed when the list was saved; purchases in the open cycle are
  added to its bill.* **(recommended if the answer is no)**
- If **yes**, the current rule is right and part B is covered. Part A would
  then be ₱321 larger in the explanation text.

**D3. Does the ₱18,237.00 opening balance include the Aerox TG payments that
are not billed yet?** (part C)

- If **yes**, the tile double-counts ₱46: a plan that was already inside the
  opening balance should not be added again in `unpaid_installments`. Fix:
  plans that a saved bill list covers (`bills_cover_rules`) no longer add
  their unbilled remainder on top of `owed`. **(recommended if yes)**
- If **no**, nothing changes; part C disappears from the explanation.

---

## Issue 2 — Tapping a bill should show what is in it

### What exists today

A bill row shows only totals, for example *"incl. ₱323.00 from plans"*. The server
works out every line when it builds a bill (`account_service._bills`) and then
discards them, so the client has nothing to list.

### Proposed fix

- **Server:** keep the lines. `Bill.lines`: each has a kind, name, date,
  amount and a link id (`transaction_id` or `rule_id`):
  - `typed`: "From the card's app" and the typed amount, which the app cannot
    itemise.
  - `purchase`: each purchase recorded after the list, with a link to the
    transaction.
  - `plan`: each installment or repeating charge that lands on this bill
    (for example "Hoodie · payment 1 of 3 · ₱323.00"), with a link to the plan.
  - `inside_typed` *(info only, not added)*: plans and purchases the typed
    amount already contains, such as "Aerox TG ₱15.33 (already in the ₱8,296.21)",
    so you can see them without them being counted twice.
  - `payment`: payments into the card that settled this bill (oldest-first
    FIFO), so *"₱X paid"* can be traced.
- **Client:** tapping a bill row in `CardBills.tsx` opens a `Sheet`: due date,
  total, the lines grouped as *What makes up this bill* / *Paid so far*, and
  each line with a link opens its transaction or plan. No new dependency.
- Tests: extend `tests/test_accounts.py` to cover the lines summing to
  `amount`, `inside_typed` not being counted, and payments summing to `paid`.

### Decisions needed

**D4. Show the plans and purchases already inside the typed amount?**

- **D4-a. Yes, greyed out as "already in the typed amount" (recommended).** This
  is the only way to see, for example, that Aerox TG is on the October bill.
- D4-b. No, show only the lines that add to the bill.

**D5. Show the payments that settled the bill in the same sheet?**

- **D5-a. Yes (recommended).**
- D5-b. No, show only what makes up the bill.

**D6. Should this also apply to cards without typed bills** (the statement
card on the account page: tap it to see the purchases in that statement)?

- D6-a. Yes, in the same change.
- **D6-b. Later, as a separate change (recommended).** It uses different code
  (`_statement`) and the typed-bill cards are the ones affected now.

---

## Issue 3 — Months ahead shows November's bill in October

### Reproduced with your data (3 months → tap October)

```
5 Oct   Maribank bill due 5 Oct    ₱1,492.90   already set aside
6 Oct   Maribank bill due 5 Nov    ₱5,513.87   ← November's bill, in October
15 Oct  Spaylater bill due 15 Oct  ₱8,619.21   already set aside
16 Oct  Spaylater bill due 15 Nov  ₱4,256.16   ← November's bill, in October
16 Oct  Spaylater bill due 15 Nov · plans  ₱323.00
```

November then shows the **December** SPayLater bill (on 16 Nov), and so on.

### Root cause

This follows the current rule, but the rule is confusing. `projection_service._bill_items`
dates each later bill **the day after the previous bill is due**, because
that is the day Home's *cash on hand* starts subtracting it (cash on hand
always holds back "the bill due now"). The month total therefore matches the
cash-on-hand figure Home will show at month end, but every bill appears one month
before its due date.

The *Card statements ahead* section has a related inconsistency. It groups
installments by statement **cycle**, so the Hoodie's 15 Oct payment appears
under "due 15 Nov". The Bills section, correctly, puts it on the 15 Oct bill.
The two sections disagree about the same payment.

### Decisions needed

**D7. In which month does a bill count?**

- **D7-a. In the month it is due, in both the list and the totals
  (recommended).** The November bill appears in November and leaves cash in
  November, which is when the money really leaves. October's "end" figure
  becomes higher than the cash on hand Home would show on 31 Oct (Home holds
  back the next bill early). To avoid confusion, the month card adds a line
  like *"₱9,770 of it is set aside for November's card bills"*.
- D7-b. Keep the current timing and totals, but list the bill under the month it
  is due, with a note. The list and the numbers would no longer agree, so I
  don't recommend it.
- D7-c. Keep it as is and only rename the item: *"Set aside for the 15 Nov bill"*.
  This is the smallest change, but the bill still appears in October.

**D8. For cards with typed bills, should *Card statements ahead* show the bills
themselves** (the same figures as the card's Bills section: due date, amount,
what is in it) instead of the statement-cycle grouping?

- **D8-a. Yes (recommended).** One answer everywhere; cards without typed
  bills keep the current view.
- D8-b. No, keep the cycle view, but put installments on the bill due on or after
  their date (the `_lands_on_bill` rule) so the two sections agree.

---

## Order of work (once decided)

1. Issue 3 (Months ahead dating, D7/D8): self-contained, in `projection_service`
   + `Projection.tsx`, with tests in `tests/test_projection*.py`.
2. Issue 1 (reconciliation row + the payment-on-save-day bug + D2/D3 fixes):
   `account_service._bills` / `_credit_view`, `CardBills.tsx`.
3. Issue 2 (bill lines + sheet): builds on the lines that step 2 already
   has to track.
4. Update `misc/FEATURES.md` ACC-35 / REC-25, the CLAUDE.md "Cards and balances"
   notes, then `npm run build` and commit `app/web/static/dist/` (invariant 9).

`_bills` and `projection_service._lands_on_bill` must keep answering "which
bill does this charge land on" the same way. Each step above changes both
together, with a test that checks they agree.
