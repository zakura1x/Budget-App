"""
Against the company SQL Server. SKIPPED unless ZBDGT_DB_TESTS=1.

Run after `alembic upgrade head`:

    set ZBDGT_DB_TESTS=1
    pytest tests/test_db_mssql.py tests/test_crypto_performance.py -s

Every test creates a throwaway, inactive user and removes everything it made,
whatever happens. Nothing here reads or writes a real user's rows.
"""

import os

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.crypto.dek import generate_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.errors import DecryptionError
from app.core.crypto.user_cipher import UserCipher
from app.db.models import ENCRYPTED_MODELS, Transaction, User
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.db.types import utcnow

pytestmark = [pytest.mark.db, pytest.mark.security]


class TransactionRepo(EncryptedRepository):
    model = Transaction


@pytest.fixture(scope="module")
def factory():
    from app.db.connection import create_db_engine

    engine = create_db_engine()
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def throwaway_user(factory):
    with factory() as session:
        now = utcnow()
        user = User(email_bidx=os.urandom(32).hex(), password_hash="db-test", key_version=1,
                    dek_wrapped=PLACEHOLDER, is_active=False, created_at=now, updated_at=now)
        session.add(user)
        session.commit()
        user_id = user.id
    yield user_id
    with factory() as session:
        for model in ENCRYPTED_MODELS:
            session.execute(delete(model).where(model.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_schema_and_all_fifteen_tables_exist(factory):
    with factory() as session:
        names = session.execute(
            text("SELECT t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id WHERE s.name = :s"),
            {"s": settings.DB_SCHEMA},
        ).scalars().all()
    expected = {"users", "refresh_tokens", "login_attempts", "audit_log"} | {m.__tablename__ for m in ENCRYPTED_MODELS}
    assert expected <= set(names)


def test_a_row_written_by_the_app_is_unreadable_to_a_plain_select(factory, throwaway_user):
    """Exactly what a DBA in SSMS would see: SELECT * FROM ZBDGT.transactions."""
    cipher = UserCipher(throwaway_user, generate_dek(), 1)
    with factory() as session:
        created = TransactionRepo(session, cipher).create(
            {"txn_date": "2026-09-08", "amount": "3500.00", "merchant": "SM Supermarket",
             "splits": [{"category_id": 11, "amount": "3500.00"}]}
        )
        session.commit()
        raw = session.execute(
            text(f"SELECT * FROM {settings.DB_SCHEMA}.transactions WHERE id = :id"), {"id": created.id}
        ).mappings().one()
        blob = bytes(raw["payload"])
        for needle in (b"3500", b"SM Supermarket", b"2026-09-08", b"splits"):
            assert needle not in blob
        assert TransactionRepo(session, cipher).get(created.id).data["amount"] == "3500.00"


def test_tampering_in_the_database_fails_loudly(factory, throwaway_user):
    cipher = UserCipher(throwaway_user, generate_dek(), 1)
    with factory() as session:
        created = TransactionRepo(session, cipher).create({"amount": "5.00", "splits": []})
        session.commit()
        blob = bytearray(session.execute(select(Transaction.payload).where(Transaction.id == created.id)).scalar_one())
        blob[20] ^= 1
        session.execute(
            text(f"UPDATE {settings.DB_SCHEMA}.transactions SET payload = :p WHERE id = :id"),
            {"p": bytes(blob), "id": created.id},
        )
        session.commit()
        with pytest.raises(DecryptionError):
            TransactionRepo(session, cipher).get(created.id)
