"""
Request and response shapes for /transactions (TXN-01..TXN-21).

Amounts cross the wire as strings in both directions (common.Money). Splits are
optional on the way in - `category_id` alone is shorthand for one split - but
every transaction in a response carries its splits, because every stored one
has them (TXN-16).
"""

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.accounts import AccountOut, CashOnHandOut
from app.api.v1.schemas.budgets import StatusOut
from app.api.v1.schemas.common import Money

TransactionType = Literal["expense", "income", "transfer"]  # what can be entered
# A balance adjustment (ACC-29) is shown, never entered: it comes from setting an account's balance.
ListedType = Literal["expense", "income", "transfer", "adjustment"]


class SplitIn(BaseModel):
    category_id: int
    amount: Money
    note: Optional[str] = Field(default=None, max_length=120)


class TransactionIn(BaseModel):
    type: TransactionType
    amount: Money
    account_id: int
    txn_date: Optional[date] = None  # the client's own today, ideally; the server's otherwise
    category_id: Optional[int] = None  # shorthand for a single split
    splits: Optional[List[SplitIn]] = Field(default=None, min_length=1, max_length=20)
    counter_account_id: Optional[int] = None  # transfers: where the money goes
    merchant: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)


class RepeatIn(BaseModel):
    on: Optional[date] = None


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: Optional[int]
    amount: Money
    note: Optional[str] = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ListedType
    txn_date: date
    amount: Money
    account_id: int
    splits: List[SplitOut]
    merchant: Optional[str] = None
    notes: Optional[str] = None
    direction: Optional[Literal["out", "in"]] = None
    counter_account_id: Optional[int] = None
    pair_id: Optional[int] = None
    created_at: Optional[datetime] = None
    card_posted_on: Optional[date] = None  # ACC-26


class DayTotalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    spent: Money
    earned: Money


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: List[TransactionOut]
    next_cursor: Optional[str]
    total_count: int
    days: List[DayTotalOut]


class OutcomeOut(BaseModel):
    """
    Everything a write changed, so no screen needs a second request - the
    rows, the touched accounts, cash on hand, and the budget status the home
    ring animates to (null until a budget exists).
    """

    model_config = ConfigDict(from_attributes=True)

    transactions: List[TransactionOut]
    accounts: List[AccountOut]
    cash_on_hand: CashOnHandOut
    budget_status: Optional[StatusOut] = None
