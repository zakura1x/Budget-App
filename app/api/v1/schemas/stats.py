"""Response shapes for /calendar and /stats (CAL-01..CAL-05, STA-01..STA-11). Amounts and ratios are strings."""

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.budgets import Ratio
from app.api.v1.schemas.common import Money


class CalendarDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    on: date
    spent: Money
    earned: Money
    count: int
    level: int
    reference: Optional[Money] = None
    reference_kind: Optional[Literal["budget", "typical"]] = None


class CalendarMonthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year: int
    month: int
    start: date
    end: date
    spent: Money
    earned: Money
    days: List[CalendarDayOut]


class CalendarYearOut(BaseModel):
    """CAL-06 - twelve months, each exactly as GET /calendar/{year}/{month} gives it."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    spent: Money
    earned: Money
    months: List[CalendarMonthOut]


class TotalsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    spent: Money
    earned: Money
    net: Money
    transaction_count: int
    days: int
    days_counted: int
    average_daily_spend: Money
    adjustment_losses: Money
    adjustment_gains: Money


class CategoryShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: Optional[int] = None
    amount: Money
    share: Ratio
    transaction_count: int
    previous_amount: Money
    direct: Money
    children: List["CategoryShareOut"] = []
    unrecorded: bool = False  # ACC-29 - the balance adjustments' own row


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    spent: Money
    earned: Money
    spent_to_same_day: Optional[Money] = None


class TrendPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    spent: Money
    earned: Money


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    amount: Money
    transaction_count: int


class AccountTotalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: int
    spent: Money
    earned: Money


class TagTotalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tag_id: int
    spent: Money
    transaction_count: int


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    spent_to_date: Money
    days_elapsed: int
    days_left: int
    daily_rate: Money
    projected: Money
    budget_available: Optional[Money] = None


class CashPointOut(BaseModel):
    """STA-10 - cash on hand at the end of a day: plain balances of the accounts that count in it today."""

    model_config = ConfigDict(from_attributes=True)

    on: date
    amount: Money


class OverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    span: Optional[Literal["budget", "month", "year"]] = None
    granularity: Literal["day", "week", "month"]
    totals: TotalsOut
    categories: List[CategoryShareOut]
    income_categories: List[CategoryShareOut]
    previous: ComparisonOut
    trend: List[TrendPointOut]
    merchants: List[MerchantOut]
    accounts: List[AccountTotalOut]
    tags: List[TagTotalOut]
    forecast: Optional[ForecastOut] = None
    cash_on_hand: List[CashPointOut] = []


# ------------------------------------------------------ STA-12 the monthly review


class ReviewPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    span: Literal["budget", "month"]


class BudgetResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    available: Money
    carried_in: Money
    spent: Money
    remaining: Money  # negative when over
    carry_over: bool


class CategoryChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: Optional[int] = None
    amount: Money
    previous: Money
    change: Money


class PlanEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    name: str
    kind: str
    event: Literal["started", "finished", "cancelled", "price"]
    on: date
    amount: Optional[Money] = None
    previous_amount: Optional[Money] = None


class BigPurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: int
    on: date
    amount: Money
    category_id: Optional[int] = None
    merchant: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period: ReviewPeriodOut
    spent: Money
    earned: Money
    net: Money
    previous_spent: Money
    budget: Optional[BudgetResultOut] = None
    changes: List[CategoryChangeOut]
    plans: List[PlanEventOut]
    purchases: List[BigPurchaseOut]
    cashback: Money
    interest: Money
    cash_start: Money
    cash_end: Money
    later: Optional[date] = None  # the next finished period's first day


class ReviewOfferOut(BaseModel):
    """Home's card, or null outside the first days of a period."""

    period: Optional[ReviewPeriodOut] = None
