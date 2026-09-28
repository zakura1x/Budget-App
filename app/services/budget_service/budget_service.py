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
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

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
from app.core.utils.money import CENTS, ZERO, money, total
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
    StatementDiffers,
    SubscriptionDue,
    account_alerts,
    budget_alerts,
)
from app.services.budget_service.allowance import (
    MODES,
    Allowance,
    Spend,
    daily_allowance,
)
from app.services.budget_service.carry_over import carried_in
from app.services.budget_service import suggest as suggest_rules

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
class Reminder:
    """BUD-17. "Your spending has changed" - what the suggestion comes to beside the budget in force."""

    suggested: Decimal
    in_force: Decimal
    periods: int


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
    reminder: Optional[Reminder] = None  # BUD-17 - only in the first days of a period, and only when it drifted


@dataclass(frozen=True)
class SuggestionView:
    """
    BUD-17. The suggestion for the period containing today, from the finished
    periods before it. `periods` are the ones actually used - fewer than
    `asked` when there is not that much history - and `suggestion` is None
    when there is none at all.
    """

    period: BudgetPeriod
    kind: str
    asked: int
    periods: Tuple[BudgetPeriod, ...]
    in_force: Optional[Decimal]
    suggestion: Optional[suggest_rules.Suggestion]


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
        cards_due, card_limits, statements_differ = _card_alerts(db, cipher, today)
        alerts = budget_alerts(
            allowance,
            warn_pct=int(prefs.get("alert_warn_threshold_pct") or settings.ALERT_WARN_THRESHOLD_PCT),
            pace_enabled=bool(prefs.get("alert_pace_enabled", settings.ALERT_PACE_ENABLED)),
            pace_tolerance_pct=settings.ALERT_PACE_TOLERANCE_PCT,
            categories=[CategoryUse(c.category_id, c.allocated, c.spent) for c in categories],
            category_level=settings.ALERT_CATEGORY_LEVEL,
            cards_due=cards_due,
            card_limits=card_limits,
            subscriptions_due=_subscriptions_due(db, cipher, today),
            statements_differ=statements_differ,
        )

    reminder = None
    if is_current and suggest_rules.reminder_window(
        today_index=(today - period.start).days, kind=str(data["period"]), period=period,
        dismissed_for=data.get("suggestion_dismissed_for"),
        enabled=bool(prefs.get("budget_suggestion_nudge", True)),
    ):
        found = suggestion(db, cipher, today=today, periods=suggest_rules.REMINDER_HISTORY,
                           step=_step(prefs), spends=spends)
        if found.suggestion is not None and suggest_rules.reminder_due(
            history=len(found.periods), suggested=found.suggestion.total, in_force=amount,
        ):
            reminder = Reminder(found.suggestion.total, amount, len(found.periods))

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
        reminder=reminder,
    )


