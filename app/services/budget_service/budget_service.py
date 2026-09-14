"""
The budget, its allocations, and the status the home screen is built from.

ONE BUDGET PER USER. Its payload:

    {"period": "monthly", "month_start_day": 25, "week_start_day": 1,
     "custom_days": null, "custom_anchor": null,
     "amounts": [{"from": "2026-09-01", "amount": "30000.00"},
                 {"from": "2026-09-13", "amount": "32000.00"}],
     "structure_from": "2026-08-25"}

  * THE AMOUNT KEEPS A DATED HISTORY. A period is budgeted with the latest
    amount set on or before its last day, so a mid-period change applies to
    the current period straight away and never rewrites a finished one -
    which matters, because carry-over replays finished periods.
  * THE STRUCTURE (period kind, start days) records when it last changed.
    Carry-over chains periods only from there (carry_over.py).
  * ALLOCATIONS STAY IN FORCE across periods until changed. That is BUD-13's
    purpose - starting a new period without retyping every category - with
    nothing to copy, because nothing was cleared.

Spending is the EXPENSE SPLITS inside the period (TXN-16), read from the working
set. Income does not raise a budget, a transfer is not spending, and a balance
adjustment - loss or gain - is neither (ACC-29, confirmed 2026-09-14), so none
of them is ever a Spend.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BusinessRuleException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.core.utils.date_utils import PERIOD_KINDS, BudgetPeriod, budget_period
from app.core.utils.money import ZERO, money, total
from app.db.repositories.budget_repository import (
    BudgetAllocationRepository,
    BudgetRepository,
)
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.preferences_repository import PreferencesRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import account_service, audit_service, transaction_service
from app.services.budget_service.alerts import (
    Alert,
    CardDue,
    CardLimit,
    CategoryUse,
    budget_alerts,
)
from app.services.budget_service.allowance import (
    MODES,
    Allowance,
    Spend,
    daily_allowance,
)
from app.services.budget_service.carry_over import carried_in

MAX_BUDGET = Decimal("999999999.99")


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class AllocationView:
    id: int
    category_id: int
    amount: Decimal


@dataclass(frozen=True)
class BudgetView:
    id: int
    period: str
    month_start_day: int
    week_start_day: int
    custom_days: Optional[int]
    custom_anchor: Optional[date]
    amount: Decimal  # the amount in force today
    structure_from: date
    allocations: Tuple[AllocationView, ...] = ()


@dataclass(frozen=True)
class CategoryProgress:
    category_id: int
    allocated: Decimal
    spent: Decimal
    remaining: Decimal
    used_ratio: Decimal
    over: bool


@dataclass(frozen=True)
class BudgetStatus:
    budget: BudgetView
    period: BudgetPeriod
    previous_period: BudgetPeriod
    next_period: BudgetPeriod
    is_current: bool
    carry_over: bool
    allowance: Allowance
    categories: List[CategoryProgress]
    allocated: Decimal
    unallocated: Decimal  # the period's amount minus every allocation; negative when over-allocated
    alerts: List[Alert] = field(default_factory=list)


# ------------------------------------------------------------------ reading


def get_budget(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Optional[BudgetView]:
    record = _current_record(db, cipher)
    if record is None:
        return None
    return _view(db, cipher, record, today or date.today())


def status(
    db: Session,
    cipher: UserCipher,
    *,
    today: Optional[date] = None,
    on: Optional[date] = None,
) -> Optional[BudgetStatus]:
    """
    The home screen's payload for the period containing `on` (today by
    default), seen from `today` - the client's own date, so "today" means the
    user's day and not the server's.
    """
    today = today or date.today()
    record = _current_record(db, cipher)
    if record is None:
        return None

    data = record.data
    budget = _view(db, cipher, record, today)
    period_of = _period_of(data)
    period = period_of(on or today)
    amount = _amount_for(data, period)

    prefs = _preferences(db, cipher)
    carry = bool(prefs.get("carry_over", settings.DEFAULT_CARRY_OVER_UNSPENT))
    mode = str(prefs.get("daily_allowance_mode") or settings.DAILY_ALLOWANCE_MODE)
    if mode not in MODES:
        mode = MODES[0]

    spends = _spends(db, cipher)
    carry_in = ZERO
    if carry and amount is not None:
        carry_in = carried_in(
            period,
            _parse_date(data["structure_from"]),
            period_of,
            lambda p: _amount_for(data, p),
            lambda p: total(s.amount for s in spends if p.covers(s.on)),
        )

    allowance = daily_allowance(period, today, amount or ZERO, spends, mode=mode, carried_in=carry_in)
    categories = _category_progress(db, cipher, budget.allocations, period, spends)
    allocated = total(a.amount for a in budget.allocations)

    is_current = period.covers(today)
    alerts: List[Alert] = []
    if settings.ALERT_ENABLED and is_current:
        cards_due, card_limits = _card_alerts(db, cipher, today)
        alerts = budget_alerts(
            allowance,
            warn_pct=int(prefs.get("alert_warn_threshold_pct") or settings.ALERT_WARN_THRESHOLD_PCT),
            pace_enabled=bool(prefs.get("alert_pace_enabled", settings.ALERT_PACE_ENABLED)),
            pace_tolerance_pct=settings.ALERT_PACE_TOLERANCE_PCT,
            categories=[CategoryUse(c.category_id, c.allocated, c.spent) for c in categories],
            category_level=settings.ALERT_CATEGORY_LEVEL,
            cards_due=cards_due,
            card_limits=card_limits,
        )

    return BudgetStatus(
        budget=budget,
        period=period,
        previous_period=period_of(_day_before(period.start)),
        next_period=period_of(_day_after(period.end)),
        is_current=is_current,
        carry_over=carry,
        allowance=allowance,
        categories=categories,
        allocated=allocated,
        unallocated=(amount or ZERO) - allocated,
        alerts=alerts,
    )


# ------------------------------------------------------------------ writing


def create_budget(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> BudgetView:
    today = today or date.today()
    repo = BudgetRepository(db, cipher)
    if _current_record(db, cipher) is not None:
        raise ConflictException("You already have a budget - change it instead")

    structure = _structure(payload, existing=None)
    amount = _positive(payload.get("amount"))
    first_period = budget_period(today, **_config(structure))
    data = {
        **structure,
        # Start of the period it was made in: the whole current period is budgeted.
        "amounts": [{"from": first_period.start.isoformat(), "amount": str(amount)}],
        "structure_from": first_period.start.isoformat(),
    }
    record = repo.create(data)
    _replace_allocations(db, cipher, record.id, payload.get("allocations") or [], amount)
    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="budgets", entity_id=record.id,
        cipher=cipher, detail={"period": data["period"], "amount": str(amount)},
    )
    db.commit()
    return _view(db, cipher, record, today)


def update_budget(
    db: Session,
    cipher: UserCipher,
    budget_id: int,
    payload: Mapping[str, Any],
    *,
    today: Optional[date] = None,
) -> BudgetView:
    today = today or date.today()
    repo = BudgetRepository(db, cipher)
    record = repo.get(budget_id)
    if record is None:
        raise NotFoundException("Budget not found")
    data: Dict[str, Any] = dict(record.data)

    structure = _structure(payload, existing=data)
    if any(structure[k] != data.get(k) for k in structure):
        # A new rhythm: the old periods' closing positions mean nothing for the
        # new ones, so carry-over restarts from the period this change lands in.
        data.update(structure)
        data["structure_from"] = budget_period(today, **_config(structure)).start.isoformat()

    amounts = [dict(a) for a in data.get("amounts") or []]
    if payload.get("amount") is not None:
        amount = _positive(payload["amount"])
        current = _amount_for(data, budget_period(today, **_config(structure)))
        if current != amount:
            amounts = [a for a in amounts if a.get("from") != today.isoformat()]
            amounts.append({"from": today.isoformat(), "amount": str(amount)})
            amounts.sort(key=lambda a: a["from"])
    data["amounts"] = amounts
    repo.update(budget_id, data)

    if payload.get("allocations") is not None:
        in_force = _amount_for(data, budget_period(today, **_config(structure))) or ZERO
        _replace_allocations(db, cipher, budget_id, payload["allocations"], in_force)

    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="budgets", entity_id=budget_id,
        cipher=cipher, detail={"period": data["period"]},
    )
    db.commit()
    return _view(db, cipher, repo.get(budget_id), today)


def on_categories_deleted(db: Session, cipher: UserCipher, doomed: Set[int], reassign_to: Optional[int]) -> None:
    """
    CAT-08, for allocations. Called by category_service inside its delete, in
    the same database transaction. An allocation for a deleted category would
    budget money nothing can ever be spent against; it is dropped, or folded
    into the category its transactions were moved to.
    """
    repo = BudgetAllocationRepository(db, cipher)
    records = repo.list()
    moving = ZERO
    for record in records:
        if record.data.get("category_id") in doomed:
            moving += money(record.data.get("amount", ZERO))
            repo.soft_delete(record.id)
    if reassign_to is None or moving == ZERO:
        return
    target = next((r for r in records if r.data.get("category_id") == reassign_to), None)
    if target is not None:
        repo.update(target.id, {**target.data, "amount": str(money(target.data["amount"]) + moving)})
    else:
        budget = _current_record(db, cipher)
        if budget is not None:
            repo.create({"budget_id": budget.id, "category_id": reassign_to, "amount": str(moving)})


# ---------------------------------------------------------------- internals


def _current_record(db: Session, cipher: UserCipher):
    records = BudgetRepository(db, cipher).list()
    return records[-1] if records else None


def _view(db: Session, cipher: UserCipher, record, today: date) -> BudgetView:
    data = record.data
    allocations = tuple(
        AllocationView(a.id, int(a.data["category_id"]), money(a.data.get("amount", ZERO)))
        for a in BudgetAllocationRepository(db, cipher).for_budget(record.id)
    )
    anchor = data.get("custom_anchor")
    return BudgetView(
        id=record.id,
        period=str(data["period"]),
        month_start_day=int(data.get("month_start_day") or 1),
        week_start_day=int(data.get("week_start_day") or 1),
        custom_days=data.get("custom_days"),
        custom_anchor=_parse_date(anchor) if anchor else None,
        amount=_amount_for(data, _period_of(data)(today)) or ZERO,
        structure_from=_parse_date(data["structure_from"]),
        allocations=allocations,
    )


def _config(data: Mapping[str, Any]) -> Dict[str, Any]:
    anchor = data.get("custom_anchor")
    return {
        "kind": data["period"],
        "month_start_day": int(data.get("month_start_day") or 1),
        "week_start_day": int(data.get("week_start_day") or 1),
        "custom_days": data.get("custom_days"),
        "custom_anchor": _parse_date(anchor) if isinstance(anchor, str) else anchor,
    }


def _period_of(data: Mapping[str, Any]):
    config = _config(data)
    return lambda day: budget_period(day, **config)


def _amount_for(data: Mapping[str, Any], period: BudgetPeriod) -> Optional[Decimal]:
    """The latest amount set on or before the period's last day - or None if it predates the budget."""
    chosen = None
    for entry in data.get("amounts") or []:
        if _parse_date(entry["from"]) <= period.end:
            chosen = entry
    return money(chosen["amount"]) if chosen else None


