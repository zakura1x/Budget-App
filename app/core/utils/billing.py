"""
billing - which bill a charge lands on, and what of a list of bills is due now
(ACC-35 cards, ACC-40 loans, REC-14/34 plans).

Pure: no session, no database, no clock. Every caller that asks these two
questions asks HERE, so they cannot answer differently (architecture review
2026-10-12 - the projection had its own copy of the placement rule, kept in
step by a docstring, and it drifted once, fixed 2026-09-16):

- account_service._bills places each charge on a card's bills;
- projection_service asks whether a charge to come is already on one;
- installment_conversion dates a card plan's first payment;
- account_service (card and loan) and projection_service read `due_now`.
"""

from datetime import date
from decimal import Decimal
from typing import Iterable, NamedTuple, Optional, Sequence, Tuple

from app.core.utils.date_utils import clamp_day, statement_period
from app.core.utils.money import ZERO, total


def bill_due(
    on: date,
    *,
    installment: bool,
    closing_day: int,
    due_day: int,
    bill_dues: Iterable[date] = (),
) -> date:
    """
    The due date of the bill a charge dated `on` joins.

    An INSTALLMENT payment is already a bill line: its date is the day the bank
    BILLS it ("first payment 5 Oct" is on the October bill), so it joins the
    first of `bill_dues` falling due on or after that day (fixed 2026-09-16,
    user: a payment dated 15 Oct showed on the 15 Nov bill). Past the last of
    them it keeps the last one's day of the month, so the bills stay on one
    rhythm; with no bills at all, the card's own due day.

    Anything else is a PURCHASE: billed with the statement it falls in, which
    falls due after that statement closes.
    """
    if not installment:
        return statement_period(on, closing_day, due_day).due
    dues = sorted(bill_dues)
    nearest = next((due for due in dues if due >= on), None)
    if nearest is not None:
        return nearest
    return _due_on_or_after(on, dues[-1].day if dues else due_day)


def on_a_bill(on: date, *, installment: bool, closing_day: int, due_day: int, last_due: date) -> bool:
    """
    Whether a charge dated `on` lands on a bill no later than `last_due` - the
    projection's question: a charge already inside a card's bills is not
    counted a second time. The same rule as bill_due, by construction.
    """
    return bill_due(on, installment=installment, closing_day=closing_day, due_day=due_day,
                    bill_dues=(last_due,)) <= last_due


class Owing(NamedTuple):
    """One bill (or loan payment) as `due_now` reads it."""

    due: date
    left: Decimal
    overdue: bool


class DueNow(NamedTuple):
    amount: Decimal  # every overdue bill plus the next due date's - what cash on hand holds back
    dues: Tuple[date, ...]  # the due dates inside that amount, oldest first
    next_on: Optional[date]  # the next due date not yet overdue, if any
    next_amount: Decimal  # what falls due on it


def due_now(bills: Sequence[Owing]) -> DueNow:
    """
    ACC-35 / ACC-40. What is due NOW: everything overdue plus the next due
    date - every bill on it, so two loan plans due the same day are both held
    (fixed 2026-10-12: the second was held by Months ahead and by nothing
    else). A card and a loan hold money back by this one rule. Bills with
    nothing left are skipped; each caller decides what `overdue` means.
    """
    unpaid = [b for b in bills if b.left > ZERO]
    next_on = min((b.due for b in unpaid if not b.overdue), default=None)
    now = sorted((b for b in unpaid if b.overdue or b.due == next_on), key=lambda b: b.due)
    return DueNow(
        amount=total(b.left for b in now).quantize(ZERO),
        dues=tuple(sorted({b.due for b in now})),
        next_on=next_on,
        next_amount=total(b.left for b in unpaid if b.due == next_on and not b.overdue).quantize(ZERO),
    )


def _due_on_or_after(day: date, due_day: int) -> date:
    """The day-of-month `due_day` on or after `day`."""
    this_month = clamp_day(day.year, day.month, due_day)
    if this_month >= day:
        return this_month
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return clamp_day(year, month, due_day)
