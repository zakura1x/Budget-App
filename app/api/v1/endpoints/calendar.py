"""
/calendar - one month of days, each with its totals and heatmap level
(CAL-01..CAL-05). A day's transactions come from GET /transactions?from=&to=.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.v1.schemas.stats import CalendarMonthOut, CalendarYearOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/{year}", response_model=CalendarYearOut)
def year(
    year: int = Path(ge=2000, le=2100),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> CalendarYearOut:
    """CAL-06 - the year view: twelve months in one request."""
    return CalendarYearOut.model_validate(calendar_service.year(db, ctx.cipher, year))


@router.get("/{year}/{month}", response_model=CalendarMonthOut)
def month(
    year: int = Path(ge=2000, le=2100),
    month: int = Path(ge=1, le=12),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> CalendarMonthOut:
    return CalendarMonthOut.model_validate(calendar_service.month(db, ctx.cipher, year, month))
