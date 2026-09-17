"""
Savings goals (GOA-01..08). Since 2026-09-16 a goal holds money SET ASIDE inside
its account: the balance never moves (it still matches the bank), what is set
aside comes off what the account has available and off cash on hand, net worth
still counts it, and nothing is ever written to the ledger.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.services import account_service, category_service, goal_service, projection_service, transaction_service

TODAY = date(2026, 9, 16)


@pytest.fixture
def accounts(session, owner):
    seabank = account_service.create_account(session, owner, {"name": "Seabank", "type": "debit",
                                                              "opening_balance": "36794.01"})
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash", "opening_balance": "2000.00"})
    card = account_service.create_account(session, owner, {"name": "Card", "type": "credit",
                                                           "statement_closing_day": 16, "payment_due_day": 6})
    return seabank.id, wallet.id, card.id


def goal(session, owner, account_id, **extra):
    return goal_service.create_goal(session, owner, {"name": "Emergency fund", "target": "30000.00",
                                                     "account_id": account_id, **extra}, today=TODAY)


def account(session, owner, account_id):
    return account_service.get_account(session, owner, account_id,
                                       postings=transaction_service.postings(session, owner), today=TODAY)


def listed(session, owner):
    return account_service.list_accounts(session, owner, postings=transaction_service.postings(session, owner),
                                         today=TODAY)


def test_a_new_goal_holds_nothing_and_the_balance_is_untouched(session, owner, accounts):
    """Goals made before the change - and every new one - start at nothing set aside (the user's choice)."""
    seabank, _, _ = accounts
    made = goal(session, owner, seabank, target_date="2027-06-30")
    assert (made.saved, made.remaining, made.ratio, made.reached) == (
        Decimal("0.00"), Decimal("30000.00"), Decimal("0.0000"), False)
    assert account(session, owner, seabank).balance == Decimal("36794.01")


def test_adding_money_sets_it_aside_and_moves_nothing(session, owner, accounts):
    seabank, wallet, _ = accounts
    made = goal(session, owner, seabank)
    before_cash = account_service.cash_on_hand(listed(session, owner)).total
    before_worth = account_service.net_worth(listed(session, owner)).total

    after = goal_service.add_money(session, owner, made.id, {"amount": "5000.00"}, today=TODAY)
    assert (after.saved, after.remaining) == (Decimal("5000.00"), Decimal("25000.00"))

    view = account(session, owner, seabank)
    assert view.balance == Decimal("36794.01")  # still matches the bank
    assert (view.set_aside, view.available) == (Decimal("5000.00"), Decimal("31794.01"))
    assert transaction_service.views(session, owner) == []  # nothing in the ledger
    assert account_service.cash_on_hand(listed(session, owner)).total == before_cash - Decimal("5000.00")
    assert account_service.net_worth(listed(session, owner)).total == before_worth  # still yours


def test_goals_can_share_an_account_but_not_its_money_twice(session, owner, accounts):
    seabank, _, _ = accounts
    fund = goal(session, owner, seabank)
    laptop = goal(session, owner, seabank, name="Laptop", target="60000.00")
    goal_service.add_money(session, owner, fund.id, {"amount": "30000.00"}, today=TODAY)
    with pytest.raises(BusinessRuleException):
        goal_service.add_money(session, owner, laptop.id, {"amount": "8000.00"}, today=TODAY)  # only 6,794.01 left
    ok = goal_service.add_money(session, owner, laptop.id, {"amount": "6794.01"}, today=TODAY)
    assert ok.account_available == Decimal("0.00")


def test_using_money_releases_it(session, owner, accounts):
    seabank, _, _ = accounts
    made = goal(session, owner, seabank)
    goal_service.add_money(session, owner, made.id, {"amount": "5000.00"}, today=TODAY)
    after = goal_service.use_money(session, owner, made.id, {"amount": "1500.00", "note": "Dentist"}, today=TODAY)
    assert after.saved == Decimal("3500.00")
    assert account(session, owner, seabank).available == Decimal("33294.01")
    with pytest.raises(BusinessRuleException):
        goal_service.use_money(session, owner, made.id, {"amount": "3500.01"}, today=TODAY)


def test_reaching_the_target(session, owner, accounts):
    seabank, _, _ = accounts
    made = goal(session, owner, seabank, target="2500.00")
    reached = goal_service.add_money(session, owner, made.id, {"amount": "2600.00"}, today=TODAY)
    assert (reached.reached, reached.ratio, reached.remaining) == (True, Decimal("1.0000"), Decimal("0.00"))


def test_spending_below_what_is_set_aside_says_so(session, owner, accounts):
    """The goal never pretends: if the balance falls under what it holds, it reports the shortfall."""
    _, wallet, _ = accounts
    food = category_service.create_category(session, owner, {"name": "Food"})
    made = goal(session, owner, wallet)
    goal_service.add_money(session, owner, made.id, {"amount": "1800.00"}, today=TODAY)
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "500.00", "account_id": wallet, "category_id": food.id,
        "txn_date": TODAY.isoformat()}, today=TODAY)
    view = goal_service.get_goal(session, owner, made.id, today=TODAY)
    assert (view.account_balance, view.short_by) == (Decimal("1500.00"), Decimal("300.00"))


