# BUDGET APP — Architecture at a Glance

> The visual tour. [ARCHITECTURE.md](ARCHITECTURE.md) is the same system in
> detail; [phases.md](phases.md) is the order it gets built in;
> [FEATURES.md](FEATURES.md) is the feature-by-feature scope list.

**Personal Budget & Spending Tracker**
FastAPI · SQL Server (`ZBDGT` schema) · React 19 + Vite · AES-256-GCM at rest

---

## 1. What the system does

You set a budget for a period. You log what you spend. The app answers one
question better than any other: **how much can I still spend today?**

It is a web reimplementation of the iOS app *Budget App — Spending Tracker*,
with two deliberate differences: it runs on a shared company database, so
**every field of financial data is encrypted before it leaves the process**;
and it is a mobile-first React PWA rather than a native app.

```mermaid
graph LR
    A["Set a budget<br/>weekly / monthly / custom"] --> B["Log spending<br/>2 taps + a number"]
    B --> C["Daily allowance<br/>recomputed instantly"]
    C --> D["Calendar heatmap<br/>Stats · Subscriptions"]
    D --> B

    style A fill:#dbeafe,stroke:#1e40af
    style B fill:#dcfce7,stroke:#166534
    style C fill:#fef3c7,stroke:#b45309
    style D fill:#f3e8ff,stroke:#6b21a8
```

Two kinds of entry the app writes for you, rather than asking you to type
them, both as ordinary rows you can see and delete:

```mermaid
graph LR
    I["Savings interest<br/>ACC-37"] -->|"one income entry a day,<br/>net of tax"| L["Your ledger"]
    C["A purchase with cashback<br/>TXN-22"] -->|"the purchase, full amount<br/>+ the credit beside it"| L

    style I fill:#dcfce7,stroke:#166534
    style C fill:#f3e8ff,stroke:#6b21a8
    style L fill:#dbeafe,stroke:#1e40af
```

Neither is a special kind of transaction: interest is income filed in the
category you chose, and cashback is income joined to its purchase the way a
transfer's two legs are joined. Anything that reads the ledger — stats, the
budget, the calendar — sees them without knowing they exist.

---

## 2. How a request reaches the code

One process serves the API, the SPA shell, and the built React bundle. There is
no separate frontend service to deploy, and no Node on the server.

```mermaid
graph TD
    U["iPhone / browser<br/>installed PWA"] -->|"https://host/ZBDGT/..."| IIS["IIS<br/>(httpPlatformHandler)"]
    IIS -->|"launches, forwards<br/>the path unchanged"| UV["uvicorn — 1 worker"]
    UV --> APP["FastAPI app"]

    APP --> M1["SecurityHeaders<br/>CSP nonce, frame DENY"]
    M1 --> M2["RateLimit"]
    M2 --> M3["Logging<br/>(redaction filter on)"]
    M3 --> M4["Auth<br/>attaches identity + DEK handle"]
    M4 --> R{"Which router?"}

    R -->|"/ZBDGT/api/v1/*"| API["API router → JSON"]
    R -->|"/ZBDGT/static/*"| ST["StaticFiles → the React bundle"]
    R -->|"anything else"| SPA["SPA fallback → index.html"]

    style IIS fill:#fee2e2,stroke:#991b1b
    style APP fill:#dbeafe,stroke:#1e40af
    style M4 fill:#fef3c7,stroke:#b45309
```

Four things worth knowing:

- **One worker — QUOT runs two, this app can't.** The decrypted working set and
  the session keys live in process memory. A second worker would hold its own
  copy, serve stale numbers after a write landed on the other, and see users as
  locked who had just unlocked. One worker is correct here.
- **The SPA fallback is a catch-all.** React Router owns the URL space, so any
  unmatched path returns `index.html` and lets the client route it.
- **`AuthMiddleware` does not block.** It attaches identity when a token is
  valid and lets everything through; the `get_current_user` dependency enforces.
  Same deliberate split as QUOT — a failed login still gets audited.
- **The app refuses to boot without a valid master key.** Not a warning. A
  budget app that quietly starts writing plaintext is worse than one that stops.

---

## 3. The layers

Every feature is the same four steps, in the same direction, with encryption
sitting on exactly one boundary.