def _spends(db: Session, cipher: UserCipher) -> List[Spend]:
    spends: List[Spend] = []
    for record in TransactionRepository(db, cipher).cached():
        data = record.data
        if data.get("type") != "expense":
            continue
        on = _parse_date(data["txn_date"])
        for split in data.get("splits") or []:
            spends.append(Spend(on, split.get("category_id"), money(split.get("amount", ZERO))))
    return spends


def _category_progress(
    db: Session,
    cipher: UserCipher,
    allocations: Sequence[AllocationView],
    period: BudgetPeriod,
    spends: Sequence[Spend],
) -> List[CategoryProgress]:
    """
    Per-category spending from SPLITS, not a top-level category (TXN-16). An
    allocation on a parent covers its sub-categories too - "Food" budgets the
    groceries and the coffee under it.
    """
    children: Dict[int, Set[int]] = {}
    for record in CategoryRepository(db, cipher).list():
        parent = record.data.get("parent_id")
        if parent is not None:
            children.setdefault(parent, set()).add(record.id)

    in_period = [s for s in spends if period.covers(s.on)]
    progress: List[CategoryProgress] = []
    for allocation in allocations:
        scope = {allocation.category_id} | children.get(allocation.category_id, set())
        spent = total(s.amount for s in in_period if s.category_id in scope)
        allocated = allocation.amount
        progress.append(CategoryProgress(
            category_id=allocation.category_id,
            allocated=allocated,
            spent=spent,
            remaining=allocated - spent,
            used_ratio=(spent / allocated).quantize(Decimal("0.0001")) if allocated > ZERO else Decimal("0.0000"),
            over=allocated > ZERO and spent >= allocated,
        ))
    return sorted(progress, key=lambda p: (-p.used_ratio, p.category_id))


