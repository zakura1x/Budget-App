"""
/budgets - the budget, and the status the home screen is drawn from.

`today` is the CLIENT's date, passed by the client. The daily allowance is
about the user's day; on a server in another timezone, "today" would be wrong
for part of every day. The server's date is only the fallback.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.budgets import (
    AlertOut,
    BudgetEnvelope,
    BudgetIn,
    BudgetOut,
    ProgressOut,
    StatusEnvelope,
    StatusOut,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.core.exceptions import NotFoundException
from app.db.session import get_db
from app.services.budget_service import budget_service

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=BudgetEnvelope)
def get_budget(
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> BudgetEnvelope:
    view = budget_service.get_budget(db, ctx.cipher, today=today)
    return BudgetEnvelope(budget=BudgetOut.model_validate(view) if view else None)


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget(
    body: BudgetIn,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> BudgetOut:
    view = budget_service.create_budget(db, ctx.cipher, body.model_dump(mode="python", exclude_none=True), today=today)
    return BudgetOut.model_validate(view)


@router.get("/current", response_model=StatusEnvelope)
def current(
    today: Optional[date] = Query(default=None),
    on: Optional[date] = Query(default=None, description="any day in the period to show; today by default"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> StatusEnvelope:
    """The home screen payload: allowance, per-category progress and alerts, in one response."""
    result = budget_service.status(db, ctx.cipher, today=today, on=on)
    if result is None:
        # No budget - but a card's bill or a subscription still deserves a banner.
        alerts = budget_service.standalone_alerts(db, ctx.cipher, today=today)
        return StatusEnvelope(status=None, alerts=[AlertOut.model_validate(a) for a in alerts])
    return StatusEnvelope(status=StatusOut.model_validate(result),
                          alerts=[AlertOut.model_validate(a) for a in result.alerts])


@router.patch("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: int,
    body: BudgetIn,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> BudgetOut:
    view = budget_service.update_budget(
        db, ctx.cipher, budget_id, body.model_dump(mode="python", exclude_none=True), today=today
    )
    return BudgetOut.model_validate(view)


@router.get("/{budget_id}/progress", response_model=ProgressOut)
def progress(
    budget_id: int,
    today: Optional[date] = Query(default=None),
    on: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ProgressOut:
    result = budget_service.status(db, ctx.cipher, today=today, on=on)
    if result is None or result.budget.id != budget_id:
        raise NotFoundException("Budget not found")
    return ProgressOut.model_validate(
        {"period": result.period, "categories": result.categories,
         "allocated": result.allocated, "unallocated": result.unallocated},
        from_attributes=True,
    )
