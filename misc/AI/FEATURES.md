# AI companion — Features

Same conventions as `misc/FEATURES.md`: IDs are stable, quote them when asking
for a change, change a `Status` cell to change the scope. Architecture
references are to [ARCHITECTURE.md](ARCHITECTURE.md) (`AI-ARCH §n`); phases to
[PHASES.md](PHASES.md).

## Status legend

| Status | Meaning |
|---|---|
| ✅ **Built** | Built and tested (A1, A2 and A3 on 2026-09-30). |
| 📋 **Planned** | In scope, in the phase named. Not built. |
| 🟡 **Later** | Wanted; the architecture leaves room; not scheduled. |
| ❌ **Out** | Deliberately not built. Reason given. |
| ❓ **Decide** | Needs the user's call before its phase starts. |

## Summary

| Group | IDs | ✅ | 📋 | 🟡 | ❌ | ❓ |
|---|---|---|---|---|---|---|
| 1. Foundation | AI-01 – AI-08 | 8 | 0 | 0 | 0 | 0 |
| 2. Ask about your money | AI-10 – AI-21 | 12 | 0 | 0 | 0 | 0 |
| 3. Can I afford it? | AI-30 – AI-35 | 6 | 0 | 0 | 0 | 0 |
| 4. In context, and acting on answers | AI-40 – AI-45 | 0 | 6 | 0 | 0 | 0 |
| 5. Privacy and control | AI-50 – AI-55 | 5 | 0 | 1 | 0 | 0 |
| 6. Later / out | AI-60 – AI-67 | 1 | 0 | 3 | 4 | 0 |

---

## 1. Foundation

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-01 | **watsonx through the company IAM service** | ✅ | A1 | STWRD's `credential_loader.py`, `watsonx_client.py`, `llm_service.py` ported into `app/ai/`; the key is fetched from `IAM_MANAGEMENT_URL` for `COMPANY_NAME`, tested against IBM once, cached for `CREDENTIAL_CACHE_TTL`, never written to disk, the database or a log. `ibm/granite-4-h-small`, us-south. AI-ARCH §3 |
| AI-02 | **Kill switch** | ✅ | A1 | `AI_ENABLED=false` (the default): nothing imported, no thread, no IAM call, no entry point in the UI. Startup validation of the IAM settings only when it is true |
| AI-03 | **Health check** | ✅ | A1 | `GET /assistant/health` (admin) and `scripts/ai_health.py`: credentials loaded and accepted by IBM, model replies, milliseconds each - STWRD's `health()` |
| AI-04 | **Capacity guards** | ✅ | A1 | 30 s timeout on the SDK's HTTP client; one question in flight per user; three model calls per process (one uvicorn worker); timeouts never retried. AI-ARCH §12 |
| AI-05 | **Daily limit and usage counts** | ✅ | A1 | `assistant_usage` (Shape A): questions, tokens, model calls and fallbacks per user per day - counts only. 100 questions a day by default; the Admin screen shows totals |
| AI-06 | **Facts, not arithmetic** | ✅ | A2 | Every figure comes from an existing service through a skill, pre-formatted; the model only phrases. AI-ARCH §5.1 |
| AI-07 | **Figure verifier** | ✅ | A2 | Every amount, percentage and date in a reply must appear in the facts block, or the reply is replaced by a template answer. A made-up number cannot be shown |
| AI-08 | **Works without the model** | ✅ | A2 | Every skill has a template reply. IAM down, a timeout or a verifier failure gives the same figures, marked "Answered without AI" - never an error, never a lost question |

## 2. Ask about your money

Each skill reports the figure its screen shows - a test holds them equal.

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-10 | **Assistant screen** | ✅ | A2 | More → *Assistant* (`/assistant`). Chat of neo-brutalist cards, suggestion chips when empty, a typing indicator, no streaming. AI-ARCH §11 |
| AI-11 | **Budget status** | ✅ | A2 | *"How much is left?"*, *"Am I on track?"*, *"What's my daily allowance?"* - `budget_service.status` |
| AI-12 | **Spending breakdown** | ✅ | A2 | *"Where did my money go in September?"*, *"How much on food this month vs last?"* - `stats_service.overview` / `category_shares` |
| AI-13 | **Cash and net worth** | ✅ | A2 | *"How much cash do I have?"* - `cash_on_hand` (set-aside money excluded, as on Home), `net_worth` |
| AI-14 | **What's coming up** | ✅ | A2 | *"What bills are due before payday?"*, *"What's due this week?"* - the Months ahead projection and subscription reminders |
| AI-15 | **Card questions** | ✅ | A2 | *"How much do I owe on my BPI card?"*, *"When is it due?"*, *"How much limit is left?"* - credit views (`owed_with_plans`, bills, `due_now`) |
| AI-16 | **"Based on" panel** | ✅ | A2 | Every reply lists the facts behind it and the screens they came from, with a link to each |
| AI-17 | **Monthly review** | ✅ | A3 | *"How did I do last month?"* - `stats_service.review` (STA-12) |
| AI-18 | **Goals** | ✅ | A3 | *"How's my Japan fund?"*, *"How much a month to reach it by March?"* - `goal_service` (`monthly_need`, sinking funds GOA-09) |
| AI-19 | **Emergency fund** | ✅ | A3 | *"Is my emergency fund enough?"* - `safety_service.advice` (GOA-10/11), the rules that fired, the target |
| AI-20 | **Subscriptions and debts** | ✅ | A3 | *"What am I subscribed to?"*, *"Which debt should I pay first?"* - `subscription_service.overview`, `payoff_service.plan` (REC-35) |
| AI-21 | **How do I…?** | ✅ | A3 | Help questions about the app answered from a hand-written index - no user data sent |

