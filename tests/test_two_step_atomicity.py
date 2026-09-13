"""
The two-step insert is atomic (ARCHITECTURE.md 5.3, invariant 2) - the Phase 4
verify item "kill the process mid-write, no orphan rows".

A row's id is part of its AAD, so a transaction is written as INSERT
(placeholder) -> flush for the id -> seal -> UPDATE. Between the first step and
the last, the database holds a row whose payload is PLACEHOLDER. If the process
dies there, that row must not survive: nothing reads a placeholder, so it would
be an orphan no report could see and no cleanup would know to look for.

"Dies" is simulated by making the seal raise - the one step after the INSERT
that can fail - and then doing what a dying connection does: never committing.
"""

import pytest
from sqlalchemy import func, select

from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.core.crypto.working_set import get_working_set
from app.db.models import AuditLog, Transaction
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import account_service, category_service, transaction_service

pytestmark = pytest.mark.security


class ProcessDied(Exception):
    pass


def die_on_seal(monkeypatch, after=0):
    """Make the (after+1)-th seal raise, as if the process stopped right there."""
    original = UserCipher.seal
    calls = {"n": 0}

    def seal(self, table, row_id, data):
        calls["n"] += 1
        if calls["n"] > after:
            raise ProcessDied("killed between INSERT and UPDATE")
        return original(self, table, row_id, data)

    monkeypatch.setattr(UserCipher, "seal", seal)


def rows(session, model=Transaction):
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_a_death_between_insert_and_seal_leaves_no_row(session, owner, monkeypatch):
    die_on_seal(monkeypatch)
    with pytest.raises(ProcessDied):
        TransactionRepository(session, owner).create({"type": "expense", "amount": "1.00", "splits": []})
    session.rollback()
    assert rows(session) == 0
    placeholders = session.execute(select(Transaction.id).where(Transaction.payload == PLACEHOLDER)).all()
    assert placeholders == []


def test_a_death_after_the_first_leg_of_a_transfer_leaves_neither_leg(session, owner, monkeypatch):
    """A transfer is two two-step inserts. Dying after the first must not leave half a transfer."""
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
    before_audit = rows(session, AuditLog)

    die_on_seal(monkeypatch, after=1)  # the out leg seals; the in leg dies
    with pytest.raises(ProcessDied):
        transaction_service.create_transaction(session, owner, {
            "type": "transfer", "amount": "5000.00", "account_id": bank.id, "counter_account_id": wallet.id,
        })
    session.rollback()
    assert rows(session) == 0
    assert rows(session, AuditLog) == before_audit  # no audit row for a write that never happened


def test_a_death_before_anything_is_queued_leaves_the_warm_cache_correct(session, owner, monkeypatch):
    """
    The seal failed inside create(), so nothing was ever queued for the cache.
    It stays warm - and it is still right: the row it never received is the
    row the database never committed. No reload is owed.
    """
    account = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
    category = category_service.create_category(session, owner, {"name": "Food"})
    kept = transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "5.00", "account_id": account.id, "category_id": category.id,
    }).transactions[0]
    transaction_service.warm(session, owner)

    die_on_seal(monkeypatch)
    with pytest.raises(ProcessDied):
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": "10.00", "account_id": account.id, "category_id": category.id,
        })
    session.rollback()
    monkeypatch.undo()

    assert [v.id for v in transaction_service.list_transactions(session, owner).items] == [kept.id]


def test_a_death_after_a_queued_write_drops_the_cache(session, owner, monkeypatch):
    """
    A transfer's out leg was written and queued for the cache before the in
    leg died. The rollback cannot un-queue selectively, so it drops the cache:
    cold is honest, and the next read reloads only what was committed.
    """
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash"})
    transaction_service.warm(session, owner)

    die_on_seal(monkeypatch, after=1)
    with pytest.raises(ProcessDied):
        transaction_service.create_transaction(session, owner, {
            "type": "transfer", "amount": "5000.00", "account_id": bank.id, "counter_account_id": wallet.id,
        })
    session.rollback()
    monkeypatch.undo()

    assert not get_working_set().is_warm(owner.user_id, "transactions")
    assert transaction_service.list_transactions(session, owner).items == []
