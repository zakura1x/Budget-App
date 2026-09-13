"""
The daily allowance, carry-over and alerts - the pure core of Phase 5.

Every figure here is checked against a hand calculation, as a Decimal string.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.utils.date_utils import budget_period
from app.core.utils.money import ZERO
from app.services.budget_service.alerts import CardDue, CategoryUse, budget_alerts
from app.services.budget_service.allowance import Spend, daily_allowance
from app.services.budget_service.carry_over import carried_in

SEPTEMBER = budget_period(date(2026, 9, 13), "monthly", month_start_day=1)  # 1-30 Sep, 30 days
D = Decimal


def spend(day, amount, category=1):
    return Spend(date(2026, 9, day), category, D(amount))


def allowance(today, spends=(), amount="30000.00", **options):
    return daily_allowance(SEPTEMBER, date(2026, 9, today), D(amount), list(spends), **options)


# ------------------------------------------------------ remaining over days left


def test_the_first_day_of_an_untouched_month():
    a = allowance(1)
    assert (str(a.daily), a.days_left, a.days_elapsed, str(a.remaining)) == ("1000.00", 30, 1, "30000.00")


@pytest.mark.security
def test_overspending_today_lowers_tomorrows_allowance():
    """The Phase 5 verify item - and today's figure does not move while you spend."""
    before = [spend(d, "1000.00") for d in range(1, 10)]  # on track: 9,000 by the 9th

    today = allowance(10, before + [spend(10, "3000.00")])
    assert str(today.daily) == "1000.00"  # (30000 - 9000) / 21, fixed for the day
    assert str(today.spent_today) == "3000.00"
    assert str(today.left_today) == "-2000.00"

    tomorrow = allowance(11, before + [spend(10, "3000.00")])
    assert str(tomorrow.daily) == "900.00"  # (30000 - 12000) / 20
    assert tomorrow.daily < today.daily


def test_allowances_round_down_so_following_them_never_overspends():
    three_days = budget_period(date(2026, 9, 1), "custom", custom_days=3, custom_anchor=date(2026, 9, 1))
    a = daily_allowance(three_days, date(2026, 9, 1), D("1000.00"), [])
    assert str(a.daily) == "333.33"
    assert a.daily * 3 <= D("1000.00")


def test_the_last_day_gets_everything_left():
    a = allowance(30, [spend(1, "29500.00")])
    assert (str(a.daily), a.days_left) == ("500.00", 1)


def test_a_centavo_split_adds_up_exactly():
    a = allowance(2, [spend(1, "0.10"), spend(1, "0.20")])
    assert str(a.spent) == "0.30"
    assert str(a.remaining) == "29999.70"


def test_an_empty_period():
    a = allowance(15)
    assert (str(a.spent), str(a.used_ratio), str(a.over_by)) == ("0.00", "0.0000", "0.00")


def test_over_budget_is_zero_a_day_never_negative():
    a = allowance(20, [spend(5, "31000.00")])
    assert (str(a.daily), str(a.over_by), str(a.remaining)) == ("0.00", "1000.00", "-1000.00")


def test_spending_outside_the_period_is_ignored():
    outside = [Spend(date(2026, 8, 31), 1, D("5000.00")), Spend(date(2026, 10, 1), 1, D("5000.00"))]
    assert allowance(15, outside).spent == ZERO


# --------------------------------------------------------------- fixed daily


def test_fixed_daily_ignores_what_was_spent_before_today():
    a = allowance(10, [spend(1, "20000.00"), spend(10, "250.00")], mode="fixed_daily")
    assert (str(a.daily), str(a.left_today)) == ("1000.00", "750.00")


# ---------------------------------------------------- viewing other periods


def test_a_finished_period_has_no_allowance_left():
    a = daily_allowance(SEPTEMBER, date(2026, 10, 5), D("30000.00"), [spend(3, "100.00")])
    assert (str(a.daily), a.days_left, str(a.spent_today), str(a.spent)) == ("0.00", 0, "0.00", "100.00")


def test_a_period_that_has_not_started_spreads_over_every_day():
    a = daily_allowance(SEPTEMBER, date(2026, 8, 20), D("30000.00"), [])
    assert (str(a.daily), a.days_elapsed) == ("1000.00", 0)


