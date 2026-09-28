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
    SuggestionOut,
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


@router.get("/suggestion", response_model=SuggestionOut)
def suggestion(
    today: Optional[date] = Query(default=None),
    periods: int = Query(default=3),
    step: Optional[int] = Query(default=None, description="PHP to round up to; the Settings choice by default"),
    trim: int = Query(default=0),
    fit: bool = Query(default=False),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> SuggestionOut:
    """BUD-17 - a budget worked out from recent spending. Writes nothing; Save is PATCH/POST as ever."""
    view = budget_service.suggestion(db, ctx.cipher, today=today, periods=periods, step=step, trim=trim, fit=fit)
    body = {"period": view.period, "kind": view.kind, "asked": view.asked, "periods": list(view.periods),
            "in_force": view.in_force, "ready": view.suggestion is not None}
    if view.suggestion is not None:
        s = view.suggestion
        body.update({"lines": list(s.lines), "occasional": list(s.occasional), "buffer": s.buffer,
                     "total": s.total, "income": s.income, "over_income": s.over_income, "fitted": s.fitted,
                     "cannot_fit": s.cannot_fit, "step": s.step, "trim": s.trim})
    return SuggestionOut.model_validate(body, from_attributes=True)


@router.post("/suggestion/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_reminder(
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> None:
    """BUD-17 - "Not now": the reminder stays away until the next period."""
    budget_service.dismiss_reminder(db, ctx.cipher, today=today)


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
