"""
/goals - savings goals (GOA-01..08).

Since 2026-09-16 a goal holds money SET ASIDE inside its account: add and use
change what the goal holds and what the account has available, and never the
balance - there is no transfer (GOA-08).
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.settings import (
    AdviceOut,
    GoalIn,
    GoalMoneyIn,
    GoalOut,
    PaydayIn,
    PaydayOut,
    YearlyBillOut,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import goal_service, safety_service

router = APIRouter(prefix="/goals", tags=["goals"])

TODAY = Query(default=None, description="the client's date")


@router.get("", response_model=List[GoalOut])
def list_goals(today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
               db: Session = Depends(get_db)) -> List[GoalOut]:
    return [GoalOut.model_validate(g) for g in goal_service.list_goals(db, ctx.cipher, today=today)]


# Phase 13 - declared before /{goal_id} so their names are never read as an id.
@router.get("/yearly-bills", response_model=List[YearlyBillOut])
def yearly_bills(today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
                 db: Session = Depends(get_db)) -> List[YearlyBillOut]:
    """GOA-09 - bills that come once a year with no sinking fund following them yet."""
    return [YearlyBillOut.model_validate(b) for b in goal_service.yearly_bills(db, ctx.cipher, today=today)]


@router.get("/emergency", response_model=AdviceOut)
def emergency(today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
              db: Session = Depends(get_db)) -> AdviceOut:
    """GOA-10/11 - how long the emergency money lasts, and what it should be. Reads only."""
    return AdviceOut.model_validate(safety_service.advice(db, ctx.cipher, today=today))


@router.get("/payday", response_model=Optional[PaydayOut])
def payday(today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
           db: Session = Depends(get_db)) -> Optional[PaydayOut]:
    """GOA-12 - the income worth offering to set aside from, or null."""
    found = goal_service.payday(db, ctx.cipher, today=today)
    return PaydayOut.model_validate(found) if found else None


@router.post("/payday/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def set_aside_payday(transaction_id: int, body: PaydayIn, today: Optional[date] = TODAY,
                     ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> Response:
    """GOA-12 - set each amount aside for its goal; the income is answered. One commit."""
    goal_service.set_aside_payday(db, ctx.cipher, transaction_id, body.amounts, today=today)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/payday/{transaction_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_payday(transaction_id: int, ctx: UnlockedContext = Depends(get_unlocked_context),
                   db: Session = Depends(get_db)) -> Response:
    """GOA-12 - "Not now": this income is never asked about again."""
    goal_service.dismiss_payday(db, ctx.cipher, transaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalIn, today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
                db: Session = Depends(get_db)) -> GoalOut:
    return GoalOut.model_validate(goal_service.create_goal(db, ctx.cipher, body.model_dump(exclude_none=True), today=today))


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, body: GoalIn, today: Optional[date] = TODAY,
                ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> GoalOut:
    return GoalOut.model_validate(
        goal_service.update_goal(db, ctx.cipher, goal_id, body.model_dump(exclude_none=True), today=today))


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, ctx: UnlockedContext = Depends(get_unlocked_context),
                db: Session = Depends(get_db)) -> Response:
    goal_service.delete_goal(db, ctx.cipher, goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{goal_id}/add", response_model=GoalOut)
def add_money(goal_id: int, body: GoalMoneyIn, today: Optional[date] = TODAY,
              ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> GoalOut:
    """GOA-08 - set part of the account aside for the goal: available goes down, the balance does not."""
    return GoalOut.model_validate(
        goal_service.add_money(db, ctx.cipher, goal_id, body.model_dump(mode="python", exclude_none=True), today=today))


@router.post("/{goal_id}/use", response_model=GoalOut)
def use_money(goal_id: int, body: GoalMoneyIn, today: Optional[date] = TODAY,
              ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> GoalOut:
    """GOA-08 - release what the goal held. The purchase itself is an ordinary expense."""
    return GoalOut.model_validate(
        goal_service.use_money(db, ctx.cipher, goal_id, body.model_dump(mode="python", exclude_none=True), today=today))
