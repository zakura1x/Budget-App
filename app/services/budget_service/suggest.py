"""
BUD-17 - a budget suggested from recent spending. Pure: plain inputs in, a
suggestion out, so every rule is tested directly (like allowance.py and
carry_over.py). budget_service gathers the inputs from the working set.

Decided by the user on 2026-09-28: it SUGGESTS and never sets anything; the
typical figure is the MEDIAN, with the average shown beside it; allocations
round UP to a step chosen in Settings (`budget_round_step`); and a reminder
at the start of a period (`reminder`) says when the budget has drifted from
what is actually spent, behind a Settings switch.

The rules, each named by the `reason` it leaves on a line:

    median      the median of the chosen finished periods - one big purchase
                does not set next month's budget
    scheduled   never below what recurring charges, subscriptions and
                installment payments will charge that category this period
    kept        a category you already budget with no regular spending in
                the window keeps its amount; you put it there for a reason
    single      only one period to go on - its own figure

A category spent in in FEWER than half the periods (and not budgeted now) is
OCCASIONAL: it gets no line of its own and its spending joins the buffer. The
buffer - the part of the total no category holds - is the median, per
period, of everything spent outside the suggested lines.

Everything is Decimal; a median of an even count is the mean of the middle
two, to the centavo, before it is rounded up.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.utils.date_utils import BudgetPeriod
from app.core.utils.money import CENTS, ZERO, total

STEPS: Tuple[int, ...] = (1, 10, 50, 100, 500, 1000)  # the Settings choices, in pesos
DEFAULT_STEP = 100
TRIMS: Tuple[int, ...] = (0, 5, 10)  # "spend 5% / 10% less"
PERIOD_CHOICES: Tuple[int, ...] = (1, 3, 6)

# The reminder (decided 2026-09-28, option 1 plus a Settings switch).
REMINDER_DIFFERENCE = Decimal("0.15")  # more than 15% either way
REMINDER_HISTORY = 3  # finished periods needed before it may show
REMINDER_DAYS = 3  # shown in the first three days of a period, then gone


@dataclass(frozen=True)
class Line:
    category_id: int
    history: Tuple[Decimal, ...]  # per period, oldest first
    median: Decimal
    average: Decimal
    scheduled: Decimal
    current: Optional[Decimal]  # what is allocated now, if anything
    spent_in: int  # periods with any spending
    suggested: Decimal
    reason: str  # median | scheduled | kept | single


@dataclass(frozen=True)
class Occasional:
    category_id: int
    history: Tuple[Decimal, ...]
    spent_in: int


@dataclass(frozen=True)
class Suggestion:
    lines: Tuple[Line, ...]
    occasional: Tuple[Occasional, ...]
    buffer: Decimal
    total: Decimal
    income: Optional[Decimal]  # median income per period; None when nothing came in
    over_income: bool  # the total is more than that income
    fitted: bool  # Fit to my income was applied
    cannot_fit: bool  # scheduled charges alone are more than the income
    step: Decimal
    trim: int


def median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle].quantize(CENTS)
    return ((ordered[middle - 1] + ordered[middle]) / 2).quantize(CENTS, rounding=ROUND_HALF_UP)


def average(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return (total(values) / len(values)).quantize(CENTS, rounding=ROUND_HALF_UP)


def round_up(amount: Decimal, step: Decimal) -> Decimal:
    """Up to the next multiple of `step` - rounding down would start you over budget."""
    if amount <= ZERO:
        return ZERO
    return ((amount / step).to_integral_value(rounding=ROUND_CEILING) * step).quantize(CENTS)


def round_down(amount: Decimal, step: Decimal) -> Decimal:
    if amount <= ZERO:
        return ZERO
    return ((amount / step).to_integral_value(rounding=ROUND_FLOOR) * step).quantize(CENTS)


def suggest(
    history: Mapping[int, Sequence[Decimal]],
    *,
    periods: int,
    income: Sequence[Decimal] = (),
    scheduled: Optional[Mapping[int, Decimal]] = None,
    current: Optional[Mapping[int, Decimal]] = None,
    step: int = DEFAULT_STEP,
    trim: int = 0,
    fit: bool = False,
) -> Suggestion:
    """
    `history` maps each category that may be suggested to its spending in each
    of the `periods` finished periods, oldest first. `scheduled` is this
    period's committed charges per category (the floor), `current` the
    allocations in force now. `income` is money in per period.
    """
    if step not in STEPS:
        raise ValueError(f"step must be one of {STEPS}")
    if trim not in TRIMS:
        raise ValueError(f"trim must be one of {TRIMS}")
    scheduled = scheduled or {}
    current = current or {}
    unit = Decimal(step)
    zeros = (ZERO,) * periods

    lines: List[Line] = []
    occasional: List[Occasional] = []
    outside: List[Decimal] = list(zeros)  # per period, everything no line holds
    for category_id in sorted(set(history) | set(current) | set(scheduled)):
        spent = tuple(history.get(category_id, zeros))
        spent_in = sum(1 for amount in spent if amount > ZERO)
        floor = scheduled.get(category_id, ZERO)
        now = current.get(category_id)
        if now is None and floor <= ZERO and spent_in * 2 < periods:
            if spent_in:
                occasional.append(Occasional(category_id, spent, spent_in))
                outside = [a + b for a, b in zip(outside, spent)]
            continue

        typical = median(spent)
        if periods == 1:
            raw, reason = typical, "single"
        else:
            raw, reason = typical, "median"
        if floor > raw:
            raw, reason = floor, "scheduled"
        if raw <= ZERO and now is not None:
            raw, reason = now, "kept"
        lines.append(Line(category_id, spent, typical, average(spent), floor, now, spent_in, raw, reason))

    buffer = median(outside)

    # Trim: the part above the floor gets smaller, never the floor itself.
    def trimmed(line: Line) -> Decimal:
        if line.reason in ("kept", "scheduled") or trim == 0:
            return line.suggested
        return line.scheduled + (line.suggested - line.scheduled) * (100 - trim) / 100

    amounts: Dict[int, Decimal] = {line.category_id: round_up(trimmed(line), unit) for line in lines}
    buffer = round_up(buffer * (100 - trim) / 100, unit)
    grand = total(amounts.values()) + buffer

    typical_income = median([i for i in income]) if any(i > ZERO for i in income) else None
    over_income = typical_income is not None and grand > typical_income
    fitted = cannot_fit = False
    if fit and over_income:
        fitted = True
        floors = {line.category_id: round_up(line.scheduled, unit) for line in lines}
        fixed = total(floors.values())
        flexible = grand - fixed
        room = typical_income - fixed
        if room <= ZERO or flexible <= ZERO:
            cannot_fit = room <= ZERO
            amounts = {cid: floors[cid] for cid in amounts}
            buffer = ZERO
        else:
            factor = room / flexible
            # Rounded DOWN here: rounding up could push it back over what comes in.
            amounts = {cid: floors[cid] + round_down((amounts[cid] - floors[cid]) * factor, unit) for cid in amounts}
            buffer = round_down(buffer * factor, unit)
        grand = total(amounts.values()) + buffer
        over_income = grand > typical_income

    final = tuple(
        Line(line.category_id, line.history, line.median, line.average, line.scheduled, line.current,
             line.spent_in, amounts[line.category_id], line.reason)
        for line in lines
    )
    return Suggestion(
        lines=final,
        occasional=tuple(occasional),
        buffer=buffer,
        total=grand,
        income=typical_income,
        over_income=over_income,
        fitted=fitted,
        cannot_fit=cannot_fit,
        step=unit.quantize(CENTS),
        trim=trim,
    )


def reminder_window(
    *,
    today_index: int,
    kind: str,
    period: BudgetPeriod,
    dismissed_for: Optional[str],
    enabled: bool,
) -> bool:
    """
    The cheap half of the reminder, checked BEFORE a suggestion is worked out
    - it is false on all but a few days a month. `today_index` is how many
    days into the period today is (0 on its first day).
    """
    if not enabled or today_index < 0 or today_index >= REMINDER_DAYS:
        return False
    if kind == "weekly" and period.start.day > 7:
        return False  # a weekly budget is asked once a month, not every week
    return dismissed_for != period.start.isoformat()


def reminder_due(*, history: int, suggested: Decimal, in_force: Optional[Decimal]) -> bool:
    """
    BUD-17's period-start reminder: "Your spending has changed - review your
    budget?" - once `reminder_window` holds. It compares TOTALS only (the
    suggestion screen shows the categories) and only ever OPENS the
    suggestion; nothing is changed.
    """
    if in_force is None or in_force <= ZERO or history < REMINDER_HISTORY:
        return False
    return abs(suggested - in_force) > in_force * REMINDER_DIFFERENCE