# ---------------------------------------------------------------- carry-over


WEEK = {"kind": "weekly", "week_start_day": 1}
FIRST_WEEK = budget_period(date(2026, 9, 7), **WEEK)  # Mon 7 - Sun 13 Sep


def week(n):
    return budget_period(date.fromordinal(FIRST_WEEK.start.toordinal() + 7 * n), **WEEK)


def carry(target_week, spent_by_week, amount="10000.00"):
    return carried_in(
        week(target_week),
        FIRST_WEEK.start,
        lambda day: budget_period(day, **WEEK),
        lambda p: D(amount),
        lambda p: D(spent_by_week.get(p.start, "0")),
    )


def test_a_surplus_rolls_forward():
    """FEATURES.md §13-B: spend 7,000 of 10,000 and next week starts at 13,000."""
    assert str(carry(1, {week(0).start: "7000.00"})) == "3000.00"


def test_an_overspend_follows_you():
    """§13-B: spend 12,000 of 10,000 and next week starts at 8,000."""
    assert str(carry(1, {week(0).start: "12000.00"})) == "-2000.00"


@pytest.mark.security
def test_three_bad_weeks_compound_but_never_render_as_nonsense():
    """The Phase 5 compounding case: the debt is honest, the allowance is never negative."""
    bad = {week(n).start: "15000.00" for n in range(3)}
    carried = carry(3, bad)
    assert str(carried) == "-15000.00"

    fourth = daily_allowance(week(3), week(3).start, D("10000.00"), [], carried_in=carried)
    assert (str(fourth.available), str(fourth.daily), str(fourth.over_by)) == ("-5000.00", "0.00", "5000.00")
    assert str(fourth.left_today) == "0.00"


def test_the_first_period_of_a_chain_carries_nothing():
    assert carry(0, {}) == ZERO


def test_a_period_before_the_budget_existed_restarts_the_chain():
    result = carried_in(
        week(2), week(0).start, lambda day: budget_period(day, **WEEK),
        lambda p: None if p == week(0) else D("10000.00"),
        lambda p: D("4000.00"),
    )
    assert str(result) == "6000.00"  # only week 1 counts: 10,000 - 4,000


# -------------------------------------------------------------------- alerts


def kinds(alerts):
    return [a.kind for a in alerts]


def test_over_supersedes_approaching_and_pace():
    a = allowance(5, [spend(1, "30000.00")])
    assert kinds(budget_alerts(a)) == ["over"]


def test_approaching_at_the_threshold():
    a = allowance(29, [spend(1, "24000.00")])
    assert kinds(budget_alerts(a, warn_pct=80)) == ["approaching"]


def test_the_pace_alert_from_the_spec():
    """Day 10 of 30 with 60% spent warns while there is still time to act."""
    a = allowance(10, [spend(1, "18000.00")])
    assert kinds(budget_alerts(a, pace_tolerance_pct=10)) == ["pace"]


def test_pace_within_tolerance_stays_quiet():
    a = allowance(10, [spend(1, "12000.00")])  # 40% spent at 33% elapsed, tolerance 10
    assert budget_alerts(a, pace_tolerance_pct=10) == []


def test_pace_can_be_switched_off():
    a = allowance(10, [spend(1, "18000.00")])
    assert budget_alerts(a, pace_enabled=False) == []


def test_a_finished_period_raises_no_pace_alert():
    a = daily_allowance(SEPTEMBER, date(2026, 10, 2), D("30000.00"), [spend(1, "20000.00")])
    assert "pace" not in kinds(budget_alerts(a))


def test_category_and_card_alerts():
    a = allowance(10)
    alerts = budget_alerts(
        a,
        categories=[CategoryUse(4, D("5000.00"), D("5000.00")), CategoryUse(5, D("5000.00"), D("4999.99"))],
        cards_due=[CardDue(account_id=9, due_in_days=3)],
    )
    assert [(x.kind, x.category_id, x.account_id) for x in alerts] == [
        ("category_over", 4, None),
        ("card_due", None, 9),
    ]


def test_category_alerts_can_be_switched_off():
    a = allowance(10)
    assert budget_alerts(a, categories=[CategoryUse(4, D("1.00"), D("2.00"))], category_level=False) == []
