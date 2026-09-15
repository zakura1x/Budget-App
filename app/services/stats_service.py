"""
stats_service - every chart figure in the app, computed in Python over the
warm working set (STA-01..STA-11, TXN-10). SQL can compute none of it: every
amount, date and category is inside a ciphertext (ARCHITECTURE.md §4.3).

WHAT COUNTS, the same rules as the budget and the ledger:

  * SPENDING is expense SPLITS (TXN-16). A ₱3,500 receipt split ₱2,800
    groceries / ₱700 household puts ₱2,800 in one slice and ₱700 in the other.
    `transaction_count` on a slice counts TRANSACTIONS touching it, so that
    receipt is one transaction in each slice - and slice counts do not add up
    to the total count, on purpose.
  * INCOME is income splits.
  * A TRANSFER is neither (TXN-04).
  * A BALANCE ADJUSTMENT is neither (ACC-29). Losses and gains are reported
    only as their own totals, so the user can still see them.
  * An INVESTMENT REVALUATION is not a transaction at all (ACC-12) - it lives
    on the account - so nothing here can count it.
  * SPENDING BY TAG gives each tag the whole amount of every expense carrying
    it. A purchase tagged twice counts toward both, so tag totals can add up
    to more than spending; the screen says so.

THE RANGE (STA-09) is `from`..`to`, or a span around `on`: a calendar month,
a calendar year, or the budget period (a month when there is no budget).
The comparison (STA-04) is the range just before: the previous budget period,
the same number of whole months, or the same number of days. When the range
contains today it also reports the previous range's spending up to the same
day - "₱8,200 by this point last month" is the fair comparison mid-month.

THE FORECAST (STA-11) exists only while the range contains today: spending so
far, spread over the whole range at the rate it has run - "at this rate you
finish the month at ₱43,200". Past spending only; the months ahead, from
rules, are Phase 7's projection (REC-21). It reports the budget beside it when
the range is the budget period.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import ValidationException
from app.core.utils.date_utils import add_months, days_in_month
from app.core.utils.money import CENTS, ZERO, total
from app.db.repositories.category_repository import CategoryRepository
from app.services import transaction_service
from app.services.budget_service import budget_service
from app.services.transaction_service import TransactionView

SPANS = ("budget", "month", "year")
GRANULARITIES = ("day", "week", "month")
MAX_RANGE_DAYS = 366 * 5
TOP_MERCHANTS = 5
RATIO = Decimal("0.0001")


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Totals:
    spent: Decimal
    earned: Decimal
    net: Decimal  # earned - spent
    transaction_count: int  # expenses and income - what the totals are made of
    days: int
    days_counted: int  # days up to today, when the range runs past it
    average_daily_spend: Decimal  # STA-07, over days_counted
    adjustment_losses: Decimal  # ACC-29 - reported, never spending
    adjustment_gains: Decimal


@dataclass(frozen=True)
class CategoryShare:
    category_id: Optional[int]  # None only for a split whose category no longer exists
    amount: Decimal
    share: Decimal  # of total spending; a sub-category's is of its parent
    transaction_count: int
    previous_amount: Decimal = ZERO
    direct: Decimal = ZERO  # on the parent itself, not one of its sub-categories
    children: Tuple["CategoryShare", ...] = ()


@dataclass(frozen=True)
class Comparison:
    start: date
    end: date
    spent: Decimal
    earned: Decimal
    spent_to_same_day: Optional[Decimal]  # only while the current range contains today


@dataclass(frozen=True)
class TrendPoint:
    start: date
    end: date
    spent: Decimal
    earned: Decimal


@dataclass(frozen=True)
class MerchantTotal:
    name: str
    amount: Decimal
    transaction_count: int


@dataclass(frozen=True)
class AccountTotal:
    account_id: int
    spent: Decimal
    earned: Decimal


@dataclass(frozen=True)
class TagTotal:
    tag_id: int
    spent: Decimal
    transaction_count: int


@dataclass(frozen=True)
class Forecast:
    spent_to_date: Decimal
    days_elapsed: int  # including today
    days_left: int  # after today
    daily_rate: Decimal
    projected: Decimal
    budget_available: Optional[Decimal] = None  # when the range is the budget period


@dataclass(frozen=True)
class Overview:
    start: date
    end: date
    span: Optional[str]  # None for a custom from/to
    granularity: str
    totals: Totals
    categories: List[CategoryShare]
    income_categories: List[CategoryShare]
    previous: Comparison
    trend: List[TrendPoint]
    merchants: List[MerchantTotal]
    accounts: List[AccountTotal]
    tags: List[TagTotal]
    forecast: Optional[Forecast]


# ------------------------------------------------------ the pure arithmetic


def month_range(day: date) -> Tuple[date, date]:
    return date(day.year, day.month, 1), date(day.year, day.month, days_in_month(day.year, day.month))


def previous_range(start: date, end: date) -> Tuple[date, date]:
    """
    The range just before: the same number of whole calendar months when the
    range is whole months (so February compares with January, not with the
    last 28 days of it), otherwise the same number of days.
    """
    if start.day == 1 and end.day == days_in_month(end.year, end.month):
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        return add_months(start, -months), start - timedelta(days=1)
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def auto_granularity(start: date, end: date) -> str:
    days = (end - start).days + 1
    if days <= 45:
        return "day"
    if days <= 190:
        return "week"
    return "month"


def buckets(start: date, end: date, granularity: str) -> List[Tuple[date, date]]:
    """Consecutive [start, end] pairs tiling the range - weeks count from `start`, months are calendar months."""
    result: List[Tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if granularity == "day":
            last = cursor
        elif granularity == "week":
            last = cursor + timedelta(days=6)
        else:
            last = date(cursor.year, cursor.month, days_in_month(cursor.year, cursor.month))
        last = min(last, end)
        result.append((cursor, last))
        cursor = last + timedelta(days=1)
    return result


def forecast(
    spent_to_date: Decimal, start: date, end: date, today: date, budget_available: Optional[Decimal] = None
) -> Optional[Forecast]:
    """STA-11. Spending so far, run at the same daily rate to the end of the range - or None if today is outside it."""
    if not start <= today <= end:
        return None
    elapsed = (today - start).days + 1
    length = (end - start).days + 1
    return Forecast(
        spent_to_date=spent_to_date,
        days_elapsed=elapsed,
        days_left=length - elapsed,
        daily_rate=(spent_to_date / elapsed).quantize(CENTS, rounding=ROUND_HALF_UP),
        # From the unrounded rate, so the centavo lost rounding it is not multiplied by 30.
        projected=(spent_to_date * length / elapsed).quantize(CENTS, rounding=ROUND_HALF_UP),
        budget_available=budget_available,
    )


def category_shares(
    views: Sequence[TransactionView],
    parents: Mapping[int, Optional[int]],
    previous: Sequence[TransactionView] = (),
) -> List[CategoryShare]:
    """
    STA-01/02/04. The splits of `views` rolled up to their top-level category,
    each with its sub-categories nested for the drill-down. `parents` maps
    every existing category id to its parent id (None for a main one).
    """
    now = _roll_up(views, parents)
    before = _roll_up(previous, parents)
    grand = total(now.tops.values())

    shares: List[CategoryShare] = []
    for top, amount in now.tops.items():
        children = tuple(sorted(
            (
                CategoryShare(
                    category_id=child,
                    amount=child_amount,
                    share=_ratio(child_amount, amount),
                    transaction_count=len(now.child_txns[child]),
                    previous_amount=before.children.get(top, {}).get(child, ZERO),
                )
                for child, child_amount in now.children.get(top, {}).items()
            ),
            key=_largest_first,
        ))
        shares.append(CategoryShare(
            category_id=top,
            amount=amount,
            share=_ratio(amount, grand),
            transaction_count=len(now.top_txns[top]),
            previous_amount=before.tops.get(top, ZERO),
            direct=now.direct.get(top, ZERO),
            children=children,
        ))
    return sorted(shares, key=_largest_first)


# ------------------------------------------------------------ the overview


def overview(
    db: Session,
    cipher: UserCipher,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    span: Optional[str] = None,
    on: Optional[date] = None,
    today: Optional[date] = None,
    granularity: Optional[str] = None,
) -> Overview:
    today = today or date.today()
    start, end, span, prev = _resolve_range(db, cipher, date_from, date_to, span, on or today)
    granularity = granularity or auto_granularity(start, end)
    if granularity not in GRANULARITIES:
        raise ValidationException(f"granularity must be one of: {', '.join(GRANULARITIES)}")
    prev_start, prev_end = prev

    current: List[TransactionView] = []
    earlier: List[TransactionView] = []
    for view in transaction_service.views(db, cipher):
        if start <= view.txn_date <= end:
            current.append(view)
        elif prev_start <= view.txn_date <= prev_end:
            earlier.append(view)

    expenses = [v for v in current if v.type == "expense"]
    incomes = [v for v in current if v.type == "income"]
    earlier_expenses = [v for v in earlier if v.type == "expense"]
    parents = _parents(db, cipher)

    contains_today = start <= today <= end
    counted_to = min(end, today) if start <= today else end
    days_counted = (counted_to - start).days + 1
    spent = total(v.amount for v in expenses)
    counted_spent = total(v.amount for v in expenses if v.txn_date <= counted_to)

    totals = Totals(
        spent=spent,
        earned=total(v.amount for v in incomes),
        net=total(v.amount for v in incomes) - spent,
        transaction_count=len(expenses) + len(incomes),
        days=(end - start).days + 1,
        days_counted=days_counted,
        average_daily_spend=(counted_spent / days_counted).quantize(CENTS, rounding=ROUND_HALF_UP),
        adjustment_losses=total(v.amount for v in current if v.type == "adjustment" and v.direction == "out"),
        adjustment_gains=total(v.amount for v in current if v.type == "adjustment" and v.direction == "in"),
    )

    same_day = None
    if contains_today:
        cut = min(prev_start + (today - start), prev_end)
        same_day = total(v.amount for v in earlier_expenses if v.txn_date <= cut)
    previous = Comparison(
        start=prev_start, end=prev_end,
        spent=total(v.amount for v in earlier_expenses),
        earned=total(v.amount for v in earlier if v.type == "income"),
        spent_to_same_day=same_day,
    )

    return Overview(
        start=start,
        end=end,
        span=span,
        granularity=granularity,
        totals=totals,
        categories=category_shares(expenses, parents, earlier_expenses),
        income_categories=category_shares(incomes, parents),
        previous=previous,
        trend=_trend(expenses, incomes, start, end, granularity),
        merchants=_merchants(expenses),
        accounts=_accounts(expenses, incomes),
        tags=_tags(expenses),
        forecast=_forecast(db, cipher, counted_spent, start, end, today) if contains_today else None,
    )


# ---------------------------------------------------------------- internals


@dataclass
class _Rolled:
    tops: Dict[Optional[int], Decimal]
    top_txns: Dict[Optional[int], Set[int]]
    children: Dict[Optional[int], Dict[int, Decimal]]
    child_txns: Dict[int, Set[int]]
    direct: Dict[Optional[int], Decimal]


def _roll_up(views: Iterable[TransactionView], parents: Mapping[int, Optional[int]]) -> _Rolled:
    rolled = _Rolled({}, {}, {}, {}, {})
    for view in views:
        for split in view.splits:
            category = split.category_id if split.category_id in parents else None
            parent = parents.get(category) if category is not None else None
            top = parent if parent is not None else category
            rolled.tops[top] = rolled.tops.get(top, ZERO) + split.amount
            rolled.top_txns.setdefault(top, set()).add(view.id)
            if parent is not None:
                under = rolled.children.setdefault(top, {})
                under[category] = under.get(category, ZERO) + split.amount
                rolled.child_txns.setdefault(category, set()).add(view.id)
            else:
                rolled.direct[top] = rolled.direct.get(top, ZERO) + split.amount
    return rolled


def _parents(db: Session, cipher: UserCipher) -> Dict[int, Optional[int]]:
    records = CategoryRepository(db, cipher).list()
    ids = {record.id for record in records}
    # A parent that no longer exists makes its child a main category, as the tree does.
    return {
        record.id: record.data.get("parent_id") if record.data.get("parent_id") in ids else None
        for record in records
    }


def _resolve_range(
    db: Session,
    cipher: UserCipher,
    date_from: Optional[date],
    date_to: Optional[date],
    span: Optional[str],
    on: date,
) -> Tuple[date, date, Optional[str], Tuple[date, date]]:
    if date_from is not None or date_to is not None:
        if date_from is None or date_to is None:
            raise ValidationException("A custom range needs both from and to")
        if date_from > date_to:
            raise ValidationException("The range ends before it starts")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise ValidationException("A range is at most five years")
        return date_from, date_to, None, previous_range(date_from, date_to)

    span = span or "month"
    if span not in SPANS:
        raise ValidationException(f"span must be one of: {', '.join(SPANS)}")
    if span == "budget":
        period = budget_service.period_for(db, cipher, on)
        if period is not None:
            before = budget_service.period_for(db, cipher, period.start - timedelta(days=1))
            return period.start, period.end, "budget", (before.start, before.end)
        span = "month"  # no budget: the calendar month stands in
    if span == "year":
        start, end = date(on.year, 1, 1), date(on.year, 12, 31)
    else:
        start, end = month_range(on)
    return start, end, span, previous_range(start, end)


def _forecast(
    db: Session, cipher: UserCipher, spent_to_date: Decimal, start: date, end: date, today: date
) -> Optional[Forecast]:
    status = budget_service.status(db, cipher, today=today)
    available = None
    if status is not None and (status.period.start, status.period.end) == (start, end):
        available = status.allowance.available
    return forecast(spent_to_date, start, end, today, available)


def _trend(
    expenses: Sequence[TransactionView], incomes: Sequence[TransactionView], start: date, end: date, granularity: str
) -> List[TrendPoint]:
    spent: Dict[date, Decimal] = {}
    earned: Dict[date, Decimal] = {}
    for view in expenses:
        spent[view.txn_date] = spent.get(view.txn_date, ZERO) + view.amount
    for view in incomes:
        earned[view.txn_date] = earned.get(view.txn_date, ZERO) + view.amount
    return [
        TrendPoint(
            start=first, end=last,
            spent=total(amount for day, amount in spent.items() if first <= day <= last),
            earned=total(amount for day, amount in earned.items() if first <= day <= last),
        )
        for first, last in buckets(start, end, granularity)
    ]


def _merchants(expenses: Sequence[TransactionView]) -> List[MerchantTotal]:
    """STA-06. "Jollibee", "jollibee " and "JOLLIBEE" are one merchant, shown as most recently typed."""
    groups: Dict[str, List[TransactionView]] = {}
    for view in expenses:
        name = " ".join((view.merchant or "").split())
        if name:
            groups.setdefault(name.casefold(), []).append(view)
    merchants = [
        MerchantTotal(
            name=" ".join((max(views, key=lambda v: (v.txn_date, v.id)).merchant or "").split()),
            amount=total(v.amount for v in views),
            transaction_count=len(views),
        )
        for views in groups.values()
    ]
    return sorted(merchants, key=lambda m: (-m.amount, m.name.casefold()))[:TOP_MERCHANTS]


def _accounts(expenses: Sequence[TransactionView], incomes: Sequence[TransactionView]) -> List[AccountTotal]:
    """STA-08."""
    spent: Dict[int, Decimal] = {}
    earned: Dict[int, Decimal] = {}
    for view in expenses:
        spent[view.account_id] = spent.get(view.account_id, ZERO) + view.amount
    for view in incomes:
        earned[view.account_id] = earned.get(view.account_id, ZERO) + view.amount
    rows = [AccountTotal(a, spent.get(a, ZERO), earned.get(a, ZERO)) for a in set(spent) | set(earned)]
    return sorted(rows, key=lambda r: (-r.spent, -r.earned, r.account_id))


def _tags(expenses: Sequence[TransactionView]) -> List[TagTotal]:
    """TXN-10. Each tag gets the whole amount of every expense that carries it."""
    spent: Dict[int, Decimal] = {}
    counts: Dict[int, int] = {}
    for view in expenses:
        for tag_id in set(view.tag_ids):
            spent[tag_id] = spent.get(tag_id, ZERO) + view.amount
            counts[tag_id] = counts.get(tag_id, 0) + 1
    rows = [TagTotal(tag_id, amount, counts[tag_id]) for tag_id, amount in spent.items()]
    return sorted(rows, key=lambda r: (-r.spent, r.tag_id))


def _ratio(part: Decimal, whole: Decimal) -> Decimal:
    return (part / whole).quantize(RATIO, rounding=ROUND_HALF_UP) if whole > ZERO else Decimal("0.0000")


def _largest_first(share: CategoryShare):
    return (-share.amount, share.category_id is None, share.category_id or 0)
