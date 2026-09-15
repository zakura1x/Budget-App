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
    less the payments and refunds made since. Derived on every read, never stored, so a
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

TYPES: Tuple[str, ...] = ("cash", "debit", "credit", "savings", "investment", "lent", "borrowed", "member")

# ACC-18. Credit is ON: what you have already spent on the card is money you
# no longer have, so it is subtracted. Investment is OFF: a fund you cannot
# spend today is not "in your pockets" (ACC-17).
#
# ACC-31. LENT is OFF - money someone owes you is not in your pockets until
# it comes back. BORROWED (and a loan) is OFF too: it is money you will owe
# later, which ACC-17 leaves out just as it leaves out installment remainders;
# the borrowed cash itself already sits in the account it landed in.
# ACC-32. A MEMBER card (a transport, school or store card) holds prepaid
# money you will spend, so it is ON.
COUNTS_IN_CASH_ON_HAND_DEFAULT: Mapping[str, bool] = {
    "cash": True,
    "debit": True,
    "savings": True,
    "credit": True,
    "investment": False,
    "lent": False,
    "borrowed": False,
    "member": True,
}

DEFAULT_ICON: Mapping[str, str] = {
    "cash": "cash",
    "debit": "card",
    "credit": "credit-card",
    "savings": "piggy-bank",
    "investment": "chart",
    "lent": "hand-coin",
    "borrowed": "hand-owe",
    "member": "badge",
}

# ACC-33. What the account is within its type - "e-wallet", "loan", "crypto",
# "transport-card" - chosen in the add list and shown as its label. A label
# only: nothing computes on it, so any short slug is accepted.
SUBTYPE_MAX = 32

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
    posting_lag_days: int  # ACC-26 - this card's window for "may be on next statement"


@dataclass(frozen=True)
class Bill:
    """
    ACC-35. One bill as the card's own app lists it - typed, because a BNPL
    card's bills come from purchases nobody wants to itemise. What is paid of
    it is derived: payments into the card since the list was saved, oldest bill
    first. Never stored, so a payment settles a bill by itself.
    """

    due: date
    amount: Decimal  # typed + from_plans
    paid: Decimal
    left: Decimal
    overdue: bool
    typed: Decimal = ZERO  # what the card's app lists for this due date
    from_plans: Decimal = ZERO  # installments and repeating charges on the card that land on this bill
    typed_left: Decimal = ZERO  # unpaid of the typed part - payments settle the typed part first


# One recurring charge on a card: the day it posts (or will), its amount, and whether its schedule ends.
Charge = Tuple[date, Decimal, bool]


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
    posting_lag_days: int  # ACC-26, set per card
    bills: Tuple[Bill, ...] = ()  # ACC-35, typed from the card's app
    bills_left: Decimal = Decimal("0.00")
    due_now: Optional[Decimal] = None  # overdue bills + the next one; None without bills


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
    subtype: Optional[str] = None  # ACC-33 - a label, never a rule
    # What this account adds to cash on hand when it counts: its balance - or, for a card with bills
    # (ACC-35), minus only what is due now.
    cash_amount: Optional[Decimal] = None
    counts_in_net_worth: bool = True  # ACC-36 - its own switch; on unless turned off


@dataclass(frozen=True)
class CashOnHand:
    """ACC-17. Not net worth, and it says so in its own fields."""

    total: Decimal
    account_ids: Tuple[int, ...]
    excluded_ids: Tuple[int, ...]


@dataclass(frozen=True)
class NetWorth:
    """
    ACC-36. The grand total, beside cash on hand rather than instead of it:
    every active account at its full value - savings, investments, money lent
    - less everything owed in full: cards, loans, and installments not yet
    billed. Cash on hand says what you can spend this month; this says what you
    would have if every debt were settled today.
    """

    total: Decimal
    assets: Decimal
    liabilities: Decimal


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
    unpaid = _unpaid_installments(db, cipher)
    # ACC-35. The recurring charges are read only when some card has bills to add them to.
    charges = _plan_charges(db, cipher, today) if any(r.data.get("bills") for r in records) else {}
    views = [_view(record.id, record.data, by_account.get(record.id, ()), today, unpaid, charges) for record in records]
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
    return _view(record.id, record.data, _group_postings(postings).get(account_id, ()), today,
                 _unpaid_installments(db, cipher), _plan_charges(db, cipher, today) if record.data.get("bills") else {})


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
        # ACC-35: a card with bills subtracts what is due now, not everything it will ever bill.
        total=total(v.cash_amount if v.cash_amount is not None else v.balance for v in counted),
        account_ids=tuple(v.id for v in counted),
        excluded_ids=tuple(v.id for v in excluded),
    )


