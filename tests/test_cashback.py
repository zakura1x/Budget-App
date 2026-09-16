"""
TXN-22 / ACC-38 - cashback on a purchase.

What must hold: the purchase keeps its full amount and spending stays gross;
the money that comes back is a real income row on the account and day the user
chose; the two move together through every edit and delete; and a card's usual
rate is a suggestion, never a total.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.services import account_service, category_service, stats_service, transaction_service

TODAY = date(2026, 9, 16)
LATER = date(2026, 10, 5)


def setup(session, owner):
    card = account_service.create_account(session, owner, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 5,
    })
    shopping = category_service.create_category(session, owner, {"name": "Shopping", "kind": "expense"})
    back = category_service.create_category(session, owner, {"name": "Cashback", "kind": "income"})
    return card, shopping, back


def buy(session, owner, card, shopping, cashback=None, amount="1000.00", on=TODAY):
    payload = {"type": "expense", "amount": amount, "account_id": card.id, "category_id": shopping.id,
               "txn_date": on.isoformat(), "merchant": "Lazada"}
    if cashback is not None:
        payload["cashback"] = cashback
    return transaction_service.create_transaction(session, owner, payload, today=TODAY)


def rows(session, owner):
    return {v.id: v for v in transaction_service.views(session, owner)}


def test_a_purchase_with_cashback_writes_both_rows(session, owner):
    card, shopping, back = setup(session, owner)
    outcome = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id, "rate": "2"})

    purchase = outcome.transactions[0]
    assert purchase.amount == Decimal("1000.00")  # gross, always
    assert purchase.cashback is not None and purchase.cashback.amount == Decimal("20.00")
    assert purchase.cashback.rate == Decimal("2")

    credit = rows(session, owner)[purchase.cashback_id]
    assert (credit.type, credit.amount, credit.account_id) == ("income", Decimal("20.00"), card.id)
    assert credit.txn_date == TODAY  # the purchase's own day, unless told otherwise
    assert [s.category_id for s in credit.splits] == [back.id]
    assert credit.cashback_of == purchase.id


def test_spending_stays_gross_and_the_money_back_is_income(session, owner):
    card, shopping, back = setup(session, owner)
    buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id})

    overview = stats_service.overview(session, owner, today=TODAY)
    assert overview.totals.spent == Decimal("1000.00")
    assert overview.totals.earned == Decimal("20.00")


def test_it_can_land_later_and_somewhere_else(session, owner):
    card, shopping, back = setup(session, owner)
    wallet = account_service.create_account(session, owner, {"name": "GCash", "type": "debit"})
    outcome = buy(session, owner, card, shopping,
                  {"amount": "20.00", "category_id": back.id, "account_id": wallet.id, "on": LATER.isoformat()})

    credit = rows(session, owner)[outcome.transactions[0].cashback_id]
    assert (credit.account_id, credit.txn_date) == (wallet.id, LATER)


def test_changing_the_cashback_moves_the_credit_with_it(session, owner):
    card, shopping, back = setup(session, owner)
    created = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id})
    purchase = created.transactions[0]

    transaction_service.update_transaction(session, owner, purchase.id, {
        "type": "expense", "amount": "1000.00", "account_id": card.id, "category_id": shopping.id,
        "txn_date": TODAY.isoformat(), "cashback": {"amount": "35.00", "category_id": back.id},
    }, today=TODAY)

    updated = rows(session, owner)[purchase.id]
    assert updated.cashback.amount == Decimal("35.00")
    assert rows(session, owner)[updated.cashback_id].amount == Decimal("35.00")
    # Still exactly one credit - an edit corrects it, never adds another.
    assert len([v for v in rows(session, owner).values() if v.cashback_of == purchase.id]) == 1


def test_an_edit_that_says_nothing_keeps_the_cashback(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]

    transaction_service.update_transaction(session, owner, purchase.id, {
        "type": "expense", "amount": "1000.00", "account_id": card.id, "category_id": shopping.id,
        "txn_date": TODAY.isoformat(), "merchant": "Lazada PH",
    }, today=TODAY)

    kept = rows(session, owner)[purchase.id]
    assert kept.cashback is not None and kept.cashback_id is not None


def test_sending_null_takes_the_cashback_away(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]
    credit_id = purchase.cashback_id

    transaction_service.update_transaction(session, owner, purchase.id, {
        "type": "expense", "amount": "1000.00", "account_id": card.id, "category_id": shopping.id,
        "txn_date": TODAY.isoformat(), "cashback": None,
    }, today=TODAY)

    after = rows(session, owner)
    assert after[purchase.id].cashback is None and after[purchase.id].cashback_id is None
    assert credit_id not in after  # the credit is gone with it


def test_deleting_the_purchase_takes_the_credit(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]

    transaction_service.delete_transaction(session, owner, purchase.id, today=TODAY)
    assert rows(session, owner) == {}


def test_deleting_the_credit_leaves_the_purchase_claiming_nothing(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]

    transaction_service.delete_transaction(session, owner, purchase.cashback_id, today=TODAY)
    left = rows(session, owner)
    assert list(left) == [purchase.id]
    assert left[purchase.id].cashback is None and left[purchase.id].cashback_id is None


def test_editing_the_credit_keeps_the_purchase_honest(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]

    transaction_service.update_transaction(session, owner, purchase.cashback_id, {
        "type": "income", "amount": "18.50", "account_id": card.id, "category_id": back.id,
        "txn_date": LATER.isoformat(),
    }, today=TODAY)

    block = rows(session, owner)[purchase.id].cashback
    assert block.amount == Decimal("18.50") and block.on == LATER


def test_cashback_cannot_be_more_than_what_you_spent(session, owner):
    card, shopping, back = setup(session, owner)
    with pytest.raises(BusinessRuleException):
        buy(session, owner, card, shopping, {"amount": "1200.00", "category_id": back.id})


def test_an_edit_that_drops_below_the_cashback_is_refused(session, owner):
    card, shopping, back = setup(session, owner)
    purchase = buy(session, owner, card, shopping, {"amount": "20.00", "category_id": back.id}).transactions[0]
    with pytest.raises(BusinessRuleException):
        transaction_service.update_transaction(session, owner, purchase.id, {
            "type": "expense", "amount": "10.00", "account_id": card.id, "category_id": shopping.id,
            "txn_date": TODAY.isoformat(),
        }, today=TODAY)


def test_only_a_purchase_earns_cashback(session, owner):
    card, shopping, back = setup(session, owner)
    with pytest.raises(BusinessRuleException):
        transaction_service.create_transaction(session, owner, {
            "type": "income", "amount": "500.00", "account_id": card.id, "category_id": back.id,
            "txn_date": TODAY.isoformat(), "cashback": {"amount": "5.00", "category_id": back.id},
        }, today=TODAY)


def test_cashback_needs_an_income_category(session, owner):
    card, shopping, _ = setup(session, owner)
    with pytest.raises(BusinessRuleException):
        buy(session, owner, card, shopping, {"amount": "20.00", "category_id": shopping.id})
    with pytest.raises(ValidationException):
        buy(session, owner, card, shopping, {"amount": "20.00"})


def test_the_account_remembers_the_usual_rate(session, owner):
    card, _, back = setup(session, owner)
    saved = account_service.update_account(session, owner, card.id, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 5,
        "cashback": {"rate": "2", "category_id": back.id},
    }, postings=[], today=TODAY)
    assert saved.cashback is not None
    assert (saved.cashback.rate, saved.cashback.category_id) == (Decimal("2.0000"), back.id)

    off = account_service.update_account(session, owner, card.id, {
        "name": "SPayLater", "type": "credit", "statement_closing_day": 15, "payment_due_day": 5,
        "cashback": None,
    }, postings=[], today=TODAY)
    assert off.cashback is None


def test_the_api_writes_and_removes_a_pair(api):
    api.register()
    card = api.post("/accounts", {"name": "SPayLater", "type": "credit", "statement_closing_day": 15,
                                  "payment_due_day": 5}).json()
    shopping = api.post("/categories", {"name": "Shopping", "kind": "expense"}).json()
    back = api.post("/categories", {"name": "Cashback", "kind": "income"}).json()

    created = api.post("/transactions", {
        "type": "expense", "amount": "1000.00", "account_id": card["id"], "category_id": shopping["id"],
        "txn_date": "2026-09-16", "cashback": {"amount": "20.00", "category_id": back["id"], "rate": "2"},
    })
    assert created.status_code == 201, created.text
    purchase = created.json()["transactions"][0]
    assert purchase["cashback"]["amount"] == "20.00" and purchase["cashback"]["rate"] == "2"
    assert len(api.get("/transactions").json()["items"]) == 2

    removed = api.patch(f"/transactions/{purchase['id']}", {
        "type": "expense", "amount": "1000.00", "account_id": card["id"], "category_id": shopping["id"],
        "txn_date": "2026-09-16", "cashback": None,
    })
    assert removed.status_code == 200, removed.text
    items = api.get("/transactions").json()["items"]
    assert len(items) == 1 and items[0]["cashback"] is None
