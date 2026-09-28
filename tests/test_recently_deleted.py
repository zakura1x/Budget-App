"""
TXN-25 - Recently deleted, and Undo.

What would go wrong silently, and what these catch:

  * a restore that brings back one leg of a transfer, or a purchase without
    its cashback - a ledger with half a pair in it
  * rows hidden by something other than Delete (an installment conversion, a
    credit taken away by an edit) showing up as "deleted" and coming back on
    their own, next to the plan or edit that replaced them
  * a restore that contradicts what happened since: an archived account, a
    deleted category, a plan payment whose extra part lives in the plan, a
    charge the recurring engine has already posted again
"""

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from app.core.exceptions import BusinessRuleException, NotFoundException
from app.db.repositories.transaction_repository import TransactionRepository
from app.db.types import utcnow
from app.services import account_service, category_service, recurring_service, tag_service, transaction_service


@pytest.fixture
def books(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "1000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                           "opening_balance": "20000.00"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    household = category_service.create_category(session, owner, {"name": "Household"})
    cashback = category_service.create_category(session, owner, {"name": "Cashback", "kind": "income"})

    class B:
        pass

    b = B()
    b.wallet, b.bank, b.food, b.household, b.cashback = wallet.id, bank.id, food.id, household.id, cashback.id
    return b


def spend(session, owner, books, amount="150.00", **extra):
    payload = {"type": "expense", "amount": amount, "account_id": books.wallet, "category_id": books.food,
               "txn_date": "2026-09-20", **extra}
    return transaction_service.create_transaction(session, owner, payload).transactions[0]


def balance(session, owner, account_id):
    return account_service.get_account(session, owner, account_id,
                                       postings=transaction_service.postings(session, owner)).balance


def live_ids(session, owner):
    return {v.id for v in transaction_service.views(session, owner)}


def listed(session, owner):
    return transaction_service.deleted(session, owner)


# ------------------------------------------------------------ the round trip


def test_a_deleted_entry_is_listed_and_comes_back_exactly(session, owner, books):
    row = spend(session, owner, books, merchant="Jollibee", notes="lunch")
    transaction_service.delete_transaction(session, owner, row.id)
    assert balance(session, owner, books.wallet) == D("1000.00")

    [entry] = listed(session, owner)
    assert (entry.transaction.id, entry.restorable, entry.reason) == (row.id, True, None)

    transaction_service.restore_transaction(session, owner, row.id)
    assert balance(session, owner, books.wallet) == D("850.00")
    back = transaction_service.get_transaction(session, owner, row.id)
    assert (back.merchant, back.notes, back.amount) == ("Jollibee", "lunch", D("150.00"))
    assert listed(session, owner) == []


def test_the_marker_does_not_survive_the_restore(session, owner, books):
    row = spend(session, owner, books)
    transaction_service.delete_transaction(session, owner, row.id)
    transaction_service.restore_transaction(session, owner, row.id)
    stored = TransactionRepository(session, owner).get(row.id)
    assert "deleted_at" not in stored.data


def test_a_restored_row_reaches_the_working_set_after_commit(session, owner, books):
    row = spend(session, owner, books)
    transaction_service.warm(session, owner)
    transaction_service.delete_transaction(session, owner, row.id)
    assert row.id not in live_ids(session, owner)
    transaction_service.restore_transaction(session, owner, row.id)
    assert row.id in live_ids(session, owner)


def test_a_transfer_is_listed_once_and_both_legs_come_back(session, owner, books):
    outcome = transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "500.00", "account_id": books.bank, "counter_account_id": books.wallet,
        "txn_date": "2026-09-20"})
    incoming = next(v for v in outcome.transactions if v.direction == "in")
    transaction_service.delete_transaction(session, owner, incoming.id)  # deleted from the leg you tapped

    [entry] = listed(session, owner)
    assert entry.transaction.direction == "out"

    transaction_service.restore_transaction(session, owner, entry.transaction.id)
    assert {v.id for v in outcome.transactions} <= live_ids(session, owner)
    assert balance(session, owner, books.wallet) == D("1500.00")
    assert balance(session, owner, books.bank) == D("19500.00")


