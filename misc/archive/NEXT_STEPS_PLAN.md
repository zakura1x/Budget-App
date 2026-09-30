# Phase 9, performance and what to build next — findings and plan

Written 2026-09-23, from one question: *what is the next update or upgrade?*

This is a survey, not a decision. `misc/archive/UX_RESPONSIVENESS_PLAN.md` and
`misc/archive/BILLS_FIX_PLAN.md` both open with their decisions already made; this one
does not. Part 1 is what the docs say is unfinished, Part 2 is what your own
request log says is slow, Parts 4–5 are what is worth building. The decisions
you need to make are collected at the end, and nothing here should be built
until they are answered.

Everything below is measured from the repo as it stands at `708dae0`, not
recalled from the design documents.

---

## Status — surveyed 2026-09-23 · **nothing decided, nothing built**

| | |
|---|---|
| Working tree | Clean. ACC-40 (a loan bills like a card) landed in `708dae0` |
| Tests | 756 passed, 14 skipped, 53 files. One wall-clock failure under load — §6 |
| Features | 181 ✅ v1 · 11 🟡 deferred · 17 ❌ out, of 209 |
| Phases | 1–8b built · 9 **part built, never rehearsed** · 10 is the standing gaps list |

---

## Part 1 — The real gap: this has never left your PC

Phases 1–8b are built and the feature table is 87% ✅. What is missing is not a
feature. **Every deployment and survivability item in Phase 9 is still `☐`**,
and that is the only category on this page where being wrong is unrecoverable.

> **Rehearsed 2026-09-24 — see §1.1 below.** Items 1–4 have now been taken as
> far as they can go without writing to the company database and without a
> server. Nothing on this page was built; the tools were run and their answers
> recorded. What is still genuinely unproven is narrower than it was, and named
> in §1.2.

| | What is unproven | Why it bites |
|---|---|---|
| **1** | **A backup has never been restored** | `phases.md` says it plainly: *"A backup you have never restored is not a backup, and here the cost of finding out is everything."* `restore_service` is tested against synthetic files; it has never met a real one |
| **2** | **The `.env` restore has never been rehearsed**, and the offline copy has never been checked with `env_fingerprint.py --compare` | Since the recovery phrase went (2026-09-14) that copy is the **only** insurance, for every account. An insurance policy nobody has ever claimed on |
| **3** | **Master-key rotation has never been rehearsed on a database copy** | `rotate_keys.py` is built, resumable and tested — but the risk list warns that a rotation interrupted halfway leaves DEKs split across versions, and `BUDGET_RETIRED_KEYS` must be populated *before* it starts |
| **4** | **`benchmark_fetch.py` has never run on the server** | This is the ARCHITECTURE §5.7 go/no-go for bucket columns. The dev-PC figure is network-bound (14 ms RTT over the internet) and therefore means nothing. **Part 2 below is blocked on this number** |
| **5** | **Never opened on a real iPhone; no Lighthouse run** | For a PWA whose entire point is the home screen. DevTools is not the test |
| **6** | **`BACKUP_OFFSITE_DIR` is empty** | Automatic backups live only on the app server. A different machine from the database, so losing the database does not take them — but losing the app server does |
| **7** | One real password-reset email, end to end over HTTPS | SEC-30 is built and has 11 tests, none of which can send mail. Nothing has proven the SMTP path works from the server |

None of this is building. It is proving that what you built survives contact
with the world, and it is the honest answer to "what is next".

---

### §1.1 — The rehearsal, 2026-09-24

Run against the live `ZBDGT` schema, **read-only throughout**. Three accounts
exist (11, 20, 21); 20 is the real one.

