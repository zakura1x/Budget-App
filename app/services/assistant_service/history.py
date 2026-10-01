"""
Saved conversations (misc/AI, Phase A6, AI-60).

Off by default. With the `assistant_history_days` preference at 0 a
conversation lives in process memory only and goes with the key (memory.py,
AI-53) - the promise A1-A5 made. Above 0, each turn is also written to an
`assistant_threads` row sealed under the user's DEK, kept until it has gone
that many days untouched. Locking still drops the decrypted copy in memory; the
sealed row waits for the next unlock.

The only writer of assistant_threads. The caller commits. What is saved is
the question and the reply as the API returned it, minus draft buttons: their
payloads name accounts and categories by id, and a saved thread is restored
into other accounts without its ids being remapped (references.py lists none).
Nothing here is logged.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.db.repositories.assistant_thread_repository import AssistantThreadRepository
from app.db.repositories.encrypted_repository import Record
from app.services.assistant_service.memory import Conversation, Turn

# The choices the preference allows; 0 = keep nothing (memory only).
KEEP_CHOICES = (0, 30, 90, 365)
MAX_THREADS = 50  # the oldest goes when a 51st is saved
TITLE_CHARS = 60
SAVED_ACTIONS = ("open_screen",)


@dataclass(frozen=True)
class ThreadSummary:
    conversation_id: str
    title: str
    started_at: str
    updated_at: str
    turns: int


def keep_days(db: Session, cipher: UserCipher) -> int:
    from app.services import preferences_service  # it imports this module to purge

    value = preferences_service.get_preferences(db, cipher).get("assistant_history_days") or 0
    return value if value in KEEP_CHOICES else 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _saved_reply(reply: Mapping[str, Any]) -> Dict[str, Any]:
    return {**reply, "actions": [a for a in reply.get("actions") or [] if a.get("kind") in SAVED_ACTIONS]}


def _title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def _expired(data: Mapping[str, Any], days: int, now: datetime) -> bool:
    try:
        updated = datetime.fromisoformat(str(data.get("updated_at")))
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated < now - timedelta(days=days)


def _live(repo: AssistantThreadRepository, days: int) -> List[Record]:
    """Every saved thread still inside its keeping time, newest first; the rest are deleted for good."""
    now = _now()
    kept = []
    for record in repo.list():
        if days == 0 or _expired(record.data, days, now):
            repo.hard_delete(record.id)
        else:
            kept.append(record)
    # newest first; the row id breaks a tie inside one second (a later row is a later conversation)
    return sorted(kept, key=lambda r: (str(r.data.get("updated_at")), r.id), reverse=True)


def save(db: Session, cipher: UserCipher, conversation: Conversation) -> None:
    """After a turn: write the conversation if the user keeps them. Creates the row on the first turn."""
    days = keep_days(db, cipher)
    if days == 0 or not conversation.turns:
        return
    repo = AssistantThreadRepository(db, cipher)
    now = _stamp(_now())
    turns = [{"question": t.question, "reply": _saved_reply(t.reply)} for t in conversation.turns]
    existing = repo.get(conversation.thread_id) if conversation.thread_id else None
    if existing is not None:
        repo.update(existing.id, {**existing.data, "turns": turns, "updated_at": now})
        return
    record = repo.create({
        "conversation_id": conversation.id, "title": _title(conversation.turns[0].question),
        "started_at": now, "updated_at": now, "turns": turns,
    })
    conversation.thread_id = record.id
    for old in _live(repo, days)[MAX_THREADS:]:
        repo.hard_delete(old.id)


def summaries(db: Session, cipher: UserCipher) -> Tuple[int, List[ThreadSummary]]:
    """(keep_days, the saved threads newest first). Prunes what has run out - the caller commits."""
    days = keep_days(db, cipher)
    records = _live(AssistantThreadRepository(db, cipher), days)
    return days, [
        ThreadSummary(conversation_id=str(r.data["conversation_id"]), title=str(r.data.get("title") or ""),
                      started_at=str(r.data.get("started_at")), updated_at=str(r.data.get("updated_at")),
                      turns=len(r.data.get("turns") or []))
        for r in records
    ]


def _find(repo: AssistantThreadRepository, conversation_id: str) -> Optional[Record]:
    return next((r for r in repo.list() if r.data.get("conversation_id") == conversation_id), None)


def load(db: Session, cipher: UserCipher, conversation_id: str) -> Optional[Conversation]:
    """A saved thread as a conversation, or None - also None when the user no longer keeps them."""
    if not conversation_id or keep_days(db, cipher) == 0:
        return None
    record = _find(AssistantThreadRepository(db, cipher), conversation_id)
    if record is None:
        return None
    turns = [Turn(question=t["question"], reply=t["reply"]) for t in record.data.get("turns") or []]
    return Conversation(id=conversation_id, turns=turns, thread_id=record.id)


def delete(db: Session, cipher: UserCipher, conversation_id: str) -> bool:
    repo = AssistantThreadRepository(db, cipher)
    record = _find(repo, conversation_id)
    return record is not None and repo.hard_delete(record.id)


def purge(db: Session, cipher: UserCipher) -> int:
    """Every saved thread, gone for good: keeping turned off, or the assistant turned off. The caller commits."""
    repo = AssistantThreadRepository(db, cipher)
    records = repo.list(include_deleted=True)
    for record in records:
        repo.hard_delete(record.id)
    return len(records)
