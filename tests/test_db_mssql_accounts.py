"""
Phase 3 against the company SQL Server - the SSMS check, for real. SKIPPED
unless ZBDGT_DB_TESTS=1.

    ZBDGT_DB_TESTS=1 pytest tests/test_db_mssql_accounts.py -s

tests/test_accounts.py proves a plain SELECT shows no account name, but on
SQLite, where a payload is a BLOB. Production stores it as VARBINARY(MAX)
through pyodbc. This file makes the same claims on that column type: what a
DBA running `SELECT * FROM ZBDGT.accounts` in SSMS would actually see.

Every test goes through the real services (so the audit rows they write are
covered too), uses a throwaway inactive user, and removes everything it made -
its data rows, its audit rows, and the user - whatever happens.
"""

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.crypto.dek import generate_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import ENCRYPTED_MODELS, AuditLog, User
from app.db.repositories.transaction_repository import TransactionRepository
from app.db.types import utcnow
from app.services import account_service, category_service

pytestmark = [pytest.mark.db, pytest.mark.security]

SCHEMA = settings.DB_SCHEMA


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


def raw_rows(session, table, user_id):
    return session.execute(
        text(f"SELECT * FROM {SCHEMA}.{table} WHERE user_id = :u"), {"u": user_id}
    ).mappings().all()


def test_payload_columns_are_varbinary_max(factory):
    """The premise of the whole check: the column is opaque bytes, not text."""
    with factory() as session:
        types = dict(session.execute(
            text("SELECT TABLE_NAME, DATA_TYPE + ':' + CAST(CHARACTER_MAXIMUM_LENGTH AS varchar) "
                 "FROM INFORMATION_SCHEMA.COLUMNS "
                 "WHERE TABLE_SCHEMA = :s AND COLUMN_NAME = 'payload' "
                 "AND TABLE_NAME IN ('accounts', 'categories')"),
            {"s": SCHEMA},
        ).all())
    assert types == {"accounts": "varbinary:-1", "categories": "varbinary:-1"}


def test_ssms_select_on_accounts_shows_nothing_readable(factory, owner):
    with factory() as session:
        account_service.create_account(session, owner, {
            "name": "BPI Gold Mastercard", "type": "credit", "opening_balance": "-8420.55",
            "credit_limit": "50000.00", "statement_closing_day": 20, "payment_due_day": 5,
            "note": "the travel card",
        })
        fund = account_service.create_account(session, owner, {
            "name": "COL Financial", "type": "investment", "opening_balance": "100000.00",
        })
        account_service.add_valuation(session, owner, fund.id, "104250.00", on=date(2026, 9, 10))

        rows = raw_rows(session, "accounts", owner.user_id)
        assert len(rows) == 2
        # Everything a SELECT * returns, flattened to bytes - not just the payload.
        dump = b"".join(
            value if isinstance(value, (bytes, bytearray)) else str(value).encode()
            for row in rows for value in row.values()
        )
        for needle in (b"BPI", b"Mastercard", b"COL Financial", b"travel", b"8420", b"50000",
                       b"104250", b"credit", b"investment", b"valuations", b"statement_closing_day"):
            assert needle not in dump, needle


def test_ssms_select_on_categories_shows_nothing_readable(factory, owner):
    with factory() as session:
        food = category_service.create_category(session, owner, {"name": "Food & Drink", "icon": "restaurant"})
        category_service.create_category(session, owner, {"name": "Groceries", "parent_id": food.id})

        rows = raw_rows(session, "categories", owner.user_id)
        assert len(rows) == 2
        dump = b"".join(bytes(row["payload"]) for row in rows)
        for needle in (b"Food", b"Groceries", b"restaurant", b"parent_id", b"expense"):
            assert needle not in dump, needle


def test_audit_detail_leaks_nothing_either(factory, owner):
    """The services audit every mutation; the log must not be the side channel."""
    with factory() as session:
        account_service.create_account(session, owner, {"name": "Secret Savings", "type": "savings",
                                                        "opening_balance": "777777.00"})
        rows = session.execute(
            text(f"SELECT action, entity, detail_enc FROM {SCHEMA}.audit_log WHERE user_id = :u"),
            {"u": owner.user_id},
        ).all()
        assert [(r.action, r.entity) for r in rows] == [("CREATE", "accounts")]
        assert b"Secret" not in bytes(rows[0].detail_enc)


def test_money_round_trips_decimal_exact_through_varbinary(factory, owner):
    with factory() as session:
        created = account_service.create_account(session, owner, {
            "name": "Wallet", "type": "cash", "opening_balance": "0.10",
        })
    with factory() as fresh:  # a new session: nothing cached, straight off the server
        view = account_service.get_account(fresh, owner, created.id)
    assert view.opening_balance == Decimal("0.10")
    assert str(view.balance) == "0.10"


def test_category_reassignment_walks_splits_on_the_server(factory, owner):
    with factory() as session:
        coffee = category_service.create_category(session, owner, {"name": "Coffee"})
        household = category_service.create_category(session, owner, {"name": "Household"})
        food = category_service.create_category(session, owner, {"name": "Food"})
        record = TransactionRepository(session, owner).create({
            "txn_date": "2026-09-12", "type": "expense", "amount": "1000.00", "account_id": 1,
            "splits": [{"category_id": coffee.id, "amount": "300.00"},
                       {"category_id": household.id, "amount": "700.00"}],
        })
        session.commit()

        result = category_service.delete_category(session, owner, coffee.id, reassign_to=food.id)
        assert result["transactions_moved"] == 1

    with factory() as fresh:
        data = TransactionRepository(fresh, owner).get(record.id).data
        assert [s["category_id"] for s in data["splits"]] == [food.id, household.id]
        deleted = fresh.execute(
            text(f"SELECT is_deleted FROM {SCHEMA}.categories WHERE id = :id"), {"id": coffee.id}
        ).scalar_one()
        assert deleted in (True, 1)
