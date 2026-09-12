"""
The credit-card statement cycle (ACC-09/16).

The rule being pinned down: consecutive periods tile the calendar with no gap
and no overlap, the closing day itself belongs to the period it closes, and a
due date never precedes the statement it pays for.
"""

from datetime import date

import pytest

from app.core.utils.date_utils import (
    add_months,
    clamp_day,
    days_in_month,
    due_date,
    previous_statement_period,
    statement_period,
)


def test_clamp_day_shortens_to_the_month():
    assert clamp_day(2026, 2, 31) == date(2026, 2, 28)
    assert clamp_day(2028, 2, 31) == date(2028, 2, 29)  # leap
    assert clamp_day(2026, 9, 15) == date(2026, 9, 15)
    assert days_in_month(2026, 9) == 30


def test_add_months_keeps_the_day_where_it_exists():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 9, 13), 4) == date(2027, 1, 13)
    assert add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)


def test_open_period_before_the_closing_day():
    period = statement_period(date(2026, 9, 13), closing_day=20, due_day=5)
    assert (period.start, period.closes) == (date(2026, 8, 21), date(2026, 9, 20))
    assert period.due == date(2026, 10, 5)


def test_the_closing_day_belongs_to_the_period_it_closes():
    period = statement_period(date(2026, 9, 20), closing_day=20, due_day=5)
    assert period.closes == date(2026, 9, 20)
    assert period.covers(date(2026, 9, 20))


def test_the_day_after_closing_starts_the_next_period():
    period = statement_period(date(2026, 9, 21), closing_day=20, due_day=5)
    assert (period.start, period.closes) == (date(2026, 9, 21), date(2026, 10, 20))
    assert period.due == date(2026, 11, 5)


def test_due_day_later_in_the_month_falls_in_the_same_month():
    period = statement_period(date(2026, 9, 13), closing_day=20, due_day=25)
    assert period.closes == date(2026, 9, 20)
    assert period.due == date(2026, 9, 25)
    assert period.due > period.closes


def test_a_due_date_never_precedes_its_statement():
    for closing in range(1, 32):
        for due in range(1, 32):
            period = statement_period(date(2026, 9, 13), closing_day=closing, due_day=due)
            assert period.due >= period.closes


def test_periods_tile_the_calendar():
    """No gap, no overlap - or a purchase would fall in two statements, or none."""
    period = statement_period(date(2026, 9, 13), closing_day=31, due_day=15)
    for _ in range(24):
        earlier = previous_statement_period(period, 31, 15)
        assert earlier.closes.toordinal() + 1 == period.start.toordinal()
        period = earlier


def test_a_card_closing_on_the_31st_closes_in_february():
    period = statement_period(date(2026, 2, 14), closing_day=31, due_day=15)
    assert period.closes == date(2026, 2, 28)
    assert period.start == date(2026, 2, 1)  # January closed on the 31st


def test_due_date_rolls_the_year():
    assert due_date(date(2026, 12, 20), closing_day=20, due_day=5) == date(2027, 1, 5)


@pytest.mark.parametrize("day", [0, 32, -1, "5", None, True])
def test_a_day_of_month_is_checked(day):
    with pytest.raises(ValueError):
        statement_period(date(2026, 9, 13), closing_day=day, due_day=5)
