"""
The AI companion's daily counts (misc/AI ARCHITECTURE §7, AI-05).

Reads and writes `assistant_usage`, a Shape A table of plain integers - no
question, reply or figure is ever passed in, so there is nothing to encrypt.
The caller commits. ZBDGT runs one worker and allows one question in flight per
user (AI-04), so read-then-write per (user, day) cannot race itself.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AssistantUsage


@dataclass(frozen=True)
class UsageTotals:
    users: int
    questions: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    fallbacks: int


def _row(db: Session, user_id: int, day: date) -> Optional[AssistantUsage]:
    return db.execute(
        select(AssistantUsage).where(AssistantUsage.user_id == user_id, AssistantUsage.day == day)
    ).scalar_one_or_none()


def questions_today(db: Session, user_id: int, *, day: Optional[date] = None) -> int:
    row = _row(db, user_id, day or date.today())
    return row.questions if row else 0


def questions_left(db: Session, user_id: int, *, day: Optional[date] = None) -> Optional[int]:
    """None when there is no cap (AI_MAX_QUESTIONS_PER_DAY=0)."""
    cap = settings.AI_MAX_QUESTIONS_PER_DAY
    if not cap:
        return None
    return max(0, cap - questions_today(db, user_id, day=day))


def record(
    db: Session,
    user_id: int,
    *,
    day: Optional[date] = None,
    questions: int = 0,
    model_calls: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    fallbacks: int = 0,
) -> AssistantUsage:
    """Add to today's counts, creating the row on the first question of the day."""
    day = day or date.today()
    row = _row(db, user_id, day)
    if row is None:
        row = AssistantUsage(user_id=user_id, day=day, questions=0, model_calls=0, prompt_tokens=0,
                             completion_tokens=0, fallbacks=0)
        db.add(row)
    row.questions += questions
    row.model_calls += model_calls
    row.prompt_tokens += prompt_tokens
    row.completion_tokens += completion_tokens
    row.fallbacks += fallbacks
    db.flush()
    return row


def totals(db: Session, *, day: Optional[date] = None) -> UsageTotals:
    """Every user's counts for one day, summed - what the Admin screen shows."""
    day = day or date.today()
    users, *sums = db.execute(
        select(
            func.count(AssistantUsage.id),
            func.coalesce(func.sum(AssistantUsage.questions), 0),
            func.coalesce(func.sum(AssistantUsage.model_calls), 0),
            func.coalesce(func.sum(AssistantUsage.prompt_tokens), 0),
            func.coalesce(func.sum(AssistantUsage.completion_tokens), 0),
            func.coalesce(func.sum(AssistantUsage.fallbacks), 0),
        ).where(AssistantUsage.day == day)
    ).one()
    return UsageTotals(int(users), *(int(s) for s in sums))
