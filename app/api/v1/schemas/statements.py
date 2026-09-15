"""Request and response shapes for a card's statement check (ACC-24..26, REC-29)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.accounts import StatementOut
from app.api.v1.schemas.common import Money
from app.api.v1.schemas.transactions import TransactionOut


class StatementCheckIn(BaseModel):
    """The bank's statement total - what it says you owe. One number, not every line."""

    bank_total: Money


class StatementResolveIn(BaseModel):
    """
    One way of explaining all or part of the difference. `forgot` and `leave`
    never reach the server: one is the ordinary add sheet, the other nothing.
    """

    choice: Literal["charge", "posted_next", "installment_interest", "installment_change"]
    # charge: the part of the difference it explains; installment_interest: the
    # interest on each payment; installment_change: the payment as billed
    amount: Optional[Money] = None
    category_id: Optional[int] = None  # charge: Financial > Interest or Bank fees, usually
    note: Optional[str] = Field(default=None, max_length=500)
    transaction_id: Optional[int] = None  # posted_next: the purchase the bank posted later
    rule_id: Optional[int] = None  # installment_*: which plan, when more than one is on the statement


class StatementPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    name: str
    per_payment: Money
    terms: Literal["provisional", "confirmed"]
    payments_posted: int
    payments_on_statement: int
    on_statement: Money


class StatementCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    statement: StatementOut
    checked: bool
    late_candidates: List[TransactionOut]
    suggestions: List[Literal["charge", "posted_next", "forgot", "installment_interest", "installment_change"]]
    installments: List[StatementPlanOut] = []
