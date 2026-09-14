"""
/accounts/{id}/statements/{closes} - checking a card statement against the
bank (ACC-24..26, FEATURES.md §21).

HTTP only: the figures are account_service's, the explanations are
statement_service's. `today` is the client's date, as on /budgets - whether a
statement has closed yet depends on the user's day, not the server's.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.statements import (
    StatementCheckIn,
    StatementCheckOut,
    StatementResolveIn,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import statement_service

router = APIRouter(prefix="/accounts", tags=["statements"])

TODAY = Query(default=None, description="the client's date")


@router.get("/{account_id}/statements/{closes}", response_model=StatementCheckOut)
def get_statement(
    account_id: int,
    closes: date,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> StatementCheckOut:
    return StatementCheckOut.model_validate(statement_service.get(db, ctx.cipher, account_id, closes, today=today))


@router.post("/{account_id}/statements/{closes}/check", response_model=StatementCheckOut)
def check_statement(
    account_id: int,
    closes: date,
    body: StatementCheckIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> StatementCheckOut:
    """ACC-24 - the bank's total. Typing it again replaces it."""
    result = statement_service.check(db, ctx.cipher, account_id, closes, body.bank_total, today=today)
    return StatementCheckOut.model_validate(result)


@router.post("/{account_id}/statements/{closes}/resolve", response_model=StatementCheckOut)
def resolve_statement(
    account_id: int,
    closes: date,
    body: StatementResolveIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> StatementCheckOut:
    """ACC-25 - explain all or part of the difference with one choice."""
    result = statement_service.resolve(
        db, ctx.cipher, account_id, closes, body.model_dump(mode="python", exclude_none=True), today=today
    )
    return StatementCheckOut.model_validate(result)
