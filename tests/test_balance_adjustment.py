"""
Balance adjustments (ACC-27..30, FEATURES.md §22).

A balance is never stored, so typing one is a question before it is a save.
The guarantees: nothing is written until the user answers; accepting writes an
adjustment and exactly one BALANCE_ADJUST audit entry, and moves the balance
while the budget, the day totals and a card's spending limit stay the same
(confirmed 2026-09-14); fixing the opening balance writes neither; an adjustment can be deleted but never edited, repeated or entered
by hand.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    BalanceDiffersException,
    BusinessRuleException,
    ValidationException,
)
from app.db.models import AuditLog
from app.db.repositories.audit_repository import AuditRepository
from app.services import account_service, category_service, transaction_service
from app.services.budget_service import budget_service

D = Decimal
TODAY = date(2026, 9, 14)
WALLET = {"name": "Wallet", "type": "cash", "opening_balance": "2000.00"}


@pytest.fixture
def setup(session, owner):
    wallet = account_service.create_account(session, owner, WALLET)
    food = category_service.create_category(session, owner, {"name": "Food"})
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "50.00", "account_id": wallet.id, "category_id": food.id, "txn_date": "2026-09-10"})
    budget_service.create_budget(session, owner, {
        "period": "monthly", "amount": "30000.00",
        "allocations": [{"category_id": food.id, "amount": "5000.00"}]}, today=TODAY)

    class S:
        pass

    s = S()
    s.wallet, s.food = wallet.id, food.id
    return s


def balance(session, owner, account_id, today=TODAY):
    return account_service.get_account(session, owner, account_id,
                                       postings=transaction_service.postings(session, owner), today=today).balance


def set_balance(session, owner, account_id, typed, action=None, note=None, base=WALLET):
    payload = {**base, "balance": typed}
    payload.pop("opening_balance", None)
    if action:
        payload["balance_action"] = action
    if note:
        payload["balance_note"] = note
    return account_service.update_account(session, owner, account_id, payload,
                                          postings=transaction_service.postings(session, owner), today=TODAY)


def audits(session, action):
    return session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()


def adjustments(session, owner):
    return transaction_service.list_transactions(session, owner, type="adjustment").items


# ------------------------------------------------------------ asked first


def test_a_different_balance_is_a_question_and_nothing_is_saved(session, owner, setup):
    updates_before = len(audits(session, "UPDATE"))
    with pytest.raises(BalanceDiffersException) as raised:
        set_balance(session, owner, setup.wallet, "1600.00")

    assert raised.value.extra == {"before": "1950.00", "after": "1600.00", "difference": "-350.00"}
    assert balance(session, owner, setup.wallet) == D("1950.00")
    assert adjustments(session, owner) == []
    assert audits(session, "BALANCE_ADJUST") == []
    assert len(audits(session, "UPDATE")) == updates_before


def test_the_same_balance_asks_nothing(session, owner, setup):
    set_balance(session, owner, setup.wallet, "1950.00")
    assert adjustments(session, owner) == []


# ------------------------------------------------------------ accepting


@pytest.mark.security
def test_accepting_records_an_adjustment_and_one_audit_entry(session, owner, setup):
    set_balance(session, owner, setup.wallet, "1600.00", action="adjust", note="Counted the wallet")

    assert balance(session, owner, setup.wallet) == D("1600.00")
    [entry] = adjustments(session, owner)
    assert (entry.type, entry.direction, entry.amount, entry.txn_date) == ("adjustment", "out", D("350.00"), TODAY)
    assert entry.splits[0].category_id is None

    [row] = audits(session, "BALANCE_ADJUST")
    detail = AuditRepository(session).read_detail(row, owner)
    assert detail == {"before": "1950.00", "after": "1600.00", "difference": "-350.00",
                      "note": "Counted the wallet", "transaction_id": entry.id}
    assert b"1600" not in row.detail_enc  # the trail is sealed like everything else
    assert account_service.get_account(session, owner, setup.wallet).opening_balance == D("2000.00")


def test_an_unrecorded_gain_raises_the_balance(session, owner, setup):
    set_balance(session, owner, setup.wallet, "2100.00", action="adjust")
    [entry] = adjustments(session, owner)
    assert (entry.direction, entry.amount) == ("in", D("150.00"))
    assert balance(session, owner, setup.wallet) == D("2100.00")


@pytest.mark.security
@pytest.mark.parametrize("typed", ["1600.00", "2100.00"], ids=["loss", "gain"])
def test_the_budget_stays_the_same(session, owner, setup, typed):
    """Confirmed 2026-09-14 - an adjustment moves the balance, never the budget or the day totals."""
    before = budget_service.status(session, owner, today=TODAY)
    set_balance(session, owner, setup.wallet, typed, action="adjust")
    after = budget_service.status(session, owner, today=TODAY)

    assert balance(session, owner, setup.wallet) == D(typed)
    assert (after.allowance.spent, after.allowance.daily) == (before.allowance.spent, before.allowance.daily)
    assert [(c.category_id, c.spent) for c in after.categories] == [(c.category_id, c.spent) for c in before.categories]
    assert [d for d in transaction_service.list_transactions(session, owner).days if d.on == TODAY] == []


def test_an_adjustment_on_a_card_does_not_use_its_limit(session, owner):
    card_payload = {"name": "Card", "type": "credit", "statement_closing_day": 16, "payment_due_day": 6,
                    "spending_limit": "10000.00"}
    card = account_service.create_account(session, owner, card_payload)
    set_balance(session, owner, card.id, "-800.00", action="adjust", base=card_payload)

    credit = account_service.get_account(session, owner, card.id, postings=transaction_service.postings(session, owner),
                                         today=TODAY).credit
    assert (credit.owed, credit.limit_spent) == (D("800.00"), D("0.00"))


# ------------------------------------------------------ fixing the opening


def test_fixing_the_opening_balance_writes_no_adjustment_and_no_trail(session, owner, setup):
    set_balance(session, owner, setup.wallet, "1600.00", action="fix_opening")

    assert balance(session, owner, setup.wallet) == D("1600.00")
    assert account_service.get_account(session, owner, setup.wallet).opening_balance == D("1650.00")
    assert adjustments(session, owner) == []
    assert audits(session, "BALANCE_ADJUST") == []


def test_an_unknown_action_is_refused(session, owner, setup):
    with pytest.raises(ValidationException):
        set_balance(session, owner, setup.wallet, "1600.00", action="ignore")


def test_an_investment_value_is_set_this_way_too(session, owner):
    """Changed 2026-09-18 (user): an investment's value asks like any balance - here an unrecorded loss."""
    fund = {"name": "Fund", "type": "investment", "opening_balance": "100000.00"}
    created = account_service.create_account(session, owner, fund)
    set_balance(session, owner, created.id, "90000.00", action="adjust", base=fund)
    [entry] = adjustments(session, owner)
    assert (entry.direction, str(entry.amount)) == ("out", "10000.00")


