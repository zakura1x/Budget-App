"""
calendar_service - a month of days, each with what it cost (CAL-01..CAL-05).

Per-day totals follow the ledger's rules exactly: spending is expenses, earning
is income, a transfer is neither and a balance adjustment is neither (ACC-29).
`count` is the rows the ledger would show for the day - a transfer once.

THE HEATMAP (CAL-01) colours a day against a REFERENCE, not against the
month's biggest day - one rent payment would otherwise wash every other day
out to nothing. The reference is the budget per day of the period the day
falls in (the period's amount over its days). With no budget for that day it
is the month's typical spending day - the median of the days that had any.

    level 0   nothing spent
    level 1   up to half the reference
    level 2   up to the reference
    level 3   up to twice the reference
    level 4   more than that

Tapping a day lists its transactions through GET /transactions?from=&to= -
the same list, filters and rows as the ledger, so there is no second reader
of the working set to drift from the first.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import ValidationException
from app.core.utils.date_utils import days_in_month
from app.core.utils.money import CENTS, ZERO
from app.services import transaction_service
from app.services.budget_service import budget_service

REFERENCE_BUDGET = "budget"
REFERENCE_TYPICAL = "typical"


@dataclass(frozen=True)
class CalendarDay:
    on: date
    spent: Decimal
    earned: Decimal
    count: int
    level: int
    reference: Optional[Decimal]  # what `level` was measured against
    reference_kind: Optional[str]  # "budget" | "typical" | None


@dataclass(frozen=True)
class CalendarMonth:
    year: int
    month: int
    start: date
    end: date
    spent: Decimal
    earned: Decimal
    days: List[CalendarDay]


def heat_level(spent: Decimal, reference: Optional[Decimal]) -> int:
    """Pure: how dark a day is. With nothing to measure against, any spending is level 2."""
    if spent <= ZERO:
        return 0
    if reference is None or reference <= ZERO:
        return 2
    if spent <= reference / 2:
        return 1
    if spent <= reference:
        return 2
    if spent <= reference * 2:
        return 3
    return 4


def month(db: Session, cipher: UserCipher, year: int, month_number: int) -> CalendarMonth:
    if not 2000 <= year <= 2100 or not 1 <= month_number <= 12:
        raise ValidationException("That month is outside what this app records")
    start = date(year, month_number, 1)
    end = date(year, month_number, days_in_month(year, month_number))

    spent: Dict[date, Decimal] = {}
    earned: Dict[date, Decimal] = {}
    counts: Dict[date, int] = {}
    for view in transaction_service.views(db, cipher):
        if not start <= view.txn_date <= end:
            continue
        if view.type == "transfer" and view.direction != "out":
            continue  # the ledger shows a transfer once
        counts[view.txn_date] = counts.get(view.txn_date, 0) + 1
        if view.type == "expense":
            spent[view.txn_date] = spent.get(view.txn_date, ZERO) + view.amount
        elif view.type == "income":
            earned[view.txn_date] = earned.get(view.txn_date, ZERO) + view.amount

    per_day_budget = budget_service.daily_budget(db, cipher)
    spending_days = [amount for amount in spent.values() if amount > ZERO]
    typical = Decimal(median(spending_days)).quantize(CENTS) if spending_days else None

    days: List[CalendarDay] = []
    day = start
    while day <= end:
        reference = per_day_budget(day) if per_day_budget else None
        kind = REFERENCE_BUDGET if reference is not None else None
        if reference is None and typical is not None:
            reference, kind = typical, REFERENCE_TYPICAL
        amount = spent.get(day, ZERO)
        days.append(CalendarDay(
            on=day, spent=amount, earned=earned.get(day, ZERO), count=counts.get(day, 0),
            level=heat_level(amount, reference), reference=reference, reference_kind=kind,
        ))
        day += timedelta(days=1)

    return CalendarMonth(
        year=year, month=month_number, start=start, end=end,
        spent=sum(spent.values(), ZERO), earned=sum(earned.values(), ZERO), days=days,
    )
