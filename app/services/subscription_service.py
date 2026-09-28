"""
subscription_service - your Netflix, Spotify and gym charges (SUB-00..08).

A VIEW, NOT AN ENGINE (SUB-00). A subscription is a recurring rule of kind
`subscription`; recurring_service creates, schedules and posts it, and keeps
its reminder days. This module only reads: the monthly total, the upcoming
charges, the reminders, and the price history - which is the rule's own amount
history (SUB-08, REC-20), not a second list that could disagree.

CANCELLING (SUB-07) is recurring_service's write - it ends the rule, which is
the engine's - and this module reads the result: a Cancelled list, what each
would have cost since (`saved_since`, replayed through the one schedule), and
a reminder when a "cancel by" date (a free trial) comes near.

DETECTION (SUB-03) PROPOSES, NEVER STARTS CHARGING. It looks for the same
merchant, the same amount, on the same account, in at least three months about
a month apart, that no rule already covers. Confirming one is an ordinary
POST /recurring - a step the user takes.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.utils.date_utils import add_months
from app.core.utils.money import CENTS, ZERO, total
from app.db.repositories.recurring_repository import RecurringRuleRepository, SubscriptionRepository
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
    # SUB-07. Cancelled on a day, and what it would have charged since - from
    # the one schedule, as if it had carried on. A date you mean to cancel by
    # (a free trial) is reminded like a charge.
    cancelled_on: Optional[date] = None
    saved: Decimal = ZERO
    cancel_by: Optional[date] = None
    cancel_by_in_days: Optional[int] = None
    cancel_soon: bool = False


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
    extra = _extras(db, cipher)
    items = [_item(rule, today, extra.get(rule.id)) for rule in rules]

    active = [i for i in items if not i.rule.paused and i.cancelled_on is None
              and (i.rule.end_on is None or i.rule.end_on >= today)]
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
    """
    SUB-06/07. Subscriptions charging within their reminder days, and ones due
    to be cancelled within them - shown in-app on the next open, never pushed.
    """
    today = today or date.today()
    extra = _extras(db, cipher)
    return [
        item for item in (_item(rule, today, extra.get(rule.id))
                          for rule in recurring_service.list_rules(db, cipher, today=today, kind="subscription"))
        if item.remind or item.cancel_soon
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


@dataclass(frozen=True)
class _Extra:
    """What the subscriptions row adds to its rule (SUB-07), with the rule's own payload to replay."""

    rule_data: Mapping[str, Any]
    cancelled_on: Optional[date]
    end_on_before: Optional[str]
    cancel_by: Optional[date]
    posted: FrozenSet[date] = frozenset()  # occurrences that DID post - a cancellation entered late


def _extras(db: Session, cipher: UserCipher) -> Dict[int, _Extra]:
    rules = {r.id: r.data for r in RecurringRuleRepository(db, cipher).list()}
    posted: Dict[int, Set[date]] = {}
    for view in transaction_service.views(db, cipher):
        if view.recurring_id in rules and view.recurring_on is not None:
            posted.setdefault(view.recurring_id, set()).add(view.recurring_on)
    found: Dict[int, _Extra] = {}
    for sub in SubscriptionRepository(db, cipher).list():
        rule_id = int(sub.data["recurring_rule_id"])
        if rule_id not in rules:
            continue
        data = sub.data
        found[rule_id] = _Extra(
            rule_data=rules[rule_id],
            cancelled_on=date.fromisoformat(data["cancelled_on"]) if data.get("cancelled_on") else None,
            end_on_before=data.get("end_on_before_cancel"),
            cancel_by=date.fromisoformat(data["cancel_by"]) if data.get("cancel_by") else None,
            posted=frozenset(posted.get(rule_id, ())),
        )
    return found


def saved_since(rule_id: int, rule_data: Mapping[str, Any], cancelled_on: date, end_on_before: Optional[str],
                today: date, posted: FrozenSet[date] = frozenset()) -> Decimal:
    """
    SUB-07. What a cancelled subscription would have charged from the day
    after it was cancelled to today, had it carried on - its schedule replayed
    through THE engine (recurring_service.occurrences) with the cancellation
    taken back out, never a date rule of its own. Paused dates are not money,
    and neither is saved a charge that DID post (`posted`): a cancellation
    entered late leaves those charges standing, because they were real.
    """
    if today <= cancelled_on:
        return ZERO
    carried_on = {**rule_data, "end_on": end_on_before}
    missed = recurring_service.occurrences(rule_id, carried_on, cancelled_on + timedelta(days=1), today)
    return total(o.amount for o in missed if not o.paused and o.on not in posted)


def _item(rule: RuleView, today: date, extra: Optional[_Extra] = None) -> SubscriptionView:
    monthly = (rule.amount * PER_MONTH.get(rule.frequency, Decimal(1)) / rule.interval).quantize(
        CENTS, rounding=ROUND_HALF_UP)
    cancelled_on = extra.cancelled_on if extra else None
    due = (rule.next_on - today).days if rule.next_on and cancelled_on is None else None
    remind = due is not None and 0 <= due <= (rule.reminder_days or 0) and not rule.paused
    saved = (saved_since(rule.id, extra.rule_data, cancelled_on, extra.end_on_before, today, extra.posted)
             if extra and cancelled_on else ZERO)
    cancel_by = extra.cancel_by if extra and cancelled_on is None else None
    by_in = (cancel_by - today).days if cancel_by else None
    # Reminded from its reminder days before, and every day after until it is done or the date is cleared.
    cancel_soon = by_in is not None and by_in <= max(rule.reminder_days or 0, 1)
    return SubscriptionView(rule=rule, monthly=monthly, due_in_days=due, remind=remind,
                            cancelled_on=cancelled_on, saved=saved, cancel_by=cancel_by,
                            cancel_by_in_days=max(by_in, 0) if by_in is not None else None, cancel_soon=cancel_soon)