| Check | Command | Result |
|---|---|---|
| Integrity, all accounts | `verify_integrity.py` | **OK** — 11: 1 row · 20: 251 rows · 21: 1 row · 0 receipts, no drift |
| Key status | `rotate_keys.py --status` | Master key **v1** current, versions loaded `[1]`, all 3 accounts wrapped at v1, `BUDGET_RETIRED_KEYS` empty |
| Round trip (DAT-14) | `verify_backup.py --user-id 20` | **OK** — 212 rows, 68,472 bytes, *"the backup restores, and matches the live data"*, exit 0 |
| A real file on disk | `backup.py --user-id 20` then `restore.py … --verify` | **ok: true**, `unresolved: []`, `differences: {}` — 212 rows, 106 of them transactions |
| Older files still open | same, on the 21 Sep and 22 Sep backups | **ok: true** for both — 197 and 207 rows, checksums OK, every reference resolved |
| **Corruption is caught** | one byte flipped mid-file, then `--verify` | **Refused** — *"The backup is damaged"*, exit 1, before anything was touched. It reported this as a raw traceback; `restore.py` now catches `AppException` / `CryptoError` and says it in one line, because this script runs on the worst day of the year |
| Fingerprints (SEC-31) | `env_fingerprint.py` | `BUDGET_MASTER_KEY 0e37-5931-2f91` · `BLIND_INDEX_PEPPER 30b6-d09e-135e` · `PIN_PEPPER b6c4-77b6-d6de` · `JWT_SECRET_KEY 3322-f47f-8dec` · `SESSION_SECRET 1343-be55-8af7` · retired keys empty |
| Does `--compare` actually catch drift? | two synthetic `.env` files | **Yes** — identical: every line `same`, exit 0. Two values changed: both `DIFFERENT`, *"one of these files is not current"*, exit 2. No value ever printed |
| Rotation dry runs | `--new-key --dry-run`, `--rewrap --dry-run` | *"would make version 2 the master key… `.env` is unchanged"*; *"0 to re-wrap, 3 already current"*. **`.env` SHA-256 identical before and after** |

**The cold-load benchmark (item 4), run here rather than on the server:**

```
round trip to the database : 14.8 ms
fetch 10000 x 262-byte rows : 1861 ms
decrypt + parse            :   96 ms
ESTIMATED COLD LOAD        : 1957 ms   (line: 1500 ms)
-> Over the line. Adopt the bucket-column plan (ARCHITECTURE.md 5.7).
```

**Do not act on that verdict.** It is the dev-PC number the script's own
docstring warns about, and the breakdown proves why: **1861 ms of the 1957 is
the fetch across a 14.8 ms internet link, and the crypto is 96 ms.** Decrypting
is 5% of the cost. §5.7 is a decision about the network between the app and the
database, and it can only be taken where the app runs. The figure above is the
"before" to compare the server's against — nothing more.

### §1.2 — The write path, rehearsed for real — and the bug it found

Done on your go-ahead, 2026-09-24. A throwaway account (**user 23**,
`restore-rehearsal-20260924@example.invalid`) was created on `ZBDGT`, your
212-row backup was restored into it, the result was checked, and the account
was purged. `MAX_USERS=5` and there were 3 accounts, so there was room.

**🔴 `restore.py --fresh` FAILED, always, and it is the documented recovery
path.** *(Fixed the same day — see the end of this section.)*

```
sqlalchemy.exc.IntegrityError: Violation of UNIQUE KEY constraint
'UQ_user_preferences_user'. Cannot insert duplicate key in object
'ZBDGT.user_preferences'. The duplicate key value is (23).
```

The mechanism, confirmed in the source:

1. `user_preferences` carries `UniqueConstraint("user_id")`
   (`app/db/models/user_preference.py:19`) — on `user_id` **alone**. It is not
   filtered on `is_deleted`.
2. In fresh mode `restore_service` clears the target's existing preferences row
   with `repo.soft_delete(record.id)` (`restore_service.py:165`).
3. `soft_delete` is an **UPDATE** setting `is_deleted=True`
   (`encrypted_repository.py:104`). **The row is still physically there, still
   holding that `user_id`.**
4. The backup's own preferences row is then inserted for the same `user_id` —
   and the constraint, which cannot see `is_deleted`, refuses it.

Every account has a preferences row, because `create_account` writes one. So
**fresh mode cannot succeed against any normally created account** — and
`restore.py`'s own docstring describes exactly that as the recovery procedure:
*"On a new server: put the offline copy of .env in place, sign up so the
account exists with its own key, then run this."* The transaction rolls back
cleanly, so nothing is corrupted; you simply cannot restore this way.

**`--merge` works, and is a complete recovery path.** Merge maps a singleton to
the row already there and skips it, never inserting a second one:

