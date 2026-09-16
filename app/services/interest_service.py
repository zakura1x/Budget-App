"""
interest_service - crediting what a savings account earns, day by day (ACC-37).

The banks this app is used with (SeaBank, MariBank) pay interest on YESTERDAY's
closing balance and credit it at midnight, so the account's own history is a
small income entry every single day. This service reproduces that history
locally, and the balance in the app matches the bank's every day rather than
drifting until a monthly sweep.

There is no scheduler on the server - IIS idle-stops the process (§7) - so this
works exactly like the recurring engine: `accrue()` is a CATCH-UP that is safe
to call on every open. It posts the days that have not been posted and moves
the account's `credited_through` marker in the SAME commit, so the marker and
the rows can never disagree, and an entry the user deletes is never silently
written back.

Three rules worth keeping:

  * TODAY IS NEVER ACCRUED. Interest is earned on a day's closing balance, and
    today's is not closed yet - an entry posted now would change every time
    another transaction is typed. The catch-up stops at yesterday.
  * THE CREDIT COMPOUNDS. Interest posted on day d is part of day d's closing
    balance, so day d+1 earns on it, exactly as the bank does.
  * SUB-CENTAVO INTEREST IS CARRIED, NOT ROUNDED. `carry` holds the fraction
    of a centavo still owed; it is paid out on the first day it reaches PHP
    0.01. Nothing is invented and nothing is lost.

The arithmetic itself is not here: it is pure, in app/core/utils/interest.py,
and shared with projection_service so that months ahead and days past can never
use two different formulas.

Import direction: this module imports transaction_service (like
recurring_service) and NOTHING imports it except its endpoint. account_service
reads the same settings for display through the pure helper, never through
here.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.utils.interest import (
    CARRY_PLACES,
    YEAR_DAYS,
    Band,
    credit,
    daily_net,
    parse_bands,
)
from app.core.utils.money import ZERO, money
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.services import audit_service, transaction_service

ONE_DAY = timedelta(days=1)

# A backfill is capped so that turning interest on with an old start date
# cannot post thousands of rows in one request. The sheet refuses an older
# start (ACC-37); this is the belt to that pair of braces.
MAX_CATCH_UP_DAYS = 400

# What the ledger calls the entry. The category is the user's (Investments >
# Interest by default); this is the merchant line beside it.
MERCHANT = "Interest"


@dataclass(frozen=True)
class Settings:
    """An account's interest terms, as stored and as the catch-up reads them."""

    bands: Tuple[Band, ...]
    basis: int
    tax_rate: Decimal
    category_id: Optional[int]
    started: date
    credited_through: date
    carry: Decimal


@dataclass(frozen=True)
class Accrual:
    """What a catch-up did - the shape the Home screen reports after an open."""

    posted: int
    accounts: int
    credited: Decimal
    through: Optional[date]
    needs_attention: Tuple[int, ...] = ()


def read(data: Mapping[str, Any]) -> Optional[Settings]:
    """The account's interest settings, or None when it earns none. Never raises."""
    raw = data.get("interest")
    if not isinstance(raw, Mapping):
        return None
    try:
        bands = parse_bands(raw.get("bands"))
        started = date.fromisoformat(str(raw["started"]))
        through = date.fromisoformat(str(raw["credited_through"]))
    except (ValueError, KeyError, TypeError):
        return None
    basis = int(raw.get("basis") or YEAR_DAYS)
    tax = Decimal(str(raw.get("tax_rate") or "0"))
    carry = Decimal(str(raw.get("carry") or "0"))
    category_id = raw.get("category_id")
    return Settings(bands, basis, tax, int(category_id) if category_id else None, started, through, carry)