def test_deleting_a_goal_releases_what_it_held(session, owner, accounts):
    seabank, _, _ = accounts
    made = goal(session, owner, seabank)
    goal_service.add_money(session, owner, made.id, {"amount": "1000.00"}, today=TODAY)
    goal_service.delete_goal(session, owner, made.id)
    view = account(session, owner, seabank)
    assert (view.balance, view.set_aside, view.available) == (Decimal("36794.01"), Decimal("0.00"), None)


def test_a_goal_with_money_set_aside_cannot_move_account(session, owner, accounts):
    seabank, wallet, _ = accounts
    made = goal(session, owner, seabank)
    goal_service.add_money(session, owner, made.id, {"amount": "1000.00"}, today=TODAY)
    with pytest.raises(BusinessRuleException):
        goal_service.update_goal(session, owner, made.id, {"account_id": wallet}, today=TODAY)


def test_a_goal_needs_an_account_that_holds_money(session, owner, accounts):
    _, _, card = accounts
    with pytest.raises(BusinessRuleException):
        goal(session, owner, card)
    with pytest.raises(ValidationException):
        goal(session, owner, 4242)


def test_months_ahead_starts_from_what_is_available(session, owner, accounts):
    seabank, _, _ = accounts
    made = goal(session, owner, seabank)
    before = projection_service.project(session, owner, today=TODAY, months=3).cash_on_hand
    goal_service.add_money(session, owner, made.id, {"amount": "5000.00"}, today=TODAY)
    assert projection_service.project(session, owner, today=TODAY, months=3).cash_on_hand == before - Decimal("5000.00")


def test_goals_through_the_api(api):
    assert api.register().status_code == 201
    seabank = api.post("/accounts", {"name": "Seabank", "type": "debit", "opening_balance": "9000.00"}).json()["id"]
    made = api.post("/goals", {"name": "Laptop", "target": "40000.00", "account_id": seabank})
    assert made.status_code == 201, made.text
    added = api.post(f"/goals/{made.json()['id']}/add?today=2026-09-16", {"amount": "900.00"})
    assert added.status_code == 200, added.text
    assert (added.json()["saved"], added.json()["account_available"]) == ("900.00", "8100.00")
    listed = api.get("/accounts").json()
    seabank_out = next(a for a in listed["accounts"] if a["id"] == seabank)
    assert (seabank_out["balance"], seabank_out["set_aside"], seabank_out["available"]) == ("9000.00", "900.00", "8100.00")
    used = api.post(f"/goals/{made.json()['id']}/use?today=2026-09-16", {"amount": "400.00"})
    assert used.status_code == 200, used.text
    assert api.get("/goals").json()[0]["saved"] == "500.00"
