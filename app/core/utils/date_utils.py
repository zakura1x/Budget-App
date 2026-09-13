"""
Calendar arithmetic, in one place.

Two independent cycles run in this app and they must never be conflated
(ACC-16): a credit card's STATEMENT period, which turns on the card's closing
day, and the BUDGET period, which turns on the month start day. A card closing
on the 20th has nothing to do with a budget starting on the 1st. They share
these helpers; they never share a date.

Everything here is pure `date` arithmetic - no timezone, no clock. The caller
passes "today" in, so a test can pass any day it likes.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


def days_in_month(year: int, month: int) -> int:
    return monthrange(year, month)[1]


def clamp_day(year: int, month: int, day: int) -> date:
    """
    The `day`th of that month, or its last day if the month is shorter. A card
    that closes on the 31st closes on the 28th in February; without this the
    statement period for February would not exist.
    """
    return date(year, month, min(day, days_in_month(year, month)))


def add_months(anchor: date, months: int) -> date:
    """Shift by whole months, keeping the day of month where it still exists."""
    total = (anchor.year * 12 + anchor.month - 1) + months
    return clamp_day(total // 12, total % 12 + 1, anchor.day)


@dataclass(frozen=True)
class StatementPeriod:
    """
    One credit-card statement cycle (ACC-09).

        start     first day the period covers
        closes    the statement closing date - the last day it covers
        due       when the resulting bill has to be paid

    `start` is the day after the previous closing, so consecutive periods
    tile the calendar with no gap and no overlap.
    """

    start: date
    closes: date
    due: date

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.closes


def statement_period(today: date, closing_day: int, due_day: int) -> StatementPeriod:
    """
    The statement period that `today` falls in, for a card with this closing
    and payment-due day.

    A purchase made on the closing day itself belongs to the period that
    closes that day - the statement is cut at the end of it.
    """
    _check_day(closing_day, "closing_day")
    _check_day(due_day, "due_day")

    closes = clamp_day(today.year, today.month, closing_day)
    if today > closes:
        # This month's statement is already cut; the open one closes next month.
        closes = clamp_day(*_next_month(today.year, today.month), closing_day)

    previous = clamp_day(*_previous_month(closes.year, closes.month), closing_day)
    return StatementPeriod(start=_day_after(previous), closes=closes, due=due_date(closes, closing_day, due_day))


def due_date(closes: date, closing_day: int, due_day: int) -> date:
    """
    When the bill cut on `closes` has to be paid. A due day LATER in the month
    than the closing day falls in the same month; anything else falls in the
    next one - the usual card convention, and the only reading in which the
    due date never precedes the statement it pays for.
    """
    if due_day > closing_day:
        return clamp_day(closes.year, closes.month, due_day)
    return clamp_day(*_next_month(closes.year, closes.month), due_day)


def previous_statement_period(period: StatementPeriod, closing_day: int, due_day: int) -> StatementPeriod:
    """The period immediately before this one - the bill that is due now."""
    return statement_period(_day_before(period.start), closing_day, due_day)


# --------------------------------------------------------------- internal


def _check_day(day: int, name: str) -> None:
    if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 31:
        raise ValueError(f"{name} must be 1-31")


def _next_month(year: int, month: int) -> tuple:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _previous_month(year: int, month: int) -> tuple:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _day_after(day: date) -> date:
    return date.fromordinal(day.toordinal() + 1)


def _day_before(day: date) -> date:
    return date.fromordinal(day.toordinal() - 1)


# ============================================================ budget periods
#
# BUD-01..BUD-05. The period a budget measures a day against. Consecutive
# periods tile the calendar exactly like statement periods do - no gap, no
# overlap - or a purchase would count against two budgets, or none.

PERIOD_KINDS = ("weekly", "monthly", "custom")


@dataclass(frozen=True)
class BudgetPeriod:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


def budget_period(
    day: date,
    kind: str,
    *,
    month_start_day: int = 1,
    week_start_day: int = 1,
    custom_days: Optional[int] = None,
    custom_anchor: Optional[date] = None,
) -> BudgetPeriod:
    """
    The budget period `day` falls in.

        monthly   from `month_start_day` to the day before it next month -
                  payday budgeting (BUD-04): a 25th start runs 25 Dec to
                  24 Jan across the year boundary. A start day the month does
                  not have clamps to its last day, like a statement does.
        weekly    seven days from `week_start_day`, 1 Monday .. 7 Sunday (BUD-05)
        custom    `custom_days` long, counted from `custom_anchor` in either
                  direction (BUD-03)
    """
    if kind == "monthly":
        _check_day(month_start_day, "month_start_day")
        start = clamp_day(day.year, day.month, month_start_day)
        if day < start:
            start = clamp_day(*_previous_month(day.year, day.month), month_start_day)
        following = clamp_day(*_next_month(start.year, start.month), month_start_day)
        return BudgetPeriod(start, _day_before(following))

    if kind == "weekly":
        if not isinstance(week_start_day, int) or isinstance(week_start_day, bool) or not 1 <= week_start_day <= 7:
            raise ValueError("week_start_day must be 1-7 (Monday-Sunday)")
        start = day - timedelta(days=(day.isoweekday() - week_start_day) % 7)
        return BudgetPeriod(start, start + timedelta(days=6))

    if kind == "custom":
        if not isinstance(custom_days, int) or isinstance(custom_days, bool) or not 1 <= custom_days <= 366:
            raise ValueError("custom_days must be 1-366")
        if not isinstance(custom_anchor, date):
            raise ValueError("a custom period needs custom_anchor")
        index = (day - custom_anchor).days // custom_days  # floor: works before the anchor too
        start = custom_anchor + timedelta(days=index * custom_days)
        return BudgetPeriod(start, start + timedelta(days=custom_days - 1))

    raise ValueError(f"period must be one of {PERIOD_KINDS}")
