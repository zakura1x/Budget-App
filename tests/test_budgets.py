"""
Budgets through the service and the API - the working set, the preferences
row and the category tree all taking part.

The expensive bugs this guards against: counting a transfer or income as
spending, reading a category from anywhere but the splits, a mid-period change
rewriting a finished period, and a deleted category leaving an allocation that
budgets money nothing can be spent against.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    ValidationException,
)
from app.services import (
    account_service,
    category_service,
    preferences_service,
    transaction_service,
)
from app.services.budget_service import budget_service

TODAY = date(2026, 9, 13)  # a Sunday


@pytest.fixture
def tree(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "50000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    groceries = category_service.create_category(session, owner, {"name": "Groceries", "parent_id": food.id})
    transport = category_service.create_category(session, owner, {"name": "Transport"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class T:
        pass

    t = T()
    t.wallet, t.bank = wallet.id, bank.id
    t.food, t.groceries, t.transport, t.salary = food.id, groceries.id, transport.id, salary.id
    return t


def monthly(session, owner, tree, amount="30000.00", today=TODAY, **extra):
    payload = {"period": "monthly", "month_start_day": 1, "amount": amount,
               "allocations": [{"category_id": tree.food, "amount": "10000.00"},
                               {"category_id": tree.transport, "amount": "5000.00"}], **extra}
    return budget_service.create_budget(session, owner, payload, today=today)


def expense(session, owner, tree, amount, on, category=None, splits=None):
    payload = {"type": "expense", "amount": amount, "account_id": tree.wallet, "txn_date": on}
    payload.update({"splits": splits} if splits else {"category_id": category or tree.groceries})
    return transaction_service.create_transaction(session, owner, payload)


# ------------------------------------------------------------------- basics


def test_a_new_budget_covers_the_whole_current_period(session, owner, tree):
    monthly(session, owner, tree)
    status = budget_service.status(session, owner, today=TODAY)
    assert (status.period.start, status.period.end) == (date(2026, 9, 1), date(2026, 9, 30))
    # 18 days left including today: 30000 / 18 = 1666.666..., rounded DOWN.
    assert str(status.allowance.daily) == "1666.66"
    assert str(status.unallocated) == "15000.00"


def test_no_budget_means_no_status(session, owner):
    assert budget_service.status(session, owner, today=TODAY) is None


def test_one_budget_per_user(session, owner, tree):
    monthly(session, owner, tree)
    with pytest.raises(ConflictException):
        monthly(session, owner, tree)


# ------------------------------------------------------------- what is spent


def test_spending_comes_from_expense_splits_and_rolls_up_to_the_parent(session, owner, tree):
    expense(session, owner, tree, "3500.00", "2026-09-10", splits=[
        {"category_id": tree.groceries, "amount": "2800.00"},
        {"category_id": tree.transport, "amount": "700.00"},
    ])
    monthly(session, owner, tree)
    status = budget_service.status(session, owner, today=TODAY)

    assert str(status.allowance.spent) == "3500.00"
    by_category = {c.category_id: (str(c.spent), str(c.remaining)) for c in status.categories}
    assert by_category == {tree.food: ("2800.00", "7200.00"), tree.transport: ("700.00", "4300.00")}


@pytest.mark.security
def test_income_and_transfers_are_never_spending(session, owner, tree):
    monthly(session, owner, tree)
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "42000.00", "account_id": tree.bank,
        "category_id": tree.salary, "txn_date": "2026-09-05"})
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "5000.00", "account_id": tree.bank,
        "counter_account_id": tree.wallet, "txn_date": "2026-09-06"})
    assert budget_service.status(session, owner, today=TODAY).allowance.spent == Decimal("0")


# ------------------------------------------------------------ changing it


def test_a_mid_period_change_applies_now_and_never_rewrites_a_finished_period(session, owner, tree):
    monthly(session, owner, tree)
    budget = budget_service.get_budget(session, owner, today=TODAY)
    budget_service.update_budget(session, owner, budget.id, {"amount": "40000.00"}, today=date(2026, 10, 5))

    october = budget_service.status(session, owner, today=date(2026, 10, 5))
    september = budget_service.status(session, owner, today=date(2026, 10, 5), on=date(2026, 9, 15))
    assert str(october.allowance.budget) == "40000.00"
    assert str(september.allowance.budget) == "30000.00"
    assert september.is_current is False


def test_a_payday_budget_across_the_year_boundary(session, owner, tree):
    monthly(session, owner, tree, month_start_day=25, today=date(2026, 12, 30))
    status = budget_service.status(session, owner, today=date(2027, 1, 10))
    assert (status.period.start, status.period.end) == (date(2026, 12, 25), date(2027, 1, 24))
    assert status.next_period.start == date(2027, 1, 25)


def test_allocations_are_replaced_exactly(session, owner, tree):
    monthly(session, owner, tree)
    budget = budget_service.get_budget(session, owner, today=TODAY)
    updated = budget_service.update_budget(session, owner, budget.id, {
        "allocations": [{"category_id": tree.food, "amount": "12000.00"}],
    }, today=TODAY)
    assert [(a.category_id, str(a.amount)) for a in updated.allocations] == [(tree.food, "12000.00")]


def test_only_spending_categories_can_be_allocated(session, owner, tree):
    with pytest.raises(BusinessRuleException):
        monthly(session, owner, tree, allocations=[{"category_id": tree.salary, "amount": "1.00"}])


def test_a_category_cannot_be_allocated_twice(session, owner, tree):
    with pytest.raises(ValidationException):
        monthly(session, owner, tree, allocations=[{"category_id": tree.food, "amount": "1.00"},
                                                   {"category_id": tree.food, "amount": "2.00"}])


# ---------------------------------------------------------------- carry-over


def weekly(session, owner, tree):
    return budget_service.create_budget(session, owner, {
        "period": "weekly", "week_start_day": 1, "amount": "10000.00"}, today=date(2026, 9, 7))


def test_carry_over_is_off_by_default_and_symmetric_when_on(session, owner, tree):
    weekly(session, owner, tree)
    expense(session, owner, tree, "7000.00", "2026-09-08")
    next_week = date(2026, 9, 15)

    assert str(budget_service.status(session, owner, today=next_week).allowance.available) == "10000.00"

    preferences_service.update_preferences(session, owner, {"carry_over": True})
    assert str(budget_service.status(session, owner, today=next_week).allowance.available) == "13000.00"


def test_changing_the_period_structure_restarts_carry_over(session, owner, tree):
    """
    The period the change lands in starts the new chain with nothing carried -
    the old weekly surplus does not cross into the new monthly rhythm - and
    the chain then runs on from there as normal.
    """
    budget = weekly(session, owner, tree)  # 10,000 a week from Mon 7 Sep
    expense(session, owner, tree, "2000.00", "2026-09-08")
    preferences_service.update_preferences(session, owner, {"carry_over": True})
    before = budget_service.status(session, owner, today=date(2026, 9, 15))
    assert str(before.allowance.carried_in) == "8000.00"  # week one's surplus, while still weekly

    budget_service.update_budget(session, owner, budget.id, {"period": "monthly", "month_start_day": 1},
                                 today=date(2026, 9, 20))
    september = budget_service.status(session, owner, today=date(2026, 9, 20))
    assert september.allowance.carried_in == Decimal("0")

    october = budget_service.status(session, owner, today=date(2026, 10, 2))
    assert str(october.allowance.carried_in) == "8000.00"  # September under the new rhythm: 10,000 - 2,000


# -------------------------------------------------------------------- alerts


def test_alerts_come_with_the_current_period_only(session, owner, tree):
    monthly(session, owner, tree)
    expense(session, owner, tree, "6000.00", "2026-09-02", category=tree.transport)
    current = budget_service.status(session, owner, today=TODAY)
    assert "category_over" in [a.kind for a in current.alerts]

    past = budget_service.status(session, owner, today=date(2026, 10, 5), on=date(2026, 9, 15))
    assert past.alerts == []


# ----------------------------------------------------- category deletion (CAT-08)


def test_deleting_an_unused_category_drops_its_allocation(session, owner, tree):
    monthly(session, owner, tree)
    category_service.delete_category(session, owner, tree.transport)
    allocations = budget_service.get_budget(session, owner, today=TODAY).allocations
    assert [a.category_id for a in allocations] == [tree.food]


def test_reassigning_a_category_folds_its_allocation_into_the_target(session, owner, tree):
    monthly(session, owner, tree)
    expense(session, owner, tree, "100.00", "2026-09-02", category=tree.transport)
    category_service.delete_category(session, owner, tree.transport, reassign_to=tree.food)
    allocations = {a.category_id: str(a.amount) for a in budget_service.get_budget(session, owner).allocations}
    assert allocations == {tree.food: "15000.00"}


# ---------------------------------------------------------------- the API


def api_setup(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "50000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    return wallet, food


def test_budget_status_needs_an_unlocked_session(api):
    api_setup(api)
    api.post("/auth/lock")
    response = api.get("/budgets/current")
    assert (response.status_code, response.json()["code"]) == (401, "SESSION_LOCKED")


def test_the_home_payload_through_the_api(api):
    wallet, food = api_setup(api)
    assert api.get("/budgets/current?today=2026-09-13").json() == {"status": None}

    created = api.post("/budgets?today=2026-09-13", {"period": "monthly", "amount": "30000.00",
                                                     "allocations": [{"category_id": food, "amount": "9000.00"}]})
    assert created.status_code == 201, created.text

    body = api.get("/budgets/current?today=2026-09-13").json()["status"]
    assert body["allowance"]["daily"] == "1666.66"
    assert body["period"] == {"start": "2026-09-01", "end": "2026-09-30", "days": 30}
    assert body["categories"][0]["used_ratio"] == "0.0000"


def test_a_transaction_answers_with_the_new_budget_status(api):
    """The ring animates on the POST response - no second request."""
    wallet, food = api_setup(api)
    api.post("/budgets?today=2026-09-13", {"period": "monthly", "amount": "30000.00"})
    response = api.post("/transactions?today=2026-09-13", {
        "type": "expense", "amount": "1234.56", "account_id": wallet,
        "category_id": food, "txn_date": "2026-09-13"})
    assert response.status_code == 201, response.text
    allowance = response.json()["budget_status"]["allowance"]
    assert (allowance["spent_today"], allowance["left_today"]) == ("1234.56", "432.10")


def test_carry_over_is_a_setting(api):
    api_setup(api)
    assert api.get("/settings/preferences").json()["carry_over"] is False
    response = api.patch("/settings/preferences", {"carry_over": True})
    assert response.status_code == 200 and response.json()["carry_over"] is True
    assert api.get("/settings/preferences").json()["carry_over"] is True


def test_editing_a_budget_through_the_api(api):
    wallet, food = api_setup(api)
    budget_id = api.post("/budgets?today=2026-09-13", {"period": "monthly", "amount": "30000.00"}).json()["id"]
    response = api.patch(f"/budgets/{budget_id}?today=2026-09-13", {"amount": "36000.00",
                                                                   "allocations": [{"category_id": food, "amount": "1.00"}]})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "36000.00"
    progress = api.get(f"/budgets/{budget_id}/progress?today=2026-09-13").json()
    assert progress["unallocated"] == "35999.00"
