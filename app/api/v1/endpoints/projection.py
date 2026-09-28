"""
/projection - the months ahead and each card's next statements (REC-21..26).

Read-only: nothing here posts or stores. All take the client's `today`, like
/budgets, and nothing from any response is kept in the browser (SEC-29). The
what-if (REC-27) and the payoff planner (REC-35) are POSTs only because they
carry a body - an unsaved plan, typed payments - and write nothing either.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.recurring import (
    CardLookaheadOut,
    PayoffIn,
    PayoffOut,
    ProjectionOut,
    RuleIn,
    WhatIfOut,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import payoff_service, projection_service

router = APIRouter(prefix="/projection", tags=["projection"])


@router.get("", response_model=ProjectionOut)
def months(
    today: Optional[date] = Query(default=None),
    months: int = Query(default=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ProjectionOut:
    return ProjectionOut.model_validate(projection_service.project(db, ctx.cipher, today=today, months=months))


@router.post("/what-if", response_model=WhatIfOut)
def what_if(
    body: RuleIn,
    today: Optional[date] = Query(default=None),
    months: int = Query(default=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> WhatIfOut:
    """
    REC-27 - the months ahead with an UNSAVED plan in them, beside the months as
    they are. The body is the same rule a POST /recurring would take; nothing is
    written. Saving it is that ordinary POST.
    """
    found = projection_service.what_if(db, ctx.cipher, body.model_dump(mode="python", exclude_none=True),
                                       today=today, months=months)
    return WhatIfOut.model_validate(found)


@router.post("/payoff", response_model=PayoffOut)
def payoff(
    body: PayoffIn,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> PayoffOut:
    """REC-35 - the debt payoff planner. A POST only to carry the typed payments; nothing is written."""
    return PayoffOut.model_validate(
        payoff_service.plan(db, ctx.cipher, extra=body.extra, payments=body.payments, today=today))


@router.get("/cards", response_model=List[CardLookaheadOut])
def cards(
    today: Optional[date] = Query(default=None),
    statements: int = Query(default=6, ge=1, le=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[CardLookaheadOut]:
    found = projection_service.cards(db, ctx.cipher, today=today, statements=statements)
    return [CardLookaheadOut.model_validate(card) for card in found]
