"""
The calendar (CAL-01..CAL-05): per-day totals under the ledger's rules, and a
heatmap measured against the budget rather than against the month's biggest day.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationException
from app.services import account_service, calendar_service, category_service, transaction_service
from app.services.budget_service import budget_service
from app.services.calendar_service import heat_level


@pytest.fixture
def books(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "50000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class B:
        pass

    b = B()
    b.wallet, b.bank, b.food, b.salary = wallet.id, bank.id, food.id, salary.id
    return b


def add(session, owner, books, kind, amount, on, **extra):
    payload = {"type": kind, "amount": amount, "account_id": books.wallet, "txn_date": on, **extra}
    if kind == "expense":
        payload.setdefault("category_id", books.food)
    if kind == "income":
        payload.setdefault("category_id", books.salary)
    return transaction_service.create_transaction(session, owner, payload)


def day(month, number):
    return month.days[number - 1]


@pytest.mark.parametrize("spent, reference, level", [
    ("0.00", "100.00", 0),
    ("50.00", "100.00", 1),
    ("50.01", "100.00", 2),
    ("100.00", "100.00", 2),
    ("200.00", "100.00", 3),
    ("200.01", "100.00", 4),
    ("10.00", None, 2),
])
def test_heat_levels(spent, reference, level):
    assert heat_level(Decimal(spent), Decimal(reference) if reference else None) == level


def test_a_month_has_every_day_and_the_ledgers_totals(session, owner, books):
    add(session, owner, books, "expense", "300.00", "2026-09-05")
    add(session, owner, books, "expense", "200.00", "2026-09-05")
    add(session, owner, books, "income", "20000.00", "2026-09-15")
    add(session, owner, books, "transfer", "1000.00", "2026-09-15", counter_account_id=books.bank)

    month = calendar_service.month(session, owner, 2026, 9)
    assert (month.start, month.end, len(month.days)) == (date(2026, 9, 1), date(2026, 9, 30), 30)
    assert (str(month.spent), str(month.earned)) == ("500.00", "20000.00")
    assert (str(day(month, 5).spent), day(month, 5).count) == ("500.00", 2)
    # A transfer is neither spending nor earning, and shows once.
    assert (str(day(month, 15).spent), str(day(month, 15).earned), day(month, 15).count) == ("0.00", "20000.00", 2)


def test_a_balance_adjustment_is_not_spending(session, owner, books):
    account_service.update_account(
        session, owner, books.wallet,
        {"name": "Wallet", "type": "cash", "balance": "49000.00", "balance_action": "adjust"},
        postings=transaction_service.postings(session, owner), today=date(2026, 9, 10),
    )
    month = calendar_service.month(session, owner, 2026, 9)
    assert (str(month.spent), day(month, 10).level, day(month, 10).count) == ("0.00", 0, 1)


def test_without_a_budget_days_are_measured_against_a_typical_day(session, owner, books):
    for on, amount in [("2026-09-01", "100.00"), ("2026-09-02", "200.00"), ("2026-09-03", "900.00")]:
        add(session, owner, books, "expense", amount, on)
    month = calendar_service.month(session, owner, 2026, 9)
    assert (str(day(month, 1).reference), day(month, 1).reference_kind) == ("200.00", "typical")
    assert [day(month, n).level for n in (1, 2, 3, 4)] == [1, 2, 4, 0]


def test_with_a_budget_days_are_measured_against_the_budget_per_day(session, owner, books):
    budget_service.create_budget(session, owner, {"period": "monthly", "amount": "30000.00"},
                                 today=date(2026, 9, 1))
    add(session, owner, books, "expense", "1500.00", "2026-09-04")
    month = calendar_service.month(session, owner, 2026, 9)
    assert (str(day(month, 4).reference), day(month, 4).reference_kind, day(month, 4).level) == ("1000.00", "budget", 3)


def test_a_month_outside_the_records_is_refused(session, owner):
    with pytest.raises(ValidationException):
        calendar_service.month(session, owner, 1999, 12)


def test_the_calendar_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "75.50", "account_id": wallet,
                               "category_id": food, "txn_date": "2026-02-14"})

    body = api.get("/calendar/2026/2").json()
    assert (len(body["days"]), body["spent"]) == (28, "75.50")
    assert body["days"][13] == {"on": "2026-02-14", "spent": "75.50", "earned": "0.00", "count": 1,
                                "level": 2, "reference": "75.50", "reference_kind": "typical"}
    assert api.get("/calendar/2026/13").status_code == 422
