"""
Request and response shapes for /accounts (ACC-01..ACC-18).

No currency field anywhere, on purpose (ACC-11): PHP is a formatting constant
in the frontend, not data. Amounts cross the wire as strings.
"""

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import Colour, DayOfMonth, IconName, Money

AccountType = Literal["cash", "debit", "credit", "savings", "investment"]


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: AccountType
    opening_balance: Money = Decimal("0.00")
    colour: Optional[Colour] = None
    icon: Optional[IconName] = None
    archived: bool = False
    counts_in_cash_on_hand: Optional[bool] = None  # ACC-18 - defaults by type
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)
    note: Optional[str] = Field(default=None, max_length=280)

    # Credit cards only (ACC-09/14/21). Ignored on any other type.
    statement_closing_day: Optional[DayOfMonth] = None
    payment_due_day: Optional[DayOfMonth] = None
    credit_limit: Optional[Money] = None
    spending_limit: Optional[Money] = None  # your own, per statement cycle - not the bank's

    # ACC-27/28. On an edit: the balance you typed, and - once the server has
    # answered BALANCE_DIFFERS - what to do with the difference.
    balance: Optional[Money] = None
    balance_action: Optional[Literal["adjust", "fix_opening"]] = None
    balance_note: Optional[str] = Field(default=None, max_length=280)


class ArchiveIn(BaseModel):
    archived: bool


class ValuationIn(BaseModel):
    """ACC-13 - a value you type on an investment account, kept with its date."""

    value: Money
    on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=280)


class ValuationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    value: Money
    note: Optional[str] = None


class StatementOut(BaseModel):
    """One closed statement (ACC-19/20/24). `difference` is null until the bank's total is entered."""

    model_config = ConfigDict(from_attributes=True)

    account_id: int
    start: date
    closes: date
    due: date
    amount: Money
    paid_since_close: Money
    left_to_pay: Money
    overdue: bool
    bank_total: Optional[Money] = None
    difference: Optional[Money] = None


class CreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    limit: Optional[Money]
    statement_closing_day: int
    payment_due_day: int
    period_start: date
    period_closes: date
    payment_due: date
    due_for_statement_closing: date
    period_spend: Money
    owed: Money
    unpaid_installments: Money
    available: Optional[Money]
    due_in_days: int
    due_soon: bool
    bill: StatementOut
    amount_due: Money
    spending_limit: Optional[Money] = None
    limit_spent: Money
    limit_left: Optional[Money] = None
    period_days: int
    period_days_elapsed: int


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    opening_balance: Money
    balance: Money
    colour: str
    icon: str
    archived: bool
    counts_in_cash_on_hand: bool
    sort_order: int
    note: Optional[str] = None
    credit: Optional[CreditOut] = None
    valuations: List[ValuationOut] = []
    current_value: Optional[Money] = None


class CashOnHandOut(BaseModel):
    """ACC-17. Named for what it is, so nothing downstream calls it net worth."""

    model_config = ConfigDict(from_attributes=True)

    total: Money
    account_ids: List[int]
    excluded_ids: List[int]


class AccountListOut(BaseModel):
    accounts: List[AccountOut]
    cash_on_hand: CashOnHandOut


class DeletedOut(BaseModel):
    deleted: List[int]
    transactions_moved: int
    reassigned_to: Optional[int] = None
