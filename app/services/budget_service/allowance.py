"""
The daily allowance (BUD-06) - "You can spend ₱612 today."

Pure: a period, a day, an amount and the period's spending in; figures out.
No database, no clock, so every edge case is a plain test.

TWO MODES (BUD-07/08):

    remaining_over_days_left   (default) what is left before today, spread over
                               the days left INCLUDING today. Self-correcting:
                               overspend today and tomorrow's figure drops.
    fixed_daily                the period's money over its total days. The same
                               number every day; the overspend shows only in
                               "left today" and the period's remaining.

TODAY'S ALLOWANCE IS FIXED FOR THE DAY. It is computed from spending BEFORE
today, so buying a coffee does not shrink the number you were told this
morning - it shrinks "left today" instead. Tomorrow recomputes.

NEVER NONSENSE. When the money is gone (a bad period, or carried-in overspend
from several), the allowance is ₱0.00 and `over_by` says by how much - never a
negative daily figure. Allowances round DOWN to the centavo, so following them
exactly can never overspend.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Iterable, Optional

from app.core.utils.date_utils import BudgetPeriod
from app.core.utils.money import CENTS, ZERO

MODES = ("remaining_over_days_left", "fixed_daily")


@dataclass(frozen=True)
class Spend:
    """One expense split, as the budget sees it. Transfers and income never become one."""

    on: date
    category_id: Optional[int]
    amount: Decimal


@dataclass(frozen=True)
class Allowance:
    mode: str
    budget: Decimal  # the period's own amount
    carried_in: Decimal  # from earlier periods; ZERO when carry-over is off
    available: Decimal  # budget + carried_in - may be negative after bad periods
    spent: Decimal  # the whole period, today and any future-dated entries included
    spent_before_today: Decimal
    spent_today: Decimal
    remaining: Decimal  # available - spent; negative when over
    daily: Decimal  # today's allowance, never below zero
    left_today: Decimal  # daily - spent_today; negative once today is overspent
    over_by: Decimal  # how far past `available` the period is, else zero
    days_total: int
    days_elapsed: int  # including today
    days_left: int  # including today
    used_ratio: Decimal  # spent / available, 1 when there was nothing to spend


def daily_allowance(
    period: BudgetPeriod,
    today: date,
    amount: Decimal,
    spends: Iterable[Spend],
    *,
    mode: str = "remaining_over_days_left",
    carried_in: Decimal = ZERO,
) -> Allowance:
    if mode not in MODES:
        raise ValueError(f"allowance mode must be one of {MODES}")

    spent = before = on_today = ZERO
    for spend in spends:
        if not period.covers(spend.on):
            continue
        spent += spend.amount
        if spend.on < today:
            before += spend.amount
        elif spend.on == today:
            on_today += spend.amount

    available = amount + carried_in
    days_total = period.days
    if today < period.start:  # looking ahead at a period that has not begun
        days_elapsed, days_left = 0, days_total
    elif today > period.end:  # looking back at one that has finished
        days_elapsed, days_left = days_total, 0
    else:
        days_elapsed = (today - period.start).days + 1
        days_left = (period.end - today).days + 1

    if days_left == 0:
        daily = ZERO
    elif mode == "fixed_daily":
        daily = _down(max(available, ZERO) / days_total)
    else:
        daily = _down(max(available - before, ZERO) / days_left)

    in_period_today = period.covers(today)
    remaining = available - spent
    if available > ZERO:
        used = (spent / available).quantize(Decimal("0.0001"))
    else:
        used = Decimal("1.0000") if spent > ZERO or available < ZERO else Decimal("0.0000")

    return Allowance(
        mode=mode,
        budget=amount,
        carried_in=carried_in,
        available=available,
        spent=spent,
        spent_before_today=before,
        spent_today=on_today if in_period_today else ZERO,
        remaining=remaining,
        daily=daily,
        left_today=(daily - on_today) if in_period_today else ZERO,
        over_by=max(spent - available, ZERO),
        days_total=days_total,
        days_elapsed=days_elapsed,
        days_left=days_left,
        used_ratio=used,
    )


def _down(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_DOWN)