| | |
|---|---|
| Restored | 106 transactions, 105 categories, 23 accounts, 11 recurring rules, 2 subscriptions, 2 savings goals, 1 budget |
| `user_preferences` | `in_backup: 1, restored: 0, skipped: 1` — the target keeps its own |
| References | `unresolved: []` · `differences: {}` · exit 0 |
| Integrity of the restored account | **OK — 251 rows**, exactly matching source account 20's 251 |
| Round trip on the restored copy | **OK** — 212 rows, *"the backup restores, and matches the live data"* |

That is the whole high-risk path proven at last: the two-step insert over 211
rows, the id remapping the docs call *"the highest-risk code in the project"*,
and the re-seal under a **different account's key**. Cleanup purged 252 rows;
accounts 11, 20 and 21 verify unchanged, and `backups/23/` is gone. Per
`purge_user`'s design the audit trail for user 23 is deliberately kept.

**✅ FIXED 2026-09-24**, by the second of the three options considered. The
other two were a filtered unique index (`WHERE is_deleted = 0`) — truest to
intent, but a migration on the shared database, and every other Shape B table
would then reasonably want the same — and treating it as merge does, keeping
the target's row and skipping the backup's, which is smallest but loses the
backed-up preferences. **Fresh means the file wins**, so the backup's
preferences row must land:

- `EncryptedRepository.hard_delete()` — new, and deliberately narrow. Rows are
  soft-deleted everywhere else in this app; its docstring names its one caller
  and the reason (a plaintext UNIQUE constraint that cannot see `is_deleted`).
- `restore_service` fresh mode now hard-deletes, and walks **`existing[table]`
  rather than `live`** — a preferences row that was *already* soft-deleted also
  held the slot, so the original would have failed on that too.
- `tests/test_backup.py::test_fresh_restore_into_an_account_that_has_preferences`
  — builds the target the way registration does (with a preferences row),
  restores fresh, and asserts one row survives carrying the **backup's** theme.
  Confirmed to fail with the old code and pass with the new.

Why nothing caught it: `make_user()` in the test file creates a `User` row
directly and **writes no preferences**, so every existing fresh-mode test
restored into an account that real registration could never produce.

**Re-rehearsed on SQL Server after the fix** (user 24, created → restored
`--fresh` → checked → purged): `user_preferences in_backup: 1, restored: 1,
skipped: 0`, `unresolved: []`, `differences: {}`, exit 0; integrity **OK, 251
rows**, matching source account 20; round trip on the restored copy OK. 252
rows purged, accounts 11/20/21 unchanged. **758 passed**, and `ruff check app
tests scripts` is back to its exact 1842-error baseline.

### §1.3 — What is still unproven, and what it is waiting on

| | Still unproven | Waiting on |
|---|---|---|
| **A** | ~~A restore that actually writes~~ — **done, §1.2** | — |
| **B** | **The `.env` restore.** The fingerprints in §1.1 are the card to check your offline copy against, and `--compare` is proven to catch drift — but the copy itself has never been produced and compared | You. The offline copy is deliberately not on this machine, and should not be |
| **C** | **A full rotation rehearsal.** The dry runs are clean and idempotent, but no key has ever actually moved | A copy of the database to rehearse on |
| **D** | Server benchmark, Lighthouse, a real iPhone, the offsite backup destination, one real reset email | The deployment itself |

---

## Part 2 — Performance, measured from your own log

Aggregated from `logs/app.jsonl` — 8,516 logged requests, the app's own record
of itself. Average, worst, and how many:

| Endpoint | avg | max | n |
|---|---|---|---|
| `POST /data/import/budget-app` | — | **100,586 ms** | 1 |
| `GET /projection` | 1371 ms | 2958 ms | 237 |
| `PATCH /transactions/{id}` | 1188 ms | 1246 ms | 4 |
| `POST /transactions` | 1119 ms | 2013 ms | 31 |
| `POST /recurring` | 887 ms | 1545 ms | 9 |
| `DELETE /transactions/{id}` | 787 ms | 1628 ms | 23 |
| `GET /budgets/current` | 577 ms | 8061 ms | 245 |
| `GET /projection/cards` | 479 ms | 2173 ms | 45 |
| `GET /goals` | 474 ms | 1736 ms | 262 |

Three things fall out of it.

