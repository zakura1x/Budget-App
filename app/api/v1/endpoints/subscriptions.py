"""
/subscriptions - a view over the recurring rules of kind `subscription`
(SUB-00..08). Creating, editing and posting one is /recurring's.

The three writes here are SUB-07's, and each goes through recurring_service,
which owns the rule: cancelling ends it, resuming restarts it from today, and
a cancel-by date is a reminder only.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.recurring import CancelByIn, CancelIn, CandidateOut, RuleOut, SubscriptionOverviewOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import recurring_service, subscription_service

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


@router.post("/{rule_id}/cancel", response_model=RuleOut)
def cancel(
    rule_id: int,
    body: CancelIn,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """SUB-07 - cancelled with the service: nothing charges after that day."""
    return RuleOut.model_validate(
        recurring_service.cancel_subscription(db, ctx.cipher, rule_id, on=body.on, today=today))


@router.post("/{rule_id}/resume", response_model=RuleOut)
def resume(
    rule_id: int,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """SUB-07 - signed up again; it charges from today, never the months it was cancelled."""
    return RuleOut.model_validate(recurring_service.resume_subscription(db, ctx.cipher, rule_id, today=today))


@router.post("/{rule_id}/cancel-by", response_model=RuleOut)
def cancel_by(
    rule_id: int,
    body: CancelByIn,
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """SUB-07 - remind me to cancel by a day (a free trial). A reminder only."""
    return RuleOut.model_validate(recurring_service.set_cancel_by(db, ctx.cipher, rule_id, body.on, today=today))
