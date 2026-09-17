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

from app.api.v1.schemas.settings import GoalIn, GoalMoneyIn, GoalOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import goal_service

router = APIRouter(prefix="/goals", tags=["goals"])

TODAY = Query(default=None, description="the client's date")


@router.get("", response_model=List[GoalOut])
def list_goals(today: Optional[date] = TODAY, ctx: UnlockedContext = Depends(get_unlocked_context),
               db: Session = Depends(get_db)) -> List[GoalOut]:
    return [GoalOut.model_validate(g) for g in goal_service.list_goals(db, ctx.cipher, today=today)]


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
