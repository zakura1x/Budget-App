"""
goal_service - savings goals (GOA-01..08; FEATURES.md §13-C).

A GOAL IS MONEY SET ASIDE INSIDE ONE ACCOUNT (GOA-08, 2026-09-16 - the user's
redesign). "Add money" earmarks part of the account's balance for the goal;
nothing moves. The balance stays exactly the sum of the account's transactions,
so it still matches the bank's own app, while what is set aside comes off the
account's AVAILABLE money and off cash on hand (ACC-17) - it cannot be spent by
mistake. Net worth still counts it: set-aside money is still yours.

    Seabank                         36,794.01   balance - matches the bank
      set aside · Emergency fund    -5,000.00
      set aside · Laptop            -8,000.00
      available                     23,794.01   what cash on hand counts

Progress is the goal's own dated list of what was set aside and what was used
(`set_aside` entries), summed on every read - never a stored figure, and never
the account's whole balance (the model before 2026-09-16, whose "Add money"
was a real transfer from another account). Goals made before the change start
at nothing set aside, by the user's choice.

Several goals may share an account, because each claims only its own part. What
may be set aside is limited by what is still available; when spending later
takes the balance below what is set aside, every goal on that account reports
`short_by` rather than pretending the money is there. Deleting a goal releases
what it held. A goal needs a cash, debit or savings account - a card's balance
is a debt and an investment's is a valuation, and neither is money you can set
aside.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.core.utils.money import ZERO, money
from app.db.models import SavingsGoal
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.services import account_service, audit_service, transaction_service

GOAL_ACCOUNT_TYPES = ("cash", "debit", "savings")
NAME_MAX = 60
NOTE_MAX = 120
MAX_GOALS = 50
MAX_ENTRIES = 1000  # a goal's own history; far beyond years of weekly saving
RATIO = Decimal("0.0001")
ENTRY_KINDS = ("add", "use")


class GoalRepository(EncryptedRepository):
    model = SavingsGoal


@dataclass(frozen=True)
class GoalView:
    id: int
    name: str
    target: Decimal
    target_date: Optional[date]
    account_id: int
    colour: str
    icon: str
    saved: Decimal  # what is set aside for this goal: added less used
    remaining: Decimal
    ratio: Decimal  # 0..1, for the bar
    reached: bool
    # GOA-08. The account it lives in, as far as setting aside goes.
    account_balance: Decimal = ZERO
    account_available: Decimal = ZERO  # balance less everything set aside there, by every goal
    short_by: Decimal = ZERO  # how far the balance has fallen below what is set aside there


def list_goals(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[GoalView]:
    records = GoalRepository(db, cipher).list()
    balances = _balances(db, cipher, today)
    held = _held_by_account(records)
    views = [_view(r.id, r.data, balances, held) for r in records]
    return sorted(views, key=lambda v: (v.reached, v.target_date or date.max, v.name.casefold()))


def get_goal(db: Session, cipher: UserCipher, goal_id: int, *, today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    return _view(record.id, record.data, _balances(db, cipher, today), _held_by_account(repo.list()))


def set_aside_by_account(db: Session, cipher: UserCipher) -> Dict[int, Decimal]:
    """
    GOA-08. What every account has set aside for goals - the one figure
    account_service subtracts from a balance to say what is available. Imported
    lazily there: this module imports account_service.
    """
    return _held_by_account(GoalRepository(db, cipher).list())


def create_goal(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    if repo.count() >= MAX_GOALS:
        raise BusinessRuleException(f"At most {MAX_GOALS} goals")
    data = _clean(db, cipher, payload, None)
    data["created_on"] = (today or date.today()).isoformat()
    data["set_aside"] = []
    record = repo.create(data)
    audit_service.record(db, audit_service.CREATE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=record.id, cipher=cipher, detail={"name": data["name"]})
    db.commit()
    return get_goal(db, cipher, record.id, today=today)


def update_goal(db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *,
                today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    data = _clean(db, cipher, payload, record.data)
    if data["account_id"] != record.data.get("account_id") and _saved(record.data) > ZERO:
        # What is set aside is part of THAT account's balance; it cannot follow the goal elsewhere.
        raise BusinessRuleException("Use or release what is set aside before moving the goal to another account")
    repo.update(goal_id, data)
    audit_service.record(db, audit_service.UPDATE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={"name": payload.get("name")})
    db.commit()
    return get_goal(db, cipher, goal_id, today=today)


def delete_goal(db: Session, cipher: UserCipher, goal_id: int) -> None:
    """Deleting a goal releases what it had set aside; the balance was never touched."""
    repo = GoalRepository(db, cipher)
    if repo.get(goal_id) is None:
        raise NotFoundException("Goal not found")
    repo.soft_delete(goal_id)
    audit_service.record(db, audit_service.DELETE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={})
    db.commit()


def add_money(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> GoalView:
    """
    GOA-08. Set part of the account's balance aside for the goal. Nothing moves:
    no transaction, the balance is unchanged, and only what is AVAILABLE in the
    account - and so cash on hand - goes down. At most what is still available.
    """
    return _record_entry(db, cipher, goal_id, payload, "add", today=today)


def use_money(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> GoalView:
    """
    GOA-08. Release money the goal had set aside - you bought the laptop, or
    need it back. Nothing moves here either: the purchase itself is an ordinary
    expense. At most what the goal holds.
    """
    return _record_entry(db, cipher, goal_id, payload, "use", today=today)


# ---------------------------------------------------------------- internals


def _record_entry(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], kind: str, *, today: Optional[date]
) -> GoalView:
    repo = GoalRepository(db, cipher)
    record = repo.get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    try:
        amount = money(payload.get("amount"))
    except (ValueError, TypeError):
        raise ValidationException("Type an amount") from None
    if amount <= ZERO:
        raise ValidationException("An amount is more than zero")
    entries = list(record.data.get("set_aside") or [])
    if len(entries) >= MAX_ENTRIES:
        raise BusinessRuleException("This goal's history is full")

    view = get_goal(db, cipher, goal_id, today=today)
    if kind == "add":
        if amount > view.account_available:
            raise BusinessRuleException(
                f"Only {max(view.account_available, ZERO)} of the account is not already set aside"
            )
    elif amount > view.saved:
        raise BusinessRuleException(f"This goal has {view.saved} set aside")

    when = payload.get("on") or today or date.today()
    note = " ".join(str(payload.get("note") or "").split())[:NOTE_MAX] or None
    entries.append({"on": when.isoformat() if isinstance(when, date) else str(when), "kind": kind,
                    "amount": str(amount), "note": note})
    repo.update(goal_id, {**record.data, "set_aside": entries})
    audit_service.record(
        db, audit_service.GOAL_SET_ASIDE if kind == "add" else audit_service.GOAL_USE,
        user_id=cipher.user_id, entity="savings_goals", entity_id=goal_id, cipher=cipher,
        detail={"amount": str(amount)},
    )
    db.commit()
    return get_goal(db, cipher, goal_id, today=today)


def _saved(data: Mapping[str, Any]) -> Decimal:
    """Added less used, from the goal's own entries - never below zero."""
    held = ZERO
    for entry in data.get("set_aside") or []:
        try:
            amount = money(entry.get("amount"))
        except (ValueError, TypeError):
            continue
        held += amount if entry.get("kind") == "add" else -amount
    return max(held, ZERO)


