"""Request and response shapes for /budgets and the budget settings (BUD-01..BUD-15)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.api.v1.schemas.common import Money

PeriodKind = Literal["weekly", "monthly", "custom"]

# A share of something - 0.8350 - sent as a string like money is, never a float.
Ratio = Annotated[Decimal, PlainSerializer(lambda value: str(value), return_type=str, when_used="json")]


class AllocationIn(BaseModel):
    category_id: int
    amount: Money


class BudgetIn(BaseModel):
    period: Optional[PeriodKind] = None
    amount: Optional[Money] = None
    month_start_day: Optional[int] = Field(default=None, ge=1, le=31)
    week_start_day: Optional[int] = Field(default=None, ge=1, le=7)  # 1 Monday .. 7 Sunday
    custom_days: Optional[int] = Field(default=None, ge=1, le=366)
    custom_anchor: Optional[date] = None
    allocations: Optional[List[AllocationIn]] = Field(default=None, max_length=300)


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    amount: Money


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period: PeriodKind
    month_start_day: int
    week_start_day: int
    custom_days: Optional[int] = None
    custom_anchor: Optional[date] = None
    amount: Money
    structure_from: date
    allocations: List[AllocationOut]


class BudgetEnvelope(BaseModel):
    budget: Optional[BudgetOut]


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start: date
    end: date
    days: int


class AllowanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mode: str
    budget: Money
    carried_in: Money
    available: Money
    spent: Money
    spent_before_today: Money
    spent_today: Money
    remaining: Money
    daily: Money
    left_today: Money
    over_by: Money
    days_total: int
    days_elapsed: int
    days_left: int
    used_ratio: Ratio  # a ratio, not money - still never a float


class CategoryProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int
    allocated: Money
    spent: Money
    remaining: Money
    used_ratio: Ratio
    over: bool


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    severity: Literal["danger", "warn"]
    message: str
    category_id: Optional[int] = None
    account_id: Optional[int] = None


class StatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    budget: BudgetOut
    period: PeriodOut
    previous_period: PeriodOut
    next_period: PeriodOut
    is_current: bool
    carry_over: bool
    allowance: AllowanceOut
    categories: List[CategoryProgressOut]
    allocated: Money
    unallocated: Money
    alerts: List[AlertOut]


class StatusEnvelope(BaseModel):
    status: Optional[StatusOut]


class ProgressOut(BaseModel):
    period: PeriodOut
    categories: List[CategoryProgressOut]
    allocated: Money
    unallocated: Money


class PreferencesIn(BaseModel):
    carry_over: Optional[bool] = None
    daily_allowance_mode: Optional[Literal["remaining_over_days_left", "fixed_daily"]] = None
    alert_warn_threshold_pct: Optional[int] = Field(default=None, ge=50, le=100)
    alert_pace_enabled: Optional[bool] = None
