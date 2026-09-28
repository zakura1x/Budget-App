"""
TXN-24 - merchant memory: what the add sheet suggests, and the category it
pre-selects. A wrong suggestion files the next purchase in the wrong place
without anyone noticing, so the rules are pinned here.
"""

import pytest

from app.services import account_service, category_service, transaction_service


@pytest.fixture
def books(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "5000.00"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    snacks = category_service.create_category(session, owner, {"name": "Snacks", "parent_id": food.id})
    household = category_service.create_category(session, owner, {"name": "Household"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})
    cashback = category_service.create_category(session, owner, {"name": "Cashback", "kind": "income"})

    class B:
        pass

    b = B()
    b.wallet, b.food, b.snacks, b.household = wallet.id, food.id, snacks.id, household.id
    b.salary, b.cashback = salary.id, cashback.id
    return b


def entry(session, owner, books, merchant, on="2026-09-10", category=None, kind="expense", **extra):
    payload = {"type": kind, "amount": "100.00", "account_id": books.wallet, "txn_date": on,
               "merchant": merchant, **extra}
    if "splits" not in extra:
        payload["category_id"] = category or (books.salary if kind == "income" else books.food)
    return transaction_service.create_transaction(session, owner, payload).transactions[0]


def by_name(session, owner):
    return {(m.type, m.name): m for m in transaction_service.merchants(session, owner)}


def test_most_used_first_with_the_count(session, owner, books):
    entry(session, owner, books, "Jollibee")
    entry(session, owner, books, "7-Eleven")
    entry(session, owner, books, "7-Eleven", on="2026-09-11")
    names = [m.name for m in transaction_service.merchants(session, owner)]
    assert names == ["7-Eleven", "Jollibee"]
    assert by_name(session, owner)[("expense", "7-Eleven")].count == 2


def test_case_and_spacing_do_not_make_two_shops(session, owner, books):
    entry(session, owner, books, "jollibee ", on="2026-09-01")
    entry(session, owner, books, "Jollibee", on="2026-09-02")
    entry(session, owner, books, "JOLLIBEE  ", on="2026-09-03")
    [only] = transaction_service.merchants(session, owner)
    assert (only.name, only.count) == ("JOLLIBEE", 3)  # the latest spelling


def test_the_latest_entry_decides_the_category(session, owner, books):
    """Moved from Food to Household last week: Household now, however often it was Food before."""
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        entry(session, owner, books, "Watsons", on=day, category=books.food)
    entry(session, owner, books, "Watsons", on="2026-09-10", category=books.household)
    assert by_name(session, owner)[("expense", "Watsons")].category_id == books.household


def test_a_sub_category_is_suggested_as_itself(session, owner, books):
    entry(session, owner, books, "Potato Corner", category=books.snacks)
    assert by_name(session, owner)[("expense", "Potato Corner")].category_id == books.snacks


def test_a_split_entry_suggests_the_merchant_but_no_category(session, owner, books):
    entry(session, owner, books, "SM", splits=[{"category_id": books.food, "amount": "60.00"},
                                               {"category_id": books.household, "amount": "40.00"}])
    assert by_name(session, owner)[("expense", "SM")].category_id is None


def test_an_archived_category_is_never_suggested(session, owner, books):
    entry(session, owner, books, "Watsons", category=books.household)
    category_service.update_category(session, owner, books.household, {"name": "Household", "archived": True})
    assert by_name(session, owner)[("expense", "Watsons")].category_id is None


def test_expense_and_income_are_kept_apart(session, owner, books):
    entry(session, owner, books, "Acme", category=books.food)
    entry(session, owner, books, "Acme", kind="income")
    found = by_name(session, owner)
    assert found[("expense", "Acme")].category_id == books.food
    assert found[("income", "Acme")].category_id == books.salary


def test_a_cashback_credit_is_not_a_merchant_of_its_own(session, owner, books):
    """It borrows its purchase's merchant; suggesting it as an income would file purchases there."""
    entry(session, owner, books, "SM", cashback={"amount": "5.00", "category_id": books.cashback})
    assert set(by_name(session, owner)) == {("expense", "SM")}


def test_entries_without_a_merchant_and_transfers_are_ignored(session, owner, books):
    entry(session, owner, books, None)
    entry(session, owner, books, "   ")
    assert transaction_service.merchants(session, owner) == []
