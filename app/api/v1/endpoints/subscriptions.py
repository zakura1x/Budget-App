"""
/subscriptions - a read-only view over the recurring rules of kind
`subscription` (SUB-00..08). Creating, editing and posting one is /recurring's.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.recurring import CandidateOut, SubscriptionOverviewOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import subscription_service

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=SubscriptionOverviewOut)
def overview(
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> SubscriptionOverviewOut:
    return SubscriptionOverviewOut.model_validate(subscription_service.overview(db, ctx.cipher, today=today))


@router.get("/detected", response_model=List[CandidateOut])
def detected(
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[CandidateOut]:
    """SUB-03 - proposals. Confirming one is a POST /recurring the user makes."""
    return [CandidateOut.model_validate(c) for c in subscription_service.detected(db, ctx.cipher, today=today)]