# ----------------------------------------------------- living with one


def test_deleting_the_adjustment_restores_the_balance(session, owner, setup):
    set_balance(session, owner, setup.wallet, "1600.00", action="adjust")
    [entry] = adjustments(session, owner)
    transaction_service.delete_transaction(session, owner, entry.id)
    assert balance(session, owner, setup.wallet) == D("1950.00")


def test_an_adjustment_cannot_be_edited(session, owner, setup):
    set_balance(session, owner, setup.wallet, "1600.00", action="adjust")
    [entry] = adjustments(session, owner)
    with pytest.raises(BusinessRuleException):
        transaction_service.update_transaction(session, owner, entry.id, {
            "type": "expense", "amount": "350.00", "account_id": setup.wallet,
            "category_id": setup.food, "txn_date": "2026-09-14"})


def test_an_adjustment_cannot_be_entered(session, owner, setup):
    with pytest.raises(ValidationException):
        transaction_service.create_transaction(session, owner, {
            "type": "adjustment", "amount": "1.00", "account_id": setup.wallet, "txn_date": "2026-09-14"})


# ---------------------------------------------------------------- the API


def test_the_question_and_the_answer_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "2000.00"}).json()["id"]

    asked = api.patch(f"/accounts/{wallet}?today=2026-09-14", {"name": "Wallet", "type": "cash", "balance": "1650.00"})
    assert asked.status_code == 409, asked.text
    body = asked.json()
    assert (body["code"], body["before"], body["after"], body["difference"]) == (
        "BALANCE_DIFFERS", "2000.00", "1650.00", "-350.00")

    answered = api.patch(f"/accounts/{wallet}?today=2026-09-14", {
        "name": "Wallet", "type": "cash", "balance": "1650.00", "balance_action": "adjust"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["balance"] == "1650.00"

    listed = api.get("/transactions?type=adjustment").json()["items"]
    assert [(t["type"], t["direction"], t["amount"]) for t in listed] == [("adjustment", "out", "350.00")]


def test_an_edit_without_a_balance_keeps_the_opening_balance(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "2000.00"}).json()["id"]
    renamed = api.patch(f"/accounts/{wallet}", {"name": "Pocket", "type": "cash"})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["opening_balance"]) == ("Pocket", "2000.00")