```mermaid
graph TD
    subgraph L1["1 — Endpoints (app/api/v1/endpoints/)"]
        E["HTTP in, HTTP out.<br/>Validate, check auth, call one service."]
    end
    subgraph L2["2 — Services (app/services/)"]
        S["All the thinking.<br/>Budget maths, stats, recurring expansion.<br/>Sees only plaintext domain objects."]
    end
    subgraph L3["3 — Repositories (app/db/repositories/)"]
        RP["All the SQL — and the ONLY place<br/>encrypt/decrypt is called."]
    end
    subgraph L4["4 — Models (app/db/models/)"]
        MD["15 tables. Payloads are VARBINARY."]
    end

    L1 --> L2 --> L3 --> L4 --> DB[("SQL Server — schema ZBDGT<br/>stores ciphertext it cannot read")]
    RP -.->|"encrypt / decrypt"| CR["core/crypto/<br/>keys never leave here"]

    style L1 fill:#dbeafe,stroke:#1e40af
    style L2 fill:#dcfce7,stroke:#166534
    style L3 fill:#fef3c7,stroke:#b45309
    style L4 fill:#f3e8ff,stroke:#6b21a8
    style CR fill:#fee2e2,stroke:#991b1b
```

**The rule that keeps this honest:** a service author never encrypts anything.
Repositories return fully decrypted objects and accept fully populated ones.
Forgetting to encrypt one field, in one place, once, is exactly the failure this
boundary is designed to make impossible.

**Where to look when you need to change something:**

| If you need to change… | Go to |
|---|---|
| A URL, request shape, or response shape | `app/api/v1/endpoints/` |
| Budget maths, a stat, recurring logic | `app/services/` |
| A query, or how something is stored | `app/db/repositories/` |
| A field inside an encrypted payload | the payload schema in `app/api/v1/schemas/` |
| Anything about keys or ciphers | `app/core/crypto/` — and read §5 of ARCHITECTURE.md first |
| A screen | `frontend/src/` — then rebuild and commit `dist/` |

---

## 4. The data model

Fifteen tables in two shapes. Four are operational and readable; eleven hold a
single encrypted blob each.

```mermaid
graph TD
    subgraph OPS["Operational — readable, indexed"]
        US["users<br/>email_bidx · password_hash<br/>dek_wrapped · pin_hash"]
        RT["refresh_tokens"]
        LA["login_attempts"]
        AL["audit_log"]
    end

    subgraph ENC["Data — id + user_id plaintext, everything else encrypted"]
        AC["accounts"]
        CA["categories"]
        BU["budgets"] --> BA["budget_allocations"]
        TX["transactions"]
        RR["recurring_rules"]
        SU["subscriptions"]
        SG["savings_goals"]
        TG["tags"]
        AT["attachments"]
        UP["user_preferences"]
    end

    US --> ENC
    RR -.->|"expands into"| TX
    TX -.->|"references (in ciphertext,<br/>so no FK possible)"| AC
    TX -.-> CA
    TX -.-> AT

    style OPS fill:#dbeafe,stroke:#1e40af
    style ENC fill:#fee2e2,stroke:#991b1b
```

A `transactions` row as the DBA sees it, versus as the app sees it:

```
WHAT SQL SERVER STORES                 WHAT THE APP DECRYPTS IT TO
──────────────────────                 ───────────────────────────
id          4821                       {
user_id     1                            "txn_date":   "2026-09-08",
key_version 1                            "type":       "expense",
payload     0x01 01 9f3a...              "amount":     "3500.00",
            (a 214-byte blob)            "account_id": 3,
is_deleted  0                            "merchant":   "SM Supermarket",
row_created 2026-09-08 14:22:07          "splits": [
row_updated 2026-09-08 14:22:07            {"category_id": 11,
                                            "amount": "2800.00"},
                                           {"category_id": 19,
                                            "amount":  "700.00"}
                                         ],
                                         "tag_ids":    [2, 7]
                                       }
```

Note the dotted arrows above: those relationships are **real but unenforceable**.
`category_id` is inside the ciphertext, so no foreign key can exist. Integrity is
the service layer's job, and `scripts/verify_integrity.py` checks for drift.

