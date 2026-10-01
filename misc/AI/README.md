# AI companion — plan

A budget assistant inside ZBDGT that answers questions about the user's own
money: *"Can I buy a ₱18,000 phone this month?"*, *"Where did my money go in
September?"*, *"What bills are due before payday?"*, *"How long until my
emergency fund is full?"*.

**Status (2026-10-01): A1–A6 built and committed.** Each phase in
[PHASES.md](PHASES.md) carries an "as built" note saying what changed from the
plan. What is left is on the server: install the packages, add the `.env`
block, check the connection, and watch the first week (`misc/DEPLOY.md`,
*Turning on the AI assistant*). The plan text below is kept as it was written;
where the build differs, the "as built" notes win.

| File | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it fits the app: the watsonx / IAM layer copied from STWRD, the skill engine, the privacy boundary, storage, frontend, failure modes. Numbered §1–§12; later code comments should cite `AI-ARCH §n`. |
| [FEATURES.md](FEATURES.md) | Feature-by-feature scope with IDs (`AI-01` …), in the same style as `misc/FEATURES.md`. |
| [PHASES.md](PHASES.md) | Build order A0–A6, each with its deliverables, tests, and a gate that must pass before the next one starts. |

## The five decisions everything else follows from

1. **Same AI as STWRD, same keys path.** IBM watsonx.ai
   (`ibm/granite-4-h-small`, us-south), with the API key fetched at runtime
   from the company IAM service (`IAM_MANAGEMENT_URL` +
   `/api/watson-credentials/company/{COMPANY_NAME}`). `.env` holds the IAM URL
   and company name, never the watsonx key. STWRD's `credential_loader.py`,
   `watsonx_client.py` and `llm_service.py` are ported with only the config
   plumbing changed (ARCHITECTURE §3).
2. **The model never does arithmetic and never reads the database.** Python
   answers the question with the services that already compute every figure
   (`budget_service.status`, `projection_service.project`,
   `safety_service.advice` …). The model does two narrow jobs: turn the
   question into a structured request, and turn a finished facts block into a
   sentence. Every peso figure in a reply is checked against the facts block
   before it is shown (ARCHITECTURE §5).
3. **The assistant never writes.** It can *propose* an entry or a goal, which
   opens the ordinary sheet pre-filled; the user saves it through the normal
   path and `afterWrite(...)`. No endpoint under `/assistant` changes
   financial data (ARCHITECTURE §8).
4. **Off by default, per user, with a plain disclosure.** Asking a question
   sends decrypted figures to IBM's cloud. That is the one place ZBDGT data
   leaves the process in plaintext, so each user opts in, sees exactly what is
   sent, and can switch it off (ARCHITECTURE §6).
5. **Conversations live in memory and die with the key.** Like the working
   set, a conversation is dropped on lock, sign-out or idle expiry. Nothing
   from a conversation goes into the database, the logs, or the browser's
   storage in the first release (ARCHITECTURE §7).

## Decisions taken (user, 2026-09-30)

- **Q1 — Company watsonx project: yes.** ZBDGT uses the company keys through
  IAM under the same `COMPANY_NAME` as STWRD / DMS. No separate IAM entry.
- **Q2 — Financial data to IBM us-south: yes.** Figures, and account,
  category and goal names, may be sent within the §6 minimum. This also
  clears AI-41 (merchant names for the rows `find` reports). Masking (AI-55)
  stays optional.
- **Q3 — Shared venv: yes.** Pin `ibm-watsonx-ai`, `httpx` and `requests` to
  the versions already installed in QUOT's venv
  (`C:\inetpub\wwwroot\FAST-PYTHON\.venv`). The exact numbers are read off
  the server (`pip list`) in A1 and confirmed with
  `pip install -r requirements.txt --dry-run`, so nothing QUOT uses is
  upgraded.
- **Q4 — Language: Taglish if it works, else English.** Taglish questions are
  understood from A2. Replies follow the language of the question only if
  the Taglish part of the golden set passes the same gate as English
  (PHASES A2). Otherwise every reply is in English, and that decision is
  recorded here (AI-63).
  **Decided 2026-09-30: English replies only** (`AI_REPLY_LANGUAGE=en`). The
  Taglish run passed on figures, but the user read the replies and chose
  English: several were awkward or wrong in tense. Taglish QUESTIONS are
  still understood. Ask again when the model changes.

One check is left before A1, and it isn't a decision: that this server
reaches `IAM_MANAGEMENT_URL` and `us-south.ml.cloud.ibm.com`. QUOT on the
same host suggests it does.

When this plan starts being built, add a Phase 16 row to `misc/ROADMAP.md`
pointing here, and tick features in [FEATURES.md](FEATURES.md) as they ship.
