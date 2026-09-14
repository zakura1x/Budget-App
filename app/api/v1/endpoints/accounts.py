"""
/accounts - the first endpoints that read and write encrypted money.

Every route here depends on get_unlocked_context: without the DEK in the
session keyring there is nothing to read, and a locked session gets
401 SESSION_LOCKED rather than an error (SEC-27).

The endpoints do HTTP and nothing else. Balances, statement periods and cash
on hand are account_service's, and the encryption is the repository's - an
endpoint that touched either would break invariant 1.

Balances include every transaction from Phase 4 on: the postings come from
transaction_service over the warm working set and are handed to
account_service, which is unchanged - it always took postings from its caller.

`today` is the client's date, as on /budgets. A card's bill, its open cycle
and whether a payment is due soon all turn on the user's day (ACC-19..22).
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.accounts import (
    AccountIn,
    AccountListOut,
    AccountOut,
    ArchiveIn,
    ValuationIn,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import account_service, transaction_service

router = APIRouter(prefix="/accounts", tags=["accounts"])

TODAY = Query(default=None, description="the client's date")


def _current(db: Session, ctx: UnlockedContext, account_id: int, today: Optional[date]) -> AccountOut:
    """The account as it stands now, with every transaction posted against it."""
    view = account_service.get_account(
        db, ctx.cipher, account_id, postings=transaction_service.postings(db, ctx.cipher), today=today
    )
    return AccountOut.model_validate(view)


@router.get("", response_model=AccountListOut)
def list_accounts(
    include_archived: bool = Query(default=True),
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountListOut:
    """
    The account list and, with it, cash on hand (ACC-17) - computed over the
    same set in the same request, so the headline number can never disagree
    with the cards it is the sum of.
    """
    views = account_service.list_accounts(
        db, ctx.cipher, include_archived=include_archived,
        postings=transaction_service.postings(db, ctx.cipher), today=today,
    )
    return AccountListOut(
        accounts=[AccountOut.model_validate(view) for view in views],
        cash_on_hand=account_service.cash_on_hand(views),
    )


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: int,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    return _current(db, ctx, account_id, today)


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    view = account_service.create_account(db, ctx.cipher, body.model_dump(exclude_unset=True))
    return _current(db, ctx, view.id, today)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    body: AccountIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    """
    A `balance` that differs from the account's own answers 409 BALANCE_DIFFERS
    with `before`, `after` and `difference`, and saves nothing. The client asks
    the user, then sends the same body again with a `balance_action` (ACC-28).
    """
    account_service.update_account(
        db, ctx.cipher, account_id, body.model_dump(exclude_unset=True),
        postings=transaction_service.postings(db, ctx.cipher), today=today,
    )
    return _current(db, ctx, account_id, today)


@router.post("/{account_id}/archive", response_model=AccountOut)
def set_archived(
    account_id: int,
    body: ArchiveIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    """
    ACC-06. There is no DELETE for an account: every transaction ever recorded
    points at this row, and those references live inside ciphertext where no
    foreign key can stop the deletion from stranding them.
    """
    account_service.set_archived(db, ctx.cipher, account_id, body.archived)
    return _current(db, ctx, account_id, today)


@router.post("/{account_id}/valuations", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def add_valuation(
    account_id: int,
    body: ValuationIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    """ACC-12/13 - a valuation change, appended with its date. Not income."""
    account_service.add_valuation(db, ctx.cipher, account_id, body.value, on=body.on, note=body.note)
    return _current(db, ctx, account_id, today)
