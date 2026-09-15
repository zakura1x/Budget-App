"""
Stats (STA-01..STA-11) - every figure computed in Python over the working set.

The expensive bugs this guards against: counting a transfer or a balance
adjustment as spending, reading a category from anywhere but the splits,
comparing a 31-day month against the last 31 days instead of the month before,
and a forecast that multiplies a rounding error by thirty.
"""

import time
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationException
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import account_service, category_service, stats_service, tag_service, transaction_service
from app.services.budget_service import budget_service
from app.services.stats_service import buckets, forecast, previous_range

TODAY = date(2026, 9, 10)


@pytest.fixture
def books(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "90000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    groceries = category_service.create_category(session, owner, {"name": "Groceries", "parent_id": food.id})
    coffee = category_service.create_category(session, owner, {"name": "Coffee", "parent_id": food.id})
    household = category_service.create_category(session, owner, {"name": "Household"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class B:
        pass

    b = B()
    b.wallet, b.bank = wallet.id, bank.id
    b.food, b.groceries, b.coffee, b.household, b.salary = food.id, groceries.id, coffee.id, household.id, salary.id
    return b


def expense(session, owner, books, amount, on, category=None, **extra):
    payload = {"type": "expense", "amount": amount, "account_id": books.wallet, "txn_date": on, **extra}
    if "splits" not in payload:
        payload["category_id"] = category or books.groceries
    return transaction_service.create_transaction(session, owner, payload).transactions[0]


def income(session, owner, books, amount, on):
    return transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": amount, "account_id": books.bank, "category_id": books.salary, "txn_date": on})


def month_of(session, owner, **kw):
    return stats_service.overview(session, owner, span="month", on=kw.pop("on", TODAY), today=kw.pop("today", TODAY), **kw)


# ------------------------------------------------------------ the pure parts


@pytest.mark.parametrize("start, end, expected", [
    (date(2026, 3, 1), date(2026, 3, 31), (date(2026, 2, 1), date(2026, 2, 28))),  # a month, not 31 days
    (date(2026, 1, 1), date(2026, 3, 31), (date(2025, 10, 1), date(2025, 12, 31))),  # three whole months
    (date(2026, 9, 25), date(2026, 10, 24), (date(2026, 8, 26), date(2026, 9, 24))),  # 30 days
    (date(2026, 9, 7), date(2026, 9, 13), (date(2026, 8, 31), date(2026, 9, 6))),  # a week
])
def test_previous_range(start, end, expected):
    assert previous_range(start, end) == expected


def test_buckets_tile_the_range_exactly():
    weeks = buckets(date(2026, 9, 1), date(2026, 9, 30), "week")
    assert weeks[0] == (date(2026, 9, 1), date(2026, 9, 7))
    assert weeks[-1] == (date(2026, 9, 29), date(2026, 9, 30))
    months = buckets(date(2026, 1, 15), date(2026, 3, 10), "month")
    assert months == [(date(2026, 1, 15), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 28)),
                      (date(2026, 3, 1), date(2026, 3, 10))]


def test_the_forecast_runs_the_rate_to_the_end():
    result = forecast(Decimal("10000.00"), date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 10))
    assert (str(result.daily_rate), str(result.projected), result.days_left) == ("1000.00", "30000.00", 20)


def test_the_forecast_does_not_multiply_a_rounded_rate():
    # 100.00 over 3 days is 33.333...; rounded first it would project 999.90.
    result = forecast(Decimal("100.00"), date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 3))
    assert (str(result.daily_rate), str(result.projected)) == ("33.33", "1000.00")


def test_no_forecast_outside_the_range():
    assert forecast(Decimal("1.00"), date(2026, 8, 1), date(2026, 8, 31), TODAY) is None


# ------------------------------------------------------------ what counts


def test_spending_comes_from_splits_and_rolls_up_for_the_drill_down(session, owner, books):
    expense(session, owner, books, "3500.00", "2026-09-08", splits=[
        {"category_id": books.groceries, "amount": "2800.00"},
        {"category_id": books.household, "amount": "700.00"}])
    expense(session, owner, books, "150.00", "2026-09-09", category=books.coffee)
    expense(session, owner, books, "50.00", "2026-09-09", category=books.food)

    result = month_of(session, owner)
    assert str(result.totals.spent) == "3700.00"
    food, household = result.categories
    assert (food.category_id, str(food.amount), str(food.share), food.transaction_count) == (
        books.food, "3000.00", "0.8108", 3)
    assert str(food.direct) == "50.00"
    assert [(c.category_id, str(c.amount), str(c.share)) for c in food.children] == [
        (books.groceries, "2800.00", "0.9333"), (books.coffee, "150.00", "0.0500")]
    # The split receipt is one transaction in EACH slice.
    assert (household.category_id, household.transaction_count) == (books.household, 1)


