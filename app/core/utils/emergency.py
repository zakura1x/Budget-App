"""
GOA-11 - how many months of essential spending an emergency fund should hold.
Pure: plain inputs in, a number of months and every rule that fired out, so
each rule is tested directly (like interest.py and payoff.py).

RULE-BASED ON PURPOSE, not a model: no figure may leave the encryption boundary
(ARCHITECTURE §5), a rule can be tested to the centavo, and every suggestion
can say exactly WHY. The table was approved by the user on 2026-09-28:

    base        regular employee 3 · contractual / project-based 6 ·
                self-employed / freelance 6
    +1 / +2     income swings more than 25% / 50% month to month
                (coefficient of variation over the months with history)
    +1          only one income source
    +1          a month with no income
    +1 / +2     1-2 / 3 or more dependents
    -1          two or more earners in the household
    +1          debt payments above 30% of income
    clamp       3 to 12 months

With fewer than 3 months of income history only the base applies, and it says
so - one odd month would otherwise decide the answer.

A guide, not financial advice; the screen says so.
"""

from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev
from typing import List, Sequence, Tuple

WORK = ("employee", "contract", "self")
DEPENDENTS = ("0", "1-2", "3+")
EARNERS = ("1", "2+")

BASE = {"employee": 3, "contract": 6, "self": 6}
BASE_TEXT = {
    "employee": "A regular employee starts from 3 months",
    "contract": "Contractual or project-based work starts from 6 months",
    "self": "Self-employed or freelance work starts from 6 months",
}
MIN_MONTHS, MAX_MONTHS = 3, 12
MIN_HISTORY = 3  # months of income before the adjustments apply
SWING_SOME, SWING_LOTS = Decimal("0.25"), Decimal("0.50")
DEBT_HEAVY = Decimal("0.30")


@dataclass(frozen=True)
class Fired:
    code: str
    text: str
    months: int  # what it adds; the base carries its own count


@dataclass(frozen=True)
class Target:
    months: int
    fired: List[Fired]
    short_history: bool  # fewer than MIN_HISTORY months of income: the base only


def swing(incomes: Sequence[Decimal]) -> Decimal:
    """How much income moves month to month: the population coefficient of variation, 0 with no income."""
    values = [Decimal(i) for i in incomes]
    if not values or mean(values) <= 0:
        return Decimal(0)
    return (pstdev(values) / mean(values)).quantize(Decimal("0.0001"))


def target_months(
    *,
    work: str,
    dependents: str,
    earners: str,
    incomes: Sequence[Decimal],
    sources: int,
    debt: Decimal,
) -> Target:
    """
    `incomes` is money in for each month with history, oldest first (up to 12);
    `sources` the distinct kinds of income seen lately; `debt` the average
    monthly debt payment. `work`, `dependents` and `earners` are the three
    answers, which default to the most common case until given.
    """
    if work not in WORK or dependents not in DEPENDENTS or earners not in EARNERS:
        raise ValueError("Unknown answer")
    fired: List[Fired] = [Fired("base", BASE_TEXT[work], BASE[work])]
    months = BASE[work]
    short = len(incomes) < MIN_HISTORY
    if not short:
        moved = swing(incomes)
        if moved > SWING_LOTS:
            fired.append(Fired("swing", f"Your income moves about {_pct(moved)} month to month", 2))
        elif moved > SWING_SOME:
            fired.append(Fired("swing", f"Your income moves about {_pct(moved)} month to month", 1))
        if sources <= 1:
            fired.append(Fired("one_source", "All of it comes from one source", 1))
        empty = sum(1 for i in incomes if i <= 0)
        if empty:
            fired.append(Fired("no_income", f"{empty} month{'s' if empty != 1 else ''} with no income in the last "
                                            f"{len(incomes)}", 1))
        typical = mean(Decimal(i) for i in incomes)
        if typical > 0 and debt / typical > DEBT_HEAVY:
            fired.append(Fired("debt", f"Debt payments take about {_pct(debt / typical)} of your income", 1))
    if dependents == "1-2":
        fired.append(Fired("dependents", "One or two people depend on you", 1))
    elif dependents == "3+":
        fired.append(Fired("dependents", "Three or more people depend on you", 2))
    if earners == "2+":
        fired.append(Fired("earners", "Someone else at home earns too", -1))

    months = sum(f.months for f in fired)
    clamped = min(max(months, MIN_MONTHS), MAX_MONTHS)
    if clamped != months:
        fired.append(Fired("clamp", f"Kept between {MIN_MONTHS} and {MAX_MONTHS} months", clamped - months))
    return Target(clamped, fired, short)


def _pct(ratio: Decimal) -> str:
    return f"{int((ratio * 100).to_integral_value())}%"


def cover(money: Decimal, essential: Decimal) -> Tuple[Decimal, bool]:
    """(months the money lasts, to one place; whether there is anything to measure against)."""
    if essential <= 0:
        return Decimal(0), False
    return (money / essential).quantize(Decimal("0.1")), True