def _held_by_account(records) -> Dict[int, Decimal]:
    held: Dict[int, Decimal] = {}
    for record in records:
        account_id = int(record.data["account_id"])
        held[account_id] = held.get(account_id, ZERO) + _saved(record.data)
    return held


def _balances(db: Session, cipher: UserCipher, today: Optional[date]) -> Mapping[int, Decimal]:
    views = account_service.list_accounts(db, cipher, postings=transaction_service.postings(db, cipher), today=today)
    return {v.id: v.balance for v in views}


def _view(goal_id: int, data: Mapping[str, Any], balances: Mapping[int, Decimal],
          held: Mapping[int, Decimal]) -> GoalView:
    target = money(data["target"])
    saved = _saved(data)
    account_id = int(data["account_id"])
    balance = balances.get(account_id, ZERO)
    on_account = held.get(account_id, ZERO)
    return GoalView(
        id=goal_id,
        name=str(data.get("name", "")),
        target=target,
        target_date=date.fromisoformat(data["target_date"]) if data.get("target_date") else None,
        account_id=account_id,
        colour=str(data.get("colour") or "#3FA37A"),
        icon=str(data.get("icon") or "piggy-bank"),
        saved=saved,
        remaining=max(target - saved, ZERO),
        ratio=min(saved / target, Decimal(1)).quantize(RATIO, rounding=ROUND_HALF_UP) if target > ZERO else Decimal(0),
        reached=saved >= target,
        account_balance=balance,
        account_available=balance - on_account,
        short_by=max(on_account - max(balance, ZERO), ZERO),
    )


def _clean(db: Session, cipher: UserCipher, payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]]) -> dict:
    data = dict(existing or {})
    name = " ".join(str(payload.get("name") or data.get("name") or "").split())
    if not name:
        raise ValidationException("A goal needs a name")
    data["name"] = name[:NAME_MAX]

    raw_target = payload.get("target", data.get("target"))
    try:
        target = money(raw_target)
    except (ValueError, TypeError):
        raise ValidationException("A goal needs a target amount") from None
    if target <= ZERO or target > transaction_service.MAX_AMOUNT:
        raise ValidationException("A target is more than zero")
    data["target"] = str(target)

    target_date = payload.get("target_date", data.get("target_date"))
    data["target_date"] = (target_date.isoformat() if isinstance(target_date, date) else str(target_date)) if target_date else None

    account_id = payload.get("account_id", data.get("account_id"))
    account = AccountRepository(db, cipher).get(account_id) if isinstance(account_id, int) else None
    if account is None:
        raise ValidationException("A goal needs an account to save in")
    if account.data.get("type") not in GOAL_ACCOUNT_TYPES:
        raise BusinessRuleException("Save toward a goal in a cash, debit or savings account")
    if account.data.get("archived") and account_id != (existing or {}).get("account_id"):
        raise BusinessRuleException("That account is archived")
    # GOA-08: several goals may share an account - each holds only its own part of the balance.
    data["account_id"] = account_id
    data["colour"] = str(payload.get("colour") or data.get("colour") or "#3FA37A")
    data["icon"] = str(payload.get("icon") or data.get("icon") or "piggy-bank")
    data.setdefault("set_aside", [])
    return data
