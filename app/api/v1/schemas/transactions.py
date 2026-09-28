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
from app.api.v1.schemas.common import Money, Rate

TransactionType = Literal["expense", "income", "transfer"]  # what can be entered
# A balance adjustment (ACC-29) is shown, never entered: it comes from setting an account's balance.
ListedType = Literal["expense", "income", "transfer", "adjustment"]


class SplitIn(BaseModel):
    category_id: int
    amount: Money
    note: Optional[str] = Field(default=None, max_length=120)


class CashbackIn(BaseModel):
    """
    TXN-22 - what a purchase earns back. Sent with the purchase; null takes it
    away. It lands in the same account on the same day unless told otherwise,
    which is what a wallet does - a card that pays at the end of the cycle gets
    its own date.
    """

    amount: Money
    category_id: int
    account_id: Optional[int] = None  # defaults to the account spent from
    on: Optional[date] = None  # defaults to the day of the purchase
    rate: Optional[Rate] = None  # remembered for the wording only; nothing recomputes from it


class CashbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    amount: Money
    account_id: int
    category_id: int
    on: date
    rate: Optional[Rate] = None


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
    tag_ids: Optional[List[int]] = Field(default=None, max_length=10)  # TXN-10; omitted keeps the stored ones
    # TXN-22. Left out, an edit keeps the cashback; sent as null it removes it
    # and the credit row with it.
    cashback: Optional[CashbackIn] = None


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
    tag_ids: List[int] = []
    recurring_id: Optional[int] = None  # the rule that posted it, or the plan it pays
    recurring_on: Optional[date] = None
    interest_on: Optional[date] = None  # ACC-37 - the day of savings interest this credited
    cashback: Optional[CashbackOut] = None  # TXN-22 - on the purchase
    cashback_id: Optional[int] = None  # the income row crediting it
    cashback_of: Optional[int] = None  # on that row: the purchase it came from
    attachment_id: Optional[int] = None  # TXN-15 - GET /attachments/{id}
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


class MerchantOut(BaseModel):
    """TXN-24 - a merchant typed before, and the category its latest entry was filed under."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    type: Literal["expense", "income"]
    count: int
    category_id: Optional[int] = None
    last_used: date


class DeletedOut(BaseModel):
    """TXN-25 - one line in Recently deleted; `reason` says why Restore is not offered."""

    model_config = ConfigDict(from_attributes=True)

    transaction: TransactionOut
    deleted_at: datetime
    restorable: bool
    reason: Optional[str] = None


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
