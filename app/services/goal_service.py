"""
goal_service - savings goals (GOA-01..07; FEATURES.md §13-C).

A GOAL IS A TARGET ON ONE ACCOUNT, AND ITS PROGRESS IS THAT ACCOUNT'S BALANCE.
Putting ₱5,000 toward a goal writes a real transfer into the linked account
(GOA-06), so the goal can never say ₱50,000 saved while the account holds
₱30,000 (GOA-07): there is no separate number to drift.

One goal per account, so two goals never claim the same pesos. A goal needs a
cash, debit or savings account - a card's balance is a debt and an
investment's is a valuation, and neither is money set aside. Deleting a goal
leaves the money in the account, where it always was.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, List, Mapping, Optional, Tuple

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
MAX_GOALS = 50
RATIO = Decimal("0.0001")


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
    saved: Decimal  # the linked account's balance, never below zero
    remaining: Decimal
    ratio: Decimal  # 0..1, for the bar
    reached: bool


def list_goals(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> List[GoalView]:
    balances = _balances(db, cipher, today)
    views = [_view(r.id, r.data, balances) for r in GoalRepository(db, cipher).list()]
    return sorted(views, key=lambda v: (v.reached, v.target_date or date.max, v.name.casefold()))


def get_goal(db: Session, cipher: UserCipher, goal_id: int, *, today: Optional[date] = None) -> GoalView:
    record = GoalRepository(db, cipher).get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    return _view(record.id, record.data, _balances(db, cipher, today))


def create_goal(db: Session, cipher: UserCipher, payload: Mapping[str, Any], *, today: Optional[date] = None) -> GoalView:
    repo = GoalRepository(db, cipher)
    if repo.count() >= MAX_GOALS:
        raise BusinessRuleException(f"At most {MAX_GOALS} goals")
    data = _clean(db, cipher, payload, None, goal_id=None)
    data["created_on"] = (today or date.today()).isoformat()
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
    repo.update(goal_id, _clean(db, cipher, payload, record.data, goal_id=goal_id))
    audit_service.record(db, audit_service.UPDATE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={"name": payload.get("name")})
    db.commit()
    return get_goal(db, cipher, goal_id, today=today)


def delete_goal(db: Session, cipher: UserCipher, goal_id: int) -> None:
    repo = GoalRepository(db, cipher)
    if repo.get(goal_id) is None:
        raise NotFoundException("Goal not found")
    repo.soft_delete(goal_id)
    audit_service.record(db, audit_service.DELETE, user_id=cipher.user_id, entity="savings_goals",
                         entity_id=goal_id, cipher=cipher, detail={})
    db.commit()


def contribute(
    db: Session, cipher: UserCipher, goal_id: int, payload: Mapping[str, Any], *, today: Optional[date] = None
) -> Tuple[GoalView, transaction_service.Outcome]:
    """GOA-06. A real transfer from another account into the goal's."""
    record = GoalRepository(db, cipher).get(goal_id)
    if record is None:
        raise NotFoundException("Goal not found")
    source = payload.get("from_account_id")
    if source == record.data["account_id"]:
        raise BusinessRuleException("Put money toward a goal from a different account")
    outcome = transaction_service.create_transaction(db, cipher, {
        "type": "transfer", "amount": payload.get("amount"), "account_id": source,
        "counter_account_id": record.data["account_id"], "txn_date": payload.get("txn_date") or today,
        "notes": f"Toward {record.data.get('name')}",
    }, today=today)
    return get_goal(db, cipher, goal_id, today=today), outcome


# ---------------------------------------------------------------- internals


def _balances(db: Session, cipher: UserCipher, today: Optional[date]) -> Mapping[int, Decimal]:
    views = account_service.list_accounts(db, cipher, postings=transaction_service.postings(db, cipher), today=today)
    return {v.id: v.balance for v in views}


def _view(goal_id: int, data: Mapping[str, Any], balances: Mapping[int, Decimal]) -> GoalView:
    target = money(data["target"])
    saved = max(balances.get(int(data["account_id"]), ZERO), ZERO)
    return GoalView(
        id=goal_id,
        name=str(data.get("name", "")),
        target=target,
        target_date=date.fromisoformat(data["target_date"]) if data.get("target_date") else None,
        account_id=int(data["account_id"]),
        colour=str(data.get("colour") or "#3FA37A"),
        icon=str(data.get("icon") or "piggy-bank"),
        saved=saved,
        remaining=max(target - saved, ZERO),
        ratio=min(saved / target, Decimal(1)).quantize(RATIO, rounding=ROUND_HALF_UP) if target > ZERO else Decimal(0),
        reached=saved >= target,
    )


def _clean(db: Session, cipher: UserCipher, payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]],
           *, goal_id: Optional[int]) -> dict:
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
    for other in GoalRepository(db, cipher).list():
        if other.id != goal_id and other.data.get("account_id") == account_id:
            raise BusinessRuleException("That account already holds a goal - one goal per account, so none is counted twice")
    data["account_id"] = account_id
    data["colour"] = str(payload.get("colour") or data.get("colour") or "#3FA37A")
    data["icon"] = str(payload.get("icon") or data.get("icon") or "piggy-bank")
    return data
