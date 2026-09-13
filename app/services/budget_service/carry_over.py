"""
Carry-over (BUD-11) - a Settings toggle, default OFF (FEATURES.md §13-B).

When ON it is SYMMETRIC: a surplus rolls forward, and so does an overspend.
With a ₱10,000 weekly budget, spending ₱7,000 starts the next week at ₱13,000;
spending ₱12,000 starts it at ₱8,000. A positive-only version would drift
upward forever and stop meaning anything.

The carry into a period is computed, never stored: walk the periods from the
start of the chain, each one closing at `amount + carried in - spent`, and the
next opening with that. A stored running figure would drift the first time an
old transaction was edited, and nothing could notice.

The chain starts when the budget's period STRUCTURE last changed. Switching
from weekly to monthly makes the old weeks' closing positions meaningless for
the new months, so the new chain starts clean.

Pure: the caller supplies how much a period was budgeted and how much it spent.
"""

from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from app.core.utils.date_utils import BudgetPeriod
from app.core.utils.money import ZERO

# Ten years of weekly periods. Past this the chain is a bug, not a history.
MAX_PERIODS = 530


def carried_in(
    target: BudgetPeriod,
    chain_start: date,
    period_of: Callable[[date], BudgetPeriod],
    amount_for: Callable[[BudgetPeriod], Optional[Decimal]],
    spent_in: Callable[[BudgetPeriod], Decimal],
) -> Decimal:
    """
    The balance `target` opens with: the closing position of the period before
    it, which itself opened with the one before that - back to `chain_start`.
    A period with no budget in force closes at zero; the chain restarts there.
    """
    carry = ZERO
    period = period_of(chain_start)
    for _ in range(MAX_PERIODS):
        if period.start >= target.start:
            return carry
        amount = amount_for(period)
        carry = ZERO if amount is None else amount + carry - spent_in(period)
        period = period_of(_day_after(period.end))
    raise ValueError("carry-over chain is longer than any real budget history")


def _day_after(day: date) -> date:
    return date.fromordinal(day.toordinal() + 1)
