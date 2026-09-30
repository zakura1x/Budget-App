# DEPLOYING BUDGET APP TO THE SERVER

IIS on the same host as QUOT, under `https://delca.noahapplication.com/ZBDGT`.

**Deploys are COPIED, not pulled.** There is no git remote on the server:
`scripts/make_release.py` zips the last commit on your PC and you copy that zip
over. Nothing is ever built on the server — it has no Node and no npm.

Three rules that outrank every step below:

1. **`.env` is not in the zip and never will be.** It holds the master key. It
   is copied by hand, once, and left alone afterwards.
2. **`.env`, `uploads/`, `backups/` and `logs/` on the server are never deleted
   or overwritten.** They are the data; the zip is only code.
3. **One worker.** `web.config` sets it and explains why (session keys and the
   decrypted working set live in process memory). Never raise it.

---

## Before the first deploy — what the host needs

| Needed | How to check |
|---|---|
| IIS with **httpPlatformHandler** | It is what QUOT runs on. Ask the platform team if unsure |
| The shared venv `C:\inetpub\wwwroot\FAST-PYTHON\.venv` | QUOT uses it; `web.config` points at its `python.exe` |
| **ODBC Driver 17 for SQL Server** | Matches `DB_DRIVER` in `.env` |
| Reach to `P8_NOAH_AI`, schema `ZBDGT` | The schema already exists (migrated 2026-09-11) |
| An app pool for the ZBDGT application | Idle shutdown is fine — the app is built around it |

The IIS application **must be named `ZBDGT`**. Every route the app generates
carries `/ZBDGT`, because `BASE_URL` and `API_PREFIX` say so in `web.config`.

---

## Every update

On your PC:

```bash
cd frontend
npm run build          # type-checks, writes ../app/web/static/dist/
cd ..
pytest -q              # the suite must be green
git add -A && git commit
python scripts/make_release.py      # -> release\zbdgt-<commit>.zip
```

`make_release.py` refuses while anything is uncommitted — an uncommitted edit
would silently not be in the zip. The zip is `git archive` of HEAD, so it can
never carry `.env`, `uploads/`, `backups/`, `logs/`, `.venv/` or
`node_modules/`.

On the server, in `C:\inetpub\wwwroot\ZBDGT`:

1. **Stop traffic**: in IIS Manager, stop the ZBDGT app pool.
2. **Delete** the folders `app\`, `alembic\` and `scripts\`.
   Deleting them rather than merging is what removes files that no longer exist
   in the code — above all the old hashed bundle files in
   `app\web\static\dist\assets\`.
3. **Unzip** the release over the folder, replacing the top-level files.
4. **Never touch** `.env`, `uploads\`, `backups\`, `logs\`.
5. If `requirements.txt` changed, see *Python packages* below.
6. If `alembic\versions\` gained a file, see *Database migrations* below.
7. **Start the app pool**, then open
   `https://delca.noahapplication.com/ZBDGT/api/v1/health`.

Expect `healthy`, with the database reachable, the schema present and the
master key loaded. Then sign in and check one real figure — Home, and the
Accounts tab.

A deploy is only code. Nobody is signed out: sessions live in cookies, and a
restart looks exactly like an auto-lock — the next request asks for the PIN.

---

## The first deploy

1. Build, commit and zip as above.
2. Unzip into `C:\inetpub\wwwroot\ZBDGT`.
3. **Copy `.env` by hand** into that folder. It is not in git. Check it is the
   same file as your offline copy:

   ```bash
   python scripts\env_fingerprint.py --compare <path to the offline copy>
   ```

   Different fingerprints mean different keys — stop and find out why before
   anyone signs up. Set for production, in `.env`:

   | Setting | Value |
   |---|---|
   | `DB_SERVER`, `DB_USER`, `DB_PASSWORD` | the company SQL Server |
   | `REGISTRATION_CODE` | what you hand to anyone you invite |
   | `MAX_USERS` | how many accounts are allowed at all |
   | `SMTP_*` | the mailbox reset links are sent from (SEC-30) |
   | `BACKUP_OFFSITE_DIR` | a second location, if you have one |

   `ENVIRONMENT`, `DEBUG`, `BASE_URL`, `API_PREFIX`, `SESSION_COOKIE_SECURE`
   and `APP_PUBLIC_URL` come from `web.config` — leave them out of `.env`, or
   keep them identical.
