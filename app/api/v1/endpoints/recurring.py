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
    InstallmentPreviewIn,
    InstallmentPreviewOut,
    InstallmentTermsIn,
    OccurrenceOut,
    PauseIn,
    PayNowIn,
    PlanPaymentIn,
    PlannedPaymentOut,
    PurchaseWithPlanIn,
    RuleIn,
    RuleOut,
    SkipIn,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.api.v1.schemas.transactions import TransactionOut
from app.services import installment_conversion, recurring_service

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


# ------------------------------------------------ REC-34: a purchase paid in installments
# Declared before /{rule_id} so "installments" is never read as a rule id.


@router.post("/installments/preview", response_model=InstallmentPreviewOut)
def preview_installments(
    body: InstallmentPreviewIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> InstallmentPreviewOut:
    """The plan a purchase would become - first payment and every payment. Writes nothing."""
    found = installment_conversion.preview(
        db, ctx.cipher, account_id=body.account_id, amount=body.amount, on=body.card_posted_on or body.txn_date,
        payments=body.payments, start=body.start, interest=body.interest, today=_today(today),
    )
    return InstallmentPreviewOut(
        start=found.start, payments=[PlannedPaymentOut(on=on, amount=amount) for on, amount in found.payments],
        due_now=found.due_now, on_closed_statement=found.on_closed_statement,
    )


@router.post("/installments", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_purchase_with_plan(
    body: PurchaseWithPlanIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """A new purchase on a card or loan, paid in installments from the start."""
    purchase = body.purchase.model_dump(mode="python", exclude_none=True)
    terms = body.terms.model_dump(mode="python", exclude_none=True)
    return RuleOut.model_validate(installment_conversion.create_with_plan(db, ctx.cipher, purchase, terms,
                                                                          today=_today(today)))


@router.post("/installments/from/{transaction_id}", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def convert_purchase(
    transaction_id: int,
    body: InstallmentTermsIn,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RuleOut:
    """A purchase already recorded, turned into an installment plan - the purchase is replaced by it."""
    terms = body.model_dump(mode="python", exclude_none=True)
    return RuleOut.model_validate(installment_conversion.convert(db, ctx.cipher, transaction_id, terms,
                                                                 today=_today(today)))


@router.post("/{rule_id}/revert", response_model=TransactionOut)
def revert_to_purchase(
    rule_id: int,
    today: Optional[date] = TODAY,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> TransactionOut:
    """REC-34. The plan and its payments go; the purchase it was made from comes back."""
    return TransactionOut.model_validate(installment_conversion.revert(db, ctx.cipher, rule_id, today=_today(today)))


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