def net_worth(views: Iterable[AccountView]) -> NetWorth:
    """
    ACC-36. Every active account at full value, whatever its cash-on-hand
    switch says - except one switched out of net worth. Archived ones are gone.
    """
    assets = ZERO
    liabilities = ZERO
    for view in views:
        if view.archived or not view.counts_in_net_worth:
            continue
        if view.balance > ZERO:
            assets += view.balance
        else:
            liabilities += -view.balance
        if view.credit is not None:
            liabilities += view.credit.unpaid_installments
    return NetWorth(total=(assets - liabilities).quantize(ZERO), assets=assets.quantize(ZERO),
                    liabilities=liabilities.quantize(ZERO))


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


MAX_BILLS = 24


def set_bills(
    db: Session, cipher: UserCipher, account_id: int, bills: Sequence[Mapping[str, Any]], *, today: Optional[date] = None
) -> None:
    """
    ACC-35. Replace a card's bills with the unpaid ones its own app lists today.
    The list is dated: only payments into the card from that day on are applied
    to it, because a bill already paid is not on the list any more. An empty
    list removes the bills, and cash on hand goes back to the card's balance.
    """
    repo = AccountRepository(db, cipher)
    record = repo.get(account_id)
    if record is None:
        raise NotFoundException("Account not found")
    if record.data.get("type") != "credit":
        raise BusinessRuleException("Only a credit card has bills")
    if len(bills) > MAX_BILLS:
        raise ValidationException(f"At most {MAX_BILLS} bills")

    cleaned: Dict[date, Decimal] = {}
    for item in bills:
        try:
            due = date.fromisoformat(str(item.get("due")))
        except ValueError:
            raise ValidationException("Each bill needs a due date") from None
        amount = _amount(item.get("amount"), "amount")
        if amount <= ZERO:
            raise ValidationException("A bill is more than zero")
        if due in cleaned:
            raise ValidationException("Two bills are due on the same day - add them together")
        cleaned[due] = amount

    data = dict(record.data)
    if cleaned:
        data["bills"] = [{"due": due.isoformat(), "amount": str(amount)} for due, amount in sorted(cleaned.items())]
        data["bills_from"] = (today or date.today()).isoformat()
    else:
        data.pop("bills", None)
        data.pop("bills_from", None)
    repo.update(account_id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="accounts", entity_id=account_id, cipher=cipher,
        detail={"name": data.get("name"), "bills": len(cleaned)},
    )
    db.commit()


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


def _unpaid_installments(db: Session, cipher: UserCipher) -> Mapping[int, Decimal]:
    """
    REC-14. The unpaid remainder of every open installment, per account -
    derived from the plans and the payments posted against them, never stored.
    Imported here, not at the top: recurring_service imports transaction_service,
    which imports this module.
    """
    from app.services import recurring_service

    return recurring_service.unpaid_by_account(db, cipher)


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
    unpaid: Optional[Mapping[int, Decimal]] = None,
    charges: Optional[Mapping[int, Sequence[Charge]]] = None,
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
        counts_in_net_worth=bool(data.get("counts_in_net_worth", True)),
        valuations=valuations,
        current_value=current_value,
        subtype=data.get("subtype") or None,
    )
    if kind == "credit":
        view = replace(view, credit=_credit_view(account_id, data, opening, view.balance, postings, today,
                                                 (unpaid or {}).get(account_id, ZERO),
                                                 (charges or {}).get(account_id, ())))
    due_now = view.credit.due_now if view.credit is not None else None
    return replace(view, cash_amount=-due_now if due_now is not None else view.balance)


