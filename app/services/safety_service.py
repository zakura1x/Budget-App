"""
safety_service - the emergency fund (GOA-10, GOA-11). READ-ONLY: it gathers
figures from the working set and hands them to the pure rules in
app/core/utils/emergency.py. Imported by nothing but its endpoint.

ESSENTIAL MONTHLY SPENDING - defined once, here, and shared by both features:
the average, over the last 6 full months with history, of every expense split
that is either in an ESSENTIAL category (category_service.essential_ids - by
name until switched, the user's decision 2026-09-28) or posted by a repeating
rule (bills, subscriptions, installment and loan payments are commitments,
whatever their category). With no essential category and nothing repeating,
it falls back to 70% of average spending and says it is guessing.

EMERGENCY MONEY (decided 2026-09-28): what the goal marked emergency fund has
set aside, if there is one; otherwise cash on hand. The screen says which.

    cover   = emergency money / essential monthly spending        GOA-10
    target  = essential monthly spending x the months GOA-11's rules give

A guide, not financial advice.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.utils.date_utils import add_months
from app.core.utils.emergency import DEPENDENTS, EARNERS, WORK, Fired, cover, target_months
from app.core.utils.money import CENTS, ZERO, total
from app.db.repositories.category_repository import CategoryRepository
from app.services import account_service, category_service, goal_service, preferences_service, transaction_service

ESSENTIAL_MONTHS = 6
INCOME_MONTHS = 12
GUESS_SHARE = Decimal("0.70")
TARGET_STEP = Decimal("100")  # a target is rounded up to the next PHP 100
CATCH_UP_MONTHS = 12  # "PHP X a month reaches it in 12 months"


@dataclass(frozen=True)
class Essentials:
    monthly: Decimal
    months: int  # how many months it was averaged over
    guessing: bool  # no essential category and nothing repeating: 70% of all spending


@dataclass(frozen=True)
class Advice:
    essentials: Essentials
    money: Decimal  # the emergency money
    source: str  # goal | cash
    goal_id: Optional[int]
    cover_months: Decimal  # how long the money lasts, to one place
    measurable: bool  # False: no essential spending to measure against
    target_months: int
    target: Decimal
    fired: List[Fired]
    short_history: bool
    per_month: Decimal  # reaches the target in CATCH_UP_MONTHS; 0 once reached
    answered: bool  # the three questions have been answered
    work: str
    dependents: str
    earners: str


def essentials(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Essentials:
    today = today or date.today()
    months = _months(db, cipher, today, ESSENTIAL_MONTHS)
    if not months:
        return Essentials(ZERO, 0, False)
    essential = category_service.essential_ids(CategoryRepository(db, cipher).list())
    counted = {m: ZERO for m in months}
    spent = {m: ZERO for m in months}
    for view in transaction_service.views(db, cipher):
        key = (view.txn_date.year, view.txn_date.month)
        if view.type != "expense" or key not in counted:
            continue
        for split in view.splits:
            spent[key] += split.amount
            if split.category_id in essential or view.recurring_id is not None:
                counted[key] += split.amount
    guessing = total(counted.values()) <= ZERO and total(spent.values()) > ZERO
    source = spent if guessing else counted
    monthly = (total(source.values()) / len(months)).quantize(CENTS)
    if guessing:
        monthly = (monthly * GUESS_SHARE).quantize(CENTS)
    return Essentials(monthly, len(months), guessing)


def advice(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Advice:
    today = today or date.today()
    need = essentials(db, cipher, today=today)
    prefs = preferences_service.get_preferences(db, cipher)
    work = prefs.get("safety_work") if prefs.get("safety_work") in WORK else "employee"
    dependents = prefs.get("safety_dependents") if prefs.get("safety_dependents") in DEPENDENTS else "0"
    earners = prefs.get("safety_earners") if prefs.get("safety_earners") in EARNERS else "1"
    answered = all(prefs.get(k) is not None for k in ("safety_work", "safety_dependents", "safety_earners"))

    incomes, sources, debt = _income_and_debt(db, cipher, today)
    rules = target_months(work=work, dependents=dependents, earners=earners, incomes=incomes, sources=sources,
                          debt=debt)

    money_now, source, goal_id = _emergency_money(db, cipher, today)
    lasts, measurable = cover(money_now, need.monthly)
    target = _round_up(need.monthly * rules.months)
    short = max(target - money_now, ZERO)
    per_month = (short / CATCH_UP_MONTHS).quantize(CENTS, rounding=ROUND_CEILING) if short > ZERO else ZERO
    return Advice(
        essentials=need, money=money_now, source=source, goal_id=goal_id, cover_months=lasts, measurable=measurable,
        target_months=rules.months, target=target, fired=rules.fired, short_history=rules.short_history,
        per_month=per_month, answered=answered, work=work, dependents=dependents, earners=earners,
    )


def _emergency_money(db: Session, cipher: UserCipher, today: date) -> Tuple[Decimal, str, Optional[int]]:
    """GOA-10, as decided: the emergency fund goal's money if there is one, else cash on hand."""
    goal = next((g for g in goal_service.list_goals(db, cipher, today=today) if g.kind == "emergency"), None)
    if goal is not None:
        return goal.saved, "goal", goal.id
    views = account_service.list_accounts(db, cipher, today=today)
    return account_service.cash_on_hand(views).total, "cash", None


def _income_and_debt(db: Session, cipher: UserCipher, today: date) -> Tuple[List[Decimal], int, Decimal]:
    """
    (money in per month with history, oldest first; kinds of income in the last
    6 of them; average monthly debt payment - transfers INTO a card or a loan,
    what actually went to debts - over those 6).
    """
    months = _months(db, cipher, today, INCOME_MONTHS)
    recent = set(months[-ESSENTIAL_MONTHS:])
    owed = {v.id for v in account_service.list_accounts(db, cipher, postings=(), today=today)
            if v.type in account_service.OWES}
    parents = {r.id: r.data.get("parent_id") for r in CategoryRepository(db, cipher).list()}
    income: Dict[Tuple[int, int], Decimal] = {m: ZERO for m in months}
    debt = ZERO
    kinds: Set[int] = set()
    for view in transaction_service.views(db, cipher):
        key = (view.txn_date.year, view.txn_date.month)
        if key not in income:
            continue
        if view.type == "income" and not view.cashback_of:
            income[key] += view.amount
            if key in recent:
                for split in view.splits:
                    if split.category_id is not None:
                        kinds.add(parents.get(split.category_id) or split.category_id)
        elif view.type == "transfer" and view.direction == "in" and view.account_id in owed and key in recent:
            debt += view.amount
    monthly_debt = (debt / len(recent)).quantize(CENTS) if recent else ZERO
    return [income[m] for m in months], len(kinds), monthly_debt


def _months(db: Session, cipher: UserCipher, today: date, count: int) -> List[Tuple[int, int]]:
    """The last `count` FULL calendar months before this one that have history - oldest first."""
    first = min((v.txn_date for v in transaction_service.views(db, cipher)), default=None)
    if first is None:
        return []
    found: List[Tuple[int, int]] = []
    start = date(today.year, today.month, 1)
    for back in range(count, 0, -1):
        month = add_months(start, -back)
        if add_months(month, 1) > first:  # the month ends on or after the first entry ever recorded
            found.append((month.year, month.month))
    return found


def _round_up(amount: Decimal) -> Decimal:
    if amount <= ZERO:
        return ZERO
    return ((amount / TARGET_STEP).to_integral_value(rounding=ROUND_CEILING) * TARGET_STEP).quantize(CENTS)
