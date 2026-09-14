"""
/transactions - the write path.

Every write answers with an Outcome: the rows written, the accounts they
touched with their new balances, cash on hand, and the budget status for the
client's `today` - all in the same response (phases.md, Phase 4 contract
note), so the home ring animates without a second round trip.

The list takes its filters as query parameters. That is safe to do with
figures this sensitive only because the logging middleware records the path
and never the query string.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.transactions import (
    OutcomeOut,
    PageOut,
    RepeatIn,
    TransactionIn,
    TransactionOut,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import transaction_service

router = APIRouter(prefix="/transactions", tags=["transactions"])

TODAY = Query(default=None, description="the client's date, for the budget status in the response")


@router.get("", response_model=PageOut)
def list_transactions(
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    category: Optional[int] = Query(default=None),
    account: Optional[int] = Query(default=None),
    type: Optional[str] = Query(default=None, pattern="^(expense|income|transfer|adjustment)$"),
    q: Optional[str] = Query(default=None, max_length=80),
    cursor: Optional[str] = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> PageOut:
    page = transaction_service.list_transactions(
        db, ctx.cipher, date_from=date_from, date_to=date_to, category_id=category,
        account_id=account, type=type, q=q, cursor=cursor, limit=limit,
    )
    return PageOut.model_validate(page)


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> TransactionOut:
    return TransactionOut.model_validate(transaction_service.get_transaction(db, ctx.cipher, transaction_id))


@router.post("", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: TransactionIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> OutcomeOut:
    result = transaction_service.create_transaction(
        db, ctx.cipher, body.model_dump(mode="python", exclude_none=True), today=today
    )
    return OutcomeOut.model_validate(result)


@router.post("/repeat-last", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def repeat_last(
    body: RepeatIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> OutcomeOut:
    """TXN-17 - one tap clones the most recently entered transaction onto today."""
    return OutcomeOut.model_validate(transaction_service.repeat_last(db, ctx.cipher, on=body.on, today=today))


@router.patch("/{transaction_id}", response_model=OutcomeOut)
def update_transaction(
    transaction_id: int,
    body: TransactionIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> OutcomeOut:
    result = transaction_service.update_transaction(
        db, ctx.cipher, transaction_id, body.model_dump(mode="python", exclude_none=True), today=today
    )
    return OutcomeOut.model_validate(result)


@router.delete("/{transaction_id}", response_model=OutcomeOut)
def delete_transaction(
    transaction_id: int,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> OutcomeOut:
    return OutcomeOut.model_validate(
        transaction_service.delete_transaction(db, ctx.cipher, transaction_id, today=today)
    )
