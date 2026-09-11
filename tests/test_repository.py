"""
Shape B through a real database (SQLite here, SQL Server under `db`).

What is proven at the database level, not just in memory:
  * the two-step insert yields a decryptable row and no leftover placeholder
  * a plain SELECT shows no plaintext at all - the SSMS test, locally
  * swapping or flipping stored bytes makes the row fail loudly
  * one user's cipher cannot see another user's rows
  * plaintext cannot be written to a payload column even by mistake
"""

import pytest
from sqlalchemy import select, text, update

from app.core.crypto.dek import generate_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.errors import DecryptionError
from app.core.crypto.user_cipher import UserCipher
from app.db.models import Account, Transaction, User, UserPreference
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.db.repositories.preferences_repository import PreferencesRepository
from app.db.types import utcnow

pytestmark = pytest.mark.security

TXN = {
    "txn_date": "2026-09-08",
    "type": "expense",
    "amount": "3500.00",
    "account_id": 3,
    "merchant": "SM Supermarket",
    "notes": "weekly run",
    "splits": [
        {"category_id": 11, "amount": "2800.00", "note": "groceries"},
        {"category_id": 19, "amount": "700.00", "note": "household"},
    ],
    "tag_ids": [2, 7],
    "recurring_id": None,
    "attachment_id": None,
}


class TransactionRepo(EncryptedRepository):
    model = Transaction


class AccountRepo(EncryptedRepository):
    model = Account


