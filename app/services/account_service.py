"""
account_service - the things transactions point at, and every number derived
from them (ACC-01..ACC-30, FEATURES.md).

What lives here and could not live in SQL:

  * BALANCES (ACC-04). `opening_balance + sum of postings`, added up in
    Python, because the amounts are inside ciphertext. Decimal throughout.
  * THE STATEMENT CYCLE (ACC-09/14/16). A credit card's period turns on its
    own closing day and has nothing to do with the budget month; the shared
    helpers are in app/core/date_utils.py, the dates never are.
  * THE BILL (ACC-19/20). What the card owed when its last statement closed,
    less the payments made since. Derived on every read, never stored, so a
    payment, a refund or an edited purchase can never leave it stale.
  * YOUR OWN SPENDING LIMIT (ACC-21), measured over the OPEN statement period:
    purchases minus refunds, which is exactly what the next bill will show.
  * CASH ON HAND (ACC-17) - the app's headline number, and deliberately not
    net worth. The sum of the accounts you switched on (ACC-18); nothing you
    own, and never an installment's unpaid remainder.
  * REVALUATION IS NOT INCOME (ACC-12). Typing a new value on an investment
    account appends a dated valuation (ACC-13); it moves the account's value
    and is invisible to income and spending stats.
  * A BALANCE YOU TYPE (ACC-27/28). A balance is never stored, so setting one
    has to be recorded as SOMETHING: a balance adjustment (a transaction, and
    an audit entry) or a corrected opening balance. Nothing is saved until the
    user has chosen which - update_account answers BALANCE_DIFFERS first.

Postings come from the caller, not from here: transaction_service builds them
over the working set and the endpoints hand them in.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    BalanceDiffersException,
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
MAX_AMOUNT = Decimal("999999999.99")  # what one transaction may carry - an adjustment is one

# ACC-28. What to do with the difference between a typed balance and the
# derived one. Cancelling never reaches the server.
BALANCE_ACTIONS: Tuple[str, ...] = ("adjust", "fix_opening")


# ------------------------------------------------------------------- shapes


@dataclass(frozen=True)
class Posting:
    """
    One movement against an account, as the balance sees it: SIGNED, so a
    card purchase is negative and a payment to the card is positive.

    `kind` is the transaction type, which the card needs: a purchase uses up
    the spending limit and a payment does not. `statement_on` is the day the
    bank posted it, when that is later than the purchase (ACC-26) - it moves
    the posting between statements and nowhere else.
    """

    account_id: int
    on: date
    amount: Decimal
    kind: Optional[str] = None  # None where a posting is built by hand, as in tests
    statement_on: Optional[date] = None

    @property
    def statement_day(self) -> date:
        """The day that decides which statement this lands on. The budget never reads it."""
        return self.statement_on or self.on


@dataclass(frozen=True)
class Valuation:
    """One value you typed on an investment account, with the day you typed it."""

    on: date
    value: Decimal
    note: Optional[str] = None


@dataclass(frozen=True)
class Statement:
    """
    One CLOSED statement of a card (ACC-19/20/24), derived from postings.

    `difference` is the bank's total minus the app's, and None until the
    bank's figure is entered. It is recalculated on every read and never
    stored, so any transaction that explains it brings it to zero by itself.
    """

    account_id: int
    start: date
    closes: date
    due: date
    amount: Decimal  # what the card owed at the close - the bill
    paid_since_close: Decimal
    left_to_pay: Decimal
    overdue: bool
    bank_total: Optional[Decimal]
    difference: Optional[Decimal]


@dataclass(frozen=True)
class CreditView:
    """Everything about a card that is derived rather than stored (ACC-09/14/19..21)."""

    limit: Optional[Decimal]
    statement_closing_day: int
    payment_due_day: int
    period_start: date
    period_closes: date
    payment_due: date  # the NEXT payment owed, which is usually last month's bill
    due_for_statement_closing: date  # the statement that payment settles
    period_spend: Decimal  # purchases inside the OPEN statement period
    owed: Decimal  # what the card is carrying right now, as a positive number
    unpaid_installments: Decimal  # ACC-14 - the bank blocks the whole remainder
    available: Optional[Decimal]
    due_in_days: int
    due_soon: bool
    bill: Statement  # the last closed statement, and what is left of it (ACC-19/20)
    amount_due: Decimal  # what the next payment settles - the reminder keys on this
    spending_limit: Optional[Decimal]  # ACC-21, your own; not the bank's
    limit_spent: Decimal  # purchases minus refunds in the open period
    limit_left: Optional[Decimal]  # negative once over
    period_days: int
    period_days_elapsed: int  # including today


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


def statement(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    closes: date,
    *,
    postings: Sequence[Posting] = (),
    today: Optional[date] = None,
) -> Statement:
    """Any closed statement of a card, by its closing date (ACC-19/24)."""
    when = today or date.today()
    record = AccountRepository(db, cipher).get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    period = _closed_period(record.data, closes, when)
    opening = money(record.data.get("opening_balance", ZERO))
    return _statement(account_id, record.data, opening, _group_postings(postings).get(account_id, ()), period, when)


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


def update_account(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    payload: Mapping[str, Any],
    *,
    postings: Sequence[Posting] = (),
    today: Optional[date] = None,
) -> AccountView:
    """
    Save an edited account. A `balance` that differs from the derived one is
    a question, not a save (ACC-28): without a `balance_action` this raises
    BALANCE_DIFFERS carrying the difference, and NOTHING is written. With one:

        adjust       the opening balance stays, and an adjustment transaction
                     dated today makes up the difference - plus a
                     BALANCE_ADJUST audit entry, in this same commit (ACC-30)
        fix_opening  the opening balance absorbs the difference, so every past
                     balance shifts with it; no adjustment, no BALANCE_ADJUST

    The ordinary UPDATE entry (name and type, no amounts) is written either way.
    """
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")

    data = _clean(payload, existing=record.data)
    _reject_duplicate_name(repo.list(), data["name"], account_id=account_id)

    change = _balance_change(account_id, record.data, payload, postings, today)
    if change is not None:
        before, after, action = change
        opening = money(record.data.get("opening_balance", ZERO))
        # The typed balance decides; an opening balance sent alongside it does not.
        data["opening_balance"] = str(opening + (after - before) if action == "fix_opening" else opening)

    updated = repo.update(account_id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="accounts",
        entity_id=account_id, cipher=cipher, detail={"name": data["name"], "type": data["type"]},
    )

    if change is not None and change[2] == "adjust":
        before, after, _ = change
        note = _note(payload.get("balance_note"))
        # Imported here, not at the top: transaction_service imports this module.
        from app.services import transaction_service

        entry = transaction_service.record_adjustment(
            db, cipher, account_id, after - before, on=today or date.today(), note=note
        )
        audit_service.record(
            db, audit_service.BALANCE_ADJUST, user_id=cipher.user_id, entity="accounts",
            entity_id=account_id, cipher=cipher,
            detail={"before": str(before), "after": str(after), "difference": str(after - before),
                    "note": note, "transaction_id": entry.id},
        )
    db.commit()
    return _view(account_id, updated.data, (), today)


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


def record_statement_check(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    closes: date,
    bank_total: Any,
    *,
    today: Optional[date] = None,
) -> None:
    """
    ACC-24. Keep the bank's total for one closed statement on the card - one
    figure per statement, replaced if typed again. Only the figure is kept;
    the difference it makes is derived on every read (`Statement.difference`).
    """
    when = today or date.today()
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    _closed_period(record.data, closes, when)

    amount = _amount(bank_total, "bank_total")
    if amount < ZERO:
        raise ValidationException("A statement total is zero or more - what the bank says you owe")
    if amount > MAX_AMOUNT:
        raise ValidationException("That amount is larger than this app records")

    data = dict(record.data)
    checks = [c for c in data.get("statement_checks") or [] if c.get("closes") != closes.isoformat()]
    checks.append({"closes": closes.isoformat(), "bank_total": str(amount), "entered_on": when.isoformat()})
    checks.sort(key=lambda c: str(c.get("closes")))
    data["statement_checks"] = checks

    repo.update(account_id, data)
    audit_service.record(
        db, audit_service.STATEMENT_CHECK, user_id=cipher.user_id, entity="accounts",
        entity_id=account_id, cipher=cipher, detail={"closes": closes.isoformat(), "bank_total": str(amount)},
    )
    db.commit()


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
        view = replace(view, credit=_credit_view(account_id, data, opening, view.balance, postings, today))
    return view


def _credit_view(
    account_id: int,
    data: Mapping[str, Any],
    opening: Decimal,
    balance: Decimal,
    postings: Sequence[Posting],
    today: Optional[date],
) -> CreditView:
    when = today or date.today()
    closing_day, due_day = _card_days(data)
    period: StatementPeriod = statement_period(when, closing_day, due_day)

    # THE NEXT PAYMENT IS USUALLY LAST MONTH'S BILL. The open period has not
    # been cut yet, so what you actually owe on a date is the statement that
    # closed before it - until its due date passes (ACC-15).
    previous = previous_statement_period(period, closing_day, due_day)
    if when <= previous.due:
        payment_due, due_for = previous.due, previous.closes
    else:
        payment_due, due_for = period.due, period.closes

    # Inside the OPEN period only - a card closing on the 20th says nothing
    # about a budget starting on the 1st (ACC-16). A purchase the bank posted
    # later belongs to the statement it posted on (ACC-26).
    in_open = [p for p in postings if period.covers(p.statement_day)]
    purchases = total(-p.amount for p in in_open if _is_purchase(p))
    refunds = total(p.amount for p in in_open if p.kind == "income")

    owed = -balance if balance < 0 else ZERO
    limit = money(data["credit_limit"]) if data.get("credit_limit") is not None else None
    unpaid = money(data.get("unpaid_installments", ZERO))
    # ACC-14: the bank blocks the whole unpaid remainder on day one, so leaving
    # it out would tell you that you can spend money the card will refuse.
    available = (limit - owed - unpaid).quantize(ZERO) if limit is not None else None

    bill = _statement(account_id, data, opening, postings, previous, when)
    # ACC-20. The reminder is about the bill, not the card: paying the
    # statement in full silences it even while new purchases sit on the next
    # one. Only when the open statement is the one falling due - it has not
    # been cut, so there is no bill yet - does what the card owes stand in.
    amount_due = bill.left_to_pay if due_for == previous.closes else owed.quantize(ZERO)

    own = money(data["spending_limit"]) if data.get("spending_limit") is not None else None
    spent = max(purchases - refunds, ZERO).quantize(ZERO)

    due_in_days = (payment_due - when).days
    return CreditView(
        limit=limit,
        statement_closing_day=closing_day,
        payment_due_day=due_day,
        period_start=period.start,
        period_closes=period.closes,
        payment_due=payment_due,
        due_for_statement_closing=due_for,
        period_spend=purchases.quantize(ZERO),
        owed=owed.quantize(ZERO),
        unpaid_installments=unpaid,
        available=available,
        due_in_days=due_in_days,
        due_soon=0 <= due_in_days <= settings.CREDIT_DUE_ALERT_DAYS,
        bill=bill,
        amount_due=amount_due,
        spending_limit=own,
        limit_spent=spent,
        limit_left=(own - spent).quantize(ZERO) if own is not None else None,
        period_days=(period.closes - period.start).days + 1,
        period_days_elapsed=(when - period.start).days + 1,
    )


def _statement(
    account_id: int,
    data: Mapping[str, Any],
    opening: Decimal,
    postings: Sequence[Posting],
    period: StatementPeriod,
    today: date,
) -> Statement:
    """
    ACC-19/20. The bill is the card's balance at the moment the statement was
    cut - earlier unpaid balances included, as a bank's statement does. What
    is left of it is that, less the payments into the card since.
    """
    at_close = opening + total(p.amount for p in postings if p.statement_day <= period.closes)
    amount = max(-at_close, ZERO).quantize(ZERO)
    paid = total(
        p.amount for p in postings
        if p.amount > ZERO and p.kind in (None, "transfer") and period.closes < p.statement_day <= today
    ).quantize(ZERO)
    left = max(amount - paid, ZERO).quantize(ZERO)
    bank = _bank_total(data, period.closes)
    return Statement(
        account_id=account_id,
        start=period.start,
        closes=period.closes,
        due=period.due,
        amount=amount,
        paid_since_close=paid,
        left_to_pay=left,
        overdue=today > period.due and left > ZERO,
        bank_total=bank,
        difference=(bank - amount) if bank is not None else None,
    )


def _is_purchase(posting: Posting) -> bool:
    """
    What uses up a spending limit: money spent on the card. A payment, a
    transfer or a balance adjustment is not a purchase - the adjustment
    because nobody knows what that money was (ACC-29).
    """
    return posting.amount < ZERO and posting.kind in (None, "expense")


def _card_days(data: Mapping[str, Any]) -> Tuple[int, int]:
    return int(data.get("statement_closing_day") or 1), int(data.get("payment_due_day") or 1)


def _closed_period(data: Mapping[str, Any], closes: date, today: date) -> StatementPeriod:
    """The statement that closed on `closes` - refusing any day that is not one of this card's closing dates."""
    if data.get("type") != "credit":
        raise BusinessRuleException("Only a credit card has statements")
    closing_day, due_day = _card_days(data)
    period = statement_period(closes, closing_day, due_day)
    if period.closes != closes:
        raise ValidationException("That is not a closing date for this card")
    if closes >= today:
        raise BusinessRuleException("That statement has not closed yet")
    return period


