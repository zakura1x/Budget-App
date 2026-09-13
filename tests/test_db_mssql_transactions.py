"""
Phase 4 against the company SQL Server. SKIPPED unless ZBDGT_DB_TESTS=1.

    ZBDGT_DB_TESTS=1 pytest tests/test_db_mssql_transactions.py -s

The verify items that SQLite cannot settle, because they are about the real
engine's transactions and the real column type:

  * a process that dies between the INSERT and the UPDATE of the two-step
    insert leaves no row - checked from a SEPARATE connection, the way a
    DBA would see it, after the dying one is gone
  * a transfer's two legs commit together or not at all
  * a plain SELECT on a transaction shows no merchant, amount or category

(Tampering with a payload byte failing loudly is already proven here, in
tests/test_db_mssql.py.) Every test uses a throwaway inactive user and removes
its data rows, audit rows and the user, whatever happens.
"""

import os

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.crypto.dek import generate_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import ENCRYPTED_MODELS, AuditLog, Transaction, User
from app.db.repositories.transaction_repository import TransactionRepository
from app.db.types import utcnow
from app.services import account_service, category_service, transaction_service

pytestmark = [pytest.mark.db, pytest.mark.security]


@pytest.fixture(scope="module")
def factory():
    from app.db.connection import create_db_engine

    engine = create_db_engine()
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def owner(factory):
    with factory() as session:
        now = utcnow()
        user = User(email_bidx=os.urandom(32).hex(), password_hash="db-test", key_version=1,
                    dek_wrapped=PLACEHOLDER, is_active=False, created_at=now, updated_at=now)
        session.add(user)
        session.commit()
        user_id = user.id
    yield UserCipher(user_id, generate_dek(), 1)
    with factory() as session:
        for model in ENCRYPTED_MODELS:
            session.execute(delete(model).where(model.user_id == user_id))
        session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


class ProcessDied(Exception):
    pass


def count_for(session, user_id):
    return session.execute(
        select(func.count()).select_from(Transaction).where(Transaction.user_id == user_id)
    ).scalar_one()


def test_a_death_between_insert_and_update_leaves_no_row(factory, owner, monkeypatch):
    def seal(self, table, row_id, data):
        raise ProcessDied("killed between INSERT and UPDATE")

    dying = factory()
    try:
        monkeypatch.setattr(UserCipher, "seal", seal)
        with pytest.raises(ProcessDied):
            TransactionRepository(dying, owner).create({"type": "expense", "amount": "1.00", "splits": []})
    finally:
        # What a killed process leaves: a connection that never committed, gone.
        dying.close()
        monkeypatch.undo()

    with factory() as observer:
        assert count_for(observer, owner.user_id) == 0


def test_a_transfer_commits_both_legs_or_neither(factory, owner, monkeypatch):
    with factory() as session:
        bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
        wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})

    original = UserCipher.seal
    calls = {"n": 0}

    def seal(self, table, row_id, data):
        if table == "transactions":
            calls["n"] += 1
            if calls["n"] == 2:
                raise ProcessDied("killed after the out leg")
        return original(self, table, row_id, data)

    dying = factory()
    try:
        monkeypatch.setattr(UserCipher, "seal", seal)
        with pytest.raises(ProcessDied):
            transaction_service.create_transaction(dying, owner, {
                "type": "transfer", "amount": "5000.00", "account_id": bank.id, "counter_account_id": wallet.id,
            })
    finally:
        dying.close()
        monkeypatch.undo()

    with factory() as observer:
        assert count_for(observer, owner.user_id) == 0

    with factory() as session:  # and the same transfer, uninterrupted, writes both
        result = transaction_service.create_transaction(session, owner, {
            "type": "transfer", "amount": "5000.00", "account_id": bank.id, "counter_account_id": wallet.id,
        })
        assert len(result.transactions) == 2
    with factory() as observer:
        assert count_for(observer, owner.user_id) == 2


def test_ssms_select_on_transactions_shows_nothing_readable(factory, owner):
    with factory() as session:
        wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
        groceries = category_service.create_category(session, owner, {"name": "Groceries"})
        household = category_service.create_category(session, owner, {"name": "Household"})
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": "3500.00", "account_id": wallet.id, "txn_date": "2026-09-12",
            "merchant": "SM Supermarket", "notes": "weekly run",
            "splits": [{"category_id": groceries.id, "amount": "2800.00", "note": "groceries"},
                       {"category_id": household.id, "amount": "700.00"}],
        })
        raw = session.execute(
            text(f"SELECT * FROM {settings.DB_SCHEMA}.transactions WHERE user_id = :u"), {"u": owner.user_id}
        ).mappings().all()
        assert len(raw) == 1
        dump = b"".join(
            value if isinstance(value, (bytes, bytearray)) else str(value).encode() for value in raw[0].values()
        )
        for needle in (b"SM Supermarket", b"weekly", b"3500", b"2800", b"2026-09-12", b"splits",
                       b"expense", b"category_id", b"groceries"):
            assert needle not in dump, needle