def _credit_view(
    account_id: int,
    data: Mapping[str, Any],
    opening: Decimal,
    balance: Decimal,
    postings: Sequence[Posting],
    today: Optional[date],
    unpaid: Decimal = ZERO,
    charges: Sequence[Charge] = (),
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

    # ACC-35. Typed bills, when the card has them, say what is due and when - the reminder follows them.
    bills = _bills(data, postings, when, charges)
    due_now: Optional[Decimal] = None
    if bills:
        unpaid_bills = [b for b in bills if b.left > ZERO]
        upcoming = next((b for b in unpaid_bills if not b.overdue), None)
        due_now = total([b.left for b in unpaid_bills if b.overdue] + ([upcoming.left] if upcoming else [])).quantize(ZERO)
        nearest = next(iter(unpaid_bills), None)
        if nearest is not None:
            payment_due = nearest.due if nearest.overdue else (upcoming.due if upcoming else nearest.due)
        amount_due = due_now

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
        posting_lag_days=_posting_lag(data),
        bills=bills,
        bills_left=total(b.left for b in bills).quantize(ZERO),
        due_now=due_now,
    )


def _bills(data: Mapping[str, Any], postings: Sequence[Posting], today: date, charges: Sequence[Charge] = ()) -> Tuple[Bill, ...]:
    """
    ACC-35. The typed bills plus every recurring charge on the card, each on
    the bill of the statement it posts in (its period's due date) - so adding
    an installment on the card moves the bills, due now and cash on hand.

    A charge is left out when its bill fell due before the list was saved (the
    card's app already had it), and a charge whose schedule never ends - a
    subscription - is counted only as far as the last typed bill, so the list
    does not grow a year of Netflix. Then the payments into the card since the
    list was saved settle the bills oldest first, the typed part of each first.
    """
    typed: Dict[date, Decimal] = {}
    for item in data.get("bills") or []:
        try:
            typed[date.fromisoformat(str(item["due"]))] = money(item["amount"])
        except (KeyError, TypeError, ValueError):
            continue
    if not typed:
        return ()
    try:
        since: Optional[date] = date.fromisoformat(str(data.get("bills_from")))
    except ValueError:
        since = None

    closing_day, due_day = _card_days(data)
    last_typed = max(typed)
    planned: Dict[date, Decimal] = {}
    for day, amount, ends in charges:
        due = statement_period(day, closing_day, due_day).due
        if (since is not None and due < since) or (not ends and due > last_typed):
            continue
        planned[due] = planned.get(due, ZERO) + amount

    pot = total(
        p.amount for p in postings
        if p.amount > ZERO and p.kind in (None, "transfer", "income") and (since is None or p.on >= since)
    )
    result = []
    for due in sorted(set(typed) | set(planned)):
        own = typed.get(due, ZERO)
        extra = planned.get(due, ZERO)
        amount = own + extra
        paid = min(pot, amount)
        pot -= paid
        left = amount - paid
        result.append(Bill(
            due=due, amount=amount.quantize(ZERO), paid=paid.quantize(ZERO), left=left.quantize(ZERO),
            overdue=today > due and left > ZERO, typed=own.quantize(ZERO), from_plans=extra.quantize(ZERO),
            typed_left=max(own - paid, ZERO).quantize(ZERO),
        ))
    return tuple(result)