def accrue(db: Session, cipher: UserCipher, *, today: Optional[date] = None) -> Accrual:
    """
    ACC-37. Credit every day of interest earned up to yesterday that has not
    been credited yet - safe to call as often as you like.

    One commit for the whole batch: every posting, and every account's marker,
    or nothing at all.
    """
    today = today or date.today()
    last = today - ONE_DAY
    repo = AccountRepository(db, cipher)
    records = [r for r in repo.list() if isinstance(r.data.get("interest"), Mapping)]
    if not records:
        return Accrual(0, 0, ZERO, None)

    movements = _movements(transaction_service.postings(db, cipher))
    already = _credited_days(db, cipher)
    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list()}

    posted = 0
    touched = 0
    credited = ZERO
    attention: List[int] = []
    for record in records:
        settings = read(record.data)
        if settings is None or record.data.get("archived"):
            continue
        start = max(settings.started, settings.credited_through + ONE_DAY, last - timedelta(days=MAX_CATCH_UP_DAYS))
        if start > last:
            continue
        if _problem(settings, categories):
            attention.append(record.id)
            continue

        days, carry = _run(
            record.data, movements.get(record.id, {}), settings, start=start, last=last,
            skip=already.get(record.id, set()),
        )
        for on, amount in days:
            transaction_service.post_interest(
                db, cipher,
                {"type": "income", "amount": str(amount), "account_id": record.id, "txn_date": on.isoformat(),
                 "merchant": MERCHANT, "category_id": settings.category_id},
                on=on,
            )
            posted += 1
            credited += amount
        # The marker moves whether or not a centavo was payable: the days are
        # accounted for, and the fraction lives on in `carry`.
        repo.update(record.id, {**record.data, "interest": {**record.data["interest"],
                                                            "credited_through": last.isoformat(),
                                                            "carry": str(carry)}})
        touched += 1

    if touched:
        audit_service.record(
            db, audit_service.INTEREST, user_id=cipher.user_id, entity="accounts", cipher=cipher,
            detail={"posted": posted, "accounts": touched, "through": last.isoformat()},
        )
        db.commit()
    return Accrual(posted, touched, credited, last if touched else None, tuple(attention))


# ---------------------------------------------------------------- internals


def _run(
    data: Mapping[str, Any],
    by_day: Mapping[date, Decimal],
    settings: Settings,
    *,
    start: date,
    last: date,
    skip: Set[date],
) -> Tuple[List[Tuple[date, Decimal]], Decimal]:
    """
    Walk the days, returning what to post and the fraction left over.

    `by_day` already holds every posting the account has, interest included, so
    a day credited earlier compounds without being counted twice - it is
    skipped and its own entry is simply part of the balance.
    """
    balance = money(data.get("opening_balance") or ZERO)
    for on, amount in sorted(by_day.items()):
        if on >= start:
            break
        balance += amount

    carry = settings.carry
    out: List[Tuple[date, Decimal]] = []
    on = start
    while on <= last:
        if on not in skip:
            carry += daily_net(balance, settings.bands, basis=settings.basis, tax_rate=settings.tax_rate)
            payable, carry = credit(carry)
            if payable > ZERO:
                out.append((on, payable))
                balance += payable  # it compounds from tomorrow, as the bank does
        balance += by_day.get(on, ZERO)
        on += ONE_DAY
    return out, carry.quantize(CARRY_PLACES)


def _movements(postings: Sequence[Any]) -> Dict[int, Dict[date, Decimal]]:
    """Every account's signed movements, summed per day - the balance walk's raw material."""
    result: Dict[int, Dict[date, Decimal]] = {}
    for posting in postings:
        days = result.setdefault(posting.account_id, {})
        days[posting.on] = days.get(posting.on, ZERO) + posting.amount
    return result


def _credited_days(db: Session, cipher: UserCipher) -> Dict[int, Set[date]]:
    """The days each account has already been credited for - what makes a re-run a no-op."""
    result: Dict[int, Set[date]] = {}
    for view in transaction_service.views(db, cipher):
        if view.interest_on is not None:
            result.setdefault(view.account_id, set()).add(view.interest_on)
    return result


def _problem(settings: Settings, categories: Mapping[int, Mapping[str, Any]]) -> Optional[str]:
    """Why this account cannot be credited as it stands - the category is gone or archived - or None."""
    category = categories.get(settings.category_id) if settings.category_id else None
    if category is None:
        return "its interest category no longer exists"
    if category.get("kind") != "income":
        return "interest needs an income category"
    if category.get("archived"):
        return "its interest category is archived"
    return None
