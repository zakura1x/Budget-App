"""
Conversations, in process memory only (misc/AI ARCHITECTURE §7, AI-53).

A conversation is decrypted money talk, so it follows the working set's rule:
it goes when the key goes. The first use registers a drop listener on the
session keyring, which calls forget_user() on lock, sign-out, idle expiry and
the sweep, and IIS stopping the process clears the rest. Nothing here reaches
the database, a log or the browser's storage.

Bounded per user, oldest out: at most MAX_CONVERSATIONS conversations of
MAX_TURNS turns each.
"""

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

MAX_CONVERSATIONS = 5
MAX_TURNS = 20


@dataclass
class Turn:
    question: str
    reply: Dict[str, Any]  # the reply exactly as the API returned it


@dataclass
class Conversation:
    id: str
    turns: List[Turn] = field(default_factory=list)

    def history(self) -> List[Tuple[str, str]]:
        return [(t.question, t.reply["text"]) for t in self.turns]


class ConversationMemory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_user: Dict[int, "OrderedDict[str, Conversation]"] = {}

    def get(self, user_id: int, conversation_id: Optional[str]) -> Optional[Conversation]:
        if not conversation_id:
            return None
        with self._lock:
            return self._by_user.get(user_id, OrderedDict()).get(conversation_id)

    def get_or_start(self, user_id: int, conversation_id: Optional[str]) -> Conversation:
        """The conversation asked for, or a new one - a forgotten id starts afresh rather than failing."""
        with self._lock:
            conversations = self._by_user.setdefault(user_id, OrderedDict())
            found = conversations.get(conversation_id) if conversation_id else None
            if found is None:
                found = Conversation(id=secrets.token_urlsafe(12))
                conversations[found.id] = found
                while len(conversations) > MAX_CONVERSATIONS:
                    conversations.popitem(last=False)
            conversations.move_to_end(found.id)
            return found

    def append(self, user_id: int, conversation: Conversation, turn: Turn) -> None:
        with self._lock:
            conversation.turns.append(turn)
            del conversation.turns[:-MAX_TURNS]

    def forget(self, user_id: int, conversation_id: str) -> bool:
        with self._lock:
            return self._by_user.get(user_id, OrderedDict()).pop(conversation_id, None) is not None

    def forget_user(self, user_id: int) -> None:
        with self._lock:
            self._by_user.pop(user_id, None)

    def users(self) -> int:
        with self._lock:
            return len(self._by_user)


_memory: Optional[ConversationMemory] = None
_memory_lock = threading.Lock()


def get_memory() -> ConversationMemory:
    global _memory
    with _memory_lock:
        if _memory is None:
            from app.core.crypto.session_keys import get_session_keyring

            _memory = ConversationMemory()
            get_session_keyring().add_drop_listener(_on_key_dropped)
        return _memory


def _on_key_dropped(user_id: int) -> None:
    if _memory is not None:
        _memory.forget_user(user_id)


def set_memory(memory: Optional[ConversationMemory]) -> None:
    """Tests only."""
    global _memory
    with _memory_lock:
        _memory = memory