## 3. Can I afford it?

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-30 | **Affordability verdict** | ✅ | A3 | *"Can I buy a ₱18,000 phone?"* → `yes` · `yes_over_budget` · `tight` · `wait` · `no`, from pure rules in `app/core/utils/affordability.py` over budget left, cash available, the projected lowest point before next income, the emergency fund and goals' monthly needs. The model explains the verdict; it never changes it. AI-ARCH §5.3 |
| AI-31 | **When it would fit** | ✅ | A3 | For `wait`: the first date the projection says it fits, and what income it waits for |
| AI-32 | **Pay by card or installment** | ✅ | A3 | *"What if I put it on my card in 6 months?"* - limit left, the bill it lands on, and the monthly payments laid on the Months ahead cash line (`affordability.schedule`) and the new lowest point. Writes nothing. Built pure instead of through `recurring_service.trial`, which needs an account and category the question does not give |
| AI-33 | **Take it from a goal** | ✅ | A3 | Names a goal that already holds enough to cover it. How far that goal's date would move is not worked out yet |
| AI-34 | **Effect on the budget** | ✅ | A3 | Over by how much, and the daily allowance for the rest of the period if bought today |
| AI-35 | **Not advice** | ✅ | A3 | Replies state what the numbers show and what each option does; no "you should". No product, bank, loan or investment is ever named or recommended |

## 4. In context, and acting on answers

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-40 | **Explain this** | 📋 | A4 | An *Explain* link on Home's budget card, each alert, the monthly review and an account page opens the assistant with that context; the server re-reads it (the browser names, never supplies, figures) |
| AI-41 | **Find a transaction** | 📋 | A4 | *"When did I last pay Meralco?"*, *"How much at Jollibee this month?"* - merchant names are sent to the model only for the rows reported; notes and descriptions never (the user allowed this on 2026-09-30, README Q2) |
| AI-42 | **Draft an entry** | 📋 | A4 | *"I just spent 250 on lunch"* → opens `TransactionSheet` pre-filled; the user saves through the ordinary path and `afterWrite(...MONEY)`. The assistant never saves. AI-ARCH §8 |
| AI-43 | **Draft a goal or budget** | 📋 | A4 | *"Help me save ₱50,000 for December"* → the goal editor pre-filled with the amount per month |
| AI-44 | **Try it as a what-if** | 📋 | A4 | From an affordability answer, open the What-if screen with the purchase filled in |
| AI-45 | **Home "Ask" tile** | 📋 | A4 | A small tile on Home once opted in, with two suggested questions chosen from the user's state (an alert, a near-empty budget) |

## 5. Privacy and control

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-50 | **Opt-in per user** | ✅ | A2 | `assistant` preference, server-side, off by default. Turning it on shows what is sent, to whom, and that ZBDGT keeps nothing; audited as `ASSISTANT_ENABLED` / `ASSISTANT_DISABLED`. AI-ARCH §6 |
| AI-51 | **Minimum data** | ✅ | A2 | Only the question, the facts block, and the last 6 turns. Never an email, a user or row id, a transaction note, a raw row, a receipt or a backup |
| AI-52 | **Nothing logged** | ✅ | A1 | Prompt and reply text are never logged or audited, DEBUG or not; `api_key` joins the redaction filter's named secrets. A security-marked test captures every log record |
| AI-53 | **Forgotten on lock** | ✅ | A2 | Conversations live in process memory and are dropped with the DEK (lock, sign-out, idle expiry, sweep) - the working set's hook. Nothing in the browser's storage (invariant 10) |
| AI-54 | **Pilot allow-list** | ✅ | A1 | `AI_ALLOWED_USER_IDS`; blank means every opted-in user |
| AI-55 | **Mask account names** | 🟡 | A5 | Optional: accounts go to the model as "your savings account (1)" and real names are put back in the reply server-side |

## 6. Later / out

| ID | Feature | Status | Phase | Scope |
|---|---|---|---|---|
| AI-60 | **Saved history** | 🟡 | A6 | Conversations kept across locks as a Shape B table under the user's DEK - then part of backup, restore, DEK rotation, deletion and integrity checks. AI-ARCH §7 |
| AI-61 | **Weekly nudge** | 🟡 | — | A short written summary on Home once a week. Needs a model call without the user asking, which A1–A5 never make |
| AI-62 | **Receipt reading** | 🟡 | — | Read amount and merchant from a photo. Would send an image of a receipt to IBM; a separate privacy decision |
| AI-63 | **Taglish** | ✅ | A2 | Questions in English, Filipino or Taglish are understood from A2. Replies follow the question's language (`AI_REPLY_LANGUAGE=match`) only if the Taglish golden questions pass the A2 language gate; otherwise English only (user, 2026-09-30). Template replies are English either way. Built: the switch and both prompts; the gate numbers passed (100% routed, 100% figure-checked). Waiting on the user reading the Taglish replies before `match` becomes the default |
| AI-64 | **The assistant saves entries itself** | ❌ | — | A proposal the user confirms is one tap more and removes a whole class of mistakes. STWRD decision 3 |
| AI-65 | **Investment or product advice** | ❌ | — | Not licensed, not the app's job |
| AI-66 | **Model reads the database / writes SQL** | ❌ | — | The data is ciphertext and SQL cannot see inside it; and the model must not decide what to read |
| AI-67 | **Streaming replies** | ❌ | — | The verifier needs the whole reply before any of it may be shown |
