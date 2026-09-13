"""
Transactions - the write path, the split invariant, transfers, and every read
over the working set (TXN-01..TXN-21).

The tests that would catch the expensive bugs:

  * the split invariant tested DIRECTLY (TXN-20), including the classic
    three-way split of 100.00 that leaves a centavo on the floor
  * every stored transaction has splits and no top-level category_id (TXN-16)
  * a transfer never counts as spending or income (TXN-04)
  * a rolled-back write never reaches the cache, and a lock empties it
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.crypto.working_set import get_working_set
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.db.models import Transaction
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import account_service, category_service, transaction_service
from app.services.transaction_service import validate_splits


@pytest.fixture
def ledger(session, owner):
    """A wallet, a debit account, a card, and a small category tree."""
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "1000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit",
                                                           "opening_balance": "20000.00"})
    card = account_service.create_account(session, owner, {"name": "Card", "type": "credit",
                                                           "statement_closing_day": 20, "payment_due_day": 5})
    food = category_service.create_category(session, owner, {"name": "Food"})
    groceries = category_service.create_category(session, owner, {"name": "Groceries", "parent_id": food.id})
    household = category_service.create_category(session, owner, {"name": "Household"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class L:
        pass

    ids = L()
    ids.wallet, ids.bank, ids.card = wallet.id, bank.id, card.id
    ids.food, ids.groceries, ids.household, ids.salary = food.id, groceries.id, household.id, salary.id
    return ids


def spend(session, owner, ledger, amount="150.00", on="2026-09-12", **extra):
    payload = {"type": "expense", "amount": amount, "account_id": ledger.wallet,
               "category_id": ledger.groceries, "txn_date": on, **extra}
    return transaction_service.create_transaction(session, owner, payload)


def stored(session, owner):
    return TransactionRepository(session, owner).list()


# ----------------------------------------------------- the invariant, directly


def test_splits_that_add_up_exactly_pass():
    cleaned = validate_splits(Decimal("0.30"), [{"category_id": 1, "amount": "0.10"},
                                                {"category_id": 2, "amount": "0.20"}])
    assert [s["amount"] for s in cleaned] == ["0.10", "0.20"]


def test_a_three_way_split_that_drops_a_centavo_is_refused():
    """100.00 / 3 = 33.33 x 3 = 99.99. Rounding would silently lose 0.01 forever."""
    with pytest.raises(BusinessRuleException) as raised:
        validate_splits(Decimal("100.00"), [{"category_id": 1, "amount": "33.33"}] * 3)
    assert raised.value.extra["remaining"] == "0.01"


def test_splits_over_the_amount_are_refused():
    with pytest.raises(BusinessRuleException) as raised:
        validate_splits(Decimal("10.00"), [{"category_id": 1, "amount": "10.01"}])
    assert raised.value.extra["remaining"] == "-0.01"


def test_splits_are_never_empty():
    with pytest.raises(ValidationException):
        validate_splits(Decimal("10.00"), [])


def test_a_float_split_amount_is_refused():
    with pytest.raises(ValidationException):
        validate_splits(Decimal("10.00"), [{"category_id": 1, "amount": 10.0}])


# ------------------------------------------------------------- the shape


def test_every_stored_transaction_carries_splits_and_no_top_level_category(session, owner, ledger):
    """TXN-16: category_id is input shorthand only; stored, it is one split."""
    spend(session, owner, ledger)
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "3500.00", "account_id": ledger.wallet, "txn_date": "2026-09-12",
        "splits": [{"category_id": ledger.groceries, "amount": "2800.00", "note": "groceries"},
                   {"category_id": ledger.household, "amount": "700.00"}],
    })
    for record in stored(session, owner):
        assert "category_id" not in record.data
        assert record.data["splits"]
        assert sum(Decimal(s["amount"]) for s in record.data["splits"]) == Decimal(record.data["amount"])


def test_a_bad_split_writes_nothing(session, owner, ledger):
    with pytest.raises(BusinessRuleException):
        transaction_service.create_transaction(session, owner, {
            "type": "expense", "amount": "100.00", "account_id": ledger.wallet,
            "splits": [{"category_id": ledger.groceries, "amount": "33.33"}] * 3,
        })
    session.rollback()
    assert session.execute(select(func.count()).select_from(Transaction)).scalar_one() == 0


def test_an_expense_needs_an_expense_category(session, owner, ledger):
    with pytest.raises(BusinessRuleException):
        spend(session, owner, ledger, category_id=ledger.salary)


def test_amounts_must_be_positive(session, owner, ledger):
    with pytest.raises(ValidationException):
        spend(session, owner, ledger, amount="0.00")


def test_an_archived_account_takes_no_new_entries_but_old_ones_stay_editable(session, owner, ledger):
    existing = spend(session, owner, ledger).transactions[0]
    account_service.set_archived(session, owner, ledger.wallet, True)
    with pytest.raises(BusinessRuleException):
        spend(session, owner, ledger)
    edited = transaction_service.update_transaction(session, owner, existing.id, {
        "type": "expense", "amount": "175.00", "account_id": ledger.wallet,
        "category_id": ledger.groceries, "txn_date": "2026-09-12",
    })
    assert edited.transactions[0].amount == Decimal("175.00")


# ------------------------------------------------------------- balances


def test_an_expense_moves_the_balance_and_cash_on_hand_exactly(session, owner, ledger):
    result = spend(session, owner, ledger, amount="150.25")
    wallet = next(a for a in result.accounts if a.id == ledger.wallet)
    assert wallet.balance == Decimal("849.75")
    assert result.cash_on_hand.total == Decimal("20849.75")


def test_income_adds_to_the_balance(session, owner, ledger):
    result = transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "25000.00", "account_id": ledger.bank, "category_id": ledger.salary,
    })
    assert result.accounts[0].balance == Decimal("45000.00")


def test_a_card_purchase_lands_in_the_open_statement_period(session, owner, ledger):
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "999.00", "account_id": ledger.card,
        "category_id": ledger.groceries, "txn_date": "2026-09-12",
    })
    postings = transaction_service.postings(session, owner)
    card = account_service.get_account(session, owner, ledger.card, postings=postings, today=date(2026, 9, 13))
    assert card.credit.period_spend == Decimal("999.00")
    assert card.credit.owed == Decimal("999.00")


# ------------------------------------------------------------- transfers


def move(session, owner, ledger, amount="5000.00", **extra):
    payload = {"type": "transfer", "amount": amount, "account_id": ledger.bank,
               "counter_account_id": ledger.wallet, "txn_date": "2026-09-12", **extra}
    return transaction_service.create_transaction(session, owner, payload)


def test_a_transfer_is_a_linked_pair(session, owner, ledger):
    result = move(session, owner, ledger)
    out_leg, in_leg = result.transactions
    assert (out_leg.direction, in_leg.direction) == ("out", "in")
    assert out_leg.pair_id == in_leg.id and in_leg.pair_id == out_leg.id
    balances = {a.id: a.balance for a in result.accounts}
    assert balances == {ledger.bank: Decimal("15000.00"), ledger.wallet: Decimal("6000.00")}
    assert result.cash_on_hand.total == Decimal("21000.00")  # money moved, none spent


@pytest.mark.security
def test_a_transfer_is_never_spending_or_income(session, owner, ledger):
    """The Phase 4 verify item - and the reason its split has no category."""
    move(session, owner, ledger)
    spend(session, owner, ledger, amount="150.00")
    page = transaction_service.list_transactions(session, owner)
    day = page.days[0]
    assert (day.spent, day.earned) == (Decimal("150.00"), Decimal("0.00"))
    for record in stored(session, owner):
        if record.data["type"] == "transfer":
            assert [s["category_id"] for s in record.data["splits"]] == [None]


def test_the_ledger_shows_a_transfer_once_but_each_account_sees_its_leg(session, owner, ledger):
    move(session, owner, ledger)
    assert [v.direction for v in transaction_service.list_transactions(session, owner).items] == ["out"]
    wallet_view = transaction_service.list_transactions(session, owner, account_id=ledger.wallet).items
    assert [v.direction for v in wallet_view] == ["in"]


def test_a_transfer_to_the_same_account_is_refused(session, owner, ledger):
    with pytest.raises(BusinessRuleException):
        move(session, owner, ledger, counter_account_id=ledger.bank)


def test_editing_a_transfer_edits_both_legs(session, owner, ledger):
    out_leg, _ = move(session, owner, ledger).transactions
    result = transaction_service.update_transaction(session, owner, out_leg.id, {
        "type": "transfer", "amount": "1234.56", "account_id": ledger.bank,
        "counter_account_id": ledger.wallet, "txn_date": "2026-09-12",
    })
    assert [t.amount for t in result.transactions] == [Decimal("1234.56")] * 2


def test_deleting_either_leg_deletes_the_transfer(session, owner, ledger):
    _, in_leg = move(session, owner, ledger).transactions
    transaction_service.delete_transaction(session, owner, in_leg.id)
    assert stored(session, owner) == []


def test_a_transfer_cannot_change_type(session, owner, ledger):
    out_leg, _ = move(session, owner, ledger).transactions
    with pytest.raises(BusinessRuleException):
        transaction_service.update_transaction(session, owner, out_leg.id, {
            "type": "expense", "amount": "5000.00", "account_id": ledger.bank, "category_id": ledger.groceries,
        })


# ------------------------------------------------------------- reading


def test_newest_first_and_cursor_pages_cover_everything_once(session, owner, ledger):
    for day in range(1, 8):
        spend(session, owner, ledger, amount="1.00", on=f"2026-09-0{day}")
    seen, cursor = [], None
    while True:
        page = transaction_service.list_transactions(session, owner, limit=3, cursor=cursor)
        seen.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    dates = [v.txn_date.day for v in seen]
    assert dates == [7, 6, 5, 4, 3, 2, 1]
    assert len({v.id for v in seen}) == 7


def test_day_totals_cover_the_whole_day_even_across_pages(session, owner, ledger):
    for _ in range(3):
        spend(session, owner, ledger, amount="10.00", on="2026-09-12")
    page = transaction_service.list_transactions(session, owner, limit=1)
    assert len(page.items) == 1
    assert page.days[0].spent == Decimal("30.00")


def test_search_is_case_insensitive_across_merchant_notes_and_split_notes(session, owner, ledger):
    spend(session, owner, ledger, merchant="SM Supermarket")
    spend(session, owner, ledger, notes="weekly RUN")
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": "5.00", "account_id": ledger.wallet,
        "splits": [{"category_id": ledger.groceries, "amount": "5.00", "note": "Coffee beans"}],
    })
    search = lambda q: len(transaction_service.list_transactions(session, owner, q=q).items)  # noqa: E731
    assert (search("supermarket"), search("run"), search("BEANS"), search("nothing")) == (1, 1, 1, 0)


def test_filtering_by_a_parent_includes_its_sub_categories(session, owner, ledger):
    spend(session, owner, ledger, category_id=ledger.groceries)
    spend(session, owner, ledger, category_id=ledger.household)
    assert len(transaction_service.list_transactions(session, owner, category_id=ledger.food).items) == 1


def test_date_range_and_type_filters(session, owner, ledger):
    spend(session, owner, ledger, on="2026-08-31")
    spend(session, owner, ledger, on="2026-09-01")
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "1.00", "account_id": ledger.bank,
        "category_id": ledger.salary, "txn_date": "2026-09-02",
    })
    page = transaction_service.list_transactions(session, owner, date_from=date(2026, 9, 1), type="expense")
    assert [v.txn_date for v in page.items] == [date(2026, 9, 1)]


def test_repeat_last_clones_the_most_recently_entered_onto_today(session, owner, ledger):
    spend(session, owner, ledger, amount="99.00", on="2026-09-01", merchant="Coffee")
    spend(session, owner, ledger, amount="150.00", on="2026-08-01", merchant="Bakery")  # entered last
    result = transaction_service.repeat_last(session, owner, on=date(2026, 9, 13))
    copy = result.transactions[0]
    assert (copy.merchant, copy.amount, copy.txn_date) == ("Bakery", Decimal("150.00"), date(2026, 9, 13))


def test_repeat_last_with_nothing_to_repeat(session, owner, ledger):
    with pytest.raises(NotFoundException):
        transaction_service.repeat_last(session, owner)


# ---------------------------------------------------- the cache stays honest


@pytest.mark.security
def test_writes_reach_the_warm_cache_without_a_reload(session, owner, ledger, monkeypatch):
    transaction_service.warm(session, owner)
    calls = []
    original = TransactionRepository.list
    monkeypatch.setattr(TransactionRepository, "list", lambda self, **kw: calls.append(1) or original(self, **kw))

    first = spend(session, owner, ledger).transactions[0]
    transaction_service.update_transaction(session, owner, first.id, {
        "type": "expense", "amount": "200.00", "account_id": ledger.wallet, "category_id": ledger.groceries,
    })
    second = spend(session, owner, ledger).transactions[0]
    transaction_service.delete_transaction(session, owner, second.id)

    items = transaction_service.list_transactions(session, owner).items
    assert [(v.id, v.amount) for v in items] == [(first.id, Decimal("200.00"))]
    assert calls == []


@pytest.mark.security
def test_a_rolled_back_write_never_reaches_the_cache(session, owner, ledger):
    transaction_service.warm(session, owner)
    TransactionRepository(session, owner).create({"type": "expense", "amount": "1.00", "splits": []})
    session.rollback()
    assert not get_working_set().is_warm(owner.user_id, "transactions")
    assert transaction_service.list_transactions(session, owner).items == []


def test_category_reassignment_is_visible_in_the_cache_immediately(session, owner, ledger):
    spend(session, owner, ledger, category_id=ledger.household)
    transaction_service.warm(session, owner)
    category_service.delete_category(session, owner, ledger.household, reassign_to=ledger.groceries)
    view = transaction_service.list_transactions(session, owner).items[0]
    assert [s.category_id for s in view.splits] == [ledger.groceries]


# ---------------------------------------------------------------- the API


def setup_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1000.00"}).json()["id"]
    groceries = api.post("/categories", {"name": "Groceries"}).json()["id"]
    return wallet, groceries


def test_transactions_need_an_unlocked_session(api):
    setup_api(api)
    api.post("/auth/lock")
    response = api.get("/transactions")
    assert (response.status_code, response.json()["code"]) == (401, "SESSION_LOCKED")


def test_post_answers_with_the_new_balances_in_the_same_response(api):
    wallet, groceries = setup_api(api)
    response = api.post("/transactions", {"type": "expense", "amount": "150.25", "account_id": wallet,
                                          "category_id": groceries, "txn_date": "2026-09-12"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["transactions"][0]["splits"] == [{"category_id": groceries, "amount": "150.25", "note": None}]
    assert body["accounts"][0]["balance"] == "849.75"
    assert body["cash_on_hand"]["total"] == "849.75"


def test_account_balances_now_include_transactions(api):
    """Closes the Phase 3 gap: balances were opening balances until postings existed."""
    wallet, groceries = setup_api(api)
    api.post("/transactions", {"type": "expense", "amount": "200.00", "account_id": wallet, "category_id": groceries})
    listed = api.get("/accounts").json()
    assert listed["accounts"][0]["balance"] == "800.00"
    assert api.get(f"/accounts/{wallet}").json()["balance"] == "800.00"


def test_the_api_refuses_a_float_amount(api):
    wallet, groceries = setup_api(api)
    response = api.post("/transactions", {"type": "expense", "amount": 150.25, "account_id": wallet,
                                          "category_id": groceries})
    assert response.status_code == 422


def test_list_edit_delete_and_repeat_through_the_api(api):
    wallet, groceries = setup_api(api)
    created = api.post("/transactions", {"type": "expense", "amount": "10.00", "account_id": wallet,
                                         "category_id": groceries, "txn_date": "2026-09-12"}).json()
    txn_id = created["transactions"][0]["id"]

    edited = api.patch(f"/transactions/{txn_id}", {"type": "expense", "amount": "12.50", "account_id": wallet,
                                                   "category_id": groceries, "txn_date": "2026-09-12"})
    assert edited.status_code == 200 and edited.json()["accounts"][0]["balance"] == "987.50"

    repeated = api.post("/transactions/repeat-last", {"on": "2026-09-13"})
    assert repeated.status_code == 201 and repeated.json()["transactions"][0]["amount"] == "12.50"

    page = api.get("/transactions?limit=10").json()
    assert [t["txn_date"] for t in page["items"]] == ["2026-09-13", "2026-09-12"]

    assert api.delete(f"/transactions/{txn_id}").status_code == 200
    assert api.get("/transactions").json()["total_count"] == 1


@pytest.mark.security
def test_locking_empties_the_working_set(api):
    wallet, groceries = setup_api(api)
    api.post("/transactions", {"type": "expense", "amount": "10.00", "account_id": wallet, "category_id": groceries})
    api.get("/transactions")
    user_id = api.get("/auth/me").json()["user"]["id"]
    assert get_working_set().is_warm(user_id, "transactions")

    api.post("/auth/lock")
    assert not get_working_set().is_warm(user_id, "transactions")


@pytest.mark.security
def test_one_user_cannot_see_another_users_transactions(api):
    wallet, groceries = setup_api(api)
    api.post("/transactions", {"type": "expense", "amount": "10.00", "account_id": wallet, "category_id": groceries})
    api.post("/auth/logout")

    assert api.register(email="mara@example.com", name="Mara").status_code == 201
    assert api.get("/transactions").json()["items"] == []
    # And their ids are not reachable by guessing.
    assert api.get("/transactions/1").status_code == 404
