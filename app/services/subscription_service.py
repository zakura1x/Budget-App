"""
subscription_service - your Netflix, Spotify and gym charges (SUB-00..08).

A VIEW, NOT AN ENGINE (SUB-00). A subscription is a recurring rule of kind
`subscription`; recurring_service creates, schedules and posts it, and keeps
its reminder days. This module only reads: the monthly total, the upcoming
charges, the reminders, and the price history - which is the rule's own amount
history (SUB-08, REC-20), not a second list that could disagree.

DETECTION (SUB-03) PROPOSES, NEVER STARTS CHARGING. It looks for the same
merchant, the same amount, on the same account, in at least three months about
a month apart, that no rule already covers. Confirming one is an ordinary
POST /recurring - a step the user takes.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.utils.date_utils import add_months
from app.core.utils.money import CENTS, ZERO, total
from app.services import recurring_service, transaction_service
from app.services.budget_service import budget_service
from app.services.recurring_service import RuleView

# Occurrences per month, per frequency - to state every subscription as a monthly figure.
PER_MONTH: Dict[str, Decimal] = {
    "daily": Decimal(365) / Decimal(12),
    "weekly": Decimal(52) / Decimal(12),
    "semi_monthly": Decimal(2),
    "monthly": Decimal(1),
    "yearly": Decimal(1) / Decimal(12),
}
UPCOMING_DAYS = 30
DETECT_LOOKBACK_DAYS = 190
DETECT_MIN_MONTHS = 3
RATIO = Decimal("0.0001")


@dataclass(frozen=True)
class SubscriptionView:
    rule: RuleView
    monthly: Decimal  # what it costs in an average month
    due_in_days: Optional[int]
    remind: bool  # the next charge is within its reminder days (SUB-06)


@dataclass(frozen=True)
class UpcomingCharge:
    rule_id: int
    name: str
    on: date
    amount: Decimal
    account_id: int


@dataclass(frozen=True)
class SubscriptionOverview:
    items: List[SubscriptionView]
    monthly_total: Decimal  # SUB-05 - active subscriptions only
    budget_share: Optional[Decimal]  # of this month's budget; None with no budget
    upcoming: List[UpcomingCharge]  # SUB-04 - the next 30 days


@dataclass(frozen=True)
class Candidate:
    """A repeating charge that looks like a subscription nobody has told the app about."""

    merchant: str
    amount: Decimal
    account_id: int
    category_id: Optional[int]
    months: int
    last_on: date
    next_on: date
    transaction_ids: Tuple[int, ...]


def overview(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> SubscriptionOverview:
    today = today or date.today()
    rules = recurring_service.list_rules(db, cipher, today=today, kind="subscription")
    items = [_item(rule, today) for rule in rules]

    active = [i for i in items if not i.rule.paused and (i.rule.end_on is None or i.rule.end_on >= today)]
    monthly_total = total(i.monthly for i in active)
    month_start = date(today.year, today.month, 1)
    budget = budget_service.budget_between(db, cipher, month_start, add_months(month_start, 1) - timedelta(days=1))
    share = (monthly_total / budget).quantize(RATIO, rounding=ROUND_HALF_UP) if budget > ZERO else None

    ids = {rule.id for rule in rules}
    upcoming = [
        UpcomingCharge(u.rule_id, u.name, u.on, u.amount, u.account_id)
        for u in recurring_service.upcoming(db, cipher, today, today + timedelta(days=UPCOMING_DAYS))
        if u.rule_id in ids and not u.occurrence.paused
    ]
    return SubscriptionOverview(items=items, monthly_total=monthly_total, budget_share=share, upcoming=upcoming)


def reminders(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[SubscriptionView]:
    """SUB-06. Subscriptions charging within their reminder days - shown in-app on the next open, never pushed."""
    today = today or date.today()
    return [
        item for item in (_item(rule, today) for rule in recurring_service.list_rules(db, cipher, today=today,
                                                                                     kind="subscription"))
        if item.remind
    ]


def detected(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[Candidate]:
    """SUB-03. Proposals only - nothing here writes."""
    today = today or date.today()
    since = today - timedelta(days=DETECT_LOOKBACK_DAYS)
    covered = {
        (" ".join((rule.merchant or rule.name).split()).casefold(), rule.account_id)
        for rule in recurring_service.list_rules(db, cipher, today=today)
    }

    groups: Dict[Tuple[str, Decimal, int], List[transaction_service.TransactionView]] = {}
    for view in transaction_service.views(db, cipher):
        name = " ".join((view.merchant or "").split())
        if view.type != "expense" or not name or view.recurring_id is not None or view.txn_date < since:
            continue
        groups.setdefault((name.casefold(), view.amount, view.account_id), []).append(view)

    found: List[Candidate] = []
    for (key, amount, account_id), views in groups.items():
        if (key, account_id) in covered:
            continue
        views.sort(key=lambda v: (v.txn_date, v.id))
        months = {(v.txn_date.year, v.txn_date.month) for v in views}
        if len(months) < DETECT_MIN_MONTHS:
            continue
        gaps = [(b.txn_date - a.txn_date).days for a, b in zip(views, views[1:])]
        if any(not 25 <= gap <= 35 for gap in gaps):
            continue  # not about a month apart - a habit, not a subscription
        last = views[-1]
        found.append(Candidate(
            merchant=" ".join((last.merchant or "").split()),
            amount=amount,
            account_id=account_id,
            category_id=last.splits[0].category_id if last.splits else None,
            months=len(months),
            last_on=last.txn_date,
            next_on=add_months(last.txn_date, 1),
            transaction_ids=tuple(v.id for v in views),
        ))
    return sorted(found, key=lambda c: (-c.amount, c.merchant.casefold()))


def _item(rule: RuleView, today: date) -> SubscriptionView:
    monthly = (rule.amount * PER_MONTH.get(rule.frequency, Decimal(1)) / rule.interval).quantize(
        CENTS, rounding=ROUND_HALF_UP)
    due = (rule.next_on - today).days if rule.next_on else None
    remind = due is not None and 0 <= due <= (rule.reminder_days or 0) and not rule.paused
    return SubscriptionView(rule=rule, monthly=monthly, due_in_days=due, remind=remind)