def test_a_purchase_and_its_cashback_go_and_come_back_together(session, owner, books):
    row = spend(session, owner, books, amount="1000.00",
                cashback={"amount": "20.00", "category_id": books.cashback})
    credit_id = row.cashback_id
    transaction_service.delete_transaction(session, owner, row.id)

    [entry] = listed(session, owner)  # one line: the credit is not listed beside it
    assert entry.transaction.id == row.id

    transaction_service.restore_transaction(session, owner, row.id)
    purchase = transaction_service.get_transaction(session, owner, row.id)
    credit = transaction_service.get_transaction(session, owner, credit_id)
    assert (purchase.cashback_id, credit.cashback_of) == (credit_id, row.id)
    assert balance(session, owner, books.wallet) == D("20.00")


def test_a_credit_deleted_alone_rejoins_its_purchase(session, owner, books):
    row = spend(session, owner, books, amount="1000.00",
                cashback={"amount": "20.00", "category_id": books.cashback})
    transaction_service.delete_transaction(session, owner, row.cashback_id)
    assert transaction_service.get_transaction(session, owner, row.id).cashback is None

    [entry] = listed(session, owner)
    transaction_service.restore_transaction(session, owner, entry.transaction.id)
    purchase = transaction_service.get_transaction(session, owner, row.id)
    assert purchase.cashback_id == entry.transaction.id
    assert purchase.cashback.amount == D("20.00")


def test_a_deleted_tag_is_dropped_rather_than_refused(session, owner, books):
    tag = tag_service.create_tag(session, owner, {"name": "Trip"})
    row = spend(session, owner, books, tag_ids=[tag.id])
    transaction_service.delete_transaction(session, owner, row.id)
    tag_service.delete_tag(session, owner, tag.id)

    transaction_service.restore_transaction(session, owner, row.id)
    assert transaction_service.get_transaction(session, owner, row.id).tag_ids == ()


# --------------------------------------------- hidden, not deleted: not listed


def test_a_row_hidden_by_anything_but_delete_is_not_listed(session, owner, books):
    """An installment conversion (REC-34) soft-deletes the purchase with no marker."""
    row = spend(session, owner, books)
    TransactionRepository(session, owner).soft_delete(row.id)
    session.commit()
    assert listed(session, owner) == []
    with pytest.raises(NotFoundException):
        transaction_service.restore_transaction(session, owner, row.id)


def test_cashback_removed_by_an_edit_is_not_listed(session, owner, books):
    row = spend(session, owner, books, amount="1000.00",
                cashback={"amount": "20.00", "category_id": books.cashback})
    transaction_service.update_transaction(session, owner, row.id, {
        "type": "expense", "amount": "1000.00", "account_id": books.wallet, "category_id": books.food,
        "txn_date": "2026-09-20", "cashback": None})
    assert listed(session, owner) == []


def test_only_the_last_thirty_days_are_listed(session, owner, books):
    row = spend(session, owner, books)
    transaction_service.delete_transaction(session, owner, row.id)
    later = utcnow() + timedelta(days=31)
    assert transaction_service.deleted(session, owner, now=later) == []
    assert len(transaction_service.deleted(session, owner, now=utcnow() + timedelta(days=29))) == 1


def test_newest_deletion_first(session, owner, books):
    first, second = spend(session, owner, books), spend(session, owner, books, amount="75.00")
    transaction_service.delete_transaction(session, owner, first.id)
    transaction_service.delete_transaction(session, owner, second.id)
    # Both in the same second - the id breaks the tie, newest first either way.
    assert [d.transaction.id for d in listed(session, owner)] == [second.id, first.id]
    assert isinstance(listed(session, owner)[0].deleted_at, datetime)