`row_created` is the *insert* timestamp, not the transaction date. It leaks when
you used the app — unavoidable — while `txn_date`, which is your actual financial
timeline, stays encrypted.

---

## 5. Flow A — logging an expense

The core interaction. Everything is tuned so this takes two taps and a number.

```mermaid
sequenceDiagram
    participant U as You
    participant R as React (bottom sheet)
    participant API as POST /api/v1/transactions
    participant SVC as transaction_service
    participant CR as UserCipher
    participant REPO as transaction_repository
    participant DB as SQL Server

    U->>R: tap [+], type 1250, pick Groceries
    R->>API: {amount, category_id, account_id, txn_date}
    API->>API: validate · get_current_user · get_dek
    API->>SVC: create(user, payload)
    SVC->>SVC: business rules — account exists,<br/>category exists, amount > 0
    SVC->>REPO: create(user_id, domain_object)

    rect rgb(254, 226, 226)
        REPO->>DB: INSERT placeholder → get identity id
        DB-->>REPO: id = 4821
        REPO->>CR: encrypt(payload, dek, aad="ZBDGT.transactions:4821:1:v1")
        CR-->>REPO: 0x01 01 9f3a...
        REPO->>DB: UPDATE payload = ciphertext
    end

    Note over REPO,DB: both steps, one DB transaction —<br/>AAD needs the row id to exist first

    REPO-->>SVC: saved object
    SVC->>SVC: working-set cache updated in place
    SVC->>SVC: recompute remaining + daily allowance
    SVC-->>API: {transaction, budget_status}
    API-->>R: 201
    R->>U: sheet closes, ring animates,<br/>"₱612 left today"
```

The response carries the recomputed budget status, so the home screen updates
without a second round trip. That is what makes it feel native.

---

## 6. Flow B — opening the app (the decryption path)

This is where the encryption design either pays off or hurts, so it is worth
following closely.

```mermaid
sequenceDiagram
    participant U as You
    participant R as React
    participant API as POST /api/v1/auth/login
    participant AUTH as auth_service
    participant CR as UserCipher
    participant DB as SQL Server
    participant WS as working-set cache

    U->>R: email + password
    R->>API: credentials
    API->>AUTH: authenticate()

    AUTH->>CR: blind_index(email)
    Note over CR: HMAC-SHA256(email, PEPPER)<br/>the one deterministic value in the system
    CR-->>AUTH: 3f9a2c...
    AUTH->>DB: SELECT * FROM users WHERE email_bidx = ?
    DB-->>AUTH: row (password_hash, dek_wrapped)
    AUTH->>AUTH: bcrypt verify · check lockout

    rect rgb(254, 226, 226)
        AUTH->>CR: unwrap_dek(dek_wrapped, MASTER_KEY)
        Note over CR: HKDF → wrapping key → AES-GCM open
        CR-->>AUTH: DEK (32 bytes, memory only)
        AUTH->>CR: hold DEK in session keyring
    end

    AUTH->>WS: warm(user_id, dek)
    WS->>DB: SELECT * WHERE user_id = 1 AND is_deleted = 0
    DB-->>WS: ~10,000 ciphertext rows
    loop every row
        WS->>CR: decrypt(payload, dek, aad)
    end
    Note over WS: ≈ 0.3–0.6 s, once per session,<br/>while the unlock screen is still up

    AUTH-->>API: JWT + refresh (HttpOnly cookies)
    API-->>R: 200
    R->>U: home screen — every figure from memory, < 1 ms
```

**The trade, stated plainly.** Because dates and category IDs are encrypted too,
SQL cannot filter or sum anything — so the app loads your rows once and does all
arithmetic in memory. One slow moment at login buys instant everything
afterwards. At personal scale this is comfortable. §5.7 of ARCHITECTURE.md has
the escape hatch if it ever stops being.

---

## 7. Flow C — where the daily allowance number comes from

The number the whole app exists to display. Pure Python over the warm cache.

