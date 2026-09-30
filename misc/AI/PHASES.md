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

## A6 — Saved history (optional, AI-60)

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
