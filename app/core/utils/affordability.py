"""
"Can I buy this?" - the verdict, from rules (misc/AI ARCHITECTURE §5.3, AI-30..35).

Pure: plain inputs, no database, no model. The afford skill gathers the
inputs from the services that draw Budget and Months ahead; this decides.
The model later explains the verdict and may never change it.

The model, stated plainly so a reply can say it:

- Months ahead already assumes you spend all of this budget period's
  remaining budget. So the part of a purchase made NOW that fits in what is
  left of the budget is money it already counts as gone. Only the rest is
  extra, and the extra comes off every later point of the cash timeline, from
  the day the money leaves.
- A purchase moved to a later budget period gets no such cover (the
  cautious reading: next period's budget is for next period's spending).
- Money leaves on the day it is paid: today in cash, on the bill's due date
  on a card, and one payment a month on an installment.

Verdicts, in the order they are decided:

  no               the card's available limit is less than the price, or the
                   cash timeline goes below zero even counting the money set
                   aside for goals, and waiting does not help
  wait             it goes below zero now, but bought on a later date (an
                   income day or a month's start) it never does
  tight            it only works by using money set aside for goals, or it
                   leaves the lowest point under a week of essential spending,
                   or it fits the budget but cash was ALREADY going below
                   zero without it (the budget is more than the money)
  yes_over_budget  cash never goes below zero, but the budget period goes over
  yes              fits the budget, and cash never goes below zero
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import List, Optional, Sequence, Tuple

from app.core.utils.date_utils import add_months
from app.core.utils.money import CENTS, ZERO

VERDICTS = ("yes", "yes_over_budget", "tight", "wait", "no")
METHODS = ("now", "card", "installment")
MAX_INSTALLMENT_MONTHS = 36


@dataclass(frozen=True)
class Budget:
    left: Decimal  # what is left to spend this period; negative when over
    days_left: int  # today included
    period_end: date


@dataclass(frozen=True)
class Card:
    name: str
    available: Optional[Decimal]  # the bank limit left; None when no limit is typed
    bill_due: date  # when a purchase made today is paid


@dataclass(frozen=True)
class Inputs:
    price: Decimal
    today: date
    method: str  # now | card | installment
    months: int  # installment payments; 1 otherwise
    # Months ahead's cash on hand after each event, oldest first, starting today
    # with the remaining budget already taken off - the line its lowest point is read from.
    timeline: Sequence[Tuple[date, Decimal]]
    wait_dates: Sequence[date]  # candidate later days to buy on: income days and month starts
    set_aside: Decimal  # money set aside for goals - left out of cash on hand, but there
    essentials_week: Optional[Decimal]  # a week of essential spending; None when not measurable
    budget: Optional[Budget] = None
    card: Optional[Card] = None


@dataclass(frozen=True)
class Result:
    verdict: str
    charges: Tuple[Tuple[date, Decimal], ...]  # when the money leaves, and how much
    covered_by_budget: Decimal  # of the first charge, what this period's remaining budget already counts
    extra: Decimal  # the rest: money Months ahead did not expect to go
    over_budget_by: Decimal  # how far the budget period goes over; 0 when it fits
    daily_after: Optional[Decimal]  # the daily allowance for the rest of the period, if bought today
    lowest: Decimal  # the lowest cash on hand with the purchase
    lowest_on: date
    lowest_without: Decimal  # the same, without it
    fits_from: Optional[date] = None  # verdict wait: the first day it would fit
    limit_short: Optional[Decimal] = None  # verdict no, on a card: how far the limit falls short
    reasons: List[str] = field(default_factory=list)  # codes, for tests and the facts


def schedule(price: Decimal, start: date, method: str, months: int, card: Optional[Card]) -> List[Tuple[date, Decimal]]:
    """When the money leaves. An installment splits the price evenly; the last payment takes the centavos."""
    if method == "card" and card is not None:
        return [(max(card.bill_due, start), price)]
    if method == "installment" and months > 1:
        part = (price / months).quantize(CENTS, rounding=ROUND_DOWN)
        plan = [(add_months(start, i), part) for i in range(months - 1)]
        return plan + [(add_months(start, months - 1), price - part * (months - 1))]
    return [(start, price)]


def lowest(timeline: Sequence[Tuple[date, Decimal]], outgoing: Sequence[Tuple[date, Decimal]]) -> Tuple[Decimal, date]:
    """The lowest point of the timeline once `outgoing` has left, each amount from its own day on."""
    if not timeline:
        return ZERO, date.min
    low: Optional[Tuple[Decimal, date]] = None
    for on, balance in timeline:
        gone = sum((amount for day, amount in outgoing if day <= on), ZERO)
        value = balance - gone
        if low is None or value < low[0]:
            low = (value, on)
    # A charge after the last point still has to be paid from the last balance
    last_on, last_balance = timeline[-1]
    after = sum((amount for day, amount in outgoing), ZERO)
    if last_balance - after < low[0]:
        low = (last_balance - after, max(day for day, _ in outgoing) if outgoing else last_on)
    return low


def decide(i: Inputs) -> Result:
    if i.price <= ZERO:
        raise ValueError("a price is more than zero")
    method = i.method if i.method in METHODS else "now"
    months = max(1, min(i.months, MAX_INSTALLMENT_MONTHS)) if method == "installment" else 1
    reasons: List[str] = []

    charges = schedule(i.price, i.today, method, months, i.card)
    # What this period's budget already counts: the part of the purchase booked today (the budget reads
    # the entry's date, so a card purchase counts now even though the money leaves later).
    booked_now = i.price if method != "installment" else charges[0][1]
    budget_left = max(i.budget.left, ZERO) if i.budget else ZERO
    covered = min(booked_now, budget_left)
    over_budget_by = max(booked_now - budget_left, ZERO) if i.budget else ZERO
    daily_after = None
    if i.budget and i.budget.days_left > 0:
        daily_after = max((i.budget.left - booked_now) / i.budget.days_left, ZERO).quantize(CENTS, rounding=ROUND_DOWN)

    # The covered part comes off the FIRST charge: that money is already out of the timeline.
    extra_charges = list(charges)
    first_day, first_amount = extra_charges[0]
    extra_charges[0] = (first_day, first_amount - covered)
    extra = sum((a for _, a in extra_charges), ZERO)

    low_without, _ = lowest(i.timeline, [])
    low, low_on = lowest(i.timeline, extra_charges)

    base = dict(charges=tuple(charges), covered_by_budget=covered, extra=extra, over_budget_by=over_budget_by,
                daily_after=daily_after, lowest=low, lowest_on=low_on, lowest_without=low_without)

    if method == "card" and i.card is not None and i.card.available is not None and i.card.available < i.price:
        reasons.append("card_limit")
        return Result(verdict="no", limit_short=i.price - i.card.available, reasons=reasons, **base)

    if low < ZERO and extra == ZERO:
        # The whole price is inside the budget, so it changes nothing: cash was already going
        # below zero because the budget is more than the money. Not this purchase's doing.
        reasons.append("cash_already_short")
        return Result(verdict="tight", reasons=reasons, **base)

    if low < ZERO:
        reasons.append("cash_below_zero")
        for day in sorted(d for d in i.wait_dates if d > i.today):
            later = schedule(i.price, day, method, months, i.card)  # no budget cover in a later period
            later_low, _ = lowest(i.timeline, later)
            if later_low >= ZERO:
                reasons.append("fits_later")
                return Result(verdict="wait", fits_from=day, reasons=reasons, **base)
        if low + i.set_aside >= ZERO:
            reasons.append("needs_set_aside")
            return Result(verdict="tight", reasons=reasons, **base)
        return Result(verdict="no", reasons=reasons, **base)

    if i.essentials_week is not None and low < i.essentials_week:
        reasons.append("under_a_week_of_essentials")
        return Result(verdict="tight", reasons=reasons, **base)
    if over_budget_by > ZERO:
        reasons.append("over_budget")
        return Result(verdict="yes_over_budget", reasons=reasons, **base)
    return Result(verdict="yes", reasons=reasons, **base)
