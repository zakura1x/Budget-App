"""
assistant_threads - Shape B. A saved AI companion conversation (misc/AI, A6, AI-60).

Payload: conversation_id (the token the API names it by), title (the first
question, cut short), started_at, updated_at, and turns - each the question and
the reply as the API returned it, with draft buttons left out (their payloads
name rows by id, which a restore into another account would not remap).

Written only while the user's `assistant_history_days` preference is above 0,
and only by assistant_service.history. It holds figures and the user's own
words, so it is sealed under the user's DEK like every other Shape B row, and
DEK rotation, account deletion, backup and the integrity check reach it
through ENCRYPTED_MODELS and backup_service/references.py ORDER.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class AssistantThread(EncryptedRowMixin, Base):
    __tablename__ = "assistant_threads"
