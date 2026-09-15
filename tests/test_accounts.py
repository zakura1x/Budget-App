"""
Accounts - the first encrypted CRUD, and every number derived from it
(ACC-01..ACC-18).

The things worth proving here are the ones SQL cannot check for us: that a
balance is Decimal-exact, that cash on hand counts exactly the accounts it
says it counts, that a card's available credit subtracts the installment
remainder the bank has already blocked, and that a name never reaches the
database in a readable form.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.db.models import Account
from app.services import account_service
from app.services.account_service import Posting

CASH = {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"}
CARD = {
    "name": "BPI Gold",
    "type": "credit",
    "opening_balance": "0",
    "credit_limit": "50000.00",
    "statement_closing_day": 20,
    "payment_due_day": 5,
}


def make(session, cipher, **overrides):
    payload = {**CASH, **overrides}
    return account_service.create_account(session, cipher, payload)


# ------------------------------------------------------------------ the rules


def test_create_round_trips_through_the_ciphertext(session, owner):
    created = make(session, owner)
    fetched = account_service.get_account(session, owner, created.id)
    assert fetched.name == "Wallet"
    assert fetched.balance == Decimal("1500.00")
    assert isinstance(fetched.balance, Decimal)


@pytest.mark.security
def test_the_name_is_not_readable_in_the_database(session, owner):
    """The SSMS test, locally: a plain SELECT shows nothing about the account."""
    make(session, owner, name="BPI Savings")
    stored = session.execute(select(Account.payload)).scalars().all()
    assert stored
    for payload in stored:
        assert b"BPI" not in payload
        assert b"Savings" not in payload
        assert b"1500" not in payload


def test_counts_in_cash_on_hand_defaults_by_type(session, owner):
    """ACC-18 - credit on, investment off, and the rest on."""
    kinds = {
        "cash": True, "debit": True, "savings": True, "credit": True, "investment": False,
    }
    for kind, expected in kinds.items():
        extra = {"statement_closing_day": 20, "payment_due_day": 5} if kind == "credit" else {}
        view = make(session, owner, name=f"{kind} account", type=kind, **extra)
        assert view.counts_in_cash_on_hand is expected, kind


def test_the_default_can_be_overridden(session, owner):
    view = make(session, owner, type="investment", name="COL Financial", counts_in_cash_on_hand=True)
    assert view.counts_in_cash_on_hand is True


def test_duplicate_names_are_refused(session, owner):
    make(session, owner, name="Wallet")
    with pytest.raises(BusinessRuleException):
        make(session, owner, name="wallet")


def test_type_cannot_change_after_creation(session, owner):
    created = make(session, owner)
    with pytest.raises(BusinessRuleException):
        account_service.update_account(session, owner, created.id, {**CASH, "type": "savings"})


def test_a_float_opening_balance_is_refused(session, owner):
    with pytest.raises(ValidationException):
        make(session, owner, opening_balance=1500.10)


def test_an_unknown_account_is_not_found(session, owner):
    with pytest.raises(NotFoundException):
        account_service.get_account(session, owner, 9999)


# -------------------------------------------------------------- the balances


def test_balance_is_opening_plus_postings_exactly(session, owner):
    created = make(session, owner, opening_balance="1000.00")
    postings = [
        Posting(created.id, date(2026, 9, 1), Decimal("-0.10")),
        Posting(created.id, date(2026, 9, 2), Decimal("-0.20")),
    ]
    view = account_service.get_account(session, owner, created.id, postings=postings)
    # The float answer here is 999.6999999999999; this must be 999.70.
    assert view.balance == Decimal("999.70")
    assert str(view.balance) == "999.70"


def test_postings_for_other_accounts_are_ignored(session, owner):
    mine = make(session, owner, name="Mine")
    theirs = make(session, owner, name="Theirs")
    postings = [Posting(theirs.id, date(2026, 9, 1), Decimal("-500.00"))]
    view = account_service.get_account(session, owner, mine.id, postings=postings)
    assert view.balance == Decimal("1500.00")


# ------------------------------------------------------------ cash on hand


def test_cash_on_hand_counts_only_what_is_switched_on(session, owner):
    make(session, owner, name="Wallet", opening_balance="1500.00")
    make(session, owner, name="BDO", type="debit", opening_balance="20000.00")
    make(session, owner, name="Fund", type="investment", opening_balance="100000.00")
    views = account_service.list_accounts(session, owner)

    total = account_service.cash_on_hand(views)
    assert total.total == Decimal("21500.00")  # the investment is not in my pockets
    assert len(total.account_ids) == 2
    assert len(total.excluded_ids) == 1


def test_a_card_balance_is_subtracted_from_cash_on_hand(session, owner):
    """ACC-18 - money already spent on the card is money you no longer have."""
    wallet = make(session, owner, name="Wallet", opening_balance="1500.00")
    card = make(session, owner, **CARD)
    postings = [Posting(card.id, date(2026, 9, 10), Decimal("-500.00"))]

    views = account_service.list_accounts(session, owner, postings=postings)
    assert account_service.cash_on_hand(views).total == Decimal("1000.00")
    assert {v.id for v in views} == {wallet.id, card.id}


def test_an_archived_account_never_counts(session, owner):
    make(session, owner, name="Wallet", opening_balance="1500.00")
    old = make(session, owner, name="Old bank", type="debit", opening_balance="900.00")
    account_service.set_archived(session, owner, old.id, True)

    views = account_service.list_accounts(session, owner)
    assert account_service.cash_on_hand(views).total == Decimal("1500.00")


def test_archiving_is_reversible_and_does_not_delete(session, owner):
    created = make(session, owner)
    account_service.set_archived(session, owner, created.id, True)
    assert account_service.get_account(session, owner, created.id).archived is True
    account_service.set_archived(session, owner, created.id, False)
    assert account_service.get_account(session, owner, created.id).archived is False


# ------------------------------------------------------------- credit cards


def test_statement_period_and_due_date_are_derived(session, owner):
    card = make(session, owner, **CARD)
    view = account_service.get_account(session, owner, card.id, today=date(2026, 9, 13))
    assert view.credit.period_start == date(2026, 8, 21)
    assert view.credit.period_closes == date(2026, 9, 20)
    assert view.credit.payment_due == date(2026, 10, 5)


def test_period_spend_counts_only_the_open_period(session, owner):
    card = make(session, owner, **CARD)
    postings = [
        Posting(card.id, date(2026, 8, 15), Decimal("-1000.00")),  # last statement
        Posting(card.id, date(2026, 8, 25), Decimal("-300.00")),   # this one
        Posting(card.id, date(2026, 9, 12), Decimal("-200.00")),   # this one
    ]
    view = account_service.get_account(session, owner, card.id, postings=postings, today=date(2026, 9, 13))
    assert view.credit.period_spend == Decimal("500.00")
    assert view.credit.owed == Decimal("1500.00")  # the whole carried balance


def test_available_credit_subtracts_the_installment_remainder(session, owner):
    """ACC-14 - the bank blocks the whole remainder, so we must too."""
    card = make(session, owner, **CARD)
    account_service.update_account(
        session, owner, card.id, {**CARD, "counts_in_cash_on_hand": True}
    )
    # Since Phase 7 the remainder is derived from the installment plans on the
    # card - here one that has not posted a payment yet.
    from app.services import category_service, recurring_service

    gadgets = category_service.create_category(session, owner, {"name": "Gadgets"})
    recurring_service.create_rule(session, owner, {
        "kind": "installment", "name": "Phone", "account_id": card.id, "category_id": gadgets.id,
        "frequency": "monthly", "start": "2026-10-01", "price": "36000.00", "payments": 12,
    }, today=date(2026, 9, 13))

    postings = [Posting(card.id, date(2026, 9, 10), Decimal("-4000.00"))]
    view = account_service.get_account(session, owner, card.id, postings=postings, today=date(2026, 9, 13))
    assert view.credit.owed == Decimal("4000.00")
    assert view.credit.available == Decimal("10000.00")  # 50000 - 4000 - 36000


def test_due_soon_uses_the_configured_window(session, owner):
    card = make(session, owner, **CARD)
    close = account_service.get_account(session, owner, card.id, today=date(2026, 10, 2))
    far = account_service.get_account(session, owner, card.id, today=date(2026, 9, 13))
    assert close.credit.due_soon is True and close.credit.due_in_days == 3
    assert far.credit.due_soon is False


def test_only_a_credit_account_carries_credit_terms(session, owner):
    view = make(session, owner, type="savings", name="BDO Savings",
                statement_closing_day=20, payment_due_day=5, credit_limit="1000.00")
    assert view.credit is None
    record = account_service.AccountRepository(session, owner).get(view.id)
    assert "credit_limit" not in record.data
    assert "statement_closing_day" not in record.data


def test_a_card_needs_its_closing_and_due_days(session, owner):
    with pytest.raises(ValidationException):
        make(session, owner, name="Card", type="credit", statement_closing_day=40, payment_due_day=5)


# --------------------------------------------------------------- investments


def test_a_typed_value_is_appended_with_its_date(session, owner):
    """ACC-13 - the history is kept, not overwritten."""
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    view = account_service.add_valuation(session, owner, fund.id, "103500.00", on=date(2026, 10, 1))

    assert [str(v.value) for v in view.valuations] == ["105000.00", "103500.00"]
    assert view.current_value == Decimal("103500.00")
    assert view.balance == Decimal("103500.00")


def test_before_any_valuation_the_opening_balance_stands(session, owner):
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    assert fund.current_value == Decimal("100000.00")


@pytest.mark.security
def test_a_revaluation_writes_no_transaction(session, owner):
    """ACC-12 - it is a valuation change, and stays out of income and spending."""
    from app.db.models import Transaction

    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.add_valuation(session, owner, fund.id, "105000.00", on=date(2026, 9, 1))
    assert session.execute(select(Transaction.id)).all() == []


def test_only_an_investment_account_can_be_revalued(session, owner):
    wallet = make(session, owner)
    with pytest.raises(BusinessRuleException):
        account_service.add_valuation(session, owner, wallet.id, "10.00")


def test_a_valuation_cannot_be_set_through_the_normal_update(session, owner):
    fund = make(session, owner, type="investment", name="Fund", opening_balance="100000.00")
    account_service.update_account(
        session, owner, fund.id,
        {"name": "Fund", "type": "investment", "opening_balance": "100000.00",
         "valuations": [{"on": "2026-09-01", "value": "999999.00"}]},
    )
    assert account_service.get_account(session, owner, fund.id).valuations == ()


# ---------------------------------------------------------------- the API


def register(api):
    response = api.register()
    assert response.status_code == 201, response.text
    return response


def test_accounts_need_an_unlocked_session(api):
    register(api)
    api.post("/auth/lock")
    response = api.get("/accounts")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_LOCKED"


def test_create_and_list_through_the_api(api):
    register(api)
    created = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"})
    assert created.status_code == 201, created.text
    assert created.json()["balance"] == "1500.00"

    listed = api.get("/accounts").json()
    assert [a["name"] for a in listed["accounts"]] == ["Wallet"]
    assert listed["cash_on_hand"]["total"] == "1500.00"


def test_the_api_refuses_an_amount_sent_as_a_number(api):
    """Invariant 5, at the edge: JSON 1500.10 has already been through a float."""
    register(api)
    response = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": 1500.10})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_integer_amount_is_still_accepted(api):
    register(api)
    response = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": 1500})
    assert response.status_code == 201
    assert response.json()["opening_balance"] == "1500.00"


def test_archive_through_the_api(api):
    register(api)
    account_id = api.post("/accounts", {"name": "Old", "type": "debit"}).json()["id"]
    response = api.post(f"/accounts/{account_id}/archive", {"archived": True})
    assert response.status_code == 200
    assert response.json()["archived"] is True
    assert api.get("/accounts?include_archived=false").json()["accounts"] == []


def test_there_is_no_way_to_delete_an_account(api):
    """ACC-06 - history depends on the row existing."""
    register(api)
    account_id = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    assert api.delete(f"/accounts/{account_id}").status_code == 405


def test_one_user_cannot_see_another_users_accounts(api):
    register(api)
    api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1500.00"})
    api.post("/auth/logout")

    second = api.register(email="mara@example.com", name="Mara")
    assert second.status_code == 201, second.text
    assert api.get("/accounts").json()["accounts"] == []
