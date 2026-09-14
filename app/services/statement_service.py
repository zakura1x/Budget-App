"""
statement_service - a card statement checked against the bank (ACC-24..26,
FEATURES.md §21, ARCHITECTURE.md §4.4).

At billing the user types ONE number: the bank's statement total. The app
already knows what should be on that statement, from the purchases entered on
the days they were made, so the only question left is what any difference is.

    difference = bank total - the app's statement amount

It is never stored. The bank's figure is kept on the card
(account_service.record_statement_check) and the difference is recalculated on
every read. Every way of explaining it is an ordinary transaction, so once it
posts the difference is zero and nothing else needs updating:

    charge        a one-time fee or interest: an expense on the card, dated
                  the closing date, in the category the user picks
    posted_next   the bank posted a purchase on the next statement: its
                  card_posted_on moves past the close. Its budget period does
                  not move - the budget reads txn_date only
    forgot        the ordinary add sheet; nothing here
    leave         nothing at all

THE APP SUGGESTS, IT NEVER DECIDES. One total cannot say why it differs, so the
suggestions come likeliest first and nothing is written without a choice. A
LOWER bank total is never offered as a charge: owing less than the app thinks
is a refund or a late posting, and calling it interest would invent a cost.

Installment interest (REC-29) joins the choices in Phase 7.

This service writes only through transaction_service, and nothing imports it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, List, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, ValidationException
from app.core.utils.money import ZERO, money
from app.services import account_service, audit_service, transaction_service

CHOICES = ("charge", "posted_next")


@dataclass(frozen=True)
class StatementCheck:
    statement: account_service.Statement
    checked: bool  # the bank's figure is in, and nothing is left unexplained
    late_candidates: List[transaction_service.TransactionView] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)  # likeliest first; "leave" is always allowed


def get(db: Session, cipher: UserCipher, account_id: int, closes: date, *, today: Optional[date] = None) -> StatementCheck:
    today = today or date.today()
    found = account_service.statement(
        db, cipher, account_id, closes, postings=transaction_service.postings(db, cipher), today=today
    )
    lag = found.posting_lag_days
    # ACC-26: the last `lag` days of the statement, closing day included -
    # the card's own window, since every bank posts at its own speed.
    candidates = (
        transaction_service.card_purchases(db, cipher, account_id, closes - timedelta(days=lag - 1), closes)
        if lag > 0 else []
    )
    return StatementCheck(
        statement=found,
        checked=found.difference is not None and found.difference == ZERO,
        late_candidates=candidates,
        suggestions=_suggest(found.difference, candidates),
    )


def check(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    closes: date,
    bank_total: Any,
    *,
    today: Optional[date] = None,
) -> StatementCheck:
    """ACC-24. Keep the bank's total for this statement and show what it makes of the app's figure."""
    account_service.record_statement_check(db, cipher, account_id, closes, bank_total, today=today)
    return get(db, cipher, account_id, closes, today=today)


def resolve(
    db: Session,
    cipher: UserCipher,
    account_id: int,
    closes: date,
    payload: Mapping[str, Any],
    *,
    today: Optional[date] = None,
) -> StatementCheck:
    """ACC-25. Explain all or part of the difference with one choice."""
    today = today or date.today()
    current = get(db, cipher, account_id, closes, today=today)
    difference = current.statement.difference
    if difference is None:
        raise BusinessRuleException("Enter the bank's statement total first")

    choice = payload.get("choice")
    if choice == "charge":
        _charge(db, cipher, account_id, closes, difference, payload, today)
    elif choice == "posted_next":
        _posted_next(db, cipher, closes, difference, current.late_candidates, payload)
    else:
        raise ValidationException(f"choice must be one of: {', '.join(CHOICES)}")
    return get(db, cipher, account_id, closes, today=today)


# ---------------------------------------------------------------- internals


def _suggest(difference, candidates) -> List[str]:
    if difference is None or difference == ZERO:
        return []
    if difference > ZERO:
        return ["charge", "forgot"]
    return (["posted_next"] if candidates else []) + ["forgot"]


def _charge(db, cipher, account_id, closes, difference, payload, today) -> None:
    if difference <= ZERO:
        raise BusinessRuleException(
            "The bank shows less than the app, which is not a charge - look for a refund or a purchase posted later"
        )
    try:
        amount = money(payload.get("amount"))
    except (ValueError, TypeError):
        raise ValidationException("amount is the part of the difference this charge explains") from None
    if amount <= ZERO or amount > difference:
        raise BusinessRuleException("A charge is more than zero and no more than the difference")

    # An ordinary expense on the card, on the closing date, so it lands on the
    # statement that charged it and counts in that budget period.
    transaction_service.create_transaction(db, cipher, {
        "type": "expense",
        "amount": str(amount),
        "account_id": account_id,
        "txn_date": closes,
        "category_id": payload.get("category_id"),
        "notes": payload.get("note"),
    }, today=today)


def _posted_next(db, cipher, closes, difference, candidates, payload) -> None:
    if difference >= ZERO:
        raise BusinessRuleException("Only a lower bank total can mean a purchase was posted on the next statement")
    target = payload.get("transaction_id")
    if not any(candidate.id == target for candidate in candidates):
        raise BusinessRuleException("Only a purchase from the last days before closing can move to the next statement")

    moved = transaction_service.set_card_posted_on(db, cipher, target, closes + timedelta(days=1))
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="transactions", entity_id=moved.id,
        cipher=cipher, detail={"card_posted_on": moved.card_posted_on.isoformat()},
    )
    db.commit()
