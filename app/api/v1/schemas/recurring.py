"""Request and response shapes for /recurring, /subscriptions and /projection (REC-01..30, SUB-00..08)."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.accounts import BillOut
from app.api.v1.schemas.budgets import Ratio
from app.api.v1.schemas.common import Money, Rate
from app.api.v1.schemas.transactions import TransactionIn

Kind = Literal["standard", "subscription", "installment"]
# A projected item can also be a typed card bill entering cash on hand (ACC-35):
# its typed part, or its plan part - or a month of savings interest (ACC-37).
# "bill_now" is a bill cash on hand already holds: listed with no effect, never taken twice.
ProjectedKind = Literal["standard", "subscription", "installment", "bill", "bill_plans", "bill_now", "interest"]
RuleType = Literal["expense", "income", "transfer"]
Frequency = Literal["daily", "weekly", "monthly", "yearly", "semi_monthly"]


class RuleIn(BaseModel):
    """Create or edit a rule. On an edit, anything left out keeps what the rule had."""

    kind: Optional[Kind] = None
    type: Optional[RuleType] = None
    name: Optional[str] = Field(default=None, max_length=60)
    account_id: Optional[int] = None
    counter_account_id: Optional[int] = None  # transfers
    category_id: Optional[int] = None
    interest_category_id: Optional[int] = None  # installments with interest
    merchant: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)
    tag_ids: Optional[List[int]] = Field(default=None, max_length=10)

    frequency: Optional[Frequency] = None
    interval: Optional[int] = Field(default=None, ge=1, le=52)
    start: Optional[date] = None
    days: Optional[List[int]] = Field(default=None, min_length=2, max_length=4)  # semi-monthly (REC-19)
    end_after: Optional[int] = Field(default=None, ge=1, le=999)
    end_on: Optional[date] = None
    clear_end: bool = False  # an edit that removes the end condition

    amount: Optional[Money] = None  # standard and subscription
    amount_from: Optional[date] = None  # REC-20 - when a changed amount takes effect
    price: Optional[Money] = None  # installment (REC-09)
    payments: Optional[int] = Field(default=None, ge=1, le=360)
    interest: Optional[Money] = None  # installment total interest, when known (REC-30)

    post_past: bool = False  # also post the occurrences dated before today
    reminder_days: Optional[int] = Field(default=None, ge=0, le=30)  # subscriptions (SUB-06)


class PauseIn(BaseModel):
    paused: bool


class SkipIn(BaseModel):
    on: date


class PlanPaymentIn(BaseModel):
    """
    REC-32 - money paid on an installment plan, from another account. When it
    is more than what is due, the first try answers 409 PREPAYMENT_CHOICE with
    both outcomes; send it again with `mode` to say what the extra does.
    """

    amount: Money
    from_account_id: int
    on: Optional[date] = None  # the client's today when left out
    mode: Optional[Literal["lower", "shorten"]] = None


class PayNowIn(BaseModel):
    """REC-33 - record the next occurrence now; `on` is the day it was paid (today when left out)."""

    on: Optional[date] = None


class OccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    number: int
    amount: Money
    paused: bool
    final: bool


class AmountChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    amount: Money


class InstallmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Money
    interest: Money
    total: Money
    payments: int
    per_payment: Money
    terms: Literal["provisional", "confirmed"]
    paid: Money
    remaining: Money
    payments_posted: int
    payoff_on: Optional[date] = None
    closed: bool
    # REC-32 - the plan in money terms, beside the charges above.
    money_paid: Money = Decimal("0.00")
    left_to_pay: Money = Decimal("0.00")
    current_payment: Money = Decimal("0.00")
    payments_left: int = 0
    prepaid: Money = Decimal("0.00")


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Kind
    type: RuleType
    name: str
    account_id: int
    counter_account_id: Optional[int] = None
    category_id: Optional[int] = None
    interest_category_id: Optional[int] = None
    merchant: Optional[str] = None
    notes: Optional[str] = None
    tag_ids: List[int]
    frequency: Frequency
    interval: int
    start: date
    days: List[int]
    end_after: Optional[int] = None
    end_on: Optional[date] = None
    amount: Money
    amounts: List[AmountChangeOut]
    paused: bool
    skips: List[date]
    closed_on: Optional[date] = None
    posted_through: date
    next_on: Optional[date] = None
    next_amount: Optional[Money] = None
    problem: Optional[str] = None
    reminder_days: Optional[int] = None
    cancelled_on: Optional[date] = None  # SUB-07
    installment: Optional[InstallmentOut] = None
    from_transaction: Optional[int] = None  # REC-34 - the purchase this plan replaced
    receipt_id: Optional[int] = None


class ExpansionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    posted: int
    rules: int
    needs_attention: List[int]


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule: RuleOut
    monthly: Money
    due_in_days: Optional[int] = None
    remind: bool
    cancelled_on: Optional[date] = None  # SUB-07
    saved: Money = Decimal("0.00")  # what it would have charged since
    cancel_by: Optional[date] = None
    cancel_by_in_days: Optional[int] = None
    cancel_soon: bool = False


class CancelIn(BaseModel):
    """SUB-07 - the day it was cancelled with the service; today by default."""

    on: Optional[date] = None


class CancelByIn(BaseModel):
    """SUB-07 - remind me to cancel by this day; null clears it."""

    on: Optional[date] = None


class UpcomingChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    name: str
    on: date
    amount: Money
    account_id: int


class SubscriptionOverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: List[SubscriptionOut]
    monthly_total: Money
    budget_share: Optional[Ratio] = None
    upcoming: List[UpcomingChargeOut]


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant: str
    amount: Money
    account_id: int
    category_id: Optional[int] = None
    months: int
    last_on: date
    next_on: date
    transaction_ids: List[int]


class ProjectedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    rule_id: int
    name: str
    kind: ProjectedKind
    type: RuleType
    account_id: int
    counter_account_id: Optional[int] = None
    amount: Money
    effect: Money
    paused: bool
    final: bool


class ProjectedMonthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    current: bool
    opening: Money
    income: Money
    committed: Money
    transfers: Money
    budget: Money
    spending: Money
    closing: Money
    low_point: Money
    low_on: date
    overcommitted: bool
    items: List[ProjectedItemOut]
    bills: Money = Decimal("0.00")  # ACC-35 - typed card bills taken this month, on top of spending
    bills_set_aside: Money = Decimal("0.00")  # ACC-35 - due this month, already out of cash on hand
    bills_held: Money = Decimal("0.00")  # ACC-35 - of the closing, held back on Home for bills due after it


class ProjectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    today: date
    basis: Literal["budget", "calendar"]
    cash_on_hand: Money
    months: List[ProjectedMonthOut]


class WhatIfOut(BaseModel):
    """REC-27 - the months ahead as they stand, and with the unsaved plan. Its items carry rule_id -1."""

    model_config = ConfigDict(from_attributes=True)

    without: ProjectionOut
    with_plan: ProjectionOut


class PayoffIn(BaseModel):
    """REC-35 - an extra a month, and payments typed on the planner for this run only (never stored)."""

    extra: Money = Decimal("0.00")
    payments: Dict[int, Money] = Field(default_factory=dict, max_length=100)


class PayoffDebtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: int
    name: str
    type: Literal["credit", "borrowed"]
    owed: Money
    payment: Money
    payment_source: Literal["rule", "plan", "yours", "none"]
    yearly_rate: Optional[Rate] = None
    rate: Optional[Rate] = None
    rate_per: Optional[Literal["month", "year"]] = None


class PayoffOutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    months: Optional[int] = None
    paid_off: Optional[date] = None
    interest: Money


class PayoffPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    strategy: Literal["snowball", "avalanche", "as_is"]
    extra: Money
    outcomes: List[PayoffOutcomeOut]
    months: Optional[int] = None
    debt_free: Optional[date] = None
    interest: Money


class PayoffOut(BaseModel):
    """REC-35 - as you pay now, smallest balance first, and highest rate first (only with a rate)."""

    model_config = ConfigDict(from_attributes=True)

    start: date
    debts: List[PayoffDebtOut]
    as_is: PayoffPlanOut
    snowball: PayoffPlanOut
    avalanche: Optional[PayoffPlanOut] = None


class CardStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    closes: date
    due: date
    posted: Money
    recurring: Money
    total: Money
    limit_share: Optional[Ratio] = None
    items: List[ProjectedItemOut]


class CardLookaheadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: int
    name: str
    spending_limit: Optional[Money] = None
    statements: List[CardStatementOut]
    bills: List[BillOut] = []  # ACC-35 - a card with typed bills shows them instead of statements


# ------------------------------------------------ REC-34: a purchase paid in installments


class InstallmentTermsIn(BaseModel):
    """How a purchase is spread: how many monthly payments, from when, and any interest or fee."""

    payments: int = Field(ge=1, le=360)
    start: Optional[date] = None  # the first payment; left out = the bill the purchase belongs to
    interest: Optional[Money] = None


class InstallmentPreviewIn(InstallmentTermsIn):
    account_id: int
    amount: Money
    txn_date: date
    card_posted_on: Optional[date] = None


class PlannedPaymentOut(BaseModel):
    on: date
    amount: Money


class InstallmentPreviewOut(BaseModel):
    start: date
    payments: List[PlannedPaymentOut]
    due_now: int  # posted as soon as the plan is saved
    on_closed_statement: bool


class PurchaseWithPlanIn(BaseModel):
    """The add sheet: a new purchase, paid in installments from the start."""

    purchase: TransactionIn
    terms: InstallmentTermsIn