# ------------------------------------------- what happened since: refused


def test_an_archived_account_is_refused_with_the_reason(session, owner, books):
    row = spend(session, owner, books)
    transaction_service.delete_transaction(session, owner, row.id)
    account_service.set_archived(session, owner, books.wallet, True)
    session.commit()

    [entry] = listed(session, owner)
    assert not entry.restorable and "archived" in entry.reason
    with pytest.raises(BusinessRuleException):
        transaction_service.restore_transaction(session, owner, row.id)
    assert row.id not in live_ids(session, owner)


def test_a_deleted_category_is_refused(session, owner, books):
    row = spend(session, owner, books, category_id=books.household)
    transaction_service.delete_transaction(session, owner, row.id)
    category_service.delete_category(session, owner, books.household)

    [entry] = listed(session, owner)
    assert (entry.restorable, entry.reason) == (False, "A category it was filed under was deleted")


def test_a_payment_on_a_plan_is_refused(session, owner, books):
    """REC-32. Its extra part lives in the plan's prepayments; a lone transfer would disagree with it."""
    transaction_service.post_recurring(session, owner, {
        "type": "transfer", "amount": "5000.00", "account_id": books.bank, "counter_account_id": books.wallet,
        "txn_date": "2026-09-20"}, recurring_id=999, recurring_on=None)
    session.commit()
    out_leg = next(v for v in transaction_service.views(session, owner) if v.direction == "out")
    transaction_service.delete_transaction(session, owner, out_leg.id)

    [entry] = listed(session, owner)
    assert (entry.restorable, entry.reason) == (False, "A payment on a plan - pay it again from the plan instead")


def test_a_charge_posted_again_since_is_refused(session, owner, books):
    """The occurrence was recorded again (REC-33 pay now); a second copy would charge it twice."""
    plan = recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "expense", "name": "Rent", "account_id": books.wallet,
        "category_id": books.household, "frequency": "monthly", "amount": "300.00", "start": "2026-09-01",
        "post_past": True}, today=datetime(2026, 9, 20).date())
    recurring_service.expand(session, owner, today=datetime(2026, 9, 20).date())
    [charge] = [v for v in transaction_service.views(session, owner) if v.recurring_id == plan.id]
    transaction_service.delete_transaction(session, owner, charge.id)
    assert listed(session, owner)[0].restorable

    transaction_service.post_recurring(session, owner, {
        "type": "expense", "amount": "300.00", "account_id": books.wallet, "category_id": books.household,
        "txn_date": "2026-09-01"}, recurring_id=plan.id, recurring_on=charge.recurring_on)
    session.commit()
    [entry] = listed(session, owner)
    assert (entry.restorable, entry.reason) == (False, "That charge has been recorded again since")


def test_a_row_already_restored_cannot_be_restored_again(session, owner, books):
    row = spend(session, owner, books)
    transaction_service.delete_transaction(session, owner, row.id)
    transaction_service.restore_transaction(session, owner, row.id)
    with pytest.raises(NotFoundException):
        transaction_service.restore_transaction(session, owner, row.id)


# ------------------------------------------------------------------ the API


def test_the_routes_are_not_read_as_an_id(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    row = api.post("/transactions", {"type": "expense", "amount": "150.00", "account_id": wallet,
                                     "category_id": food, "merchant": "Jollibee"}).json()["transactions"][0]

    merchants = api.get("/transactions/merchants")
    assert merchants.status_code == 200
    assert merchants.json()[0]["name"] == "Jollibee"

    assert api.delete(f"/transactions/{row['id']}").status_code == 200
    deleted = api.get("/transactions/deleted")
    assert deleted.status_code == 200
    assert [d["transaction"]["id"] for d in deleted.json()] == [row["id"]]

    restored = api.post(f"/transactions/{row['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["cash_on_hand"]["total"] == "850.00"
