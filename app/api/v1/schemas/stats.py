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