**2.1 `/projection` is the slowest call in the app, by 3×.**
`UX_RESPONSIVENESS_PLAN.md` §4.3 already lists it as *"a backend problem. The
cache hides it; nothing has fixed it."* At 237 calls it is also the most-hit
expensive path. It is one `project()` over 12 monthly windows, each walking
`occurrences()` for every rule plus `_bill_items` and `_interest_items` — the
windows are independent and the rule expansion is repeated per window.

**2.2 Every write costs about a second.** `POST /transactions` averages 1119 ms,
`PATCH` 1188 ms. Phase 10 predicted exactly this: the two-step insert costs 2–3
round trips per row at ~62 ms each *from the dev PC*, and this PC reaches the
company database over the internet. **Most of this may simply vanish on the
server.** That is why §1 item 4 comes first — measure there before optimising
anything here.

**2.3 The Budget App import took 100 seconds in one HTTP request.** Also
predicted in Phase 10 ("bulk paths should batch"), also never batched. It is a
one-time path per user, so the priority is low — but a 100 s request is a
timeout waiting to happen behind IIS, and DAT-21 is how a new user arrives.

> **Rule for this part: do not optimise before item 4 of Part 1.** The single
> most likely outcome of the server benchmark is that 2.2 disappears and only
> 2.1 is real.

---

## Part 3 — Carried over from the other plan documents

Still open from `UX_RESPONSIVENESS_PLAN.md` §4.3, unchanged:

- **The account trail on `useInfiniteQuery`.** The last list that is neither a
  query nor the ledger store, and the only remaining reader of
  `ledgerStore.version` — so it blocks step 7's deletion of that counter. It
  pages by cursor and the Month view walks every page, so it is real work on
  the account page's core list, not a mechanical migration.
- **The §4.1 manual checklist has never been walked.** Ten flows; the request
  log gives partial evidence for the POST and DELETE cascades, but a receipt
  attach, a category rename and a tag delete have not been *seen* working.
  That doc calls this *"the one piece of unfinished verification, not
  unfinished building"* — and it stays true.

---

## Part 4 — Features worth building, ranked

Of the 11 🟡 deferred features, four earn their place. The ranking is
value-to-effort, and the reasons come from how the app is actually used.

| Rank | Feature | Why now | Cost |
|---|---|---|---|
| **1** | **STA-10 — cash on hand over time** | FEATURES.md already calls it simple: *"the running balance of the counted accounts, built from transactions already stored, with no typed valuations involved."* It is the one chart that answers **am I actually getting better**, and the app has no trend view at all today. `recharts` is already in the bundle and Stats already lazy-loads it | Small. No new storage, no new reference, nothing to add to `references.py` |
| **2** | **REC-27 — what-if a plan before committing** | *"Can I afford a phone at ₱3,000 × 12?"* — described as *"nearly free once REC-21 exists"*, which it does. Given that your real usage is SPayLater, a motorcycle loan, installment conversions and now ACC-40, this is the feature that matches how you actually spend money | Small–medium. An unsaved rule overlaid on `project()`; touches §2.1's hot path, so do it **after** that is understood |
| **3** | **SEC-12 — biometric unlock** | IIS idle-stops the process after 20 minutes while cookies stay valid, so the PIN gets retyped many times a day, by design (SEC-27). A passkey on iOS Safari removes the largest piece of daily friction in the app | Medium. WebAuthn, a dependency, and a fallback path that must never become a second way in |
| **4** | **GOA-05 — required-per-month** | Trivial arithmetic over data already in the goal payload. Turns a goal from a number you look at into a plan you can follow, and pairs with GOA-08's set-aside | Trivial |

**Worth skipping, and why:** CAL-06 (month view covers the real use), DAT-09
PDF/Excel (CSV covers it, and DAT-18 already settled that the encryption
boundary keeps exactly *one* deliberate opening), UX-14 haptics (weak on iOS
Safari), UX-15 multi-language (one user, English). SUB-07 is small but buys
little. UX-13 offline writes stays deferred for the reason given: merging
offline edits into an encrypted store is genuinely hard.

**DAT-20 (nightly backup via Task Scheduler) is not a feature — it is Part 1
item 6**, and it should be done on deployment day, not scheduled as work of its
own. Writing a backup needs no key, which is what makes it possible at all.

---

## Part 5 — Two things that are in no plan document

