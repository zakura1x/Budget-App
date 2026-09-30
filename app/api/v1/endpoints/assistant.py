"""
/assistant - the AI companion (misc/AI ARCHITECTURE §10). HTTP only.

Phase A1 mounts the two routes that load nothing a user asks about:

- GET /assistant/status - whether this user may use the assistant, and how
  many questions are left today. Never loads credentials or calls IAM, so the
  client may ask it freely.
- GET /assistant/health - admin only: STWRD's health() - credentials loaded
  from IAM and accepted by IBM, the model replying, milliseconds each - plus
  today's usage totals. It makes one tiny model call ("Reply with the single
  word OK."), which carries no user data.

Questions (POST /assistant/ask) arrive in A2 (misc/AI/PHASES.md).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai import llm_service
from app.api.v1.endpoints.admin import require_admin
from app.api.v1.schemas.assistant import AssistantHealthOut, AssistantStatusOut, UsageTodayOut
from app.core.deps import UnlockedContext, get_unlocked_context
from app.db.session import get_db
from app.services.assistant_service import usage

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status", response_model=AssistantStatusOut)
def status(ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> AssistantStatusOut:
    allowed = llm_service.is_allowed(ctx.user.id)
    return AssistantStatusOut(
        enabled=allowed,
        questions_left_today=usage.questions_left(db, ctx.user.id) if allowed else 0,
    )


@router.get("/health", response_model=AssistantHealthOut)
def health(ctx: UnlockedContext = Depends(require_admin), db: Session = Depends(get_db)) -> AssistantHealthOut:
    # A plain def on purpose: FastAPI runs it in the thread pool, so the IAM and
    # watsonx waits (up to WATSONX_TIMEOUT) never block the event loop.
    report = llm_service.health(check_model=True)
    totals = usage.totals(db)
    return AssistantHealthOut(**report, usage_today=UsageTodayOut(**totals.__dict__))
