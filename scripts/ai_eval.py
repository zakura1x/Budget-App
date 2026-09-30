"""
The A2 gate: golden questions asked of the REAL model (misc/AI/PHASES.md, A2).

    python scripts/ai_eval.py                  # English replies (AI_REPLY_LANGUAGE=en)
    python scripts/ai_eval.py --language match # replies in the question's language (the Taglish gate)
    python scripts/ai_eval.py --only taglish   # just the Taglish questions
    python scripts/ai_eval.py --out report.txt # also write every reply to a file, for reading

It never touches the company database or your real keys. It uses the test
suite's setup: throwaway keys and an invalid DB_SERVER come from
tests/conftest.py, and the data is an in-memory SQLite database holding a
made-up user (Wallet, BPI Savings, a BPI card, a salary, Meralco, Netflix, a
September and an October of spending). The IAM and watsonx settings still
come from .env, so it calls the real model; it needs AI_ENABLED=True.

For each question it prints the expected skill, the skill chosen, whether the
rules or the model routed it, whether the model's reply was shown or replaced
by the template (and why), the time, and the reply. The summary checks A2's
gate: at least 90% routed right, at least 95% of replies passing the figure
check, and p95 under 8 s. The figure check means no reply ever shows a number
missing from its facts.
"""

import argparse
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TODAY = "2026-10-10"

# (question, expected skill, language)
GOLDEN = [
    ("How much is left in my budget?", "budget_status", "en"),
    ("What's my daily allowance today?", "budget_status", "en"),
    ("Am I on track with my budget this month?", "budget_status", "en"),
    ("How much of my Food budget is left?", "budget_status", "en"),
    ("How much did I spend this month?", "spending", "en"),
    ("Where did my money go last month?", "spending", "en"),
    ("How much did I spend on Transport in September?", "spending", "en"),
    ("What are my biggest expenses this month?", "spending", "en"),
    ("Am I spending more than last month?", "spending", "en"),
    ("How much cash do I have?", "cash", "en"),
    ("What's my net worth?", "cash", "en"),
    ("How much is in BPI Savings?", "cash", "en"),
    ("What bills are due before payday?", "upcoming", "en"),
    ("What's due this week?", "upcoming", "en"),
    ("Anything I need to pay before the end of the month?", "upcoming", "en"),
    ("How much do I owe on my card?", "card", "en"),
    ("When is my BPI Card bill due?", "card", "en"),
    ("How much credit limit do I have left?", "card", "en"),
    ("What's the weather tomorrow?", "off_topic", "en"),
    ("Write me a poem about cats", "off_topic", "en"),
    ("Magkano ang natitira sa budget ko?", "budget_status", "tl"),
    ("Magkano pwede kong gastusin kada araw?", "budget_status", "tl"),
    ("Magkano ang nagastos ko ngayong buwan?", "spending", "tl"),
    ("Saan napunta ang pera ko noong nakaraang buwan?", "spending", "tl"),
    ("Magkano ang gastos ko sa Food?", "spending", "tl"),
    ("Magkano pera ko ngayon?", "cash", "tl"),
    ("Ano ang mga bayarin ko bago sahod?", "upcoming", "tl"),
    ("May babayaran ba ako this week?", "upcoming", "tl"),
    ("Magkano utang ko sa card?", "card", "tl"),
    ("Kailan due ang BPI Card ko?", "card", "tl"),
    # A3 - the six skills that look further
    ("How did I do last month?", "review", "en"),
    ("How are my savings goals?", "goals", "en"),
    ("How is my Japan trip goal going?", "goals", "en"),
    ("Is my emergency fund enough?", "emergency", "en"),
    ("What subscriptions do I have?", "subscriptions", "en"),
    ("Which debt should I pay off first?", "payoff", "en"),
    ("When will I be debt-free?", "payoff", "en"),
    ("How do I add an expense?", "how_to", "en"),
    ("What is cash on hand?", "how_to", "en"),
    ("Sapat ba ang emergency fund ko?", "emergency", "tl"),
    ("Kumusta ang Japan trip goal ko?", "goals", "tl"),
    # A3 - affordability. "afford=<verdict>": the verdict was worked out BY HAND from the seeded
    # figures (see AFFORD_WORKING below) before the rules were run, and must match.
    ("Can I afford a ₱500 lunch?", "afford=yes", "en"),
    ("Can I afford a ₱15,000 phone?", "afford=yes", "en"),
    ("Can I buy a ₱21,000 TV?", "afford=yes_over_budget", "en"),
    ("Can I buy a ₱22,500 laptop?", "afford=tight", "en"),
    ("Can I afford a ₱25,000 laptop?", "afford=wait", "en"),
    ("Can I afford a ₱200,000 car?", "afford=no", "en"),
    ("Can I buy a ₱40,000 sofa on my BPI Card?", "afford=no", "en"),
    ("Can I buy a ₱30,000 fridge on my card?", "afford=no", "en"),
    ("Can I buy a ₱12,000 phone on my card?", "afford=yes", "en"),
    ("Can I get an ₱18,000 phone in 6 months?", "afford=wait", "en"),
    ("Can I afford a ₱3,000 bag in 3 months?", "afford=tight", "en"),
    ("Should I buy ₱1,200 shoes?", "afford=yes", "en"),
    ("Kaya ko bang bumili ng ₱5,000 na sapatos?", "afford=yes", "tl"),
    ("Pwede ko bang bilhin ang ₱25,000 na laptop?", "afford=wait", "tl"),
    ("Kaya ko ba ang ₱200,000 na kotse?", "afford=no", "tl"),
]

