"""
/assistant - the AI companion (misc/AI ARCHITECTURE §10). HTTP only.

- GET /assistant/status - may this user ask, have they opted in, questions
  left today, suggested questions. Never loads credentials or calls IAM.
- POST /assistant/ask - one question. Refused when the assistant is off for
  this user (503) or they have not opted in (403); a model failure is NOT an
  error - the reply is the skill's own sentence, with ai_phrased false.
- GET / DELETE /assistant/conversations/{id} - this session's turns, held in
  memory only and gone after a lock (AI-53).
- GET /assistant/health - admin only: STWRD's health() plus today's usage.
  It loads the key and asks the model for one word, so it is a button.
- GET /assistant/usage - admin only: the last week's counts, every account
  summed. Reads assistant_usage and nothing else - no IAM, no model.

Nothing here writes financial data; the only row written is the usage count.
Questions travel in POST bodies, never in a URL (IIS logs query strings).
"""

from fastapi import APIRouter, Depends, Response, status as http_status
from sqlalchemy.orm import Session

from app.ai import llm_service
from app.api.v1.endpoints.admin import require_admin
from app.api.v1.schemas.assistant import (
    AskIn,
    AssistantHealthOut,
    AssistantStatusOut,
    AssistantUsageOut,
    ConversationOut,
    ReplyOut,
    UsageDayOut,
    UsageTodayOut,
)
from app.core.config import settings
from app.core.deps import UnlockedContext, get_unlocked_context
from app.core.exceptions import AssistantDisabledException, AssistantNotOptedInException, NotFoundException
from app.db.session import get_db
from app.services import preferences_service
from app.services.assistant_service import router as assistant_router
from app.services.assistant_service import turn, usage
from app.services.assistant_service.memory import get_memory

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _opted_in(db: Session, ctx: UnlockedContext) -> bool:
    return bool(preferences_service.get_preferences(db, ctx.cipher).get("assistant"))


@router.get("/status", response_model=AssistantStatusOut)
def status(ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> AssistantStatusOut:
    allowed = llm_service.is_allowed(ctx.user.id)
    return AssistantStatusOut(
        enabled=allowed,
        opted_in=_opted_in(db, ctx),
        questions_left_today=usage.questions_left(db, ctx.user.id) if allowed else 0,
        reply_language=settings.AI_REPLY_LANGUAGE,
        suggestions=assistant_router.suggestions() if allowed else [],
    )


@router.post("/ask", response_model=ReplyOut)
def ask(body: AskIn, ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> ReplyOut:
    # A plain def: FastAPI runs it in the thread pool, so the model wait never blocks the loop.
    if not llm_service.is_allowed(ctx.user.id):
        raise AssistantDisabledException("The assistant is switched off")
    if not _opted_in(db, ctx):
        raise AssistantNotOptedInException("Turn the assistant on first")
    reply = turn.ask(db, ctx.cipher, question=body.question, today=body.today,
                     conversation_id=body.conversation_id,
                     context=body.context.model_dump(exclude_none=True) if body.context else None)
    return ReplyOut(**reply)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: str, ctx: UnlockedContext = Depends(get_unlocked_context)) -> ConversationOut:
    found = get_memory().get(ctx.user.id, conversation_id)
    if found is None:
        raise NotFoundException("That conversation has ended")
    return ConversationOut(conversation_id=found.id, turns=[ReplyOut(**t.reply) for t in found.turns])


@router.delete("/conversations/{conversation_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def forget(conversation_id: str, ctx: UnlockedContext = Depends(get_unlocked_context)) -> Response:
    get_memory().forget(ctx.user.id, conversation_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get("/usage", response_model=AssistantUsageOut)
def usage_by_day(ctx: UnlockedContext = Depends(require_admin), db: Session = Depends(get_db)) -> AssistantUsageOut:
    pilot = settings.ai_allowed_user_ids
    return AssistantUsageOut(
        enabled=llm_service.is_enabled(),
        model=settings.WATSONX_CHAT_MODEL,
        pilot_users=len(pilot) if pilot else None,
        days=[UsageDayOut(day=day, **totals.__dict__) for day, totals in usage.daily(db)],
    )


@router.get("/health", response_model=AssistantHealthOut)
def health(ctx: UnlockedContext = Depends(require_admin), db: Session = Depends(get_db)) -> AssistantHealthOut:
    report = llm_service.health(check_model=True)
    totals = usage.totals(db)
    return AssistantHealthOut(**report, usage_today=UsageTodayOut(**totals.__dict__))
