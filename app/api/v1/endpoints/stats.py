"""
/stats - every chart on the Stats tab, in one response (STA-01..STA-11).

The range is `from` and `to`, or a `span` (budget | month | year) around `on`.
The response carries the resolved start and end, so the screen steps to the
next range by asking for the day after `end`. `today` is the client's date:
the forecast and "by this point last month" both turn on it.

Like /transactions, the filters travel in the query string, which the logging
middleware never records.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas.stats import OverviewOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=OverviewOut)
def overview(
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    span: Optional[str] = Query(default=None, pattern="^(budget|month|year)$"),
    on: Optional[date] = Query(default=None, description="any day in the span; today by default"),
    granularity: Optional[str] = Query(default=None, pattern="^(day|week|month)$"),
    today: Optional[date] = Query(default=None),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> OverviewOut:
    result = stats_service.overview(
        db, ctx.cipher, date_from=date_from, date_to=date_to, span=span, on=on,
        today=today, granularity=granularity,
    )
    return OverviewOut.model_validate(result)