**5.1 Kill the version-gap crash class.**
`phases.md` records three crashes on 2026-09-16, two of them the same root:
the browser had a fresh bundle while uvicorn was still running older Python, so
a field the new UI read (`short_by`, `bills_set_aside`) was not in the response
and the screen went down on `undefined`. The Jinja shell picks up a new `dist/`
at request time **without a restart; Python changes do not.** So the two halves
can always disagree, and on the server that gap is a copied zip plus a forgotten
recycle. `formatPHP` returning `—` patched the symptom.

The fix is a **build stamp**: the shell injects the server's build id beside the
manifest it already reads, `lib/api.ts` compares it with the bundle's own, and
a mismatch prompts one reload instead of a white screen. It ends the whole
class rather than the next instance of it, and it matters more once deploys are
copied zips (`make_release.py`) than it does here.

**5.2 Widen the frontend tests past the caching layer.**
`frontend/src/tests/` holds exactly four files — `budgetStore`, `ledgerStore`,
`invalidate`, `writePaths` — and all four are about caching and write
announcement. Nothing covers `lib/money.ts` or `lib/accounts.ts`.

Yet those are precisely where the documented failures have come from: money
helpers throwing on a third decimal place (the `percentOf` crash, 2026-09-16),
`toDecimalString` refusing a stored rate so a whole account save failed
silently in the browser, and the `isOwed` / `visible` / `UNTRACKED_ID` rules
that decide whether a balance reads as owed or an account is counted at all.
They are pure functions with no DOM, which is the cheapest possible test, and
the existing suite already proves the harness works. This is the same argument
`writePaths.test.ts` was written on: **cover the things that fail silently**,
because a wrong figure is not an error.

---

## Part 6 — Found while writing this

- **`tests/test_stats.py::test_a_year_of_data_stays_fast_when_warm` is
  load-flaky.** It asserts `elapsed_ms < 250` (line 283) for a year of data.
  It failed once here while the machine was busy, then passed alone in 1.94 s.
  The comment already says *"generous for a loaded CI box; the printed figure
  is the one to read"* — so the intent is the printed number, and the
  assertion is the part that can cry wolf. Either widen it or let the printed
  figure stand on its own; a suite that fails for being busy trains you to
  ignore it. The three timing assertions in `test_crypto_performance.py` are
  the same shape and worth the same look.

---

## Part 7 — Suggested order of work

1. **Part 1, items 1–3.** Restore a backup. Move `.env` aside and bring it back
   from the offline copy. Rehearse a rotation on a copy of the database.
   Nothing here is building, and nothing else should start first.
2. **Deploy** (Part 1, items 5–7): one worker, `.env` by hand and confirmed by
   fingerprint, `SESSION_COOKIE_SECURE=True`, no HSTS, the Task Scheduler
   backup, and one real reset email.
3. **Run `benchmark_fetch.py` on the server and record it.** This answers §5.7
   and tells you whether Part 2.2 was ever real.
4. **Part 2.1** — `/projection`, now that you know what the network costs.
5. **STA-10**, then **REC-27**.
6. The rest, in whatever order the use of the app asks for.

Parts 5.1 and 5.2 are small enough to land beside any of these; 5.1 is most
valuable *before* step 2, since that is when the two halves start being copied
separately.

---

## Decisions needed

| # | Question | Options | Default if you say nothing |
|---|---|---|---|
| **N1** | Does the deployment rehearsal (Part 1, 1–3) happen before any new feature? | Yes / No | **Yes.** It is the only unrecoverable category |
| **N2** | `/projection` — optimise it, or leave the cache hiding it? | Fix / leave | **Decide after the server benchmark**, not before |
| **N3** | Which features, in which order? | §4's ranking / your own | STA-10, then REC-27 |
| **N4** | SEC-12 biometric unlock — is a passkey an acceptable second path to the DEK? | Yes / No | **Ask first.** It is a security-model change, not a UI feature, and it is the one item here that touches the key hierarchy |
| **N5** | Build stamp (5.1) and the pure-function tests (5.2) — in, or not? | In / out | **In**, both small |
| **N6** | The flaky wall-clock assertions (Part 6) — widen or drop? | Widen / drop / leave | Widen |

> **N4 is the only one with a security consequence.** Everything else on this
> page is scheduling. A passkey that can unwrap a DEK is a second way into the
> account, and ARCHITECTURE §5 currently says there is exactly one. Do not
> build it on a default.
