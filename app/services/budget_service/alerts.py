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
    card_due      a card's bill is unpaid and falls due soon       warn
                  (ACC-15/20)
    card_limit_over         your own limit on a card is used up    danger
    card_limit_approaching  ALERT_WARN_THRESHOLD_PCT of it is used warn
    card_limit_pace         the card is being spent faster than    warn
                            its statement cycle is passing (ACC-22)
    subscription_due        a subscription charges within its      warn
                            reminder days (SUB-06)
    statement_differs       a card's last statement was checked    warn
                            against the bank and does not match
                            (ACC-24)

The account alerts - every kind from card_due down - come from
account_alerts(), and are raised whether or not a budget exists: someone who
only tracks a card still needs to hear that its bill is due (Phase 10).

The card-limit checks are the budget's own rules applied to a card's statement
cycle instead of the budget period - same threshold, same pace tolerance.

`over` supersedes `approaching` and `pace` - three banners saying one thing
is noise - and `card_limit_over` does the same for its card. Messages carry no
figures; the client formats those from the status. A subscription's message
names it, because nothing else in the status can.
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
    rule_id: Optional[int] = None


@dataclass(frozen=True)
class SubscriptionDue:
    """SUB-06. A subscription whose next charge is within its reminder days."""

    rule_id: int
    name: str
    account_id: int
    due_in_days: int


@dataclass(frozen=True)
class StatementDiffers:
    """ACC-24. A card whose last closed statement has a bank total that is not the app's."""

    account_id: int


@dataclass(frozen=True)
class CategoryUse:
    category_id: int
    allocated: Decimal
    spent: Decimal


@dataclass(frozen=True)
class CardDue:
    account_id: int
    due_in_days: int


@dataclass(frozen=True)
class CardLimit:
    """ACC-21/22. A card with your own spending limit, over its open statement cycle."""

    account_id: int
    limit: Decimal
    spent: Decimal  # purchases minus refunds this cycle
    days_elapsed: int  # including today
    days_total: int


def budget_alerts(
    allowance: Allowance,
    *,
    warn_pct: int = 80,
    pace_enabled: bool = True,
    pace_tolerance_pct: int = 10,
    categories: Iterable[CategoryUse] = (),
    category_level: bool = True,
    cards_due: Iterable[CardDue] = (),
    card_limits: Iterable[CardLimit] = (),
    subscriptions_due: Iterable[SubscriptionDue] = (),
    statements_differ: Iterable[StatementDiffers] = (),
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

    alerts.extend(account_alerts(
        cards_due=cards_due, card_limits=card_limits, subscriptions_due=subscriptions_due,
        statements_differ=statements_differ,
        warn_pct=warn_pct, pace_enabled=pace_enabled, pace_tolerance_pct=pace_tolerance_pct,
    ))
    return alerts


def _when(days: int) -> str:
    return "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"


def account_alerts(
    *,
    cards_due: Iterable[CardDue] = (),
    card_limits: Iterable[CardLimit] = (),
    subscriptions_due: Iterable[SubscriptionDue] = (),
    statements_differ: Iterable[StatementDiffers] = (),
    warn_pct: int = 80,
    pace_enabled: bool = True,
    pace_tolerance_pct: int = 10,
) -> List[Alert]:
    """The alerts about accounts rather than the budget - they need no budget to exist."""
    alerts: List[Alert] = []
    for card in card_limits:
        alerts.extend(card_limit_alerts(card, warn_pct=warn_pct, pace_enabled=pace_enabled,
                                        pace_tolerance_pct=pace_tolerance_pct))
    for card in cards_due:
        alerts.append(Alert("card_due", "warn", f"A card payment is due {_when(card.due_in_days)}",
                            account_id=card.account_id))
    for statement in statements_differ:
        alerts.append(Alert("statement_differs", "warn", "A card's statement does not match the bank's total",
                            account_id=statement.account_id))
    for sub in subscriptions_due:
        alerts.append(Alert("subscription_due", "warn", f"{sub.name} charges {_when(sub.due_in_days)}",
                            account_id=sub.account_id, rule_id=sub.rule_id))
    return alerts


def card_limit_alerts(
    card: CardLimit,
    *,
    warn_pct: int = 80,
    pace_enabled: bool = True,
    pace_tolerance_pct: int = 10,
) -> List[Alert]:
    """
    ACC-22. Day 14 of a 30-day cycle with 65% of the limit spent warns on pace:
    47% of the cycle has passed, and 65 is more than 10 points ahead of it.
    """
    if card.limit <= ZERO:
        return []
    if card.spent >= card.limit:
        return [Alert("card_limit_over", "danger", "This card is at its spending limit", account_id=card.account_id)]

    alerts: List[Alert] = []
    if card.spent * 100 >= card.limit * warn_pct:
        alerts.append(Alert("card_limit_approaching", "warn", f"You have used {warn_pct}% of this card's spending limit",
                            account_id=card.account_id))
    if pace_enabled and card.spent > ZERO and 0 < card.days_elapsed <= card.days_total:
        spent_pct = card.spent * 100 / card.limit
        elapsed_pct = Decimal(card.days_elapsed * 100) / card.days_total
        if spent_pct > elapsed_pct + pace_tolerance_pct:
            alerts.append(Alert("card_limit_pace", "warn", "This card is being spent faster than its cycle is passing",
                                account_id=card.account_id))
    return alerts