```mermaid
graph TD
    S["Budget period<br/>e.g. Sept 1–30, ₱40,000"] --> C1
    T["Transactions in period<br/>splits summed per category"] --> C1
    C1["spent = sum of expense splits<br/>(decrypted, in Python)"] --> C2
    C2["remaining = budget − spent"] --> C3
    C3{"allowance mode"}

    C3 -->|"remaining ÷ days left<br/>(default)"| D1["self-corrects<br/>after overspending"]
    C3 -->|"fixed daily"| D2["budget ÷ total days<br/>constant target"]

    D1 --> OUT["'You can spend ₱612 today'"]
    D2 --> OUT

    CO["carry-over setting<br/>(default OFF)"] -.->|"if ON, last period's<br/>surplus OR overspend<br/>rolls forward"| C2

    C2 --> AL{"alert checks"}
    AL -->|"spent ≥ 100%"| A1["🔴 over budget"]
    AL -->|"spent ≥ 80%"| A2["🟠 approaching"]
    AL -->|"spent % > elapsed %"| A3["🟡 pace warning"]
    A1 --> BAN["banner on Home<br/>+ tab-bar badge"]
    A2 --> BAN
    A3 --> BAN

    CRD["each credit card<br/>(its own statement cycle)"] --> CK{"card checks"}
    CK -->|"bill left to pay,<br/>due within 5 days"| A4["🟠 card due"]
    CK -->|"own limit: 80% · pace<br/>· 100% = 🔴"| A5["🟠 / 🔴 card limit"]
    A4 --> BAN
    A5 --> BAN

    style C1 fill:#dcfce7,stroke:#166534
    style OUT fill:#fef3c7,stroke:#b45309
    style BAN fill:#fee2e2,stroke:#991b1b
```

**Alerts are computed here, in your session, from data already decrypted** —
never by a background service. That is why there is no web push: a push sender
would have to know you are over budget while you are not using the app, which
means holding your keys outside your session. Same information, no new exposure.

The default mode is self-correcting: overspend today and tomorrow's allowance
drops automatically. That is the behaviour the iOS app has, and it is the reason
the number changes behaviour rather than just reporting on it.

Recurring rules feed this too — `recurring_service` expands rules into real
transactions on their due date, so a ₱1,500 subscription reduces your allowance
on the day it charges, not as a surprise at month end.

The same rules also look **forward**. `projection_service` asks `recurring_service`
for every occurrence in the coming months and lays them out as salary in,
committed charges out, the rest of the budget, and cash on hand at each month
end. It also shows each credit card's next statements. It reads and never posts,
so a projected salary cannot turn into a real transaction by accident
(ARCHITECTURE.md §4.5).

---

## 8. The screens

Bottom tab bar, thumb-reachable, `[+]` centre and raised. Designed at 390 px.
Since 2026-09-15 the tabs are Home · Accounts · [+] · Calendar · More. Since
2026-09-18 the look is neo-brutalist - outlined tiles, hard shadows, mono
figures - in four palettes (classic, candy, lime, mono), each light and dark.

```mermaid
graph TD
    L["Lock screen<br/>PIN · biometric"] --> H

    subgraph TABS["Bottom tab bar"]
        H["🏠 Home<br/>ring · daily allowance<br/>category tiles<br/>recent activity"]
        ACC["👛 Accounts<br/>cash on hand<br/>tiles by type · cards"]
        ADD["➕ Add<br/>numpad bottom sheet"]
        CAL["📅 Calendar<br/>heatmap · month list"]
        MORE["☰ More"]
    end

    CAL <-->|"Calendar | Stats switch"| ST["📊 Stats<br/>category pie<br/>trend line<br/>drill-down"]
    H --> B["Budget<br/>gauge · Remain | Plan"]
    ACC --> AD["Account page<br/>balance banner · + / transfer<br/>trail of money in and out"]
    MORE --> M2["Budgets & categories"]
    MORE --> M3["Recurring & subscriptions<br/>projection · card look-ahead"]
    MORE --> M4["Savings goals"]
    MORE --> M5["Import / Export CSV"]
    MORE --> M6["Settings — theme, PIN,<br/>carry-over toggle,<br/>key rotation"]

    ADD -.->|"closes, ring animates"| H

    style ADD fill:#dcfce7,stroke:#166534
    style H fill:#dbeafe,stroke:#1e40af
    style L fill:#fee2e2,stroke:#991b1b
```

The add sheet opens with the amount focused and the numpad already up. No
keyboard, no tap-to-focus, no scrolling to a submit button.

