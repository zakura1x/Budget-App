"""
The A5 load test: does the rest of the app stay fast while people ask the
assistant? (misc/AI/PHASES.md, A5)

    python scripts/ai_load.py                       # 10 askers x 5 questions, 3 readers
    python scripts/ai_load.py --askers 5 --questions 3

It never touches the company database or your real keys. It starts the real
app as ONE uvicorn worker in a child process (invariant 7), on throwaway keys
and a SQLite database in a temporary folder that is deleted afterwards, and
fills it with made-up users over HTTP. The IAM and watsonx settings still come
from .env, so the questions reach the real model.

What it measures:

  1. idle      - readers open Home's own requests (budget, accounts, ledger,
                 Months ahead, calendar) with nobody asking. Run twice: the
                 gap between the two runs is the noise of this machine.
  2. loaded    - the same readers, while every asker sends its questions one
                 after another, all askers at once.

The gate is A5's: the readers' p95 under load is within 20% of idle. It also
reports what the askers got: a model reply, the template, or "busy" -
AI_MAX_CONCURRENT_CALLS answers are in flight and a further one waits
AI_QUEUE_WAIT_SECONDS for a place before it is refused.

Read the milliseconds beside the percentage. A question costs the server
about as much work as opening Home and Months ahead together (a skill reads
the same services), so questions slow the readers the way more readers would:
on 2026-09-30 ten askers moved a 26 ms p95 to 32-45 ms, which is +35% to +65%
and fails the 20% line, with two idle runs already 5-30% apart. What the test
must never show is a read waiting on a model call - a max in seconds.

SQLite on this machine stands in for SQL Server, so the absolute times are not
the server's. What carries over is the comparison: one worker, one thread
pool, and whether a model wait holds any of it up.
"""

import argparse
import base64
import os
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/ZBDGT/api/v1"
HEADERS = {"X-Requested-With": "fetch"}
PASSWORD = "Correct-Horse-9!"

QUESTIONS = [
    "How much is left in my budget?",
    "How much did I spend this month?",
    "How much cash do I have?",
    "What bills are due before payday?",
    "Can I afford a 3,000 pair of shoes?",
    "How much did I spend on Food this month?",
    "How much do I owe on my card?",
    "I spent 250 on Food",  # a draft: answered without the model
]


# ---------------------------------------------------------------- the server (child process)

