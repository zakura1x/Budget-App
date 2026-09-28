"""
REC-35 - paying debts off, month by month. Pure: plain debts in, a plan out,
so every rule is tested directly (like interest.py). Nothing here writes.

Each debt is what it OWES today (a card's owed with its plans, a loan's
balance with its unbilled plans - the figure ACC-34 fixed on 2026-09-21), the
payment already going to it each month, and optionally a yearly rate typed on
the account (as the bank shows it, per month or per year - decided by the
user 2026-09-28; stored yearly).

A month, in order:

    1. interest     each open debt grows by rate / 12 of what it owes - an
                    ESTIMATE from the rate typed; the app never calculates a
                    card's real interest (ACC-19), and says so on the screen
    2. payments     each debt takes its own monthly payment, never more than
                    it owes
    3. the extra    the extra you chose, plus - while rolling - every payment
                    freed by a debt already cleared and any part of a payment
                    a debt no longer needed, goes to the FIRST open debt in the
                    plan's order, the rest to the next

    snowball    smallest balance first - quick wins
    avalanche   highest rate first - least interest; only when a rate is known,
                and a debt with no rate comes after those that have one

Extra money on an installment plan FINISHES IT SOONER (REC-32's `shorten`,
decided 2026-09-28): the payment stays and the balance falls faster, which is
exactly what this arithmetic does.

"As you pay now" is the same walk with no extra and nothing rolled on.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence

from app.core.utils.date_utils import add_months
from app.core.utils.money import CENTS, ZERO

MAX_MONTHS = 600  # fifty years: past this, the plan says "not at this rate"
STRATEGIES = ("snowball", "avalanche")


@dataclass(frozen=True)
class Debt:
    id: int
    owed: Decimal
    payment: Decimal  # a month, already going to it
    yearly_rate: Optional[Decimal] = None  # percent a year, e.g. 36.0000; None when not typed


@dataclass(frozen=True)
class Outcome:
    id: int
    position: int  # 1 = paid off first in the plan's order
    months: Optional[int]  # None: never cleared within MAX_MONTHS
    paid_off: Optional[date]
    interest: Decimal  # estimated, from the typed rate


@dataclass(frozen=True)
class Plan:
    strategy: str  # snowball | avalanche | as_is
    extra: Decimal
    outcomes: List[Outcome]  # in the plan's order
    months: Optional[int]  # until the LAST debt is cleared; None if one never is
    debt_free: Optional[date]
    interest: Decimal


def order(debts: Sequence[Debt], strategy: str) -> List[Debt]:
    if strategy == "snowball":
        return sorted(debts, key=lambda d: (d.owed, d.id))
    if strategy == "avalanche":
        return sorted(debts, key=lambda d: (d.yearly_rate is None, -(d.yearly_rate or ZERO), d.owed, d.id))
    return list(debts)


def simulate(debts: Sequence[Debt], *, extra: Decimal, strategy: str, start: date, rolling: bool = True) -> Plan:
    """
    Month 1 is `start` (the first of the month the payments begin in). A debt
    that is never cleared - its interest outruns its payment and no extra
    reaches it - reports months None, and so does the plan.
    """
    if extra < ZERO:
        raise ValueError("The extra is zero or more")
    ranked = order(debts, strategy) if strategy in STRATEGIES else list(debts)
    owed: Dict[int, Decimal] = {d.id: d.owed for d in ranked}
    interest: Dict[int, Decimal] = {d.id: ZERO for d in ranked}
    cleared: Dict[int, int] = {d.id: 0 for d in ranked if d.owed <= ZERO}

    month = 0
    while len(cleared) < len(ranked) and month < MAX_MONTHS:
        month += 1
        for debt in ranked:
            if debt.id in cleared or not debt.yearly_rate:
                continue
            grown = (owed[debt.id] * debt.yearly_rate / Decimal(1200)).quantize(CENTS, rounding=ROUND_HALF_UP)
            owed[debt.id] += grown
            interest[debt.id] += grown

        pool = extra if rolling else ZERO
        for debt in ranked:
            if debt.id in cleared:
                if rolling:
                    pool += debt.payment  # a cleared debt's payment rolls on
                continue
            paid = min(debt.payment, owed[debt.id])
            owed[debt.id] -= paid
            if rolling:
                pool += debt.payment - paid
        for debt in ranked:
            if pool <= ZERO:
                break
            if debt.id in cleared or owed[debt.id] <= ZERO:
                continue
            paid = min(pool, owed[debt.id])
            owed[debt.id] -= paid
            pool -= paid
        for debt in ranked:
            if debt.id not in cleared and owed[debt.id] <= ZERO:
                cleared[debt.id] = month

    outcomes = [
        Outcome(
            id=d.id, position=i + 1,
            months=cleared.get(d.id),
            paid_off=add_months(start, cleared[d.id] - 1) if cleared.get(d.id) else None,
            interest=interest[d.id],
        )
        for i, d in enumerate(ranked)
    ]
    never = any(o.months is None for o in outcomes)
    last = None if never else max((o.months or 0 for o in outcomes), default=0)
    return Plan(
        strategy=strategy if rolling else "as_is",
        extra=extra if rolling else ZERO,
        outcomes=outcomes,
        months=last,
        debt_free=add_months(start, last - 1) if last else (start if last == 0 else None),
        interest=sum((o.interest for o in outcomes), ZERO),
    )


def compare(debts: Sequence[Debt], *, extra: Decimal, start: date) -> Dict[str, Optional[Plan]]:
    """As you pay now, snowball, and avalanche - the last only when some debt has a rate."""
    return {
        "as_is": simulate(debts, extra=ZERO, strategy="as_is", start=start, rolling=False),
        "snowball": simulate(debts, extra=extra, strategy="snowball", start=start),
        "avalanche": (simulate(debts, extra=extra, strategy="avalanche", start=start)
                      if any(d.yearly_rate for d in debts) else None),
    }