AFFORD_WORKING = """
The seeded user on 2026-10-10 (every figure below is from seed()):
  Cash on hand 33,262.00 = Wallet -1,400 + BPI Savings 45,000 - BPI Card 10,338.
  Budget 30,000 a month; October spent 9,549, so 20,451.00 is left over 22 days.
  Ahead: Meralco 2,450 on the 13th, Salary +25,000 on the 15th, Netflix 549 on the 20th (on the card).
  Months ahead's cash line (the remaining budget taken off at each month's start):
    Oct  15,810 -> 13th 13,360 -> 15th 38,360 -> 20th 37,811
    Nov  10,810 -> 13th  8,360 -> 15th 33,360 -> 20th 32,811
    Dec   5,810 -> 13th  3,360 -> 15th 28,360 -> 20th 27,811      lowest: 3,360 on 13 Dec
  Card: limit 50,000, 39,662 available; a purchase today is on the bill due 6 Nov.
  Nothing is set aside for goals. A week of essential spending is 1,659.23 (W).

  500 / 15,000 / 1,200 / 5,000   inside the 20,451 budget -> nothing extra -> lowest stays 3,360 -> yes
  21,000    549 over budget -> lowest 3,360 - 549 = 2,811 (above W)            -> yes_over_budget
  22,500  2,049 over budget -> lowest 1,311, above zero but under W            -> tight
  25,000  4,549 over -> lowest -1,189; bought 15 Dec every later point >= 0    -> wait (15 Dec)
  200,000 never fits, nothing set aside                                        -> no
  40,000 on the card: 39,662 available, 338 short                              -> no
  30,000 on the card: 9,549 extra leaves 6 Nov -> 13 Nov 8,360 - 9,549 < 0;
         later it is 30,000 at once, more than any point holds                 -> no
  12,000 on the card: inside the budget, nothing extra                         -> yes
  18,000 in 6: 3,000 a month; Oct's is in the budget, Nov + Dec are extra ->
         13 Dec 3,360 - 6,000 < 0; started 15 Nov only one falls before it     -> wait (15 Nov)
  3,000 in 3: 1,000 a month; Nov + Dec are extra -> 13 Dec 3,360 - 2,000 = 1,360, under W   -> tight
"""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--language", choices=("en", "match"), default="en")
    parser.add_argument("--only", choices=("en", "taglish"), default=None)
    parser.add_argument("--out", default=None, help="write the full report here as well")
    parser.add_argument("--facts", action="store_true", help="print the facts each reply was built from")
    parser.add_argument("--grep", default=None, help="only questions containing this text")
    return parser.parse_args()


