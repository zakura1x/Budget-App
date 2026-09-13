"""
Budget period resolution (BUD-01..BUD-05) - "the fiddly bit, test it hard".

The properties that matter: every day belongs to exactly one period, the
periods tile the calendar with no gap and no overlap, and a payday start day
survives month ends, short months and the year boundary.
"""

from datetime import date, timedelta

import pytest

from app.core.utils.date_utils import budget_period


def days(start: date, count: int):
    return (start + timedelta(days=n) for n in range(count))


# ------------------------------------------------------------------ monthly


def test_a_calendar_month():
    period = budget_period(date(2026, 9, 13), "monthly", month_start_day=1)
    assert (period.start, period.end, period.days) == (date(2026, 9, 1), date(2026, 9, 30), 30)


def test_a_25th_start_resolves_across_the_year_boundary():
    """The Phase 5 verify item."""
    december = budget_period(date(2026, 12, 30), "monthly", month_start_day=25)
    assert (december.start, december.end) == (date(2026, 12, 25), date(2027, 1, 24))
    assert budget_period(date(2027, 1, 10), "monthly", month_start_day=25) == december
    assert budget_period(date(2027, 1, 24), "monthly", month_start_day=25) == december

    january = budget_period(date(2027, 1, 25), "monthly", month_start_day=25)
    assert (january.start, january.end) == (date(2027, 1, 25), date(2027, 2, 24))


def test_a_31st_start_clamps_in_short_months():
    assert budget_period(date(2026, 2, 27), "monthly", month_start_day=31).start == date(2026, 1, 31)
    february = budget_period(date(2026, 2, 28), "monthly", month_start_day=31)
    assert (february.start, february.end) == (date(2026, 2, 28), date(2026, 3, 30))


@pytest.mark.parametrize("config", [
    {"kind": "monthly", "month_start_day": 1},
    {"kind": "monthly", "month_start_day": 25},
    {"kind": "monthly", "month_start_day": 29},
    {"kind": "monthly", "month_start_day": 31},
    {"kind": "weekly", "week_start_day": 1},
    {"kind": "weekly", "week_start_day": 7},
    {"kind": "custom", "custom_days": 14, "custom_anchor": date(2026, 9, 1)},
    {"kind": "custom", "custom_days": 10, "custom_anchor": date(2027, 6, 15)},
])
def test_periods_tile_two_years_of_days(config):
    """Every day in exactly one period; each period starts the day after the last one ends."""
    previous = None
    for day in days(date(2025, 11, 1), 800):
        period = budget_period(day, **config)
        assert period.covers(day)
        if previous is not None and period != previous:
            assert period.start == previous.end + timedelta(days=1)
        previous = period


# ------------------------------------------------------------------- weekly


def test_a_week_starting_monday():
    # 13 September 2026 is a Sunday.
    period = budget_period(date(2026, 9, 13), "weekly", week_start_day=1)
    assert (period.start, period.end) == (date(2026, 9, 7), date(2026, 9, 13))


def test_a_week_starting_sunday():
    period = budget_period(date(2026, 9, 13), "weekly", week_start_day=7)
    assert (period.start, period.end) == (date(2026, 9, 13), date(2026, 9, 19))


# ------------------------------------------------------------------- custom


def test_a_custom_length_counts_from_its_anchor():
    period = budget_period(date(2026, 9, 13), "custom", custom_days=14, custom_anchor=date(2026, 9, 1))
    assert (period.start, period.end) == (date(2026, 9, 1), date(2026, 9, 14))


def test_a_custom_length_works_before_its_anchor():
    period = budget_period(date(2026, 8, 20), "custom", custom_days=14, custom_anchor=date(2026, 9, 1))
    assert (period.start, period.end) == (date(2026, 8, 18), date(2026, 8, 31))


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize("kind, options", [
    ("monthly", {"month_start_day": 0}),
    ("monthly", {"month_start_day": 32}),
    ("weekly", {"week_start_day": 0}),
    ("weekly", {"week_start_day": 8}),
    ("custom", {"custom_days": 14}),  # no anchor
    ("custom", {"custom_days": 0, "custom_anchor": date(2026, 9, 1)}),
    ("fortnightly", {}),
])
def test_bad_configuration_is_refused(kind, options):
    with pytest.raises(ValueError):
        budget_period(date(2026, 9, 13), kind, **options)