def _card_alerts(db: Session, cipher: UserCipher, today: date) -> Tuple[List[CardDue], List[CardLimit]]:
    """
    The cards worth a banner. A reminder keys on what the next payment still
    owes (ACC-20) - so paying the bill silences it even while new purchases
    sit on the next statement. A limit is checked on its own cycle (ACC-22).
    """
    views = account_service.list_accounts(
        db, cipher, postings=transaction_service.postings(db, cipher), today=today, include_archived=False
    )
    cards = [v for v in views if v.credit is not None]
    due = [CardDue(v.id, v.credit.due_in_days) for v in cards if v.credit.due_soon and v.credit.amount_due > ZERO]
    limits = [
        CardLimit(v.id, v.credit.spending_limit, v.credit.limit_spent,
                  v.credit.period_days_elapsed, v.credit.period_days)
        for v in cards if v.credit.spending_limit is not None
    ]
    return due, limits


def _replace_allocations(
    db: Session,
    cipher: UserCipher,
    budget_id: int,
    raw: Sequence[Mapping[str, Any]],
    budget_amount: Decimal,
) -> None:
    """Make the budget's allocations exactly `raw` - updating, adding and removing rows as needed."""
    if not isinstance(raw, (list, tuple)):
        raise ValidationException("allocations is a list")
    categories = {record.id: record.data for record in CategoryRepository(db, cipher).list()}

    wanted: Dict[int, Decimal] = {}
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ValidationException(f"Allocation {position} is not an object")
        category_id = item.get("category_id")
        if not isinstance(category_id, int) or isinstance(category_id, bool) or category_id not in categories:
            raise ValidationException(f"Allocation {position}: that category does not exist")
        if categories[category_id].get("kind") != "expense":
            raise BusinessRuleException(f"Allocation {position}: only spending categories are budgeted")
        if category_id in wanted:
            raise ValidationException(f"Allocation {position}: that category is already allocated")
        try:
            amount = money(item.get("amount"))
        except ValueError as exc:
            raise ValidationException(f"Allocation {position}: {exc}") from None
        if amount < ZERO or amount > MAX_BUDGET:
            raise ValidationException(f"Allocation {position}: an allocation is zero or more")
        wanted[category_id] = amount

    repo = BudgetAllocationRepository(db, cipher)
    existing = {int(r.data["category_id"]): r for r in repo.for_budget(budget_id)}
    for category_id, record in existing.items():
        if category_id not in wanted:
            repo.soft_delete(record.id)
        elif money(record.data.get("amount", ZERO)) != wanted[category_id]:
            repo.update(record.id, {**record.data, "amount": str(wanted[category_id])})
    for category_id, amount in wanted.items():
        if category_id not in existing:
            repo.create({"budget_id": budget_id, "category_id": category_id, "amount": str(amount)})