def suggestion(
    db: Session,
    cipher: UserCipher,
    *,
    today: Optional[date] = None,
    periods: int = 3,
    step: Optional[int] = None,
    trim: int = 0,
    fit: bool = False,
    spends: Optional[Sequence[Spend]] = None,
) -> SuggestionView:
    """
    BUD-17. A budget worked out from the last `periods` FINISHED periods, for
    the period containing today - the one a saved budget applies to, because
    an amount changed today applies to the current period (update_budget).
    Reads only; saving goes through create_budget / update_budget like any
    other edit, so there is still one writer.

    Spending here is exactly what the budget counts - expense splits, never a
    transfer or a balance adjustment - so the suggestion and the progress bars
    can never disagree. A sub-category's spending belongs to its main
    category, as an allocation on the parent covers its children; a
    sub-category budgeted directly keeps its own.
    """
    today = today or date.today()
    if periods not in suggest_rules.PERIOD_CHOICES:
        raise ValidationException(f"periods must be one of {suggest_rules.PERIOD_CHOICES}")
    prefs = _preferences(db, cipher)
    step = _step(prefs) if step is None else step
    if step not in suggest_rules.STEPS:
        raise ValidationException(f"step must be one of {suggest_rules.STEPS}")
    if trim not in suggest_rules.TRIMS:
        raise ValidationException(f"trim must be one of {suggest_rules.TRIMS}")

    record = _current_record(db, cipher)
    config = _config(record.data) if record is not None else _default_config(prefs)
    period_of = lambda day: budget_period(day, **config)  # noqa: E731 - read as "the period of"
    current = period_of(today)
    spends = list(spends if spends is not None else _spends(db, cipher))

    # The finished periods, newest first, then only those after the first entry
    # ever recorded - a month before you started is not a month of nothing.
    earliest = min((s.on for s in spends), default=None)
    history: List[BudgetPeriod] = []
    day = current.start
    for _ in range(periods):
        day = _day_before(day)
        found = period_of(day)
        if earliest is None or found.end < earliest:
            break
        history.append(found)
        day = found.start
    history.reverse()

    in_force = _amount_for(record.data, current) if record is not None else None
    if not history:
        return SuggestionView(current, config["kind"], periods, (), in_force, None)

    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}
    allocations = (
        {a.category_id: a.amount for a in _view(db, cipher, record, today).allocations} if record is not None else {}
    )

    def unit_of(category_id: Optional[int]) -> Optional[int]:
        """The line a category's spending belongs to."""
        if category_id is None or category_id in allocations:
            return category_id
        parent = (categories.get(category_id) or {}).get("parent_id")
        return parent if parent is not None else category_id

    def usable(unit: Optional[int]) -> bool:
        """An archived or vanished category gets no new line, and its spending counts nowhere."""
        data = categories.get(unit) if unit is not None else None
        if data is None or data.get("kind") != "expense":
            return False
        return not data.get("archived") or unit in allocations

    by_unit: Dict[int, List[Decimal]] = {}
    for spend in spends:
        index = next((i for i, p in enumerate(history) if p.covers(spend.on)), None)
        unit = unit_of(spend.category_id)
        if index is None or not usable(unit):
            continue
        row = by_unit.setdefault(unit, [ZERO] * len(history))
        row[index] += spend.amount

    income = [ZERO] * len(history)
    for view in transaction_service.views(db, cipher):
        if view.type != "income":
            continue
        index = next((i for i, p in enumerate(history) if p.covers(view.txn_date)), None)
        if index is not None:
            income[index] += view.amount

    result = suggest_rules.suggest(
        {unit: [money(a) for a in row] for unit, row in by_unit.items()},
        periods=len(history),
        income=income,
        scheduled=_scheduled(db, cipher, current, unit_of, usable),
        current={unit: amount for unit, amount in allocations.items() if usable(unit)},
        step=step,
        trim=trim,
        fit=fit,
    )
    return SuggestionView(current, config["kind"], periods, tuple(history), in_force, result)