4. **Create the folders the app writes to** if they are not there: `logs\`,
   `uploads\`, `backups\`. The app pool identity needs write access to all
   three.
5. **Python packages** — preview first, because the venv is shared with QUOT:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\pip install -r requirements.txt --dry-run
   ```

   Install for real only once the preview shows nothing QUOT depends on being
   changed underneath it.
6. **Database migrations** — the schema is shared with your PC, so it is
   usually already up to date. If a release adds one, tell the DB owner, then:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\alembic upgrade head
   ```

   `alembic.ini` has no connection string: `alembic/env.py` builds it from
   `.env` through the app's own engine factory.
7. In IIS Manager, add an application named **ZBDGT** on the QUOT site,
   pointing at `C:\inetpub\wwwroot\ZBDGT`. `web.config` is already in the zip:
   one worker, the shared venv, no secrets.
8. Open `/ZBDGT/api/v1/health`, then the app itself.
9. Once, on the server — the number that settles ARCHITECTURE §5.7:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\python scripts\benchmark_fetch.py
   ```

   Read-only. Under 1500 ms and the encryption design stands as it is. (From
   your PC it reads ~2.3 s — that is the link, not the app.)

---

## Turning on the AI assistant (misc/AI)

The assistant ships switched off (`AI_ENABLED=False`): nothing is loaded, no
service is called, and the Assistant row is hidden. Turning it on is five
steps on the server, in this order.

1. **Python packages.** `requirements.txt` adds `ibm-watsonx-ai` and
   `requests`, which QUOT already has in the shared venv. Never upgrade what
   QUOT runs, so read what is installed first:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\pip list | findstr /i "ibm-watsonx-ai requests httpx"
   ```

   On your PC, lower the two floors in `requirements.txt` to those versions,
   commit, and make a new release. Then the dry run must show nothing being
   changed:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\pip install -r requirements.txt --dry-run
   ```

2. **The table.** `assistant_usage` (migration `20260930_0005`) was applied
   from the PC on 2026-09-30. `alembic current` on the server should name it.
   It holds counts per account per day and nothing else.

3. **`.env`** — add the block from `.env.example` by hand. None of it is a
   secret: the watsonx key is fetched from the company IAM service when a
   question is asked and lives only in memory.

   | Setting | Value |
   |---|---|
   | `AI_ENABLED` | `True` |
   | `COMPANY_NAME`, `IAM_MANAGEMENT_URL` | the same two lines as STWRD's `.env` |
   | `AI_ALLOWED_USER_IDS` | your own account number for the pilot; blank later, for everyone who turns it on |
   | `AI_REPLY_LANGUAGE` | `en` |
   | `IAM_REPORT_TEST_STATUS` | `False` — the IAM record is shared with QUOT, DMS and STWRD |

   Refresh the offline `.env` copy the same day.

4. **Check it from the server** before anyone uses it:

   ```bash
   C:\inetpub\wwwroot\FAST-PYTHON\.venv\Scripts\python scripts\ai_health.py --measure 20
   ```

   It fetches the key as the app does, asks the model for one word, then
   times 20 calls. It prints what each check found and never the key. p95
   should be under 5 seconds. The server must be able to reach
   `IAM_MANAGEMENT_URL`, `iam.cloud.ibm.com` and `us-south.ml.cloud.ibm.com`.

5. **Recycle the app pool.** Sign in, More → Assistant, turn it on and ask
   one question. Then More → Admin → *Check the connection*.

