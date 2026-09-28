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

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.stats import OverviewOut, ReviewOfferOut, ReviewOut, ReviewPeriodOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import preferences_service, stats_service

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


@router.get("/review", response_model=ReviewOut)
def review(
    today: date = Query(description="the client's date"),
    on: Optional[date] = Query(default=None, description="any day in a finished period; the last one by default"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ReviewOut:
    """STA-12 - one finished period looked back on. Derived; nothing is stored."""
    return ReviewOut.model_validate(stats_service.review(db, ctx.cipher, today=today, on=on))


@router.get("/review/offer", response_model=ReviewOfferOut)
def review_offer(
    today: date = Query(description="the client's date"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ReviewOfferOut:
    prefs = preferences_service.get_preferences(db, ctx.cipher)
    period = stats_service.review_offer(db, ctx.cipher, today=today, prefs=prefs)
    return ReviewOfferOut(period=ReviewPeriodOut.model_validate(period) if period else None)


@router.post("/review/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_review(
    today: date = Query(description="the client's date"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> Response:
    """Home's "Not now" - kept in the preferences on the server, never in the browser."""
    period = stats_service.review_period(db, ctx.cipher, today=today)
    preferences_service.update_preferences(db, ctx.cipher, {"review_dismissed_for": period.start.isoformat()})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
