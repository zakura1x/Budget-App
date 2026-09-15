"""
projection_service - the months ahead (REC-21..26; FEATURES.md §20; ARCHITECTURE.md §4.5).

READ-ONLY. It never posts and never stores: every figure is computed on
request from the rules, the budget and today's cash on hand. It imports
recurring_service, account_service and budget_service; nothing imports it.

ONE SCHEDULE (REC-22). The dated items come from recurring_service.upcoming(),
the same occurrences() expansion posts from - so when a month arrives, what
posts is what was projected, unless a rule changed in between.

PER MONTH, from cash on hand today:

    income     = income occurrences into counted accounts (ACC-18)
    committed  = expense occurrences on counted accounts - cards included (§19)
    transfers  = net: into an uncounted account takes cash on hand away,
                 out of one brings it back, between two counted ones is nothing
    spending   = max(budget, committed)                                REC-23
    closing    = opening + income - spending + transfers -> next opening
    low point  = the lowest running balance, with the flexible part of the
                 budget (spending - committed) set aside on day 1      REC-24

The CURRENT month counts only what is still to come: occurrences after today,
and what is left of the budget period. A "month" is the budget period when the
budget is monthly (a 25th start day included); otherwise a calendar month with
the budget pro-rated by days. Carry-over is ignored. Paused occurrences are
listed and left out of every total (REC-26).

THE CARD LOOK-AHEAD (REC-25) groups each card's recurring charges by statement.
The bill is shown, never subtracted from cash on hand a second time - the
charges already were, on the days they post.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import ValidationException
from app.core.utils.date_utils import add_months, days_in_month, statement_period
from app.core.utils.money import ZERO, total
from app.services import account_service, recurring_service, transaction_service
from app.services.budget_service import budget_service
from app.services.recurring_service import Upcoming

ONE_DAY = timedelta(days=1)
RATIO = Decimal("0.0001")
MONTH_CHOICES = (3, 6, 12)


@dataclass(frozen=True)
class ProjectedItem:
    on: date
    rule_id: int
    name: str
    kind: str
    type: str
    account_id: int
    counter_account_id: Optional[int]
    amount: Decimal
    effect: Decimal  # on cash on hand: signed, 0 when no counted account is involved
    paused: bool
    final: bool


@dataclass(frozen=True)
class ProjectedMonth:
    start: date
    end: date
    current: bool
    opening: Decimal
    income: Decimal
    committed: Decimal
    transfers: Decimal
    budget: Decimal  # the budget for the month; for the current one, what is left of it
    spending: Decimal
    closing: Decimal
    low_point: Decimal
    low_on: date
    overcommitted: bool  # committed charges alone exceed the budget (REC-23)
    items: List[ProjectedItem]


@dataclass(frozen=True)
class Projection:
    today: date
    basis: str  # "budget" - months are budget periods - or "calendar"
    cash_on_hand: Decimal
    months: List[ProjectedMonth]


@dataclass(frozen=True)
class CardStatement:
    start: date
    closes: date
    due: date
    posted: Decimal  # already on the open statement: purchases minus refunds
    recurring: Decimal  # the recurring charges still to land on it
    total: Decimal
    limit_share: Optional[Decimal]  # recurring / your own spending limit (ACC-21)
    items: List[ProjectedItem]


@dataclass(frozen=True)
class CardLookahead:
    account_id: int
    name: str
    spending_limit: Optional[Decimal]
    statements: List[CardStatement]


def project(db: Session, cipher: UserCipher, *, today: Optional[date] = None, months: int = 12) -> Projection:
    today = today or date.today()
    if months not in MONTH_CHOICES:
        raise ValidationException("months is 3, 6 or 12")

    status = budget_service.status(db, cipher, today=today)
    monthly = status is not None and status.budget.period == "monthly"
    windows = _windows(db, cipher, today, months, monthly)

    views = account_service.list_accounts(db, cipher, postings=transaction_service.postings(db, cipher), today=today)
    cash = account_service.cash_on_hand(views)
    counted: Set[int] = set(cash.account_ids)
    ahead = recurring_service.upcoming(db, cipher, today + ONE_DAY, windows[-1][1])

    result: List[ProjectedMonth] = []
    opening = cash.total
    for index, (start, end) in enumerate(windows):
        current = index == 0
        items = [_item(u, counted) for u in ahead if start <= u.on <= end]
        live = [i for i in items if not i.paused]

        income = total(i.effect for i in live if i.type == "income")
        committed = total(-i.effect for i in live if i.type == "expense")
        transfers = total(i.effect for i in live if i.type == "transfer")
        if current and monthly:
            budget = max(status.allowance.remaining, ZERO)
        else:
            budget = budget_service.budget_between(db, cipher, today if current else start, end)
        spending = max(budget, committed)
        closing = opening + income - spending + transfers

        running = opening - (spending - committed)
        low, low_on = running, today if current else start
        # Same day: the money going out first - the cautious reading.
        for item in sorted(live, key=lambda i: (i.on, i.effect >= ZERO)):
            running += item.effect
            if running < low:
                low, low_on = running, item.on

        result.append(ProjectedMonth(
            start=start, end=end, current=current, opening=opening, income=income, committed=committed,
            transfers=transfers, budget=budget, spending=spending, closing=closing, low_point=low,
            low_on=low_on, overcommitted=committed > budget, items=items,
        ))
        opening = closing
    return Projection(today=today, basis="budget" if monthly else "calendar", cash_on_hand=cash.total, months=result)


def cards(db: Session, cipher: UserCipher, *, today: Optional[date] = None, statements: int = 6) -> List[CardLookahead]:
    today = today or date.today()
    if not 1 <= statements <= 12:
        raise ValidationException("statements is 1-12")
    views = account_service.list_accounts(db, cipher, postings=transaction_service.postings(db, cipher),
                                          today=today, include_archived=False)
    credit = [v for v in views if v.credit is not None]
    if not credit:
        return []

    periods = {}
    for view in credit:
        period = statement_period(today, view.credit.statement_closing_day, view.credit.payment_due_day)
        chain = []
        for _ in range(statements):
            chain.append(period)
            period = statement_period(period.closes + ONE_DAY, view.credit.statement_closing_day,
                                      view.credit.payment_due_day)
        periods[view.id] = chain
    horizon = max(chain[-1].closes for chain in periods.values())
    ahead = recurring_service.upcoming(db, cipher, today + ONE_DAY, horizon)

    result: List[CardLookahead] = []
    for view in credit:
        own = view.credit.spending_limit
        cards_statements: List[CardStatement] = []
        for index, period in enumerate(periods[view.id]):
            items = [_item(u, set()) for u in ahead
                     if u.account_id == view.id and u.type == "expense" and period.start <= u.on <= period.closes]
            recurring = total(i.amount for i in items if not i.paused)
            posted = view.credit.limit_spent if index == 0 else ZERO
            cards_statements.append(CardStatement(
                start=period.start, closes=period.closes, due=period.due, posted=posted, recurring=recurring,
                total=posted + recurring,
                limit_share=(recurring / own).quantize(RATIO, rounding=ROUND_HALF_UP) if own else None,
                items=items,
            ))
        result.append(CardLookahead(view.id, view.name, own, cards_statements))
    return result


def _item(upcoming: Upcoming, counted: Set[int]) -> ProjectedItem:
    amount = upcoming.amount
    if upcoming.type == "income":
        effect = amount if upcoming.account_id in counted else ZERO
    elif upcoming.type == "expense":
        effect = -amount if upcoming.account_id in counted else ZERO
    else:
        out_counted = upcoming.account_id in counted
        in_counted = upcoming.counter_account_id in counted
        effect = -amount if out_counted and not in_counted else amount if in_counted and not out_counted else ZERO
    return ProjectedItem(
        on=upcoming.on, rule_id=upcoming.rule_id, name=upcoming.name, kind=upcoming.kind, type=upcoming.type,
        account_id=upcoming.account_id, counter_account_id=upcoming.counter_account_id, amount=amount,
        effect=effect, paused=upcoming.occurrence.paused, final=upcoming.occurrence.final,
    )


def _windows(db: Session, cipher: UserCipher, today: date, count: int, monthly: bool) -> List[Tuple[date, date]]:
    windows: List[Tuple[date, date]] = []
    if monthly:
        period = budget_service.period_for(db, cipher, today)
        for _ in range(count):
            windows.append((period.start, period.end))
            period = budget_service.period_for(db, cipher, period.end + ONE_DAY)
        return windows
    start = date(today.year, today.month, 1)
    for _ in range(count):
        windows.append((start, date(start.year, start.month, days_in_month(start.year, start.month))))
        start = add_months(start, 1)
    return windows
