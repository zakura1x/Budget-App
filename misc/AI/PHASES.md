# AI companion — Phases

Build order A0–A6. Each phase ships on its own, leaves the app working with
`AI_ENABLED=false`, and has a **gate** that must pass before the next phase
starts. Feature IDs are in [FEATURES.md](FEATURES.md); sections in
[ARCHITECTURE.md](ARCHITECTURE.md).

| Phase | Name | Delivers | Model calls? |
|---|---|---|---|
| A0 | Decisions | ✅ Answered 2026-09-30 (README) | — |
| A1 | Plumbing | Ported watsonx layer, settings, health, usage table | Health only |
| A2 | First questions | Skill engine, verifier, opt-in, the Assistant screen, 5 skills | Yes |
| A3 | Afford it, and the rest | Affordability engine, 6 more skills | Yes |
| A4 | In context | Explain links, drafts, what-if hand-off, Home tile | Yes |
| A5 | Hardening | Evaluation, load test, masking, deploy | Yes |
| A6 | Saved history (optional) | Encrypted conversation table | Yes |

Phase 9 of the main plan (hardening, rotation, deploy) should land first, or
at least not in parallel: A1 changes `Settings`, `requirements.txt` and the
redaction filter, which Phase 9 also touches.

---

## A0 — Decisions (no code)

- [x] **Q1** Company watsonx project under the same `COMPANY_NAME`: **yes**.
- [x] **Q2** Figures and account/category/goal names to IBM us-south:
      **yes**. AI-41 is in; AI-55 stays optional (A5).
- [x] **Q3** Pin to the versions already in the shared QUOT venv: **yes**.
      The numbers are read off the server in A1 step 3.
- [x] **Q4** Taglish replies if they pass the A2 language gate, otherwise
      English only.
- [ ] Confirm the server can reach `IAM_MANAGEMENT_URL` and
      `us-south.ml.cloud.ibm.com` (QUOT on the same host already does).

**Gate:** passed 2026-09-30, except the reachability check, which is
A1 step 8 (the health check fails loudly if either host is blocked).

---

## A1 — Plumbing (AI-01 – AI-05, AI-52, AI-54)

Backend only. No user-visible change.

**Status (2026-09-30): built, and the gate PASSED** once the user replaced
the IAM key. `scripts/ai_health.py --measure 20` from this machine:
credentials accepted by IBM (6.4 s cold); the first model call took 9.6 s
(client and token built once); then 20 calls with ~800 prompt tokens and 0
failures, p50 1,043 ms, p95 1,503 ms, max 4,826 ms. The gate was p95 under
5 s. IAM's record still says `expired` / 2026-05-14 on the new key; the
loader uses it because IBM accepts it, but the IAM owner should fix the
expiry fields. `tests/test_ai_plumbing.py` has 28 tests and passes without the
SDK. Migration `20260930_0005` has been run on ZBDGT. `.env` has
`AI_ENABLED=True`. Still open: lower the `requirements.txt` floors to QUOT's
versions on the server (step 3).

The gate failed on credentials, not on this code. IAM's record for DELCA says
the key expired on 2026-05-14, and IBM answers `BXNIM0415E Provided API key
could not be found`: the key was deleted on IBM's side. Whoever owns the IAM
record must put a live key in it. Then set `AI_ENABLED=True` and re-run
`python scripts/ai_health.py --measure 20`. Until then `AI_ENABLED=False`.
STWRD, DMS and QUOT read the same record, so they are affected too.