def _structure(payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    base = existing or {}
    kind = str(payload.get("period") or base.get("period") or settings.DEFAULT_BUDGET_PERIOD).lower()
    if kind not in PERIOD_KINDS:
        raise ValidationException(f"period must be one of: {', '.join(PERIOD_KINDS)}")

    def pick(key, default):
        value = payload.get(key)
        return base.get(key, default) if value is None else value

    month_start = _int(pick("month_start_day", settings.DEFAULT_MONTH_START_DAY), "month_start_day", 1, 31)
    week_start = _int(pick("week_start_day", settings.DEFAULT_WEEK_START_DAY), "week_start_day", 1, 7)
    custom_days = custom_anchor = None
    if kind == "custom":
        custom_days = _int(pick("custom_days", None), "custom_days", 1, 366)
        anchor = pick("custom_anchor", None)
        if anchor is None:
            raise ValidationException("A custom period needs a first day (custom_anchor)")
        custom_anchor = (anchor if isinstance(anchor, date) else _parse_date(anchor)).isoformat()
    return {
        "period": kind,
        "month_start_day": month_start,
        "week_start_day": week_start,
        "custom_days": custom_days,
        "custom_anchor": custom_anchor,
    }


def _preferences(db: Session, cipher: UserCipher) -> Mapping[str, Any]:
    record = PreferencesRepository(db, cipher).current()
    return record.data if record else {}


def _positive(value: Any) -> Decimal:
    try:
        amount = money(value)
    except ValueError as exc:
        raise ValidationException(f"amount: {exc}") from None
    if amount <= ZERO:
        raise ValidationException("A budget is more than zero")
    if amount > MAX_BUDGET:
        raise ValidationException("That budget is larger than this app records")
    return amount


def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationException(f"{name} must be {low}-{high}") from None
    if isinstance(value, bool) or not low <= number <= high:
        raise ValidationException(f"{name} must be {low}-{high}")
    return number


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationException("Dates look like 2026-09-13") from None


def _day_before(day: date) -> date:
    return date.fromordinal(day.toordinal() - 1)


def _day_after(day: date) -> date:
    return date.fromordinal(day.toordinal() + 1)