def make_user(session, user_id_hint: str = "a") -> User:
    """A bare users row, enough to satisfy the user_id foreign key."""
    now = utcnow()
    user = User(
        email_bidx=(user_id_hint * 64)[:64],
        password_hash="x",
        key_version=1,
        dek_wrapped=PLACEHOLDER,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def alice(session):
    user = make_user(session, "a")
    return UserCipher(user.id, generate_dek(), 1)


@pytest.fixture
def bob(session):
    user = make_user(session, "b")
    return UserCipher(user.id, generate_dek(), 1)


def test_two_step_insert_round_trips(session, alice):
    repo = TransactionRepo(session, alice)
    created = repo.create(TXN)
    session.commit()
    assert repo.get(created.id).data == TXN
    assert [r.data for r in repo.list()] == [TXN]


def test_no_placeholder_survives_create(session, alice):
    TransactionRepo(session, alice).create(TXN)
    session.commit()
    stored = session.execute(select(Transaction.payload)).scalars().all()
    assert stored and all(p != PLACEHOLDER for p in stored)


def test_plain_select_shows_no_plaintext(session, alice):
    """The local stand-in for 'unreadable via plain SSMS SELECT'."""
    TransactionRepo(session, alice).create(TXN)
    session.commit()
    rows = session.execute(text("SELECT * FROM ZBDGT.transactions")).fetchall()
    dump = repr(rows).encode() + b"".join(bytes(v) for row in rows for v in row if isinstance(v, (bytes, memoryview)))
    for needle in (b"3500", b"2800", b"SM Supermarket", b"weekly", b"groceries", b"txn_date", b"splits", b"2026-09-08"):
        assert needle not in dump, needle


def test_swapping_ciphertexts_between_rows_fails_loudly(session, alice):
    """A DBA copies the PHP 5 coffee over the PHP 50,000 rent."""
    repo = TransactionRepo(session, alice)
    coffee = repo.create({**TXN, "amount": "5.00", "splits": [{"category_id": 1, "amount": "5.00"}]})
    rent = repo.create({**TXN, "amount": "50000.00", "splits": [{"category_id": 2, "amount": "50000.00"}]})
    session.commit()
    coffee_blob = session.execute(select(Transaction.payload).where(Transaction.id == coffee.id)).scalar_one()
    session.execute(update(Transaction).where(Transaction.id == rent.id).values(payload=coffee_blob))
    session.commit()
    with pytest.raises(DecryptionError) as info:
        repo.get(rent.id)
    assert info.value.table == "transactions" and info.value.row_id == rent.id
    assert repo.get(coffee.id).data["amount"] == "5.00"


def test_moving_a_row_to_another_user_fails_loudly(session, alice, bob):
    created = TransactionRepo(session, alice).create(TXN)
    session.commit()
    session.execute(update(Transaction).where(Transaction.id == created.id).values(user_id=bob.user_id))
    session.commit()
    with pytest.raises(DecryptionError):
        TransactionRepo(session, bob).get(created.id)


def test_a_flipped_stored_byte_fails_loudly(session, alice):
    repo = TransactionRepo(session, alice)
    created = repo.create(TXN)
    session.commit()
    blob = bytearray(session.execute(select(Transaction.payload).where(Transaction.id == created.id)).scalar_one())
    blob[len(blob) // 2] ^= 0x04
    session.execute(update(Transaction).where(Transaction.id == created.id).values(payload=bytes(blob)))
    session.commit()
    with pytest.raises(DecryptionError):
        repo.get(created.id)
    with pytest.raises(DecryptionError):
        repo.list()


def test_editing_the_stored_key_version_fails_loudly(session, alice):
    repo = TransactionRepo(session, alice)
    created = repo.create(TXN)
    session.commit()
    session.execute(update(Transaction).where(Transaction.id == created.id).values(key_version=2))
    session.commit()
    with pytest.raises(DecryptionError):
        repo.get(created.id)


def test_users_cannot_see_each_others_rows(session, alice, bob):
    TransactionRepo(session, alice).create(TXN)
    theirs = TransactionRepo(session, bob).create({**TXN, "merchant": "Bob's"})
    session.commit()
    assert [r.data["merchant"] for r in TransactionRepo(session, alice).list()] == ["SM Supermarket"]
    assert TransactionRepo(session, alice).get(theirs.id) is None
    assert TransactionRepo(session, alice).update(theirs.id, TXN) is None
    assert TransactionRepo(session, alice).soft_delete(theirs.id) is False
    assert TransactionRepo(session, alice).count() == 1


def test_update_reseals_under_the_current_key_version(session, alice):
    dek = generate_dek()
    v1 = UserCipher(alice.user_id, dek, 1)
    created = TransactionRepo(session, v1).create(TXN)
    session.commit()

    v2 = UserCipher(alice.user_id, dek, 2)  # same DEK, after a master-key rotation
    repo = TransactionRepo(session, v2)
    assert repo.get(created.id).data == TXN  # old rows still open
    repo.update(created.id, {**TXN, "notes": "edited"})
    session.commit()
    stored = session.execute(select(Transaction.key_version).where(Transaction.id == created.id)).scalar_one()
    assert stored == 2
    assert repo.get(created.id).data["notes"] == "edited"


def test_soft_delete_hides_but_keeps(session, alice):
    repo = TransactionRepo(session, alice)
    created = repo.create(TXN)
    assert repo.soft_delete(created.id)
    session.commit()
    assert repo.get(created.id) is None
    assert repo.get(created.id, include_deleted=True).is_deleted
    assert repo.list() == [] and len(repo.list(include_deleted=True)) == 1


def test_the_two_step_insert_is_atomic(session, alice):
    """A failure between INSERT and UPDATE leaves no row behind."""

    class ExplodingCipher:
        user_id, key_version = alice.user_id, alice.key_version

        def seal(self, *args):
            raise RuntimeError("process killed mid-write")

    with pytest.raises(RuntimeError):
        TransactionRepo(session, ExplodingCipher()).create(TXN)
    session.rollback()
    assert session.execute(select(Transaction)).first() is None


@pytest.mark.parametrize("value", [{"amount": "5.00"}, "plaintext", b'{"amount": "5.00"}', b"\x01short"])
def test_plaintext_cannot_be_written_to_a_payload_column(session, alice, value):
    now = utcnow()
    session.add(Account(user_id=alice.user_id, key_version=1, payload=value, row_created=now, row_updated=now))
    with pytest.raises(Exception) as info:
        session.flush()
    assert "encrypted column" in str(info.value) or "sealed envelope" in str(info.value)
    session.rollback()


def test_preferences_are_one_row_per_user(session, alice):
    repo = PreferencesRepository(session, alice)
    repo.create({"theme": "dark"})
    session.commit()
    assert repo.current().data == {"theme": "dark"}
    with pytest.raises(Exception, match="UNIQUE"):
        repo.create({"theme": "light"})  # create() flushes; the constraint fires here
    session.rollback()
    assert len(session.execute(select(UserPreference)).scalars().all()) == 1


def test_every_encrypted_table_round_trips(session, alice):
    from app.db.models import ENCRYPTED_MODELS

    for model in ENCRYPTED_MODELS:
        repo = type(f"{model.__name__}Repo", (EncryptedRepository,), {"model": model})(session, alice)
        created = repo.create({"table": model.__tablename__, "n": 1})
        assert repo.get(created.id).data == {"table": model.__tablename__, "n": 1}
    session.commit()
