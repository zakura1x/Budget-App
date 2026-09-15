"""
/projection - the months ahead and each card's next statements (REC-21..26).

Read-only: nothing here posts or stores. Both take the client's `today`, like
/budgets, and nothing from either response is kept in the browser (SEC-29).
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.recurring import CardLookaheadOut, ProjectionOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import projection_service

router = APIRouter(prefix="/projection", tags=["projection"])


@router.get("", response_model=ProjectionOut)
def months(
    today: Optional[date] = Query(default=None),
    months: int = Query(default=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ProjectionOut:
    return ProjectionOut.model_validate(projection_service.project(db, ctx.cipher, today=today, months=months))


@router.get("/cards", response_model=List[CardLookaheadOut])
def cards(
    today: Optional[date] = Query(default=None),
    statements: int = Query(default=6, ge=1, le=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[CardLookaheadOut]:
    found = projection_service.cards(db, ctx.cipher, today=today, statements=statements)
    return [CardLookaheadOut.model_validate(card) for card in found]
