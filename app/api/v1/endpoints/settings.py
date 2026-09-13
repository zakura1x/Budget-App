"""
/settings - the user's preferences.

GET returns every preference, defaults filled in. PATCH changes the budget
behaviour keys Phase 5 needs - carry-over (BUD-11), the allowance mode
(BUD-07/08) and the alert thresholds (BUD-14/15); the rest of Settings is
Phase 8b.

Both sit behind get_unlocked_context: a preferences row is sealed under the
DEK like any other, and a locked session gets 401 SESSION_LOCKED here.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.schemas.budgets import PreferencesIn
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services import preferences_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/preferences")
def get_preferences(ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> dict:
    return preferences_service.get_preferences(db, ctx.cipher)


@router.patch("/preferences")
def update_preferences(
    body: PreferencesIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> dict:
    return preferences_service.update_preferences(db, ctx.cipher, body.model_dump(exclude_none=True))