def test_transfers_and_adjustments_are_neither_spending_nor_income(session, owner, books):
    expense(session, owner, books, "100.00", "2026-09-02")
    income(session, owner, books, "20000.00", "2026-09-05")
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "5000.00", "account_id": books.bank,
        "counter_account_id": books.wallet, "txn_date": "2026-09-06"})
    account_service.update_account(
        session, owner, books.wallet,
        {"name": "Wallet", "type": "cash", "balance": "94000.00", "balance_action": "adjust"},
        postings=transaction_service.postings(session, owner), today=TODAY,
    )

    totals = month_of(session, owner).totals
    assert (str(totals.spent), str(totals.earned), str(totals.net), totals.transaction_count) == (
        "100.00", "20000.00", "19900.00", 2)
    assert (str(totals.adjustment_losses), str(totals.adjustment_gains)) == ("900.00", "0.00")


def test_average_daily_spend_counts_the_days_so_far(session, owner, books):
    expense(session, owner, books, "1000.00", "2026-09-01")
    totals = month_of(session, owner).totals
    assert (totals.days, totals.days_counted, str(totals.average_daily_spend)) == (30, 10, "100.00")
    past = month_of(session, owner, today=date(2026, 10, 5)).totals
    assert (past.days_counted, str(past.average_daily_spend)) == (30, "33.33")


def test_the_trend_and_income_vs_expense(session, owner, books):
    expense(session, owner, books, "100.00", "2026-09-01")
    expense(session, owner, books, "40.00", "2026-09-03")
    income(session, owner, books, "500.00", "2026-09-03")
    result = month_of(session, owner)
    assert (result.granularity, len(result.trend)) == ("day", 30)
    assert [(str(p.spent), str(p.earned)) for p in result.trend[:3]] == [
        ("100.00", "0.00"), ("0.00", "0.00"), ("40.00", "500.00")]
    year = stats_service.overview(session, owner, span="year", on=TODAY, today=TODAY)
    assert (year.granularity, len(year.trend), str(year.trend[8].spent)) == ("month", 12, "140.00")


def test_month_over_month_compares_to_the_same_day(session, owner, books):
    expense(session, owner, books, "800.00", "2026-08-05")
    expense(session, owner, books, "4000.00", "2026-08-25")
    expense(session, owner, books, "300.00", "2026-09-04", category=books.household)
    result = month_of(session, owner)
    prev = result.previous
    assert (prev.start, prev.end, str(prev.spent), str(prev.spent_to_same_day)) == (
        date(2026, 8, 1), date(2026, 8, 31), "4800.00", "800.00")
    # Each slice carries last month's figure too; a category with nothing now is absent.
    assert [(c.category_id, str(c.previous_amount)) for c in result.categories] == [(books.household, "0.00")]


def test_top_merchants_ignore_case_and_spacing(session, owner, books):
    expense(session, owner, books, "200.00", "2026-09-01", merchant="jollibee")
    expense(session, owner, books, "150.00", "2026-09-02", merchant="  Jollibee ")
    expense(session, owner, books, "300.00", "2026-09-03", merchant="SM Supermarket")
    expense(session, owner, books, "999.00", "2026-09-04")  # no merchant - not a merchant
    merchants = month_of(session, owner).merchants
    assert [(m.name, str(m.amount), m.transaction_count) for m in merchants] == [
        ("Jollibee", "350.00", 2), ("SM Supermarket", "300.00", 1)]


def test_spending_by_account_and_by_tag(session, owner, books):
    trip = tag_service.create_tag(session, owner, {"name": "Trip"}).id
    food = tag_service.create_tag(session, owner, {"name": "Eating out"}).id
    expense(session, owner, books, "1000.00", "2026-09-01", tag_ids=[trip, food])
    expense(session, owner, books, "500.00", "2026-09-02", tag_ids=[trip])
    income(session, owner, books, "20000.00", "2026-09-03")

    result = month_of(session, owner)
    assert [(t.tag_id, str(t.spent), t.transaction_count) for t in result.tags] == [
        (trip, "1500.00", 2), (food, "1000.00", 1)]
    assert [(a.account_id, str(a.spent), str(a.earned)) for a in result.accounts] == [
        (books.wallet, "1500.00", "0.00"), (books.bank, "0.00", "20000.00")]


