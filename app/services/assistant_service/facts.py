"""
What a skill hands back: finished facts, never raw numbers (misc/AI ARCHITECTURE §5.1).

Every figure a reply may show is already formatted here - `php()` for money,
`day()` for dates, `pct()` for shares - so the model copies text instead of
doing arithmetic, and the verifier can check each figure in its reply against
these lines (AI-06, AI-07). `template` is the reply given without the model
(AI-08): it must read well on its own.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from app.core.utils.money import CENTS


@dataclass(frozen=True)
class Source:
    """Where a fact came from - a screen the user can open (AI-16)."""

    label: str
    route: str


@dataclass(frozen=True)
class Action:
    """A button under a reply. A2 only navigates; A4 adds drafts (ARCHITECTURE §8)."""

    kind: str  # open_screen
    label: str
    route: str


@dataclass
class Facts:
    skill: str
    title: str  # what the facts are about, e.g. "Budget, 1 Oct - 31 Oct"
    lines: List[str]
    template: str
    sources: List[Source] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    # ok | warn | danger - money state, the only meaning those tokens have (CLAUDE.md, Design)
    tone: Optional[str] = None
    # False: answer with the template and never call the model (off-topic, a clarifying question)
    phrase: bool = True
    follow_ups: List[str] = field(default_factory=list)


def php(amount: Decimal) -> str:
    """₱1,234.50 - and -₱1,234.50. The one money format every fact uses."""
    value = Decimal(amount).quantize(CENTS, rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    return f"{sign}₱{abs(value):,.2f}"


def day(value: date, today: Optional[date] = None) -> str:
    """8 Oct - with the year only when it is not this year's."""
    text = f"{value.day} {value.strftime('%b')}"
    if today is not None and value.year != today.year:
        text += f" {value.year}"
    return text


def pct(ratio: Decimal) -> str:
    """0.853 -> 85%. Whole percents only: a share is a feel, not a figure to add up."""
    return f"{int((Decimal(ratio) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))}%"


def days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def names(items: List[str]) -> str:
    """a, b and c"""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