def seed(api):
    """The made-up user. Figures are fixed so a reader can check the replies by hand."""
    assert api.register().status_code == 201
    assert api.patch("/settings/preferences", {"assistant": True}).status_code == 200
    q = f"?today={TODAY}"
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "8500.00"}).json()["id"]
    savings = api.post("/accounts", {"name": "BPI Savings", "type": "savings",
                                     "opening_balance": "45000.00"}).json()["id"]
    card = api.post("/accounts", {"name": "BPI Card", "type": "credit", "statement_closing_day": 16,
                                  "payment_due_day": 6, "credit_limit": "50000.00"}).json()["id"]
    cats = {name: api.post("/categories", {"name": name}).json()["id"]
            for name in ("Food", "Transport", "Bills", "Shopping")}
    cats["Salary"] = api.post("/categories", {"name": "Salary", "kind": "income"}).json()["id"]
    api.post(f"/budgets{q}", {"period": "monthly", "amount": "30000.00", "allocations": [
        {"category_id": cats["Food"], "amount": "9000.00"},
        {"category_id": cats["Transport"], "amount": "3000.00"},
        {"category_id": cats["Shopping"], "amount": "4000.00"},
    ]})
    entries = [
        ("2026-09-03", "1850.00", wallet, "Food"), ("2026-09-08", "620.00", wallet, "Transport"),
        ("2026-09-12", "3499.00", card, "Shopping"), ("2026-09-19", "2200.00", wallet, "Food"),
        ("2026-09-25", "980.00", wallet, "Transport"), ("2026-09-28", "1540.00", card, "Food"),
        ("2026-10-01", "2100.00", wallet, "Food"), ("2026-10-03", "450.00", wallet, "Transport"),
        ("2026-10-05", "5299.00", card, "Shopping"), ("2026-10-07", "1320.00", wallet, "Food"),
        ("2026-10-09", "380.00", wallet, "Transport"),
    ]
    for when, amount, account, category in entries:
        r = api.post(f"/transactions{q}", {"type": "expense", "amount": amount, "txn_date": when,
                                            "account_id": account, "category_id": cats[category]})
        assert r.status_code == 201, r.text
    # A goal with nothing set aside yet, so cash on hand stays as worked out in AFFORD_WORKING
    goal = api.post("/goals", {"name": "Japan trip", "target": "60000.00", "account_id": savings,
                               "target_date": "2027-03-31"})
    assert goal.status_code == 201, goal.text
    for body in (
        {"kind": "standard", "type": "income", "name": "Salary", "amount": "25000.00", "account_id": savings,
         "category_id": cats["Salary"], "frequency": "monthly", "start": "2026-10-15"},
        {"kind": "standard", "type": "expense", "name": "Meralco", "amount": "2450.00", "account_id": wallet,
         "category_id": cats["Bills"], "frequency": "monthly", "start": "2026-10-13"},
        {"kind": "subscription", "type": "expense", "name": "Netflix", "amount": "549.00", "account_id": card,
         "category_id": cats["Bills"], "frequency": "monthly", "start": "2026-10-20"},
    ):
        r = api.post(f"/recurring{q}", body)
        assert r.status_code == 201, r.text


