"""
The in-memory session keyring - where an unlocked DEK lives, and dies.

ARCHITECTURE.md section 5.5: a plaintext DEK is held in process memory only,
for the life of a session, and is zeroed on logout, expiry or lock.

Two behaviours matter more than the rest:

  * AN EMPTY KEYRING MEANS LOCKED, NEVER AN ERROR (SEC-27). IIS idle-stops
    this process after 20 minutes, recycles it, and restarts it on deploy.
    Each time, every entry here is gone while the browser's cookies are still
    valid. cipher_for() returns None, the caller answers "locked", and the PIN
    brings the key back. Nobody sees a 500.

  * AUTO-LOCK IS ENFORCED HERE, NOT ONLY IN THE BROWSER. An entry idle for
    longer than the timeout is dropped the next time anyone asks for it. A
    frontend timer is a convenience; this is the guarantee.

One process, one keyring: this is why web.config runs exactly one worker.

Whatever else was decrypted with a key must go when the key goes. Listeners
added with add_drop_listener() hear the user id of every entry dropped, for
any reason, AFTER its DEK is zeroed - the working set uses this to forget that
user's plaintext rows in the same moment (ARCHITECTURE.md 5.5).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

from app.core.crypto.dek import zero
from app.core.crypto.envelope import KEY_BYTES
from app.core.crypto.user_cipher import UserCipher


@dataclass
class _Entry:
    user_id: int
    key_version: int
    dek: bytearray
    cipher: UserCipher
    unlocked_at: float
    last_used: float = field(default=0.0)


class SessionKeyring:
    """Session id -> unlocked DEK. Thread-safe; zeroes what it drops."""

    def __init__(self, idle_timeout_seconds: Optional[float], clock: Callable[[], float] = time.monotonic):
        self._idle_timeout = idle_timeout_seconds
        self._clock = clock
        self._entries: Dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._listeners: List[Callable[[int], None]] = []

    def add_drop_listener(self, listener: Callable[[int], None]) -> None:
        """Hear the user id of every dropped entry. Adding the same one twice is a no-op."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def _dropped(self, user_ids: Iterable[int]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for user_id in set(user_ids):
            for listener in listeners:
                try:
                    listener(user_id)
                except Exception:  # a listener must never stop a lock from completing
                    logger.exception("Keyring drop listener failed")

    def unlock(self, session_id: str, user_id: int, dek: bytearray, key_version: int) -> None:
        """
        Store a DEK for a session. TAKES OWNERSHIP: the keyring copies the key
        into its own buffer and zeroes the one it was given, so the caller is
        left holding nothing worth stealing.
        """
        if len(dek) != KEY_BYTES:
            raise ValueError(f"a DEK is {KEY_BYTES} bytes")
        own = bytearray(dek)
        zero(dek)
        now = self._clock()
        entry = _Entry(
            user_id=user_id,
            key_version=key_version,
            dek=own,
            cipher=UserCipher(user_id, own, key_version),
            unlocked_at=now,
            last_used=now,
        )
        with self._lock:
            previous = self._entries.pop(session_id, None)
            self._entries[session_id] = entry
        if previous is not None:
            zero(previous.dek)

    def cipher_for(self, session_id: str) -> Optional[UserCipher]:
        """
        The session's cipher, or None if it is locked. Counts as activity.
        None covers every reason - never unlocked, locked, idle too long,
        process restarted - because the caller's answer is the same for all.
        """
        now = self._clock()
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if self._is_idle(entry, now):
                del self._entries[session_id]
                expired = entry
            else:
                entry.last_used = now
                return entry.cipher
        zero(expired.dek)
        self._dropped([expired.user_id])
        return None

    def is_unlocked(self, session_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(session_id)
            return entry is not None and not self._is_idle(entry, self._clock())

    def user_of(self, session_id: str) -> Optional[int]:
        with self._lock:
            entry = self._entries.get(session_id)
            return entry.user_id if entry else None

    def lock(self, session_id: str) -> bool:
        """Drop one session's key. True if there was one."""
        with self._lock:
            entry = self._entries.pop(session_id, None)
        if entry is None:
            return False
        zero(entry.dek)
        self._dropped([entry.user_id])
        return True

    def lock_user(self, user_id: int) -> int:
        """Drop every session of one user - rotation, deletion, 'sign out everywhere'."""
        with self._lock:
            doomed = [sid for sid, e in self._entries.items() if e.user_id == user_id]
            entries = [self._entries.pop(sid) for sid in doomed]
        for entry in entries:
            zero(entry.dek)
        self._dropped(entry.user_id for entry in entries)
        return len(entries)

    def lock_all(self) -> int:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            zero(entry.dek)
        self._dropped(entry.user_id for entry in entries)
        return len(entries)

    def sweep(self) -> int:
        """Drop every idle entry now, rather than on next access."""
        now = self._clock()
        with self._lock:
            doomed = [sid for sid, e in self._entries.items() if self._is_idle(e, now)]
            entries = [self._entries.pop(sid) for sid in doomed]
        for entry in entries:
            zero(entry.dek)
        self._dropped(entry.user_id for entry in entries)
        return len(entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _is_idle(self, entry: _Entry, now: float) -> bool:
        return self._idle_timeout is not None and now - entry.last_used > self._idle_timeout

    def __repr__(self) -> str:
        return f"SessionKeyring(sessions={len(self)})"


_session_keyring: Optional[SessionKeyring] = None
_session_keyring_lock = threading.Lock()


def get_session_keyring() -> SessionKeyring:
    """The process-wide keyring. Idle timeout = PIN_AUTO_LOCK_MINUTES."""
    global _session_keyring
    with _session_keyring_lock:
        if _session_keyring is None:
            from app.core.config import settings

            _session_keyring = SessionKeyring(idle_timeout_seconds=settings.PIN_AUTO_LOCK_MINUTES * 60)
        return _session_keyring
