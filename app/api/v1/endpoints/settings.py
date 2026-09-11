"""
/settings - the user's preferences. Read-only until Phase 8b adds editing.

Also the first endpoint behind get_unlocked_context: a locked session gets
401 SESSION_LOCKED here, which is how the lock is proven end to end.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.repositories.preferences_repository import PreferencesRepository
from app.db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/preferences")
def get_preferences(ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> dict:
    record = PreferencesRepository(db, ctx.cipher).current()
    return record.data if record else {}