---

## 9. How React gets to the server

The server has no Node and no npm, permanently. The build happens on your
machine and the output is committed.

```mermaid
graph LR
    subgraph LOCAL["Your PC"]
        SRC["frontend/src/*.tsx"] -->|"npm run build<br/>(Vite)"| DIST["app/web/static/dist/<br/>index-[hash].js<br/>index-[hash].css<br/>manifest · sw.js"]
    end

    DIST -->|"git commit"| REPO[("git")]
    REPO -->|"git pull + restart"| SRV

    subgraph SRV["The server"]
        SF["FastAPI StaticFiles<br/>serves bytes.<br/>No Node. No npm.<br/>No build step."]
    end

    style LOCAL fill:#dcfce7,stroke:#166534
    style SRV fill:#dbeafe,stroke:#1e40af
```

`dist/` is committed on purpose — `.gitignore` says so at the line where it
would otherwise be excluded. Because Vite hashes filenames, the app reads
`dist/.vite/manifest.json` at startup and injects the current names into the
Jinja shell, so `index.html` always points at the bundle that is really there.

Development is different: Vite dev server on `:5173` with hot reload, proxying
API calls to uvicorn on `:8000`. That is the only reason `CORS_ORIGINS` exists —
in production both come from one origin.

---

## 10. What is protected, and what is not

Worth being exact, because "encrypted" is often claimed more broadly than it is
true.

```mermaid
graph TD
    subgraph SAFE["Defended against"]
        S1["DBA running SELECT *"]
        S2["Anyone with db_datareader"]
        S3["A stolen backup file"]
        S4["A tampered row<br/>(GCM tag fails loudly)"]
        S5["Swapping one row's<br/>ciphertext for another<br/>(AAD binds row id)"]
    end

    subgraph NOT["NOT defended against"]
        N1["Admin on the app server<br/>— can read .env"]
        N2["Anyone who can dump<br/>process memory while running"]
        N3["Anyone holding .env or its offline copy<br/>AND the database or a backup"]
    end

    style SAFE fill:#dcfce7,stroke:#166534
    style NOT fill:#fee2e2,stroke:#991b1b
```

**`.env` is the one key, and its offline copy is the insurance.** There is no
recovery phrase (removed 2026-09-14): every user's DEK is wrapped by the master
key alone. The server owner keeps a copy of the whole `.env` off the server, in
at least two places, apart from the backup files, and refreshes it whenever a
key changes. A forgotten password is reset by an emailed link, which touches no data.

The trade is concentration. Users carry nothing, and the owner carries all of
it: losing `.env` and every copy loses every account at once, and whoever holds
`.env` plus the database can read everything.

The honest summary: this defends your data from **the database and everyone with
access to it**, which is precisely the risk you took on by using the company
server for personal finances. It does **not** defend against someone with
administrative control of the machine doing the decrypting. If the same team
administers both, this buys less than it appears to.

On key loss: **there is one way in** — `BUDGET_MASTER_KEY` in `.env`. Keep the
offline copy current and check it against the server by fingerprint. Losing
`.env` with a good copy is a five-minute restore. Losing it without one is
permanent, for everyone, and no support ticket will change that.

---

## 11. Backup — so the database is not your only copy

The company database is shared infrastructure you do not control. The app
therefore owns a complete, portable, **still-encrypted** copy of itself.

```mermaid
graph LR
    DB[("SQL Server<br/>ZBDGT schema")] -->|"copy rows exactly as stored<br/>no key needed"| EX["export"]
    EX --> F["budget-2026-09-08.budgetbak<br/>manifest · keys.enc<br/>every row · attachments"]

    F --> U["USB stick"]
    F --> C["Cloud storage"]
    F --> L["Personal laptop"]

    F -->|"restore"| IM["import"]
    IM -->|"unwrap DEK → decrypt with ORIGINAL AAD<br/>→ INSERT → re-encrypt with NEW AAD"| DB2[("any database,<br/>anywhere")]

    style F fill:#dcfce7,stroke:#166534
    style DB fill:#dbeafe,stroke:#1e40af
    style DB2 fill:#dbeafe,stroke:#1e40af
```

