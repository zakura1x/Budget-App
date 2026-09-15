"""/goals - savings goals; putting money toward one is a real transfer (GOA-01..07)."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.settings import ContributeIn, GoalIn, GoalOut
from app.api.v1.schemas.transactions import OutcomeOut
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


@router.post("/{goal_id}/contribute", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def contribute(goal_id: int, body: ContributeIn, today: Optional[date] = TODAY,
               ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> OutcomeOut:
    _, outcome = goal_service.contribute(db, ctx.cipher, goal_id, body.model_dump(mode="python", exclude_none=True),
                                         today=today)
    return OutcomeOut.model_validate(outcome)