def serve(port: int, folder: str) -> None:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    import uvicorn
    from sqlalchemy import create_engine, event

    import app.api.v1.endpoints.health as health_module
    import app.main as main_module
    from app.core.config import settings
    from app.db.base import Base
    from app.db.connection import set_engine
    import app.db.models  # noqa: F401 - registers every table

    engine = create_engine(f"sqlite:///{folder}/main.db", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _attach_schema(dbapi_connection, _record):
        dbapi_connection.execute(f"ATTACH DATABASE '{folder}/schema.db' AS {settings.DB_SCHEMA}")
        dbapi_connection.execute(f"PRAGMA {settings.DB_SCHEMA}.journal_mode = WAL")
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    set_engine(engine)
    ok = {"reachable": True, "schema_present": True}
    health_module.check_database = lambda: dict(ok)
    main_module.check_database = lambda: dict(ok)
    uvicorn.run(main_module.app, host="127.0.0.1", port=port, log_level="warning", workers=1)


def child_env(code: str, folder: str) -> dict:
    """Throwaway keys, as tests/conftest.py sets them - env beats .env, so the real ones are never read."""
    env = dict(os.environ)
    env.update({
        "BUDGET_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "BUDGET_KEY_VERSION": "1",
        "BUDGET_RETIRED_KEYS": "",
        "BUDGET_BLIND_INDEX_PEPPER": base64.b64encode(secrets.token_bytes(32)).decode(),
        "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "PIN_PEPPER": base64.b64encode(secrets.token_bytes(32)).decode(),
        "SESSION_SECRET": secrets.token_urlsafe(32),
        "REGISTRATION_CODE": code,
        "ENVIRONMENT": "test",
        "DEBUG": "False",
        "LOG_LEVEL": "WARNING",
        "LOG_DIR": folder,
        "BCRYPT_ROUNDS": "4",
        "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
        "APP_PUBLIC_URL": "https://budget.example.test",
        "DB_SERVER": "zbdgt-load-must-not-connect.invalid",
        # More accounts than the server allows, all of them browsing at once
        "MAX_USERS": "40", "CACHE_MAX_USERS": "40",
        "RATE_LIMIT_ENABLED": "False",
        "AI_MAX_QUESTIONS_PER_DAY": "0",
        "AI_ALLOWED_USER_IDS": "",
    })
    return env


# ---------------------------------------------------------------- made-up users

class User:
    def __init__(self, base: str, number: int):
        import httpx
        self.number = number
        self.client = httpx.Client(base_url=base, headers=HEADERS, timeout=90)

    def call(self, method: str, path: str, **kw):
        return self.client.request(method, PREFIX + path, **kw)

    def must(self, method: str, path: str, body=None, expect=(200, 201)):
        response = self.call(method, path, json=body)
        if response.status_code not in expect:
            raise SystemExit(f"{method} {path} -> {response.status_code} {response.text[:200]}")
        return response.json() if response.content else None

    def seed(self, code: str, today: date) -> None:
        d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
        ahead = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
        q = f"?today={today.isoformat()}"
        self.must("POST", "/auth/register", {"email": f"load{self.number}@example.com", "password": PASSWORD,
                                             "registration_code": code, "display_name": f"Load {self.number}"})
        self.must("PATCH", "/settings/preferences", {"assistant": True})
        wallet = self.must("POST", f"/accounts{q}", {"name": "Wallet", "type": "cash", "opening_balance": "18500.00"})["id"]
        savings = self.must("POST", f"/accounts{q}", {"name": "BPI Savings", "type": "savings",
                                                      "opening_balance": "45000.00"})["id"]
        card = self.must("POST", f"/accounts{q}", {"name": "BPI Card", "type": "credit", "statement_closing_day": 16,
                                                   "payment_due_day": 6, "credit_limit": "50000.00"})["id"]
        cats = {n: self.must("POST", "/categories", {"name": n})["id"] for n in ("Food", "Transport", "Bills", "Shopping")}
        cats["Salary"] = self.must("POST", "/categories", {"name": "Salary", "kind": "income"})["id"]
        self.must("POST", f"/budgets{q}", {"period": "monthly", "amount": "30000.00", "allocations": [
            {"category_id": cats["Food"], "amount": "9000.00"}, {"category_id": cats["Transport"], "amount": "3000.00"}]})
        spending = [(d(n), f"{180 + (n * 37) % 900}.00", wallet if n % 3 else card,
                     ("Food", "Transport", "Shopping")[n % 3]) for n in range(1, 61)]
        for when, amount, account, category in spending:
            self.must("POST", f"/transactions{q}", {"type": "expense", "amount": amount, "txn_date": when,
                                                    "account_id": account, "category_id": cats[category]})
        self.must("POST", f"/recurring{q}", {"kind": "standard", "type": "income", "name": "Salary", "amount": "25000.00",
                                             "account_id": savings, "category_id": cats["Salary"],
                                             "frequency": "monthly", "start": ahead(12)})
        self.must("POST", f"/recurring{q}", {"kind": "standard", "type": "expense", "name": "Meralco",
                                             "amount": "2450.00", "account_id": wallet, "category_id": cats["Bills"],
                                             "frequency": "monthly", "start": ahead(4)})


# ---------------------------------------------------------------- the two workloads

def reads(today: date) -> list:
    q = f"today={today.isoformat()}"
    return [f"/budgets/current?{q}", f"/accounts?{q}", "/transactions?limit=50", f"/projection?{q}&months=12",
            f"/calendar/{today.year}/{today.month}"]


def reader(user: User, paths: list, stop: threading.Event, out: list, errors: list) -> None:
    """Someone moving between screens: Home's requests, one after another, with a breath between."""
    while not stop.is_set():
        for path in paths:
            started = time.perf_counter()
            response = user.call("GET", path)
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code == 200:
                out.append((path.split("?")[0], elapsed))
            else:
                errors.append((path, response.status_code))
            if stop.is_set():
                return
            time.sleep(0.05)


def asker(user: User, questions: list, today: date, out: list, start: threading.Event) -> None:
    start.wait()
    conversation = None
    for question in questions:
        started = time.perf_counter()
        response = user.call("POST", "/assistant/ask", json={"question": question, "today": today.isoformat(),
                                                             "conversation_id": conversation})
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code == 200:
            body = response.json()
            conversation = body["conversation_id"]
            kind = "model" if body["ai_phrased"] else ("no_model_needed" if body["skill"] in ("draft", "how_to")
                                                       else "template")
        elif response.status_code == 429:
            kind = "busy"
        else:
            kind = f"error_{response.status_code}"
        out.append((kind, elapsed))


def measure(readers: list, paths: list, *, seconds: float = 0, askers: list = (), questions: int = 0,
            today: date = None) -> tuple:
    stop, start = threading.Event(), threading.Event()
    timings, errors, asked = [], [], []
    read_threads = [threading.Thread(target=reader, args=(u, paths, stop, timings, errors)) for u in readers]
    ask_threads = [
        threading.Thread(target=asker, args=(u, [QUESTIONS[(i + n) % len(QUESTIONS)] for n in range(questions)],
                                             today, asked, start))
        for i, u in enumerate(askers)
    ]
    for thread in read_threads + ask_threads:
        thread.start()
    began = time.perf_counter()
    start.set()
    if ask_threads:
        for thread in ask_threads:
            thread.join()
    else:
        time.sleep(seconds)
    took = time.perf_counter() - began
    stop.set()
    for thread in read_threads:
        thread.join()
    return timings, errors, asked, took


def p(values: list, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def line(name: str, timings: list) -> str:
    values = [ms for _path, ms in timings]
    return f"  {name:<10} {len(values):>5} requests   p50 {p(values, 0.5):6.1f} ms   p95 {p(values, 0.95):6.1f} ms   " \
           f"max {max(values, default=0):6.1f} ms"


# ---------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description="A5 load test for the AI companion")
    parser.add_argument("--serve", nargs=2, metavar=("PORT", "FOLDER"), help=argparse.SUPPRESS)
    parser.add_argument("--askers", type=int, default=10)
    parser.add_argument("--questions", type=int, default=5)
    parser.add_argument("--readers", type=int, default=3)
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()
    if args.serve:
        serve(int(args.serve[0]), args.serve[1])
        return 0

    import httpx

    folder = tempfile.mkdtemp(prefix="zbdgt-load-").replace("\\", "/")
    code = secrets.token_urlsafe(12)
    base = f"http://127.0.0.1:{args.port}"
    today = date.today()
    log = open(os.path.join(folder, "server.log"), "w")
    server = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", str(args.port), folder],
                              env=child_env(code, folder), stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            if server.poll() is not None:
                log.close()
                print(open(os.path.join(folder, "server.log")).read()[-2000:])
                return 2
            try:
                if httpx.get(base + PREFIX + "/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            print("The server did not start.")
            return 2

        print(f"One worker on :{args.port}, pid {server.pid}. Making {args.readers + args.askers} users...")
        readers = [User(base, n) for n in range(args.readers)]
        askers = [User(base, args.readers + n) for n in range(args.askers)]
        for user in readers + askers:
            user.seed(code, today)
        paths = reads(today)
        for user in readers:  # every read answers, and the working set is warm
            for path in paths:
                user.must("GET", path)

        status = askers[0].must("GET", "/assistant/status")
        if not status["enabled"]:
            print("The assistant is off. Set AI_ENABLED=True in .env; this test needs the real model.")
            return 2
        # The first call loads the key from IAM and builds the client; keep that out of the numbers.
        warm = askers[0].call("POST", "/assistant/ask", json={"question": QUESTIONS[0], "today": today.isoformat()})
        print(f"Warm-up question: {warm.status_code}, "
              f"{'model reply' if warm.status_code == 200 and warm.json()['ai_phrased'] else 'template'}")

        idle_a, errors_a, _, _ = measure(readers, paths, seconds=20)
        idle_b, errors_b, _, _ = measure(readers, paths, seconds=20)
        loaded, errors_c, asked, took = measure(readers, paths, askers=askers, questions=args.questions, today=today)

        print("\nReaders (Home's requests, one worker)")
        print(line("idle 1", idle_a))
        print(line("idle 2", idle_b))
        print(line("loaded", loaded))
        for path in paths:
            name = path.split("?")[0]
            before = [ms for n, ms in idle_a + idle_b if n == name]
            during = [ms for n, ms in loaded if n == name]
            print(f"    {name:<24} idle p95 {p(before, 0.95):6.1f} ms   loaded p95 {p(during, 0.95):6.1f} ms")

        kinds = {}
        for kind, _ms in asked:
            kinds[kind] = kinds.get(kind, 0) + 1
        answered = [ms for kind, ms in asked if kind in ("model", "template", "no_model_needed")]
        print(f"\nAskers: {args.askers} at once x {args.questions} questions, {took:.1f} s in all")
        for kind in sorted(kinds):
            print(f"  {kind:<16} {kinds[kind]:>3}")
        if answered:
            print(f"  answered in      p50 {p(answered, 0.5) / 1000:.1f} s   p95 {p(answered, 0.95) / 1000:.1f} s   "
                  f"max {max(answered) / 1000:.1f} s")

        idle = [ms for _n, ms in idle_a + idle_b]
        idle_p95, loaded_p95 = p(idle, 0.95), p([ms for _n, ms in loaded], 0.95)
        noise = abs(p([ms for _n, ms in idle_a], 0.95) - p([ms for _n, ms in idle_b], 0.95)) / idle_p95 * 100
        moved = (loaded_p95 - idle_p95) / idle_p95 * 100
        errors = errors_a + errors_b + errors_c
        failed = [k for k in kinds if k.startswith("error_")]
        print(f"\nIdle p95 {idle_p95:.1f} ms, loaded p95 {loaded_p95:.1f} ms: {moved:+.0f}% "
              f"(two idle runs differ by {noise:.0f}%; median {statistics.median(idle):.1f} -> "
              f"{statistics.median([ms for _n, ms in loaded]):.1f} ms)")
        passed = moved <= 20 and not errors and not failed
        if errors:
            print(f"Reads that failed: {errors[:5]}")
        if failed:
            print(f"Questions that failed: {failed}")
        print(f"A5's gate (the readers' p95 moves at most 20% while questions run): "
              f"{'PASSED' if passed else 'FAILED'} - it moved {loaded_p95 - idle_p95:+.1f} ms.")
        return 0 if passed else 1
    finally:
        server.terminate()  # this child only, by its own handle
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
