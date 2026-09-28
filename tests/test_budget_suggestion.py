"""
BUD-17 - the suggested budget, and its period-start reminder.

The pure rules are tested one by one (suggest.py), then the service over real
entries: that it counts exactly what the budget counts, rolls sub-categories
into their main, takes its floor from THE schedule, and never writes.
Decided by the user 2026-09-28: suggest only, the median, a rounding step
from Settings, and a reminder when the total drifts more than 15%.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import ValidationException
from app.core.utils.date_utils import BudgetPeriod
from app.db.repositories.budget_repository import BudgetRepository
from app.services import account_service, category_service, preferences_service, recurring_service
from app.services import transaction_service
from app.services.budget_service import budget_service
from app.services.budget_service.suggest import (
    median,
    reminder_due,
    reminder_window,
    round_up,
    suggest,
)

TODAY = date(2026, 9, 13)  # periods used: June, July, August 2026


# ---------------------------------------------------------- the pure rules


def test_median_ignores_the_one_big_month():
    assert median([D("4200.00"), D("3900.00"), D("25100.00")]) == D("4200.00")


def test_median_of_an_even_count_is_the_mean_of_the_middle_two():
    assert median([D("100.00"), D("200.00"), D("301.00"), D("401.00")]) == D("250.50")
    assert median([D("0.01"), D("0.02")]) == D("0.02")  # half a centavo rounds half up


def test_rounding_is_always_up():
    assert round_up(D("4201.00"), D("100")) == D("4300.00")
    assert round_up(D("4200.00"), D("100")) == D("4200.00")
    assert round_up(D("0.01"), D("1")) == D("1.00")
    assert round_up(D("0.00"), D("100")) == D("0.00")


def test_a_line_is_the_median_rounded_up_to_the_step():
    result = suggest({1: [D("4200.00"), D("3900.00"), D("5100.00")]}, periods=3, step=500)
    [line] = result.lines
    assert (line.median, line.average, line.suggested, line.reason) == (D("4200.00"), D("4400.00"), D("4500.00"), "median")


def test_scheduled_charges_are_the_floor():
    result = suggest({1: [D("500.00"), D("600.00"), D("700.00")]}, periods=3, scheduled={1: D("1499.00")})
    [line] = result.lines
    assert (line.suggested, line.reason) == (D("1500.00"), "scheduled")


def test_a_scheduled_category_with_no_history_still_gets_its_floor():
    result = suggest({}, periods=3, scheduled={7: D("549.00")})
    assert [(line.category_id, line.suggested) for line in result.lines] == [(7, D("600.00"))]


def test_an_occasional_category_joins_the_buffer():
    """Spent in 1 of 3 months: no line of its own, and the buffer is the median of what no line holds."""
    history = {1: [D("1000.00")] * 3, 2: [D("0.00"), D("0.00"), D("1500.00")], 3: [D("300.00"), D("0.00"), D("0.00")]}
    result = suggest(history, periods=3)
    assert [line.category_id for line in result.lines] == [1]
    assert [o.category_id for o in result.occasional] == [2, 3]
    # outside the lines, per month: 300, 0, 1500 -> median 300
    assert result.buffer == D("300.00")
    assert result.total == D("1300.00")


def test_a_budgeted_category_with_no_spending_is_kept():
    result = suggest({}, periods=3, current={4: D("2000.00")})
    [line] = result.lines
    assert (line.suggested, line.reason, line.current) == (D("2000.00"), "kept", D("2000.00"))


def test_one_period_is_that_periods_figure():
    [line] = suggest({1: [D("3210.00")]}, periods=1).lines
    assert (line.suggested, line.reason) == (D("3300.00"), "single")


def test_trim_takes_off_the_part_above_the_floor_only():
    result = suggest({1: [D("10000.00")] * 3}, periods=3, scheduled={1: D("4000.00")}, trim=10)
    # the floor stays; 10% off the 6,000 above it -> 9,400
    assert result.lines[0].suggested == D("9400.00")


def test_over_income_is_said_and_fit_scales_the_flexible_part_down():
    history = {1: [D("20000.00")] * 3, 2: [D("20000.00")] * 3}
    income = [D("30000.00")] * 3
    loose = suggest(history, periods=3, income=income, scheduled={2: D("10000.00")})
    assert (loose.total, loose.income, loose.over_income) == (D("40000.00"), D("30000.00"), True)

    fitted = suggest(history, periods=3, income=income, scheduled={2: D("10000.00")}, fit=True)
    assert fitted.fitted and not fitted.over_income and fitted.total <= D("30000.00")
    assert next(line for line in fitted.lines if line.category_id == 2).suggested >= D("10000.00")


def test_fit_cannot_go_below_the_scheduled_charges():
    fitted = suggest({1: [D("5000.00")] * 3}, periods=3, income=[D("1000.00")] * 3,
                     scheduled={1: D("2000.00")}, fit=True)
    assert fitted.cannot_fit and fitted.lines[0].suggested == D("2000.00")


def test_no_income_means_no_income_check():
    result = suggest({1: [D("5000.00")] * 3}, periods=3)
    assert (result.income, result.over_income) == (None, False)


def test_an_unknown_step_is_refused():
    with pytest.raises(ValueError):
        suggest({}, periods=3, step=7)


# ------------------------------------------------------------ the reminder


PERIOD = BudgetPeriod(date(2026, 10, 1), date(2026, 10, 31))


def window(**extra):
    base = {"today_index": 0, "kind": "monthly", "period": PERIOD, "dismissed_for": None, "enabled": True}
    return reminder_window(**{**base, **extra})


def test_the_reminder_shows_in_the_first_three_days_only():
    assert [window(today_index=i) for i in range(5)] == [True, True, True, False, False]


def test_the_reminder_respects_the_switch_and_a_dismissal():
    assert not window(enabled=False)
    assert not window(dismissed_for="2026-10-01")
    assert window(dismissed_for="2026-09-01")  # last period's dismissal does not hide this one


def test_a_weekly_budget_is_asked_once_a_month():
    assert window(kind="weekly", period=BudgetPeriod(date(2026, 10, 5), date(2026, 10, 11)))
    assert not window(kind="weekly", period=BudgetPeriod(date(2026, 10, 12), date(2026, 10, 18)))


def test_the_reminder_needs_more_than_fifteen_percent_either_way_and_three_periods():
    assert reminder_due(history=3, suggested=D("35500.00"), in_force=D("30000.00"))
    assert reminder_due(history=3, suggested=D("22000.00"), in_force=D("30000.00"))
    assert not reminder_due(history=3, suggested=D("34500.00"), in_force=D("30000.00"))  # exactly 15%
    assert not reminder_due(history=2, suggested=D("50000.00"), in_force=D("30000.00"))
    assert not reminder_due(history=3, suggested=D("50000.00"), in_force=None)


# ------------------------------------------------------ over real entries


@pytest.fixture
def tree(session, owner):
    wallet = account_service.create_account(session, owner, {"name": "Wallet", "type": "cash",
                                                             "opening_balance": "500000.00"})
    bank = account_service.create_account(session, owner, {"name": "BDO", "type": "debit"})
    food = category_service.create_category(session, owner, {"name": "Food"})
    groceries = category_service.create_category(session, owner, {"name": "Groceries", "parent_id": food.id})
    transport = category_service.create_category(session, owner, {"name": "Transport"})
    gifts = category_service.create_category(session, owner, {"name": "Gifts"})
    bills = category_service.create_category(session, owner, {"name": "Bills"})
    salary = category_service.create_category(session, owner, {"name": "Salary", "kind": "income"})

    class T:
        pass

    t = T()
    t.wallet, t.bank = wallet.id, bank.id
    t.food, t.groceries, t.transport, t.gifts, t.bills, t.salary = (
        food.id, groceries.id, transport.id, gifts.id, bills.id, salary.id)
    return t


def spend(session, owner, tree, amount, on, category):
    transaction_service.create_transaction(session, owner, {
        "type": "expense", "amount": amount, "account_id": tree.wallet, "txn_date": on, "category_id": category})


def three_months(session, owner, tree):
    """June to August: food (partly as groceries), transport, one gift, and salary."""
    for month, food, groceries, transport in (("06", "3000.00", "1000.00", "1500.00"),
                                              ("07", "2500.00", "1400.00", "1600.00"),
                                              ("08", "9000.00", "1000.00", "1700.00")):
        spend(session, owner, tree, food, f"2026-{month}-05", tree.food)
        spend(session, owner, tree, groceries, f"2026-{month}-12", tree.groceries)
        spend(session, owner, tree, transport, f"2026-{month}-20", tree.transport)
        transaction_service.create_transaction(session, owner, {
            "type": "income", "amount": "30000.00", "account_id": tree.bank, "txn_date": f"2026-{month}-15",
            "category_id": tree.salary})
    spend(session, owner, tree, "2000.00", "2026-07-25", tree.gifts)


def line(view, category_id):
    return next(line for line in view.suggestion.lines if line.category_id == category_id)


def test_nothing_to_suggest_without_a_finished_period(session, owner, tree):
    spend(session, owner, tree, "500.00", "2026-09-02", tree.food)
    view = budget_service.suggestion(session, owner, today=TODAY)
    assert (view.suggestion, view.periods) == (None, ())


def test_fewer_periods_than_asked_says_how_many(session, owner, tree):
    spend(session, owner, tree, "500.00", "2026-08-02", tree.food)
    view = budget_service.suggestion(session, owner, today=TODAY, periods=6)
    assert (view.asked, len(view.periods)) == (6, 1)


def test_sub_categories_roll_into_their_main_and_the_median_decides(session, owner, tree):
    three_months(session, owner, tree)
    view = budget_service.suggestion(session, owner, today=TODAY)
    assert [p.start for p in view.periods] == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    food = line(view, tree.food)
    assert food.history == (D("4000.00"), D("3900.00"), D("10000.00"))
    assert (food.median, food.suggested) == (D("4000.00"), D("4000.00"))  # August's feast does not set it
    assert all(x.category_id != tree.groceries for x in view.suggestion.lines)
    assert line(view, tree.transport).suggested == D("1600.00")
    assert [o.category_id for o in view.suggestion.occasional] == [tree.gifts]
    assert view.suggestion.income == D("30000.00")
    assert view.suggestion.total == D("5600.00")  # 4,000 + 1,600 + a buffer of 0 (one gift in three)


def test_transfers_and_adjustments_are_not_spending(session, owner, tree):
    three_months(session, owner, tree)
    before = budget_service.suggestion(session, owner, today=TODAY).suggestion.total
    transaction_service.create_transaction(session, owner, {
        "type": "transfer", "amount": "9999.00", "account_id": tree.wallet, "counter_account_id": tree.bank,
        "txn_date": "2026-08-10"})
    assert budget_service.suggestion(session, owner, today=TODAY).suggestion.total == before


def test_the_floor_comes_from_the_schedule(session, owner, tree):
    three_months(session, owner, tree)
    recurring_service.create_rule(session, owner, {
        "kind": "standard", "type": "expense", "name": "Internet", "account_id": tree.wallet,
        "category_id": tree.bills, "frequency": "monthly", "amount": "1699.00", "start": "2026-09-20"}, today=TODAY)
    bills = line(budget_service.suggestion(session, owner, today=TODAY), tree.bills)
    assert (bills.scheduled, bills.suggested, bills.reason) == (D("1699.00"), D("1700.00"), "scheduled")


def test_a_sub_category_budgeted_directly_keeps_its_own_line(session, owner, tree):
    three_months(session, owner, tree)
    budget_service.create_budget(session, owner, {
        "period": "monthly", "month_start_day": 1, "amount": "10000.00",
        "allocations": [{"category_id": tree.groceries, "amount": "1000.00"}]}, today=TODAY)
    view = budget_service.suggestion(session, owner, today=TODAY)
    assert line(view, tree.groceries).history == (D("1000.00"), D("1400.00"), D("1000.00"))
    assert line(view, tree.food).history == (D("3000.00"), D("2500.00"), D("9000.00"))
    assert view.in_force == D("10000.00")


def test_the_step_comes_from_settings(session, owner, tree):
    three_months(session, owner, tree)
    preferences_service.update_preferences(session, owner, {"budget_round_step": 1000})
    view = budget_service.suggestion(session, owner, today=TODAY)
    assert (view.suggestion.step, line(view, tree.transport).suggested) == (D("1000.00"), D("2000.00"))


def test_a_bad_step_setting_is_refused(session, owner):
    with pytest.raises(ValidationException):
        preferences_service.update_preferences(session, owner, {"budget_round_step": 7})


def test_suggesting_writes_nothing(session, owner, tree):
    three_months(session, owner, tree)
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 1, "amount": "10000.00"},
                                 today=TODAY)
    before = [r.data for r in BudgetRepository(session, owner).list()]
    budget_service.suggestion(session, owner, today=TODAY, fit=True, trim=10)
    assert [r.data for r in BudgetRepository(session, owner).list()] == before


# ------------------------------------------------ the reminder in the status


def test_the_status_carries_the_reminder_on_the_first_days_of_a_period(session, owner, tree):
    three_months(session, owner, tree)  # suggests 5,600
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 1, "amount": "30000.00"},
                                 today=date(2026, 9, 1))
    first_day = budget_service.status(session, owner, today=date(2026, 9, 1))
    assert first_day.reminder is not None
    assert (first_day.reminder.suggested, first_day.reminder.in_force, first_day.reminder.periods) == (
        D("5600.00"), D("30000.00"), 3)
    assert budget_service.status(session, owner, today=date(2026, 9, 4)).reminder is None


def test_not_now_hides_it_until_the_next_period(session, owner, tree):
    three_months(session, owner, tree)
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 1, "amount": "30000.00"},
                                 today=date(2026, 9, 1))
    budget_service.dismiss_reminder(session, owner, today=date(2026, 9, 1))
    assert budget_service.status(session, owner, today=date(2026, 9, 2)).reminder is None
    assert budget_service.status(session, owner, today=date(2026, 10, 1)).reminder is not None


def test_the_switch_turns_the_reminder_off(session, owner, tree):
    three_months(session, owner, tree)
    budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 1, "amount": "30000.00"},
                                 today=date(2026, 9, 1))
    preferences_service.update_preferences(session, owner, {"budget_suggestion_nudge": False})
    assert budget_service.status(session, owner, today=date(2026, 9, 1)).reminder is None


def test_an_edit_to_the_budget_keeps_the_dismissal(session, owner, tree):
    three_months(session, owner, tree)
    budget = budget_service.create_budget(session, owner, {"period": "monthly", "month_start_day": 1,
                                                           "amount": "30000.00"}, today=date(2026, 9, 1))
    budget_service.dismiss_reminder(session, owner, today=date(2026, 9, 1))
    budget_service.update_budget(session, owner, budget.id, {"amount": "31000.00"}, today=date(2026, 9, 2))
    assert budget_service.status(session, owner, today=date(2026, 9, 2)).reminder is None


# ------------------------------------------------------------------ the API


def test_the_suggestion_endpoint(api):
    assert api.register().status_code == 201
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "9000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    api.post("/transactions", {"type": "expense", "amount": "1234.00", "account_id": wallet,
                               "category_id": food, "txn_date": "2026-08-10"})

    body = api.get("/budgets/suggestion", params={"today": "2026-09-13", "periods": 1}).json()
    assert body["ready"] is True
    assert body["lines"] == [{"category_id": food, "history": ["1234.00"], "median": "1234.00",
                              "average": "1234.00", "scheduled": "0.00", "current": None, "spent_in": 1,
                              "suggested": "1300.00", "reason": "single"}]
    assert body["total"] == "1300.00"
    assert api.get("/budgets/suggestion", params={"periods": 2}).status_code == 422
    assert api.patch("/settings/preferences", {"budget_round_step": 7}).status_code == 422