**Why only the import re-encrypts.** AAD binds every ciphertext to its row `id` —
the thing that stops a DBA swapping your ₱5 coffee over your ₱50,000 rent. So
rows can't simply be reloaded into a new database, which assigns new ids. The
export copies each row exactly as stored, along with its original `id`; the
import uses that to rebuild the original AAD, decrypts, inserts, and re-encrypts
under the new id. **Writing a backup decrypts nothing and needs no key.**

**When.** Five minutes after your last change, and at login if the newest backup
is over a day old — never at a fixed time, because IIS stops the app after 20
idle minutes and a 02:00 job would rarely fire. Data only changes while the app
is in use, so nothing is missed.

The file carries the wrapped DEK, so it is **standalone** wherever the master key
exists — a new server, an empty database, and the offline `.env` copy bring
everything back. Keep the file and that copy apart: together they are the data.

Safe to put anywhere: it is ciphertext throughout. There is deliberately **no
plaintext full archive**; per-transaction CSV export remains for Excel, and that
stays the single warned opening in the encryption boundary.

> The test that makes it real: **export → restore into an empty database →
> export again → the two must match.** Until that passes, you have a file.

---

## 12. Multiple users

Supported — and it was nearly free, because every table has carried `user_id`
and a per-user key since Phase 1.

```mermaid
graph TD
    subgraph A["Alice"]
        AK["Alice DEK"] --> AR["rows WHERE user_id = 1"]
    end
    subgraph B["Bob"]
        BK["Bob DEK"] --> BR["rows WHERE user_id = 2"]
    end

    AK -.->|"cannot open"| BR
    BK -.->|"cannot open"| AR

    ADM["Admin<br/>creates · disables · deletes accounts"] -.->|"CANNOT decrypt<br/>either one"| A
    ADM -.-> B

    style A fill:#dbeafe,stroke:#1e40af
    style B fill:#dcfce7,stroke:#166534
    style ADM fill:#fee2e2,stroke:#991b1b
```

Bob cannot read Alice's data — **not by policy, by cryptography**. Their DEKs
are unrelated keys. Which leads to the property worth understanding before you
add a second user:

> **No administrator can read anyone's data in the app**, or reset anyone's
> password — a reset link goes only to the account's own email, so the mailbox
> is what guards it. Outside the app, whoever holds `.env` and the
> database can read everything. If `.env` and every offline copy are lost,
> nobody can help anyone — not you, not the DBA. Correct behaviour here, not a
> gap.

**Shared budgets are still out.** Two people with *separate* data is a config
flag; two people editing *one* budget needs a per-budget key wrapped to each
member, which needs public-key crypto (an X25519 keypair per user) because Alice
cannot wrap a key to Bob without knowing his DEK. Roughly 2–3 weeks, and it
changes the key model rather than extending it. ARCHITECTURE.md §13.4 has the
sketch if you ever want it.

---

## 13. Current state, honestly

Phases 1 and 2 are built (2026-09-11): the crypto core, the database layer and
migration, the frontend shell, and the whole sign-in / lock flow, with 212
passing tests. They also built a 12-word recovery phrase; on 2026-09-14 it was
reversed in favour of an offline `.env` copy, and its code was removed the same day. Schema ZBDGT and its fifteen
tables exist on P8_NOAH_AI. Everything from Phase 3 on is still a decision, not
an observation.

The three things most likely to change:

1. **The performance numbers in §6 are measured, except from the server.**
   Decrypt + parse of 10,000 transactions: 123-140 ms. From the dev PC the
   SQL Server cold load is 2.3 s, nearly all of it the internet link. The
   deciding run is `scripts/benchmark_fetch.py` on the app server; if that
   exceeds ~1.5 s, the bucket-column escape hatch becomes the plan.
2. **The two-step insert in §5** is the least elegant thing in the design. If it
   proves error-prone, bind AAD to a client-generated UUID instead of the
   identity column.
3. **Offline writes are deferred to Phase 9 and may not land at all.** Merging
   offline edits into an encrypted store is genuinely hard. Do not let the PWA
   shell imply a capability that is not there.

Start with [phases.md](phases.md) — its Phase 1 section says what was built,
what was built differently from the plan, and what is left: your first
account (the sign-up screen), and the benchmark run on the server.