def _plan_charges(db: Session, cipher: UserCipher, today: Optional[date]) -> Dict[int, List[Charge]]:
    """
    ACC-35. Every recurring expense per account: those already posted (they
    carry the rule's id) and those still to come from recurring_service.upcoming()
    - the one schedule (REC-22), so no date here is worked out twice.
    Imported here, not at the top: recurring_service imports transaction_service,
    which imports this module.
    """
    from app.services import recurring_service, transaction_service

    when = today or date.today()
    charges: Dict[int, List[Charge]] = {}
    for view in transaction_service.views(db, cipher):
        if view.recurring_id is not None and view.type == "expense":
            charges.setdefault(view.account_id, []).append((view.card_posted_on or view.txn_date, view.amount, True))
    start = date.fromordinal(when.toordinal() + 1)
    for item in recurring_service.upcoming(db, cipher, start, date.fromordinal(when.toordinal() + 366 * 3)):
        if item.type == "expense" and not item.occurrence.paused:
            charges.setdefault(item.account_id, []).append((item.on, item.amount, item.kind == "installment"))
    return charges


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
    is left of it is that, less the payments into the card since - and, as
    decided 2026-09-14, the refunds: money returned to the card after the cut
    reduces what you still have to pay.
    """
    at_close = opening + total(p.amount for p in postings if p.statement_day <= period.closes)
    amount = max(-at_close, ZERO).quantize(ZERO)
    paid = total(
        p.amount for p in postings
        if p.amount > ZERO and p.kind in (None, "transfer", "income") and period.closes < p.statement_day <= today
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
        posting_lag_days=_posting_lag(data),
    )


def _is_purchase(posting: Posting) -> bool:
    """
    What uses up a spending limit: money spent on the card. A payment, a
    transfer or a balance adjustment is not a purchase - the adjustment
    because nobody knows what that money was (ACC-29).
    """
    return posting.amount < ZERO and posting.kind in (None, "expense")


def _posting_lag(data: Mapping[str, Any]) -> int:
    """A card saved before the window was per-card uses the configured default."""
    try:
        return int(data.get("posting_lag_days", settings.CARD_POSTING_LAG_DAYS))
    except (TypeError, ValueError):
        return settings.CARD_POSTING_LAG_DAYS


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
    # ACC-33. An edit that does not mention the subtype keeps it.
    if "subtype" in payload:
        subtype = _slug(payload.get("subtype"), what="A subtype")
        data["subtype"] = subtype or None
    else:
        data.setdefault("subtype", None)
    data["archived"] = bool(payload.get("archived", data.get("archived", False)))
    data["counts_in_cash_on_hand"] = bool(
        payload.get(
            "counts_in_cash_on_hand",
            data.get("counts_in_cash_on_hand", COUNTS_IN_CASH_ON_HAND_DEFAULT[kind]),
        )
    )
    # ACC-36. An edit that does not mention it keeps it; a new account starts in.
    data["counts_in_net_worth"] = bool(payload.get("counts_in_net_worth", data.get("counts_in_net_worth", True)))
    if payload.get("sort_order") is not None:
        data["sort_order"] = int(payload["sort_order"])
    note = payload.get("note")
    data["note"] = str(note)[:NOTE_MAX] if note else None

    # --- credit terms (ACC-09/14/21), only on a card
    for field in ("statement_closing_day", "payment_due_day", "credit_limit", "spending_limit",
                  "posting_lag_days", "unpaid_installments", "statement_checks", "bills", "bills_from"):
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
        # ACC-26. How many days before closing this bank may still post a
        # purchase on the next statement. Banks differ, so it is the card's
        # own setting; a new card starts from CARD_POSTING_LAG_DAYS, and an
        # edit that does not mention it keeps what the card had.
        lag = payload.get("posting_lag_days")
        if lag is None:
            lag = (existing or {}).get("posting_lag_days", settings.CARD_POSTING_LAG_DAYS)
        data["posting_lag_days"] = _lag_days(lag)
        # The bank's statement totals (ACC-24) are only ever written by
        # record_statement_check() - never set from a submitted body.
        checks = (existing or {}).get("statement_checks")
        if checks:
            data["statement_checks"] = list(checks)
        # ACC-35. Bills are only ever written by set_bills(); an ordinary edit keeps them.
        for kept in ("bills", "bills_from"):
            if (existing or {}).get(kept):
                data[kept] = (existing or {})[kept]

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


def _lag_days(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationException("posting_lag_days is 0-10 days")
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise ValidationException("posting_lag_days is 0-10 days") from None
    if not 0 <= days <= 10:
        raise ValidationException("posting_lag_days is 0-10 days")
    return days


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


def _slug(value: Any, what: str = "An icon") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if len(text) > SUBTYPE_MAX or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in text):
        raise ValidationException(f"{what} is a short name like 'credit-card'")
    return text


def _next_sort_order(existing: Sequence) -> int:
    orders = [int(record.data.get("sort_order") or 0) for record in existing]
    return (max(orders) + 1) if orders else 0


def _reject_duplicate_name(existing: Sequence, name: str, account_id: Optional[int]) -> None:
    lowered = name.casefold()
    for record in existing:
        if record.id != account_id and str(record.data.get("name", "")).casefold() == lowered:
            raise BusinessRuleException(f"You already have an account called {name}")
