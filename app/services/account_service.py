"""
account_service - the things transactions point at, and every number derived
from them (ACC-01..ACC-18, FEATURES.md).

What lives here and could not live in SQL:

  * BALANCES (ACC-04). `opening_balance + sum of postings`, added up in
    Python, because the amounts are inside ciphertext. Decimal throughout.
  * THE STATEMENT CYCLE (ACC-09/14/16). A credit card's period turns on its
    own closing day and has nothing to do with the budget month; the shared
    helpers are in app/core/date_utils.py, the dates never are.
  * CASH ON HAND (ACC-17) - the app's headline number, and deliberately not
    net worth. The sum of the accounts you switched on (ACC-18); nothing you
    own, and never an installment's unpaid remainder.
  * REVALUATION IS NOT INCOME (ACC-12). Typing a new value on an investment
    account appends a dated valuation (ACC-13); it moves the account's value
    and is invisible to income and spending stats.

Postings come from the caller, not from here. Until Phase 4 there are none,
so every balance is its opening balance; from Phase 4 the working-set cache
hands in the transactions and nothing in this file changes.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BusinessRuleException,
    NotFoundException,
    ValidationException,
)
from app.core.utils.date_utils import (
    StatementPeriod,
    previous_statement_period,
    statement_period,
)
from app.core.utils.money import ZERO, money, total
from app.db.repositories.account_repository import AccountRepository
from app.services import audit_service

# ---------------------------------------------------------------- the rules

TYPES: Tuple[str, ...] = ("cash", "debit", "credit", "savings", "investment")

# ACC-18. Credit is ON: what you have already spent on the card is money you
# no longer have, so it is subtracted. Investment is OFF: a fund you cannot
# spend today is not "in your pockets" (ACC-17).
COUNTS_IN_CASH_ON_HAND_DEFAULT: Mapping[str, bool] = {
    "cash": True,
    "debit": True,
    "savings": True,
    "credit": True,
    "investment": False,
}

DEFAULT_ICON: Mapping[str, str] = {
    "cash": "cash",
    "debit": "card",
    "credit": "credit-card",
    "savings": "piggy-bank",
    "investment": "chart",
}

NAME_MAX = 60
NOTE_MAX = 280
MAX_ACCOUNTS = 60  # a personal budget; a four-figure list is a bug, not a use case


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Posting:
    """
    One movement against an account, as the balance sees it: SIGNED, so a
    card purchase is negative and a payment to the card is positive. Phase 4
    builds these from the working set; Phase 3 computes over an empty list.
    """

    account_id: int
    on: date
    amount: Decimal


@dataclass(frozen=True)
class Valuation:
    """One value you typed on an investment account, with the day you typed it."""

    on: date
    value: Decimal
    note: Optional[str] = None


@dataclass(frozen=True)
class CreditView:
    """Everything about a card that is derived rather than stored (ACC-09/14)."""

    limit: Optional[Decimal]
    statement_closing_day: int
    payment_due_day: int
    period_start: date
    period_closes: date
    payment_due: date  # the NEXT payment owed, which is usually last month's bill
    due_for_statement_closing: date  # the statement that payment settles
    period_spend: Decimal  # spending inside the OPEN statement period
    owed: Decimal  # what the card is carrying right now, as a positive number
    unpaid_installments: Decimal  # ACC-14 - the bank blocks the whole remainder
    available: Optional[Decimal]
    due_in_days: int
    due_soon: bool


@dataclass(frozen=True)
class AccountView:
    """An account as the API returns it: stored payload plus derived money."""

    id: int
    name: str
    type: str
    opening_balance: Decimal
    balance: Decimal
    colour: str
    icon: str
    archived: bool
    counts_in_cash_on_hand: bool
    sort_order: int
    note: Optional[str]
    credit: Optional[CreditView] = None
    valuations: Tuple[Valuation, ...] = ()
    current_value: Optional[Decimal] = None  # investment only (ACC-08)


@dataclass(frozen=True)
class CashOnHand:
    """ACC-17. Not net worth, and it says so in its own fields."""

    total: Decimal
    account_ids: Tuple[int, ...]
    excluded_ids: Tuple[int, ...]


# ------------------------------------------------------------------ reading


def list_accounts(
    db: Session,
    cipher: UserCipher,
    *,
    postings: Sequence[Posting] = (),
    today: Optional[date] = None,
    include_archived: bool = True,
) -> List[AccountView]:
    records = AccountRepository(db, cipher).list()
    by_account = _group_postings(postings)
    views = [_view(record.id, record.data, by_account.get(record.id, ()), today) for record in records]
    if not include_archived:
        views = [v for v in views if not v.archived]
    return sorted(views, key=lambda v: (v.archived, v.sort_order, v.name.lower(), v.id))


def get_account(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    *,
    postings: Sequence[Posting] = (),
    today: Optional[date] = None,
) -> AccountView:
    record = AccountRepository(db, cipher).get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    return _view(record.id, record.data, _group_postings(postings).get(account_id, ()), today)


def cash_on_hand(views: Iterable[AccountView]) -> CashOnHand:
    """
    ACC-17. The sum of the balances of the accounts that count - and nothing
    else. An ARCHIVED account never counts however its switch is set: you
    archived it because the money is no longer yours to spend.

    An installment's unpaid remainder is not subtracted here and never will
    be; that is future money, and it shows on the installment card (§4.4).
    """
    counted: List[AccountView] = []
    excluded: List[AccountView] = []
    for view in views:
        (counted if view.counts_in_cash_on_hand and not view.archived else excluded).append(view)
    return CashOnHand(
        total=total(v.balance for v in counted),
        account_ids=tuple(v.id for v in counted),
        excluded_ids=tuple(v.id for v in excluded),
    )


# ------------------------------------------------------------------ writing


def create_account(db: Session, cipher: UserCipher, payload: Mapping[str, Any]) -> AccountView:
    repo = AccountRepository(db, cipher)
    if repo.count() >= MAX_ACCOUNTS:
        raise BusinessRuleException(f"An account list stops being useful past {MAX_ACCOUNTS} accounts")

    existing = repo.list()
    data = _clean(payload, existing=None)
    _reject_duplicate_name(existing, data["name"], account_id=None)
    if data.get("sort_order") is None:
        data["sort_order"] = _next_sort_order(existing)

    record = repo.create(data)
    audit_service.record(
        db, audit_service.CREATE, user_id=cipher.user_id, entity="accounts",
        entity_id=record.id, cipher=cipher, detail={"name": data["name"], "type": data["type"]},
    )
    db.commit()
    return _view(record.id, record.data, (), None)


def update_account(db: Session, cipher: UserCipher, account_id: int, payload: Mapping[str, Any]) -> AccountView:
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")

    data = _clean(payload, existing=record.data)
    _reject_duplicate_name(repo.list(), data["name"], account_id=account_id)

    updated = repo.update(account_id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="accounts",
        entity_id=account_id, cipher=cipher, detail={"name": data["name"], "type": data["type"]},
    )
    db.commit()
    return _view(account_id, updated.data, (), None)


def set_archived(db: Session, cipher: UserCipher, account_id: int, archived: bool) -> AccountView:
    """
    ACC-06. Archive, never delete - every transaction ever recorded points at
    this row, and those references are inside ciphertext where no foreign key
    can protect them.
    """
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")

    data = dict(record.data)
    data["archived"] = bool(archived)
    updated = repo.update(account_id, data)
    audit_service.record(
        db, audit_service.ARCHIVE if archived else audit_service.RESTORE,
        user_id=cipher.user_id, entity="accounts", entity_id=account_id,
        cipher=cipher, detail={"name": data.get("name")},
    )
    db.commit()
    return _view(account_id, updated.data, (), None)


def add_valuation(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    value: Any,
    *,
    on: Optional[date] = None,
    note: Optional[str] = None,
) -> AccountView:
    """
    ACC-12/ACC-13. Type a new value for an investment account: the value is
    APPENDED with its date, not overwritten, so the history survives.

    This is a valuation change, not income. It writes nothing to transactions,
    which is precisely why market noise never reaches a spending report.
    """
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    if record.data.get("type") != "investment":
        raise BusinessRuleException("Only an investment account has a typed value (ACC-08)")

    amount = _amount(value, "value")
    when = on or date.today()
    entry = {"on": when.isoformat(), "value": str(amount)}
    if note:
        entry["note"] = str(note)[:NOTE_MAX]

    data = dict(record.data)
    history = list(data.get("valuations") or [])
    history.append(entry)
    history.sort(key=lambda item: (str(item.get("on")), str(item.get("value"))))
    data["valuations"] = history

    updated = repo.update(account_id, data)
    audit_service.record(
        db, audit_service.REVALUE, user_id=cipher.user_id, entity="accounts",
        entity_id=account_id, cipher=cipher, detail={"on": entry["on"], "value": entry["value"]},
    )
    db.commit()
    return _view(account_id, updated.data, (), None)


# ---------------------------------------------------------------- internals


def _group_postings(postings: Sequence[Posting]) -> Dict[int, List[Posting]]:
    grouped: Dict[int, List[Posting]] = {}
    for posting in postings:
        grouped.setdefault(posting.account_id, []).append(posting)
    return grouped


def _view(
    account_id: int,
    data: Mapping[str, Any],
    postings: Sequence[Posting],
    today: Optional[date],
) -> AccountView:
    kind = str(data.get("type", "cash"))
    opening = money(data.get("opening_balance", ZERO))
    balance = opening + total(p.amount for p in postings)

    valuations = _valuations(data.get("valuations"))
    current_value: Optional[Decimal] = None
    if kind == "investment":
        # ACC-08: the account IS the number you typed. The postings against it
        # are contributions you have already reflected in that number, so the
        # latest valuation replaces the running sum rather than adding to it.
        current_value = valuations[-1].value if valuations else opening
        balance = current_value

    view = AccountView(
        id=account_id,
        name=str(data.get("name", "")),
        type=kind,
        opening_balance=opening,
        balance=balance.quantize(ZERO),
        colour=str(data.get("colour") or "#8E8E93"),
        icon=str(data.get("icon") or DEFAULT_ICON.get(kind, "wallet")),
        archived=bool(data.get("archived", False)),
        counts_in_cash_on_hand=bool(
            data.get("counts_in_cash_on_hand", COUNTS_IN_CASH_ON_HAND_DEFAULT.get(kind, True))
        ),
        sort_order=int(data.get("sort_order") or 0),
        note=data.get("note"),
        valuations=valuations,
        current_value=current_value,
    )
    if kind == "credit":
        view = replace(view, credit=_credit_view(data, view.balance, postings, today))
    return view


def _credit_view(
    data: Mapping[str, Any],
    balance: Decimal,
    postings: Sequence[Posting],
    today: Optional[date],
) -> CreditView:
    when = today or date.today()
    closing_day = int(data.get("statement_closing_day") or 1)
    due_day = int(data.get("payment_due_day") or 1)
    period: StatementPeriod = statement_period(when, closing_day, due_day)

    # THE NEXT PAYMENT IS USUALLY LAST MONTH'S BILL. The open period has not
    # been cut yet, so what you actually owe on a date is the statement that
    # closed before it - until its due date passes (ACC-15).
    previous = previous_statement_period(period, closing_day, due_day)
    if when <= previous.due:
        payment_due, due_for = previous.due, previous.closes
    else:
        payment_due, due_for = period.due, period.closes

    # Spending inside the OPEN period only - a card closing on the 20th says
    # nothing about a budget starting on the 1st (ACC-16).
    period_spend = total(-p.amount for p in postings if period.covers(p.on) and p.amount < 0)

    owed = -balance if balance < 0 else ZERO
    limit = money(data["credit_limit"]) if data.get("credit_limit") is not None else None
    unpaid = money(data.get("unpaid_installments", ZERO))
    # ACC-14: the bank blocks the whole unpaid remainder on day one, so leaving
    # it out would tell you that you can spend money the card will refuse.
    available = (limit - owed - unpaid).quantize(ZERO) if limit is not None else None

    due_in_days = (payment_due - when).days
    return CreditView(
        limit=limit,
        statement_closing_day=closing_day,
        payment_due_day=due_day,
        period_start=period.start,
        period_closes=period.closes,
        payment_due=payment_due,
        due_for_statement_closing=due_for,
        period_spend=period_spend,
        owed=owed.quantize(ZERO),
        unpaid_installments=unpaid,
        available=available,
        due_in_days=due_in_days,
        due_soon=0 <= due_in_days <= settings.CREDIT_DUE_ALERT_DAYS,
    )


def _valuations(raw: Any) -> Tuple[Valuation, ...]:
    if not isinstance(raw, list):
        return ()
    entries: List[Valuation] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            entries.append(
                Valuation(
                    on=date.fromisoformat(str(item.get("on"))),
                    value=money(item.get("value", ZERO)),
                    note=item.get("note"),
                )
            )
        except (ValueError, TypeError):
            continue
    entries.sort(key=lambda v: (v.on, v.value))
    return tuple(entries)


def _clean(payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Validate a submitted account into the payload that gets sealed.

    The type decides which fields are allowed to exist: credit terms on a cash
    account, or a valuation history on a debit card, would be fields nothing
    reads and every later report has to remember to ignore.
    """
    data: Dict[str, Any] = dict(existing or {})

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationException("An account needs a name")
    if len(name) > NAME_MAX:
        raise ValidationException(f"An account name is at most {NAME_MAX} characters")
    data["name"] = name

    kind = str(payload.get("type") or "").strip().lower()
    if kind not in TYPES:
        raise ValidationException(f"Account type must be one of: {', '.join(TYPES)}")
    if existing and existing.get("type") != kind:
        # The type decides what the balance MEANS. Changing it silently
        # reinterprets every posting already recorded against the account.
        raise BusinessRuleException("An account's type cannot change - archive it and make a new one")
    data["type"] = kind

    data["opening_balance"] = str(_amount(payload.get("opening_balance", ZERO), "opening_balance"))
    data["colour"] = _colour(payload.get("colour"))
    data["icon"] = _slug(payload.get("icon")) or DEFAULT_ICON.get(kind, "wallet")
    data["archived"] = bool(payload.get("archived", data.get("archived", False)))
    data["counts_in_cash_on_hand"] = bool(
        payload.get(
            "counts_in_cash_on_hand",
            data.get("counts_in_cash_on_hand", COUNTS_IN_CASH_ON_HAND_DEFAULT[kind]),
        )
    )
    if payload.get("sort_order") is not None:
        data["sort_order"] = int(payload["sort_order"])
    note = payload.get("note")
    data["note"] = str(note)[:NOTE_MAX] if note else None

    # --- credit terms (ACC-09/14), only on a card
    for field in ("statement_closing_day", "payment_due_day", "credit_limit", "unpaid_installments"):
        data.pop(field, None)
    if kind == "credit":
        data["statement_closing_day"] = _day_of_month(payload.get("statement_closing_day"), "statement_closing_day")
        data["payment_due_day"] = _day_of_month(payload.get("payment_due_day"), "payment_due_day")
        if payload.get("credit_limit") is not None:
            limit = _amount(payload["credit_limit"], "credit_limit")
            if limit < ZERO:
                raise ValidationException("A credit limit cannot be negative")
            data["credit_limit"] = str(limit)

    # --- valuation history (ACC-13), only on an investment account, and only
    #     ever appended by add_valuation() - never set from a submitted body.
    if kind == "investment":
        data["valuations"] = list((existing or {}).get("valuations") or [])
    else:
        data.pop("valuations", None)
    return data


def _amount(value: Any, field: str) -> Decimal:
    try:
        return money(value)
    except ValueError as exc:
        raise ValidationException(f"{field}: {exc}") from None


def _day_of_month(value: Any, field: str) -> int:
    try:
        day = int(value)
    except (TypeError, ValueError):
        raise ValidationException(f"{field} is a day of the month, 1-31") from None
    if not 1 <= day <= 31:
        raise ValidationException(f"{field} is a day of the month, 1-31")
    return day


def _colour(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "#8E8E93"
    if len(text) != 7 or not text.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in text[1:]):
        raise ValidationException("A colour is #RRGGBB")
    return text.upper()


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if len(text) > 32 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in text):
        raise ValidationException("An icon is a short name like 'credit-card'")
    return text


def _next_sort_order(existing: Sequence) -> int:
    orders = [int(record.data.get("sort_order") or 0) for record in existing]
    return (max(orders) + 1) if orders else 0


def _reject_duplicate_name(existing: Sequence, name: str, account_id: Optional[int]) -> None:
    lowered = name.casefold()
    for record in existing:
        if record.id != account_id and str(record.data.get("name", "")).casefold() == lowered:
            raise BusinessRuleException(f"You already have an account called {name}")
