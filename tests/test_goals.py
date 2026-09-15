"""
Savings goals (GOA-01..07): progress IS the linked account's balance, and
putting money toward a goal is a real transfer - so the two cannot disagree.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BusinessRuleException, ValidationException
from app.services import account_service, goal_service, transaction_service

TODAY = date(2026, 9, 14)


@pytest.fixture
def accounts(session, owner):
    savings = account_service.create_account(session, owner, {"name": "Emergency fund", "type": "savings",
                                                              "opening_balance": "2000.00"})
    bdo = account_service.create_account(session, owner, {"name": "BDO", "type": "debit", "opening_balance": "50000.00"})
    card = account_service.create_account(session, owner, {"name": "Card", "type": "credit",
                                                           "statement_closing_day": 16, "payment_due_day": 6})
    return savings.id, bdo.id, card.id


def goal(session, owner, account_id, **extra):
    return goal_service.create_goal(session, owner, {"name": "Emergency fund", "target": "30000.00",
                                                     "account_id": account_id, **extra}, today=TODAY)


def test_progress_is_the_accounts_balance(session, owner, accounts):
    savings, bdo, _ = accounts
    made = goal(session, owner, savings, target_date="2027-06-30")
    assert (made.saved, made.remaining, made.ratio, made.reached) == (
        Decimal("2000.00"), Decimal("28000.00"), Decimal("0.0667"), False)

    after, outcome = goal_service.contribute(session, owner, made.id, {"amount": "5000.00", "from_account_id": bdo},
                                             today=TODAY)
    assert after.saved == Decimal("7000.00")
    legs = outcome.transactions
    assert {leg.type for leg in legs} == {"transfer"} and len(legs) == 2
    balance = account_service.get_account(session, owner, savings, postings=transaction_service.postings(session, owner))
    assert balance.balance == after.saved  # GOA-07: never two numbers


def test_reaching_the_target(session, owner, accounts):
    savings, bdo, _ = accounts
    made = goal(session, owner, savings, target="2500.00")
    reached, _ = goal_service.contribute(session, owner, made.id, {"amount": "600.00", "from_account_id": bdo}, today=TODAY)
    assert (reached.reached, reached.ratio, reached.remaining) == (True, Decimal("1.0000"), Decimal("0.00"))


def test_a_goal_needs_an_account_that_holds_money(session, owner, accounts):
    _, _, card = accounts
    with pytest.raises(BusinessRuleException):
        goal(session, owner, card)
    with pytest.raises(ValidationException):
        goal(session, owner, 4242)


def test_one_goal_per_account(session, owner, accounts):
    savings, _, _ = accounts
    goal(session, owner, savings)
    with pytest.raises(BusinessRuleException):
        goal(session, owner, savings, name="Holiday")


def test_deleting_a_goal_leaves_the_money(session, owner, accounts):
    savings, bdo, _ = accounts
    made = goal(session, owner, savings)
    goal_service.contribute(session, owner, made.id, {"amount": "1000.00", "from_account_id": bdo}, today=TODAY)
    goal_service.delete_goal(session, owner, made.id)
    assert goal_service.list_goals(session, owner, today=TODAY) == []
    balance = account_service.get_account(session, owner, savings, postings=transaction_service.postings(session, owner))
    assert balance.balance == Decimal("3000.00")


def test_goals_through_the_api(api):
    assert api.register().status_code == 201
    savings = api.post("/accounts", {"name": "Savings", "type": "savings", "opening_balance": "100.00"}).json()["id"]
    bdo = api.post("/accounts", {"name": "BDO", "type": "debit", "opening_balance": "9000.00"}).json()["id"]
    made = api.post("/goals", {"name": "Laptop", "target": "40000.00", "account_id": savings})
    assert made.status_code == 201, made.text
    moved = api.post(f"/goals/{made.json()['id']}/contribute?today=2026-09-14",
                     {"amount": "900.00", "from_account_id": bdo})
    assert moved.status_code == 201, moved.text
    assert api.get("/goals").json()[0]["saved"] == "1000.00"
