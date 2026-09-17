"""
/recurring - the one engine's rules, and the catch-up that posts them
(REC-01..30, SUB-00).

POST /recurring/expand is safe to call on every open: it posts what is due up
to the client's `today` and nothing twice. The app calls it when Home loads, so
ten days away means exactly ten days of charges, once.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.recurring import (
    ExpansionOut,
    OccurrenceOut,
    PauseIn,
    PayNowIn,
    PlanPaymentIn,
    RuleIn,
    RuleOut,
    SkipIn,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import recurring_service

router = APIRouter(prefix="/recurring", tags=["recurring"])

TODAY = Query(default=None, description="the client's date")


def _today(value: Optional[date]) -> date:
    return value or date.today()


@router.get("", response_model=List[RuleOut])
def list_rules(
    kind: Optional[str] = Query(default=None, pattern="^(standard|subscription|installment)$"),
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> List[RuleOut]:
    views = recurring_service.list_rules(db, ctx.cipher, today=_today(today), kind=kind)
    return [RuleOut.model_validate(view) for view in views]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    view = recurring_service.create_rule(db, ctx.cipher, body.model_dump(mode="python", exclude_none=True),
                                         today=_today(today))
    return RuleOut.model_validate(view)


@router.post("/preview", response_model=List[OccurrenceOut])
def preview(
    body: RuleIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
) -> List[OccurrenceOut]:
    """The next five dates and amounts of a rule not yet saved. Nothing is read or written."""
    found = recurring_service.preview(body.model_dump(mode="python", exclude_none=True), today=_today(today))
    return [OccurrenceOut.model_validate(o) for o in found]


@router.post("/expand", response_model=ExpansionOut)
def expand(
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ExpansionOut:
    return ExpansionOut.model_validate(recurring_service.expand(db, ctx.cipher, today=_today(today)))


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int,
    body: RuleIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    view = recurring_service.update_rule(db, ctx.cipher, rule_id, body.model_dump(mode="python", exclude_none=True),
                                         today=_today(today))
    return RuleOut.model_validate(view)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> Response:
    recurring_service.delete_rule(db, ctx.cipher, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{rule_id}/pause", response_model=RuleOut)
def pause(
    rule_id: int,
    body: PauseIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    return RuleOut.model_validate(recurring_service.set_paused(db, ctx.cipher, rule_id, body.paused,
                                                               today=_today(today)))


@router.post("/{rule_id}/skip", response_model=RuleOut)
def skip(
    rule_id: int,
    body: SkipIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    return RuleOut.model_validate(recurring_service.skip(db, ctx.cipher, rule_id, body.on, today=_today(today)))


@router.post("/{rule_id}/payments", response_model=RuleOut)
def pay_plan(
    rule_id: int,
    body: PlanPaymentIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """
    REC-32. Pay money on an installment plan from another account. What is due
    is covered first; an EXTRA answers 409 PREPAYMENT_CHOICE - with what the
    monthly payment would become, and how many payments would be left, either
    way - and writes nothing until the same body returns with a `mode`.
    """
    return RuleOut.model_validate(recurring_service.pay_plan(
        db, ctx.cipher, rule_id, amount=body.amount, from_account_id=body.from_account_id,
        on=body.on, mode=body.mode, today=_today(today),
    ))


@router.post("/{rule_id}/pay-now", response_model=RuleOut)
def pay_now(
    rule_id: int,
    body: PayNowIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """
    REC-33. Record a repeating charge's next occurrence now, so it does not
    post again on its own day. Installments use /payments instead.
    """
    return RuleOut.model_validate(recurring_service.pay_now(db, ctx.cipher, rule_id, on=body.on,
                                                           today=_today(today)))


@router.post("/{rule_id}/payoff", response_model=RuleOut)
def pay_off(
    rule_id: int,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    return RuleOut.model_validate(recurring_service.pay_off(db, ctx.cipher, rule_id, today=_today(today)))