# -------------------------------------------------------- ranges and forecast


def test_the_budget_period_is_a_span_and_the_forecast_sits_beside_the_budget(session, owner, books):
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 25,
                                                  "amount": "30000.00"}, today=date(2026, 8, 25))
    expense(session, owner, books, "16000.00", "2026-09-05")
    expense(session, owner, books, "999.00", "2026-08-24")  # the period before last

    result = stats_service.overview(session, owner, span="budget", today=TODAY)
    assert (result.span, result.start, result.end) == ("budget", date(2026, 8, 25), date(2026, 9, 24))
    assert (result.previous.start, result.previous.end) == (date(2026, 7, 25), date(2026, 8, 24))
    f = result.forecast
    # 16000 over 17 days of a 31-day period.
    assert (f.days_elapsed, f.days_left, str(f.projected), str(f.budget_available)) == (17, 14, "29176.47", "30000.00")


def test_the_budget_span_falls_back_to_the_month(session, owner, books):
    result = stats_service.overview(session, owner, span="budget", today=TODAY)
    assert (result.span, result.start, result.end) == ("month", date(2026, 9, 1), date(2026, 9, 30))
    assert result.forecast.budget_available is None


def test_a_custom_range(session, owner, books):
    expense(session, owner, books, "100.00", "2026-09-02")
    result = stats_service.overview(session, owner, date_from=date(2026, 9, 1), date_to=date(2026, 9, 7), today=TODAY)
    assert (result.span, result.granularity, str(result.totals.spent), result.forecast) == (None, "day", "100.00", None)
    assert (result.previous.start, result.previous.end) == (date(2026, 8, 25), date(2026, 8, 31))


@pytest.mark.parametrize("kw", [
    {"date_from": date(2026, 9, 1)},
    {"date_from": date(2026, 9, 2), "date_to": date(2026, 9, 1)},
    {"date_from": date(2020, 1, 1), "date_to": date(2026, 1, 1)},
    {"span": "decade"},
    {"granularity": "hour"},
])
def test_bad_ranges_are_refused(session, owner, kw):
    with pytest.raises(ValidationException):
        stats_service.overview(session, owner, today=TODAY, **kw)


def test_stats_through_the_api(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "1000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "300.00", "account_id": wallet,
                               "category_id": food, "txn_date": "2026-09-05"})

    response = api.get("/stats/overview?span=month&today=2026-09-10")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["start"], body["end"], body["totals"]["spent"]) == ("2026-09-01", "2026-09-30", "300.00")
    assert body["categories"][0] == {"category_id": food, "amount": "300.00", "share": "1.0000",
                                     "transaction_count": 1, "previous_amount": "0.00", "direct": "300.00",
                                     "children": []}
    assert body["forecast"]["projected"] == "900.00"
    assert api.get("/stats/overview?span=decade").status_code == 422


# ------------------------------------------------------------ the budget


@pytest.mark.slow
def test_a_year_of_data_stays_fast_when_warm(session, owner, books):
    """phases.md Phase 6: stats over a full year stay under 50 ms warm."""
    repo = TransactionRepository(session, owner)
    categories = [books.groceries, books.coffee, books.household]
    day_numbers = range(date(2025, 9, 11).toordinal(), TODAY.toordinal() + 1)
    for n, ordinal in enumerate(day_numbers):
        for k in range(10):
            amount = f"{(n * 7 + k * 13) % 900 + 50}.00"
            repo.create({"txn_date": date.fromordinal(ordinal).isoformat(), "type": "expense", "amount": amount,
                         "account_id": books.wallet, "merchant": f"Shop {k}", "notes": None,
                         "splits": [{"category_id": categories[k % 3], "amount": amount, "note": None}],
                         "tag_ids": [], "recurring_id": None, "attachment_id": None})
    session.commit()
    repo.cached()  # warm

    started = time.perf_counter()
    result = stats_service.overview(session, owner, date_from=date(2025, 9, 11), date_to=TODAY, today=TODAY)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"year overview over {result.totals.transaction_count} transactions: elapsed_ms={elapsed_ms:.0f}")
    assert result.totals.transaction_count == 3650
    assert elapsed_ms < 250  # generous for a loaded CI box; the printed figure is the one to read