1. `app/ai/credential_loader.py`, `watsonx_client.py`, `llm_service.py` —
   copy from `D:\Shared Files\STWRD_UPDATED\services\`, replace `Config` with
   `settings`, rename `WATSONX_ENABLED` → `AI_ENABLED`, drop `_check_tables`,
   log token counts as integers. Keep every comment explaining *why* (they
   record fixes from three apps) and add a header line saying where it was
   copied from and on what date.
2. `Settings` fields and the `.env` block from AI-ARCH §3; update
   `.env.example`. Validation: when `AI_ENABLED` is true,
   `IAM_MANAGEMENT_URL` and `COMPANY_NAME` must be set; when false, nothing is
   checked.
3. `requirements.txt`: run `pip list` in `C:\inetpub\wwwroot\FAST-PYTHON\.venv`
   on the server, pin the three packages to exactly those versions in their
   own commented block, and confirm `pip install -r requirements.txt
   --dry-run` changes nothing QUOT uses.
4. Redaction filter: add `api_key|apikey` to the named-secret pattern in
   `app/core/logging_config.py`; test that a logged credentials dict is
   redacted.
5. `assistant_usage` (Shape A) model + Alembic migration. Ask before running
   it on `ZBDGT` (memory: destructive / schema changes on the company DB need
   a go-ahead).
6. `GET /assistant/health` (admin) and `scripts/ai_health.py`.
7. `GET /assistant/status` returning `enabled: false` everywhere.
8. Measure from this machine: `scripts/ai_health.py --measure 20` prints p50 /
   p95 for a ~600-token prompt (STWRD's `scripts/measure_watsonx.py` is the
   model for it).

**Tests:** settings validation both ways; `get_llm_service()` raises
`AssistantDisabled` when off and imports nothing (check `sys.modules`);
`ConcurrencyGuard` per-user and per-process limits; `invoke_with_recovery`
retries an auth error once and never a timeout (fake model); the log-capture
test (security marker).

**Gate:** `ai_health.py` reports credentials accepted and the model replying
from this machine; p95 under 5 s; `pytest` green with the SDK not installed.

---

## A2 — First questions (AI-06 – AI-08, AI-10 – AI-16, AI-50, AI-51, AI-53)

**Status (2026-09-30): built; the gate passed on the numbers.** The Taglish
default is waiting on the user.
`scripts/ai_eval.py` asks 30 golden questions of the real model, 10 of them in
Taglish, for a made-up user on in-memory SQLite (throwaway keys, never ZBDGT):

| Run | Routed right | Figure check passed | p50 | p95 | Cold start |
|---|---|---|---|---|---|
| `AI_REPLY_LANGUAGE=en` | 100% | 100% of 28 | 642 ms | 3,138 ms | 8,057 ms |
| `AI_REPLY_LANGUAGE=match` | 100% | 100% of 28 | 669 ms | 3,773 ms | 8,281 ms |

Reading the replies found three wrong answers that the figure check could not
catch (every number was real, just used wrongly). All three were fixed before
the runs above:
- "more than last month" set the period to last month, so September was
  compared with August. `find_period` now reads a comparison as this month.
- "the statement that closed 16 Oct" was said before 16 Oct. The card facts
  now say "closes" for a date still ahead.
- A net-worth reply was garbled. The net-worth line was split in two, and the
  prompt (now `answer-2`) says not to explain how a figure is made unless asked.

The lesson: the figure check makes an invented number impossible, but a wrong
answer built from true numbers is still possible. Keep the golden set growing
and keep reading its replies at every phase.

Built as planned, with these differences:
- The card rule: a question that mentions a card goes to the card skill,
  whatever else matches.
- The cold start is about 8 s: the first question after the process starts
  fetches the key and builds the client. IIS idle-stops the process after 20
  minutes, so the first question after a quiet spell pays this once.
- The model sometimes answers a Taglish question in Taglish even with `en`.
  The figures still check out, so this is left alone.
- The screen was checked in the running app (local, in-memory data): opting
  in, a question, and a reply card with the right figures. The Based-on
  panel, follow-up chips and "New chat" are exercised by the vitest store test
  and the API tests.

Tests: `tests/test_ai_assistant.py` (43), `tests/test_ai_plumbing.py` (28),
`frontend/src/tests/assistantStore.test.ts` (5).

1. `assistant_service`: `turn.py`, `router.py` (rules first, model ROUTE call
   when unsure, pydantic-validated slots, names → ids server-side),
   `prompts.py` (ROUTE and ANSWER, each with a version constant),
   `verifier.py`, `memory.py` (registered with the keyring drop hook).
2. Skills: `budget_status`, `spending`, `cash`, `upcoming`, `card`,
   `off_topic`. Each returns `Facts` with pre-formatted figures and a template
   reply.
3. `POST /assistant/ask`, `GET/DELETE /assistant/conversations/{id}`, the
   problem codes in AI-ARCH §10, the daily cap.
4. `assistant` preference in `preferences_service`, the audit actions, the
   opt-in card with the disclosure text.
5. Frontend: `screens/Assistant.tsx`, `components/assistant/` (reply card,
   Based-on panel, suggestion chips, typing indicator), the More row, the
   store cleared in the App.tsx lock effect, `keys.assistantStatus` in
   `queryKeys.ts`, the `writePaths.test.ts` exemption. `npm run build` and
   commit `dist/` (invariant 9).
6. Taglish (AI-63). The rule router gets Taglish keywords (*magkano*,
   *natitira*, *gastos*, *bayarin*, *kaya ko ba*, *utang*…) next to the
   English ones, and the ROUTE prompt says questions may be in English,
   Filipino or a mix. The ANSWER prompt takes a `reply_language` of `en` or
   `match`. `match` means answer in the language of the question, with
   figures still copied exactly as written. It is set by
   `AI_REPLY_LANGUAGE` in `.env`, default `en` until the gate below passes.
   Template replies (the fallback) are English in both modes.

**Tests:** for every skill, its figure equals the matching endpoint's for the
same fixture; the verifier table (formats, rounding, a reply with one
invented number); turn with `FakeLLM` - good reply, invented figure, timeout,
auth error; memory empty after `keyring.drop()`; `/assistant/ask` refuses
locked, not opted in, disabled, over the cap; no Shape B write from any
`/assistant` route (security marker); vitest - store cleared on lock.

**Gate:** `scripts/ai_eval.py` on the A2 golden set (~30 questions over these
five skills, a fixture user with known figures): router ≥ 90% right intent,
verifier passes ≥ 95% of replies, **zero** replies shown with a figure not
in the facts, p95 turn under 8 s. The user reads 20 replies and finds none
misleading.

**Language gate (Taglish, AI-63):** about 10 of the golden questions are
asked in Taglish. Routing them must meet the same 90% bar; if it doesn't,
add keywords and re-run. Then run them with `AI_REPLY_LANGUAGE=match`. The
verifier must pass at least 95% of those replies, and the user reads them
and finds them natural and correct. If all of that passes, set the default
to `match`. If not, keep `en`, record "English replies only" in the README
under Q4, and ask again when the model changes.

---

## A3 — Afford it, and the rest (AI-17 – AI-21, AI-30 – AI-35)

**Status (2026-09-30): built; the gate passed.** `scripts/ai_eval.py` now asks
56 questions of the real model. Fifteen are affordability questions whose
verdicts were worked out by hand from the seeded figures before the rules were
run (`AFFORD_WORKING` in the script). All 15 match.

| Run | Routed right, verdicts included | Replies accepted | p50 | p95 |
|---|---|---|---|---|
| `AI_REPLY_LANGUAGE=en` | 100% of 56 | 98% of 52 | 595 ms | 1,449 ms |
| `AI_REPLY_LANGUAGE=match` | 100% of 56 | 98% of 52 | 671 ms | 1,536 ms |

Built as planned, with these differences and lessons:
- **The budget-aware cash model.** Months ahead already assumes the rest of
  this period's budget is spent. So the part of a purchase made now that fits
  the budget is not taken off the cash line a second time; only the rest is
  extra. A later period gives no such cover. This is stated in
  `affordability.py` and in the facts, so a reply can say it.
- **A sixth case, `cash_already_short`.** When the budget is more than the
  money, Months ahead is below zero before any purchase. A purchase inside
  the budget then gets `tight`, with the facts saying the shortfall is not its
  doing. It first came out as `no`; a test caught it.
- **The installment check is pure.** The plan was to go through
  `recurring_service.trial`. That needs an account, a category and terms the
  question does not give, so the payments are laid on the Months ahead line
  directly (`affordability.schedule`). Nothing is written either way.
- **Alternatives are listed only when they do better** than the way asked
  about (`RANK`), so a reply is not padded with worse options.
- **Three more reply checks**, all found by reading real replies:
  `against_verdict` (a reply may not open against the decided verdict, and
  `tight` is neither a yes nor a no), `advice` ("you should", "I recommend",
  "advisable", or an instruction opening a sentence or clause), and `meta`
  ("the facts do not show"). "You need to pay 2,450 on 13 Oct" is a bill
  stated, not advice, and is allowed.
- **Facts are written as finished sentences.** "Income minus spending:
  -10,689" was read as a balance, and "left before buying" as "left after".
  Each line now says the conclusion itself.
- `how_to` answers from a hand-written index with no model call and no user
  data.

Tests: `tests/test_ai_afford.py` (62), with the A1 and A2 files 133 in all.

**Taglish replies: decided 2026-09-30, English only.** The `match` run passes
on figures, but several replies read awkwardly or wrongly ("Kasya lang kung
bumili ka noong 15 Dec pa o mamaya" uses a past-tense word for a future date),
so the user chose `AI_REPLY_LANGUAGE=en`. Taglish questions are still
understood.

1. `app/core/utils/affordability.py` — pure; one threshold table; returns a
   verdict, reasons and alternatives as data.
2. `afford` skill: gathers inputs (AI-ARCH §5.3), including the installment
   what-if through `recurring_service.trial` → `projection_service.project`
   (writes nothing).
3. Skills: `review`, `goals`, `emergency`, `subscriptions`, `payoff`,
   `how_to` (with the hand-written help index).
4. ANSWER prompt additions: the verdict is final; no "you should"; never name
   a product, bank or investment.
5. Verdict label on the reply card (`ok` / `warn` / `danger` tokens).

**Tests:** the verdict table row by row and at every boundary (exactly zero
at the lowest point, the day income lands, a price equal to limit left);
installment path writes nothing (row counts before and after); a reply
that contradicts the verdict is rejected (verifier checks the verdict word).

**Gate:** golden set grows to ~60 with 15 affordability questions whose
verdicts are worked out by hand beforehand; all 15 match; the rest as A2.

---

## A4 — In context (AI-40 – AI-45)

**Status (2026-09-30): built; the gate's checks passed.** The plan's gate also
asks for a week of real use, which starts now.
`scripts/ai_eval.py` (60 questions, real model): 100% routed, 98% of replies
accepted, p95 1.7 s. The A4 paths were also walked in the running app on
in-memory data: Home's tile asking a question, a drafted entry opening the add
sheet pre-filled, a drafted goal opening the goal sheet, and an installment
handed to Months ahead's what-if.

What was built:
- **Explain (AI-40).** `/ask` takes `context` (`screen`, `alert`,
  `account_id`). `turn.context_intent` checks it against two tables and the
  user's own visible accounts, and it decides the skill. An account that is
  not the user's is dropped, not refused. Links: each alert banner on Home,
  the monthly review (only on the latest finished period, which is the one
  the skill looks at), and an account's page. The budget is reached through
  the Home tile rather than a link on the budget card.
- **Find (AI-41).** One merchant's or one bill's entries. It is routed only
  when the question names a merchant the user has typed or a recurring rule.
  Facts carry the name asked about and its dates, amounts and accounts - never
  a note, never another merchant.
- **Drafts (AI-42, AI-43).** "I spent 250 on lunch" and "Help me save 50,000
  by December" answer with a button and no model call. Every field is read
  from the words; a merchant typed before brings its last category (TXN-24).
  The button opens the ORDINARY sheet pre-filled (`AddPreset` gained
  `categoryId`, `merchant`, `note`; `GoalSheet` takes a `preset`). Tests count
  rows before and after: nothing is written.
- **What-if hand-off (AI-44).** An affordability reply that is an installment,
  or is tight / wait / no, offers "Try it as an installment". It opens Months
  ahead's own installment sheet pre-filled, through router state that is
  cleared once read.
- **Home tile (AI-45).** Two questions chosen from the alerts and budget
  status Home already holds. It makes no request of its own and shows only
  after opt-in.

Differences from the plan:
- **No budget draft.** "Draft a goal or budget" built the goal only. A budget
  has allocations a sentence cannot carry. A request to set one up is not
  handled specially yet.
- **The model cannot route to `find`, `draft` or `draft_goal`.** Their fields
  come from the words, so only the rules reach them.

Found by reading replies, and fixed:
- A Taglish reply turned "1 Oct to 31 Oct" into "Enero 1 hanggang Disyembre
  31". Every digit was in the facts. The verifier now checks month names too
  (`unknown_month`).
- "It's tight" kept coming back as "No, ...", and "which debt first?" as
  advice. A decided answer is now given to the model as the exact first
  sentence (`answer-5`), and the payoff skill sets one.
- The English instruction is repeated at the very end of the prompt; a
  Taglish question otherwise pulled the reply into Taglish.
- "from Wallet" was read as a merchant, and "get a 60,000 laptop" as an item
  called "a 60".
- One question hit IBM's 30 s timeout in a run and fell back to the template,
  as designed. IAM itself also timed out once (a 10 s read), and the retry got
  through.

Tests: `tests/test_ai_context.py` (33); the four AI files are 171 in all.

1. `context` on `/ask`; server-side resolvers for `screen`, `alert`,
   `account`, `review`. The browser names the object; the server reads it.
2. *Explain* links on the budget card, alerts, the monthly review, account
   pages.
3. Actions: `open_screen`, `draft_transaction`, `draft_goal`,
   `draft_budget`, `try_installment`. The client opens the ordinary sheet /
   editor pre-filled; saving goes through the normal path and `afterWrite`.
4. Home "Ask" tile with two state-based suggestions.
5. `find` skill (AI-41): merchant names only for the rows it reports; never
   notes or descriptions.

**Tests:** a draft action's payload uses only the user's own ids; opening a
draft and closing it writes nothing; a context naming another user's account
resolves to nothing.

**Gate:** the user uses it for a week; no draft ever saved without a tap.

---

## A5 — Hardening and deploy (AI-55, if chosen)

**Status (2026-09-30): built as far as this PC reaches.** Still to do on the
server: install the packages, add the `.env` block, run
`ai_health.py --measure 20`, and watch the first week. `misc/DEPLOY.md` has the
steps. Two decisions by the user the same day: the package floors stay at
STWRD's versions (the shared venv is upgraded if it is older), and there is no
pilot list - `AI_ALLOWED_USER_IDS` stays blank, so every account may turn the
assistant on.

What was built:
- **Load test** - `scripts/ai_load.py`. The real app as one uvicorn worker in
  a child process, SQLite in a temporary folder, 13 made-up accounts: 3 read
  Home's requests in a loop, 10 ask 5 questions each at the same time, real
  model.
- **A question now waits for a place** (`AI_QUEUE_WAIT_SECONDS`, default 10).
  The first run found the fault the test was for: with 3 places and STWRD's
  refuse-at-once guard, 35 of 50 questions came back "busy". With the wait all
  50 are answered (p50 2.3 s, p95 3.0 s, max under 6 s). A user's own second
  question is still refused at once.
- **Admin line** - `GET /assistant/usage` (admin only; reads the table, calls
  nothing) and an Assistant card on the Admin screen: per day, questions,
  accounts, answered without AI with its share, tokens; and a *Check the
  connection* button on the health route.
- **Docs** - `misc/DEPLOY.md` (*Turning on the AI assistant*, three
  troubleshooting rows), `misc/how-to-run.txt` (*THE AI ASSISTANT*).

The gate, honestly:
- "The rest of the app's p95 must not move more than 20%" **is not met as
  written.** Four runs: 5 askers +20% and +31%, 10 askers +35%, +45% and +65%.
  In milliseconds that is a p95 of 23-28 ms becoming 32-45 ms; the median
  moves by 1-2 ms and the worst single read was 132 ms. Two idle runs differ
  by 5-30% on their own, so a 20% line on a 26 ms figure is inside the noise.
- The cause is work, not waiting. A turn costs 22-56 ms of Python (profiled
  with a fake model) against 5-16 ms for a read, because a skill calls the
  same services the screens do. Ten people asking slow the readers the way
  more readers would. No read ever waited on a model call.
- Ten askers is twice `MAX_USERS` (5). SQLite stood in for SQL Server, so the
  server's own numbers are still to be seen.
- Not chosen: masking (AI-55). Nobody has asked for it.

Tests: `test_ai_plumbing.py` gained the wait, the per-day totals and the admin
route (31); the four AI files are 174.

Found in use, the same day:
- "Can you compute if how much money did I spent including the unrecorded loss
  and gain" was answered "How much was it?": the question holds "I spent", so
  the rules took it for an entry to record. A sentence that is asking (how
  much, did I, compute, total, magkano...) and names no amount is no longer a
  draft; with an amount it still is.
- The spending skill now says how much of each total is unrecorded loss or
  gain (Stats counts them inside spending and income), with the recorded part
  beside it, so the model never subtracts. The question joined the golden set
  (61); the AI tests are 181.

1. Load test: 10 parallel users × 5 questions against the one worker; the
   rest of the app's p95 must not move more than 20% while it runs.
2. Masking (AI-55), only if the user asks for it after using A2–A4.
3. Admin screen line: questions, tokens and fallbacks per day (from
   `assistant_usage`).
4. `misc/DEPLOY.md`: the new `.env` block, the migration, `pip` step in the
   shared venv, flipping `AI_ENABLED`. `misc/how-to-run.txt`: health check and
   what to do when IAM rejects the key (it is IAM's record, not ours — tell
   its owner).
5. Update `CLAUDE.md` (a short "AI companion" paragraph with its invariants:
   facts not arithmetic, never writes, never logs content, memory dropped
   with the DEK), `misc/ARCHITECTURE.md` and `misc/FEATURES.md` (a new `AI`
   group), `misc/ROADMAP.md`.

**Gate:** load test passes; deployed with `AI_ENABLED=true` for the pilot
list only; a week with no fallback rate above 10%.

---

## After A6 — a conversation, not a string of strangers (2026-10-01)

The user found the assistant "not adaptive to the message, not communicative".
Six multi-turn conversations against the real model showed why: every message
was read on its own.
- "Hi", "thanks!", "Salamat" and "ok" were told the assistant only talks
  about money, or got an unrelated budget answer.
- "What about last month?" became a monthly review; "and on Food?" went back
  to this month; "how about on installment for 6 months?" lost the price; "eh
  sa Food?" left the budget question.
- "Why is it so high?", "Is that good?" and "Can you explain that more?"
  jumped to another skill, or repeated the last answer.

What changed:
- **`router.small_talk`**: a message that is only a greeting, thanks or an
  ok gets a short friendly reply (skill `chat`, no model call) and the last
  answer's follow-up questions.
- **`router.follow_up`**: a message that asks about the last answer ("why",
  "is that good", "explain"), opens like a follow-up ("and", "what about",
  "what if", "eh", "paano kung") or is short and names only a month, category,
  account, price or bill continues the previous turn's intent - its skill,
  unless its own keywords name another, and every slot it does not replace.
  The intent rides on each turn in memory (`Turn.intent`).
- **The prompt (`answer-6`)** says when a message continues the last one and
  spells out what it is asking about ("What about last month? (meaning:
  Spending, 1 Sep to 30 Sep)") - the model had answered with the facts'
  "period before" line, the month before last. "Why" and "explain" ask it to
  use facts the conversation has not mentioned yet. The ROUTE prompt names the
  previous question.
- **`scripts/ai_eval.py`** gained `CHATS`: the six conversations, 22 turns.
  83 questions: 100% routed, 99% accepted, p95 1.6 s.

Tests: `tests/test_ai_conversation.py`.

The user's own screenshot (`misc/AI-Test`, 2026-10-03) showed two more:
- "If I paid a 7000 bill for papa bern, will my budget be sufficient for the
  month?" was drafted as an entry - "I paid" and an amount. A payment asked
  about IF it happens ("if I paid", "will my budget be enough", "sapat ba",
  "kung bumili ako") is now an affordability question, never a draft.
- "It is for the motorcycle installment plan" got "I'm not sure". A message
  that says what the last one was FOR ("it is for...", "that's for...", "para
  sa...") continues it, without turning "installment plan" into a request to
  pay in installments or moving it to another month. After a draft it fills
  in what the entry was for. When it names one of the user's plans, the
  affordability answer finds that plan's next scheduled payment (its own, or
  the loan's or card's bill it lands on), says it is already scheduled, and
  counts the price once in its place rather than on top.

On the same day IBM began rejecting the IAM key (IAM: expired 2026-05-14), so
the model could not be asked; routing was checked with every conversation,
and every reply fell back to the template as designed.


**Status (2026-10-01): built; the gate's checks passed.** The user asked for it
on 2026-10-01. Migration `20261001_0006` was applied to ZBDGT the same day.

What was built:
- **`assistant_threads`** (Shape B, `AssistantThread`,
  `AssistantThreadRepository`) and migration `20261001_0006`. One row per
  conversation: `conversation_id`, `title` (the first question, cut to 60
  characters), `started_at`, `updated_at`, `turns`.
- **`assistant_service/history.py`**, the only writer. `turn.ask` saves after
  each turn, in the same commit as the usage count. A conversation id the
  memory no longer holds (after a lock) is read back from its row and carried
  on.
- **The choice is the user's, and off by default.** `assistant_history_days`
  is 0 (gone on lock, as before), 30, 90 or 365. Setting it to 0, or turning
  the assistant off, deletes every saved thread at once. A thread untouched
  for longer than the setting is deleted the next time the list is read. At
  most 50 are kept.
- **Deleting is for good.** Threads use `hard_delete`, not the soft delete the
  rest of the app uses: a conversation the user deleted must not sit in the
  table marked hidden.
- **Draft buttons are not saved.** Their payloads name accounts and categories
  by id, and `references.py` lists no references for this table, so a restore
  into another account would have left them pointing at the wrong rows.
  `open_screen` buttons are kept.
- **Step 2 needed almost nothing.** DEK rotation, account deletion, the Admin
  row counts and the integrity check all loop over `ENCRYPTED_MODELS` or
  `ORDER`, so adding the model and one `ORDER` entry was enough. The
  "ORDER covers every encrypted table" test failed until that entry was added,
  as planned. The working-set drop already covered memory; saved rows are not
  cached.
- **API:** `GET /assistant/conversations` (the list, newest first),
  `GET /assistant/conversations/{id}` (memory, then the saved row), `DELETE`
  (both). `/assistant/status` carries `history_days`.
- **Screen:** a "Keep conversations" choice under the question box; with it
  on, "Earlier conversations" on the empty screen, each with a two-tap delete.
  "New chat" leaves a kept conversation in the list. The opt-in card now says
  conversations are kept only if the user chooses.

Checked in the running app on made-up data: chose 90 days, asked, locked and
unlocked, opened the conversation from the list, started a new chat (it stayed
listed), chose "Until the app locks" (the list emptied and the row was gone).

Tests: `tests/test_ai_history.py` (13) - nothing kept by default, the payload
sealed, carried on after an unlock, draft buttons dropped, delete is for good,
both ways of turning it off, expiry, the 50 cap, another user cannot read or
delete one, DEK rotation re-seals it, account deletion removes it, and backup
and restore carry it. The store gained three vitest cases (83 in all).

Only if losing history on lock turns out to matter in use.

1. `assistant_threads` (Shape B) + `AssistantThreadRepository(EncryptedRepository)`.
2. Add it to `backup_service/references.py` ORDER, `rotation_repository.py`,
   account deletion, `verify_integrity.py`, and the working-set drop.
3. Retention: delete threads untouched for 90 days (a preference).

**Tests:** the existing "ORDER covers every encrypted table" test fails until
step 2 is done - that is the point; round-trip through backup and restore;
DEK rotation re-seals it.

**Gate:** the security-marked suite green; the user decides it is worth the
extra surface.