def main() -> int:
    args = parse_args()
    # Before anything under app/ is imported: the test suite's throwaway keys and
    # harmless DB_SERVER, plus this run's language and no daily cap.
    os.environ["AI_REPLY_LANGUAGE"] = args.language
    os.environ["AI_MAX_QUESTIONS_PER_DAY"] = "0"
    import tests.conftest as harness  # noqa: F401 - sets the environment on import

    from fastapi.testclient import TestClient

    import app.api.v1.endpoints.health as health_module
    import app.main as main_module
    from app.core.config import settings
    from app.db.connection import set_engine

    if not settings.AI_ENABLED:
        print("AI_ENABLED is false in .env - nothing to evaluate.")
        return 1

    ok = {"reachable": True, "schema_present": True}
    health_module.check_database = lambda: dict(ok)
    main_module.check_database = lambda: dict(ok)
    set_engine(harness.make_sqlite_engine())

    questions = [g for g in GOLDEN if args.only is None
                 or (args.only == "taglish") == (g[2] == "tl")]
    if args.grep:
        questions = [g for g in questions if args.grep.lower() in g[0].lower()]
    rows, report = [], []
    with TestClient(main_module.app, raise_server_exceptions=True) as client:
        logging.getLogger().setLevel(logging.WARNING)  # the request log would bury the report
        # ...but keep each turn's own line: it says why a reply was replaced (never what was said)
        turns = []
        turn_log = logging.getLogger("app.services.assistant_service.turn")
        turn_log.setLevel(logging.INFO)
        turn_log.propagate = False
        capture = logging.Handler()
        capture.emit = lambda record: turns.append(record.getMessage())
        turn_log.addHandler(capture)
        # The first call after a start fetches the key from IAM and builds the client
        # (6-9 s, once per process). Timed on its own so p95 measures ordinary questions.
        from app.ai import llm_service

        started = time.perf_counter()
        llm_service.get_llm_service().invoke(settings.WATSONX_CHAT_MODEL, {"max_new_tokens": 5}, "Reply OK.")
        cold_ms = int((time.perf_counter() - started) * 1000)
        api = harness.ApiClient(client, settings.API_PREFIX)
        seed(api)
        for question, expected, lang in questions:
            started = time.perf_counter()
            response = api.post("/assistant/ask", {"question": question, "today": TODAY})
            ms = int((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                rows.append((question, expected, "ERROR", False, ms, lang))
                report.append(f"[ERROR {response.status_code}] {question}\n    {response.text[:200]}\n")
                continue
            body = response.json()
            # "afford=wait" also holds the reply to the verdict worked out by hand
            got = body["skill"] + (f"={body['verdict']}" if "=" in expected else "")
            rows.append((question, expected, got, body["ai_phrased"], ms, lang))
            mark = "ok " if got == expected else "MISS"
            phrased = "model" if body["ai_phrased"] else "template"
            reason = re.search(r"reason=(\S+)", turns[-1]) if turns else None
            if not body["ai_phrased"] and reason and reason.group(1) != "-":
                phrased += f" ({reason.group(1)})"
            report.append(f"[{mark}] ({lang}) {question}\n    expected {expected}, got {got}; "
                          f"{phrased}; {ms} ms\n    > {body['text']}\n"
                          + ("".join(f"      | {line}\n" for line in body["facts"]) if args.facts else ""))

    routed = sum(1 for r in rows if r[1] == r[2]) / len(rows)
    phrasable = [r for r in rows if r[2].split("=")[0] not in ("off_topic", "clarify", "how_to", "ERROR")]
    phrased = sum(1 for r in phrasable if r[3]) / len(phrasable) if phrasable else 0.0
    times = sorted(r[4] for r in rows)
    p95 = times[min(len(times) - 1, round(0.95 * (len(times) - 1)))]
    summary = [
        f"Questions: {len(rows)}  (language setting: {args.language})",
        f"Routed right: {routed:.0%}  (gate 90%)",
        f"Model replies that passed the figure check: {phrased:.0%} of {len(phrasable)}  (gate 95%)",
        f"Time: p50 {int(statistics.median(times))} ms, p95 {p95} ms, max {times[-1]} ms  (gate p95 8000 ms)",
        f"Cold start (first model call after the process starts, not in p95): {cold_ms} ms",
    ]
    passed = routed >= 0.9 and phrased >= 0.95 and p95 < 8000
    summary.append("GATE: " + ("PASSED" if passed else "NOT PASSED"))
    text = "\n".join(report) + "\n" + "\n".join(summary)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
