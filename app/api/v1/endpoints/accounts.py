"""
/accounts - the first endpoints that read and write encrypted money.

Every route here depends on get_unlocked_context: without the DEK in the
session keyring there is nothing to read, and a locked session gets
401 SESSION_LOCKED rather than an error (SEC-27).

The endpoints do HTTP and nothing else. Balances, statement periods and cash
on hand are account_service's, and the encryption is the repository's - an
endpoint that touched either would break invariant 1.
"""

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
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=AccountListOut)
def list_accounts(
    include_archived: bool = Query(default=True),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountListOut:
    """
    The account list and, with it, cash on hand (ACC-17) - computed over the
    same set in the same request, so the headline number can never disagree
    with the cards it is the sum of.
    """
    views = account_service.list_accounts(db, ctx.cipher, include_archived=include_archived)
    return AccountListOut(
        accounts=[AccountOut.model_validate(view) for view in views],
        cash_on_hand=account_service.cash_on_hand(views),
    )


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    return AccountOut.model_validate(account_service.get_account(db, ctx.cipher, account_id))


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    view = account_service.create_account(db, ctx.cipher, body.model_dump(exclude_unset=True))
    return AccountOut.model_validate(view)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    body: AccountIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    view = account_service.update_account(db, ctx.cipher, account_id, body.model_dump(exclude_unset=True))
    return AccountOut.model_validate(view)


@router.post("/{account_id}/archive", response_model=AccountOut)
def set_archived(
    account_id: int,
    body: ArchiveIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    """
    ACC-06. There is no DELETE for an account: every transaction ever recorded
    points at this row, and those references live inside ciphertext where no
    foreign key can stop the deletion from stranding them.
    """
    view = account_service.set_archived(db, ctx.cipher, account_id, body.archived)
    return AccountOut.model_validate(view)


@router.post("/{account_id}/valuations", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def add_valuation(
    account_id: int,
    body: ValuationIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AccountOut:
    """ACC-12/13 - a valuation change, appended with its date. Not income."""
    view = account_service.add_valuation(
        db, ctx.cipher, account_id, body.value, on=body.on, note=body.note
    )
    return AccountOut.model_validate(view)
