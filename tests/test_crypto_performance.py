"""
The benchmark that replaces the estimates in ARCHITECTURE.md section 5.6.

Seeds 10,000 realistic transactions for one user through the real repository
(two-step insert and all), then measures the COLD LOAD the working-set cache
will pay once per session: fetch + decrypt + parse.

Two numbers:
  * test_cold_load_sqlite      fetch from SQLite + decrypt + parse. Runs always.
                               The fetch here is local and nearly free, so this
                               is effectively the CPU cost of the design.
  * test_cold_load_sql_server  the same against the company SQL Server, where
                               the fetch goes over ODBC and the network. The
                               number that decides section 5.7. Marked `db`.

Run with -s to see the figures:  pytest tests/test_crypto_performance.py -s
"""

import os
import random
import statistics
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.core.crypto.dek import generate_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import Transaction, User
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.db.types import utcnow

ROWS = 10_000
THRESHOLD_MS = 1500  # ARCHITECTURE.md 5.7: above this, adopt bucket columns now

MERCHANTS = ["SM Supermarket", "Jollibee", "Grab", "Meralco", "Globe", "Mercury Drug", "Shell", "7-Eleven"]


class TransactionRepo(EncryptedRepository):
    model = Transaction


def realistic_payload(rng: random.Random, n: int) -> dict:
    amount = Decimal(rng.randint(2000, 500000)) / 100
    split = (amount * Decimal("0.8")).quantize(Decimal("0.01"))
    splits = (
        [{"category_id": rng.randint(1, 30), "amount": str(amount), "note": None}]
        if rng.random() < 0.9
        else [
            {"category_id": rng.randint(1, 30), "amount": str(split), "note": "main"},
            {"category_id": rng.randint(1, 30), "amount": str(amount - split), "note": "other"},
        ]
    )
    return {
        "txn_date": (date(2021, 9, 1) + timedelta(days=n // 6)).isoformat(),
        "type": "expense",
        "amount": str(amount),
        "account_id": rng.randint(1, 5),
        "merchant": rng.choice(MERCHANTS),
        "notes": rng.choice([None, "", "weekly run", "with friends"]),
        "splits": splits,
        "tag_ids": [],
        "recurring_id": None,
        "attachment_id": None,
    }


def seed(session, cipher, rows: int) -> None:
    rng = random.Random(10_000)
    repo = TransactionRepo(session, cipher)
    for n in range(rows):
        repo.create(realistic_payload(rng, n))
    session.commit()


def measure(session_factory, cipher, runs: int = 3) -> dict:
    """Best and median of `runs` cold loads, each in a fresh session."""
    load_ms, decrypt_ms = [], []
    for _ in range(runs):
        with session_factory() as session:
            repo = TransactionRepo(session, cipher)
            m = Transaction
            from sqlalchemy import select

            query = select(m.id, m.key_version, m.payload).where(m.user_id == cipher.user_id, m.is_deleted == False)  # noqa: E712
            t0 = time.perf_counter()
            raw = session.execute(query).all()
            t1 = time.perf_counter()
            records = [cipher.open("transactions", r[0], r[2], r[1]) for r in raw]
            t2 = time.perf_counter()
            assert len(records) == len(raw)
            load_ms.append((t2 - t0) * 1000)
            decrypt_ms.append((t2 - t1) * 1000)
            # And through the repository, which is what Phase 4 will call.
            assert len(repo.list()) == len(raw)
    return {
        "cold_load_ms_best": min(load_ms),
        "cold_load_ms_median": statistics.median(load_ms),
        "decrypt_parse_ms_median": statistics.median(decrypt_ms),
    }


@pytest.mark.slow
def test_cold_load_sqlite(engine, session):
    now = utcnow()
    user = User(email_bidx="p" * 64, password_hash="x", key_version=1, dek_wrapped=PLACEHOLDER,
                created_at=now, updated_at=now)
    session.add(user)
    session.flush()
    cipher = UserCipher(user.id, generate_dek(), 1)

    t0 = time.perf_counter()
    seed(session, cipher, ROWS)
    seed_s = time.perf_counter() - t0

    result = measure(sessionmaker(bind=engine, expire_on_commit=False), cipher)
    print(
        f"\n[benchmark] SQLite, {ROWS} transactions: seed {seed_s:.1f}s | "
        f"cold load best {result['cold_load_ms_best']:.0f} ms, median {result['cold_load_ms_median']:.0f} ms | "
        f"decrypt+parse median {result['decrypt_parse_ms_median']:.0f} ms"
    )
    assert result["cold_load_ms_median"] < THRESHOLD_MS


@pytest.mark.db
@pytest.mark.slow
def test_cold_load_sql_server():
    """
    Against the real server. Creates one throwaway user, seeds 10,000 rows,
    measures, then deletes everything it created. Needs `alembic upgrade head`
    to have been run, and ZBDGT_DB_TESTS=1.
    """
    from app.db.connection import create_db_engine

    engine = create_db_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    marker = os.urandom(32).hex()
    with factory() as session:
        now = utcnow()
        user = User(email_bidx=marker, password_hash="benchmark", key_version=1, dek_wrapped=PLACEHOLDER,
                    is_active=False, created_at=now, updated_at=now)
        session.add(user)
        session.commit()
        user_id = user.id
    cipher = UserCipher(user_id, generate_dek(), 1)
    try:
        with factory() as session:
            t0 = time.perf_counter()
            seed(session, cipher, ROWS)
            seed_s = time.perf_counter() - t0
        result = measure(factory, cipher)
        print(
            f"\n[benchmark] SQL Server, {ROWS} transactions: seed {seed_s:.1f}s | "
            f"cold load best {result['cold_load_ms_best']:.0f} ms, median {result['cold_load_ms_median']:.0f} ms | "
            f"decrypt+parse median {result['decrypt_parse_ms_median']:.0f} ms"
        )
        # The fetch half of this number is the network between THIS machine and
        # the database. From the development PC (2026-09-11: 14 ms round trip,
        # ~12 Mbit/s) it was 2.2 s of a 2.35 s cold load, and it says nothing
        # about production, which runs beside the database. So the 1.5 s
        # go/no-go for section 5.7 is taken from scripts/benchmark_fetch.py run
        # ON THE SERVER. What this test holds the design to is the part the
        # design controls: decryption and parsing.
        if result["cold_load_ms_median"] >= THRESHOLD_MS:
            print(
                f"[benchmark] cold load is over {THRESHOLD_MS} ms from here - run "
                "scripts/benchmark_fetch.py on the app server for the number that decides section 5.7"
            )
        assert result["decrypt_parse_ms_median"] < 500
    finally:
        with factory() as session:
            session.execute(delete(Transaction).where(Transaction.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
        engine.dispose()
