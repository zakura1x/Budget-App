"""
In-app alerts (BUD-12/14/15, ACC-15) - computed inside the user's own session.

There is no push (BUD-16). A sender that could tell you "you are over budget"
while you are not using the app would have to decrypt your transactions with
nobody signed in - a service holding keys outside a session, which is exactly
what ARCHITECTURE.md 5.5 rules out. So every alert here is worked out at the
moment you look, and returned in the same response as the figures it is about.

    over          spent has reached the period's money            danger
    approaching   spent has reached ALERT_WARN_THRESHOLD_PCT       warn
    pace          spent% is ahead of elapsed% by more than the     warn
                  tolerance - day 10 of 30 with 60% spent warns
                  while there is still time to act
    category_over one allocation is used up                        danger
    card_due      a credit card payment falls due soon (ACC-15)    warn

`over` supersedes `approaching` and `pace` - three banners saying one thing
is noise. Messages carry no figures; the client formats those from the status.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional

from app.core.utils.money import ZERO
from app.services.budget_service.allowance import Allowance


@dataclass(frozen=True)
class Alert:
    kind: str
    severity: str  # "danger" | "warn"
    message: str
    category_id: Optional[int] = None
    account_id: Optional[int] = None


@dataclass(frozen=True)
class CategoryUse:
    category_id: int
    allocated: Decimal
    spent: Decimal


@dataclass(frozen=True)
class CardDue:
    account_id: int
    due_in_days: int


def budget_alerts(
    allowance: Allowance,
    *,
    warn_pct: int = 80,
    pace_enabled: bool = True,
    pace_tolerance_pct: int = 10,
    categories: Iterable[CategoryUse] = (),
    category_level: bool = True,
    cards_due: Iterable[CardDue] = (),
) -> List[Alert]:
    alerts: List[Alert] = []
    available, spent = allowance.available, allowance.spent

    if spent > ZERO and spent >= available:
        alerts.append(Alert("over", "danger", "You have spent this period's budget"))
    else:
        if available > ZERO and spent * 100 >= available * warn_pct:
            alerts.append(Alert("approaching", "warn", f"You have used {warn_pct}% of this period's budget"))
        if (
            pace_enabled
            and available > ZERO
            and allowance.days_elapsed > 0
            and allowance.days_left > 0  # a finished period has no pace left to fix
        ):
            spent_pct = spent * 100 / available
            elapsed_pct = Decimal(allowance.days_elapsed * 100) / allowance.days_total
            if spent_pct > elapsed_pct + pace_tolerance_pct:
                alerts.append(Alert("pace", "warn", "You are spending faster than the period is passing"))

    if category_level:
        for use in categories:
            if use.allocated > ZERO and use.spent >= use.allocated:
                alerts.append(Alert("category_over", "danger", "This category is over its budget",
                                    category_id=use.category_id))

    for card in cards_due:
        when = "today" if card.due_in_days == 0 else f"in {card.due_in_days} day{'s' if card.due_in_days != 1 else ''}"
        alerts.append(Alert("card_due", "warn", f"A card payment is due {when}", account_id=card.account_id))

    return alerts