def _bank_total(data: Mapping[str, Any], closes: date) -> Optional[Decimal]:
    for check in data.get("statement_checks") or []:
        if isinstance(check, Mapping) and check.get("closes") == closes.isoformat():
            try:
                return money(check.get("bank_total"))
            except (ValueError, TypeError):
                return None
    return None


def _balance_change(
    account_id: int,
    existing: Mapping[str, Any],
    payload: Mapping[str, Any],
    postings: Sequence[Posting],
    today: Optional[date],
) -> Optional[Tuple[Decimal, Decimal, str]]:
    """
    ACC-27/28. (before, after, action) when a typed balance differs from the
    derived one and the user has said what to do; None when there is nothing
    to do. Raises BALANCE_DIFFERS when there is a difference and no answer.
    """
    if payload.get("balance") is None:
        return None
    if existing.get("type") == "investment":
        raise BusinessRuleException("An investment account's value is recorded as a valuation (ACC-13)")

    after = _amount(payload["balance"], "balance")
    before = _view(account_id, existing, _group_postings(postings).get(account_id, ()), today).balance
    if after == before:
        return None
    if abs(after - before) > MAX_AMOUNT:
        raise ValidationException("That difference is larger than this app records")

    action = payload.get("balance_action")
    if action is None:
        raise BalanceDiffersException(
            "Choose how to record the difference",
            extra={"before": str(before), "after": str(after), "difference": str(after - before)},
        )
    if action not in BALANCE_ACTIONS:
        raise ValidationException(f"balance_action must be one of: {', '.join(BALANCE_ACTIONS)}")
    return before, after, str(action)


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

    # An edit that does not mention the opening balance keeps it - the sheet
    # edits an existing account's CURRENT balance instead (ACC-27).
    opening = payload.get("opening_balance")
    data["opening_balance"] = str(_amount(opening if opening is not None else data.get("opening_balance", ZERO),
                                          "opening_balance"))
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

    # --- credit terms (ACC-09/14/21), only on a card
    for field in ("statement_closing_day", "payment_due_day", "credit_limit", "spending_limit",
                  "unpaid_installments", "statement_checks"):
        data.pop(field, None)
    if kind == "credit":
        data["statement_closing_day"] = _day_of_month(payload.get("statement_closing_day"), "statement_closing_day")
        data["payment_due_day"] = _day_of_month(payload.get("payment_due_day"), "payment_due_day")
        if payload.get("credit_limit") is not None:
            limit = _amount(payload["credit_limit"], "credit_limit")
            if limit < ZERO:
                raise ValidationException("A credit limit cannot be negative")
            data["credit_limit"] = str(limit)
        if payload.get("spending_limit") is not None:
            own = _amount(payload["spending_limit"], "spending_limit")
            if own <= ZERO:
                raise ValidationException("A spending limit is more than zero - leave it empty for none")
            data["spending_limit"] = str(own)
        # The bank's statement totals (ACC-24) are only ever written by
        # record_statement_check() - never set from a submitted body.
        checks = (existing or {}).get("statement_checks")
        if checks:
            data["statement_checks"] = list(checks)

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


def _note(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:NOTE_MAX] or None


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