**The pilot.** Admin's Assistant lines show, per day and for all accounts
together, the questions asked, how many the app answered without the model,
and the tokens used. A day above 10% answered without AI is worth a look
(`logs\app.jsonl` has one "Assistant turn" line per question with the reason -
never the question). After a quiet week, blank `AI_ALLOWED_USER_IDS`.

**Turning it off** is `AI_ENABLED=False` and a recycle. Nothing else changes:
the row disappears, and no figure anywhere depends on the assistant.

---

## After a deploy — worth doing once

- **Sign in on the phone** and add it to the home screen (PWA).
- **Send one real password-reset email** end to end over HTTPS, and confirm the
  link opens `/ZBDGT/reset`.
- **Practise a restore**: `python scripts\restore.py FILE --target-user-id N
  --verify` writes nothing and diffs. A backup you have never restored is not a
  backup.
- **Refresh the offline `.env` copy** if anything in `.env` changed.

---

## Rolling back

Keep the previous `release\zbdgt-<commit>.zip`. To roll back: stop the pool,
delete `app\`, `alembic\`, `scripts\`, unzip the older release, start the pool.
Data is untouched — it lives in SQL Server and in the folders you never delete.

A rollback across a migration is the exception. If the newer release migrated
the schema, roll the database back first, or leave it if the change was
additive and the older code ignores it. Ask the DB owner before either.

---

## When something is wrong

| Symptom | Where to look |
|---|---|
| **HTTP 500.19** on every page | `web.config` is malformed. A literal double hyphen inside an XML comment does this |
| **502 / "process failed to start"** | `logs\uvicorn.log`. Usually `.env` missing or a bad `BUDGET_MASTER_KEY` — the app refuses to start rather than write plaintext |
| Health says **database unreachable** | `DB_*` in `.env`, the ODBC driver, and whether the server can see SQL Server |
| Health says **master key not loaded** | `.env` missing, unreadable by the app pool identity, or the key is the wrong length |
| **Every route 404s** | The IIS application is not named `ZBDGT`, or `BASE_URL` was changed |
| Signed out on every request | `SESSION_COOKIE_SECURE=true` without HTTPS, or `SESSION_COOKIE_PATH` outside `BASE_URL` |
| Old screens after a deploy | `app\web\static\dist\` was merged instead of replaced — delete `app\` and unzip again. In the browser, reload once so the service worker picks up the new build |
| Reset emails never arrive | `logs\app.jsonl` says "Email could not be sent" with the reason; check the Gmail App Password |
| No **Assistant** row under More | `AI_ENABLED` is `False`, or `AI_ALLOWED_USER_IDS` names other accounts |
| Every reply says **"Answered straight from your figures"** | The model is not answering; the figures are still right. Admin → *Check the connection* names which half failed — see `misc/how-to-run.txt`, *THE AI ASSISTANT* |
| **"The assistant is busy"** | More than `AI_MAX_CONCURRENT_CALLS` questions were in flight for longer than `AI_QUEUE_WAIT_SECONDS`. Usually IBM answering slowly; it clears by itself |

Logs: `logs\uvicorn.log` (startup and crashes) and `logs\app.jsonl` (one line
per request, money and key material redacted by design).

---

## What this app deliberately does not ask the host for

- **AlwaysRunning / idle timeout 0** — declined for QUOT on a server running
  ~90 applications, and nothing here needs it. Recurring charges and backups
  catch up when the app is next used (ARCHITECTURE §12.6).
- **HSTS** — it would apply to the whole host, which this app shares.
- **Security headers in IIS** — the app sends its own, with a per-request CSP
  nonce. Two owners would send them twice.
- **A scheduled task** — optional (DAT-20) and not built. Writing a backup needs
  no key, so `scripts\backup.py --all` under Task Scheduler is possible the day
  you want backups that do not depend on anyone opening the app.

See also: `misc/how-to-run.txt` (day-to-day runbook, key rotation, the offline
`.env` copy) and `misc/ARCHITECTURE.md` §10 (why the deployment is shaped this
way).