def dismiss_reminder(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> None:
    """
    BUD-17. "Not now" - hide the reminder until the next period. Kept in the
    budget's own payload, on the server: nothing may be remembered in the
    browser (invariant 10), and it means dismissing it on the phone hides it
    on the PC too.
    """
    today = today or date.today()
    record = _current_record(db, cipher)
    if record is None:
        raise NotFoundException("There is no budget yet")
    data = dict(record.data)
    data["suggestion_dismissed_for"] = _period_of(data)(today).start.isoformat()
    BudgetRepository(db, cipher).update(record.id, data)
    db.commit()


def _scheduled(
    db: Session,
    cipher: UserCipher,
    period: BudgetPeriod,
    unit_of: Callable[[Optional[int]], Optional[int]],
    usable: Callable[[Optional[int]], bool],
) -> Dict[int, Decimal]:
    """
    BUD-17's floor: what recurring charges, subscriptions and installment
    payments charge each line in `period` - posted already or still to come,
    because both are this period's spending. From THE schedule
    (recurring_service.occurrences, REC-22), never a date rule of its own.
    Imported here: recurring_service reaches this module through
    transaction_service, so a top-level import would be a cycle.
    """
    from app.db.repositories.recurring_repository import RecurringRuleRepository
    from app.services import recurring_service

    floor: Dict[int, Decimal] = {}
    for rule in RecurringRuleRepository(db, cipher).list():
        if rule.data.get("type") != "expense":
            continue
        for occurrence in recurring_service.occurrences(rule.id, rule.data, period.start, period.end):
            if occurrence.paused:
                continue
            for category_id, amount in occurrence.splits:
                unit = unit_of(category_id)
                if usable(unit):
                    floor[unit] = floor.get(unit, ZERO) + amount
    return floor


def _step(prefs: Mapping[str, Any]) -> int:
    value = prefs.get("budget_round_step", suggest_rules.DEFAULT_STEP)
    return value if value in suggest_rules.STEPS else suggest_rules.DEFAULT_STEP


def _default_config(prefs: Mapping[str, Any]) -> Dict[str, Any]:
    """The Settings defaults a new budget would start from - custom falls back to monthly, having no length."""
    kind = prefs.get("budget_period") or settings.DEFAULT_BUDGET_PERIOD
    return {
        "kind": kind if kind in ("weekly", "monthly") else "monthly",
        "month_start_day": int(prefs.get("month_start_day") or settings.DEFAULT_MONTH_START_DAY),
        "week_start_day": int(prefs.get("week_start_day") or settings.DEFAULT_WEEK_START_DAY),
        "custom_days": None,
        "custom_anchor": None,
    }


def standalone_alerts(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[Alert]:
    """
    Phase 10. The account alerts - a card's bill or limit, a statement that
    does not match the bank, a subscription about to charge - for someone with
    NO budget. With a budget, status() carries exactly these inside its alerts.
    """
    if not settings.ALERT_ENABLED:
        return []
    today = today or date.today()
    prefs = _preferences(db, cipher)
    cards_due, card_limits, statements_differ = _card_alerts(db, cipher, today)
    return account_alerts(
        cards_due=cards_due,
        card_limits=card_limits,
        statements_differ=statements_differ,
        subscriptions_due=_subscriptions_due(db, cipher, today),
        warn_pct=int(prefs.get("alert_warn_threshold_pct") or settings.ALERT_WARN_THRESHOLD_PCT),
        pace_enabled=bool(prefs.get("alert_pace_enabled", settings.ALERT_PACE_ENABLED)),
        pace_tolerance_pct=settings.ALERT_PACE_TOLERANCE_PCT,
    )


def period_for(db: Session, cipher: UserCipher, day: date) -> Optional[BudgetPeriod]:
    """The budget period `day` falls in, or None with no budget - what Stats calls "this period"."""
    record = _current_record(db, cipher)
    return _period_of(record.data)(day) if record is not None else None


def budget_between(db: Session, cipher: UserCipher, start: date, end: date) -> Decimal:
    """
    REC-21. The budget for [start, end]: each period's amount times the share
    of its days inside the range, summed in Decimal and rounded once at the
    end. A whole monthly period comes out as exactly its amount; a weekly
    budget is pro-rated into calendar months. ZERO with no budget.
    """
    record = _current_record(db, cipher)
    if record is None or end < start:
        return ZERO
    data = record.data
    period_of = _period_of(data)
    amount = Decimal(0)
    day = start
    while day <= end:
        period = period_of(day)
        last = min(period.end, end)
        in_force = _amount_for(data, period) or ZERO
        amount += in_force * ((last - day).days + 1) / period.days
        day = last + timedelta(days=1)
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def daily_budget(db: Session, cipher: UserCipher) -> Optional[Callable[[date], Optional[Decimal]]]:
    """
    CAL-01. A function giving the budget per day of the period a day falls
    in - the period's amount over its days - or None with no budget. The
    calendar colours a day against it; a period from before the budget
    existed gives None.
    """
    record = _current_record(db, cipher)
    if record is None:
        return None
    data = record.data
    period_of = _period_of(data)
    known: Dict[date, Optional[Decimal]] = {}

    def per_day(day: date) -> Optional[Decimal]:
        period = period_of(day)
        if period.start not in known:
            amount = _amount_for(data, period)
            known[period.start] = (amount / period.days).quantize(CENTS) if amount else None
        return known[period.start]

    return per_day


# ------------------------------------------------------------------ writing


def create_budget(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> BudgetView:
    today = today or date.today()
    repo = BudgetRepository(db, cipher)
    if _current_record(db, cipher) is not None:
        raise ConflictException("You already have a budget - change it instead")

    # A new budget starts from the user's own defaults (Settings), then what the sheet sent.
    prefs = _preferences(db, cipher)
    defaults = {key: prefs[pref] for key, pref in (("period", "budget_period"), ("month_start_day", "month_start_day"),
                                                   ("week_start_day", "week_start_day")) if prefs.get(pref) is not None}
    structure = _structure({**defaults, **{k: v for k, v in payload.items() if v is not None}}, existing=None)
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


def _card_alerts(
    db: Session, cipher: UserCipher, today: date
) -> Tuple[List[CardDue], List[CardLimit], List[StatementDiffers]]:
    """
    The cards worth a banner. A reminder keys on what the next payment still
    owes (ACC-20) - so paying the bill silences it even while new purchases
    sit on the next statement. A limit is checked on its own cycle (ACC-22).
    A last statement whose bank total was entered and does not match raises
    one too (ACC-24) - until the difference is explained or the total fixed.
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
    differ = [
        StatementDiffers(v.id)
        for v in cards if v.credit.bill.difference is not None and v.credit.bill.difference != ZERO
    ]
    return due, limits, differ


def _subscriptions_due(db: Session, cipher: UserCipher, today: date) -> List[SubscriptionDue]:
    """
    SUB-06. Imported here, not at the top: subscription_service reads the
    budget for its share figure, so a top-level import would be a cycle.
    """
    from app.services import subscription_service

    items = subscription_service.reminders(db, cipher, today=today)
    due = [
        SubscriptionDue(item.rule.id, item.rule.name, item.rule.account_id, item.due_in_days)
        for item in items if item.remind and item.due_in_days is not None
    ]
    cancel = [
        SubscriptionDue(item.rule.id, item.rule.name, item.rule.account_id, item.cancel_by_in_days, cancel_by=True)
        for item in items if item.cancel_soon and item.cancel_by_in_days is not None
    ]
    return due + cancel


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
