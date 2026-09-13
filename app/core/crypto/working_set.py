"""
The working set - each unlocked user's decrypted rows, held in process memory
(ARCHITECTURE.md 5.5, 5.6).

SQL cannot filter, sort, sum or search inside a payload, so every list, total
and search in this app is a Python loop over decrypted records. Decrypting the
whole table on every request would cost a cold load each time; this keeps the
result between requests instead.

    per user, per table   one dict of row id -> Record
    TTL-bounded           CACHE_TTL_SECONDS since it was loaded; a safety net
                          for writes that bypass the app (a script, a restore)
    LRU across users      CACHE_MAX_USERS, least recently used evicted first
    write-through         the repository applies each committed write here, so
                          a mutation never costs a reload
    dropped with the key  lock, logout, idle expiry and process restart all
                          empty a user's entry the moment their DEK goes -
                          decrypted data must not outlive the key that made it

This module decrypts nothing and imports nothing from app/db. It is handed a
LOADER by the repository (invariant 1: repositories are the only layer that
opens a ciphertext), and it stores whatever that loader returns.

Records are shared, not copied. They are frozen dataclasses, but their `data`
dicts are not - a caller that wants to change one builds a new dict.
"""

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class _Table:
    rows: Dict[int, Any]
    loaded_at: float


@dataclass
class _UserEntry:
    tables: Dict[str, _Table] = field(default_factory=dict)


class WorkingSet:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_users: int,
        max_rows_per_user: int,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._ttl = ttl_seconds
        self._max_users = max(1, max_users)
        self._max_rows = max_rows_per_user
        self._enabled = enabled
        self._clock = clock
        self._users: "OrderedDict[int, _UserEntry]" = OrderedDict()
        # Per-user epoch, bumped by every write and every drop, and kept even
        # after the user's entry is gone. A cold load that started in an older
        # epoch may predate the data it would overwrite, so it is not stored.
        # One int per user ever seen - bounded by MAX_USERS in practice.
        self._epochs: Dict[int, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ read

    def rows(self, user_id: int, table: str, loader: Callable[[], Iterable[Any]]) -> List[Any]:
        """
        Every cached row for (user, table), loading them on a miss. Ordered by
        id, which is insertion order - the same order `list()` returns.
        """
        if not self._enabled:
            return list(loader())

        now = self._clock()
        with self._lock:
            entry = self._users.get(user_id)
            if entry is not None:
                self._users.move_to_end(user_id)
                cached = entry.tables.get(table)
                if cached is not None and now - cached.loaded_at <= self._ttl:
                    return [cached.rows[k] for k in sorted(cached.rows)]
            epoch = self._epochs.get(user_id, 0)

        # Load OUTSIDE the lock - a cold load is the slow path and must not
        # stall every other user's warm reads while it runs.
        started = self._clock()
        loaded = list(loader())
        elapsed_ms = int((self._clock() - started) * 1000)

        if len(loaded) > self._max_rows:
            logger.warning("Working set not cached: rows=%d over CACHE_MAX_ROWS_PER_USER=%d table=%s",
                           len(loaded), self._max_rows, table)
            return loaded

        with self._lock:
            if self._epochs.get(user_id, 0) != epoch:
                # A write or a lock landed while this load ran. The load may
                # predate it; serve it to this caller, never keep it.
                return loaded
            entry = self._users.get(user_id)
            if entry is None:
                entry = self._users[user_id] = _UserEntry()
            entry.tables[table] = _Table({row.id: row for row in loaded}, self._clock())
            self._users.move_to_end(user_id)
            self._evict()
        logger.info("Working set loaded table=%s rows=%d elapsed_ms=%d", table, len(loaded), elapsed_ms)
        return loaded

    def is_warm(self, user_id: int, table: str) -> bool:
        with self._lock:
            entry = self._users.get(user_id)
            cached = entry.tables.get(table) if entry else None
            return cached is not None and self._clock() - cached.loaded_at <= self._ttl

    # ----------------------------------------------------------------- write

    def put(self, user_id: int, table: str, row: Any) -> None:
        """A committed insert or update. Ignored if the table is not loaded -
        the next read loads it from the database, which already has the row."""
        with self._lock:
            self._bump(user_id)
            entry = self._users.get(user_id)
            cached = entry.tables.get(table) if entry else None
            if cached is not None:
                cached.rows[row.id] = row

    def remove(self, user_id: int, table: str, row_id: int) -> None:
        with self._lock:
            self._bump(user_id)
            entry = self._users.get(user_id)
            cached = entry.tables.get(table) if entry else None
            if cached is not None:
                cached.rows.pop(row_id, None)

    def drop(self, user_id: int) -> bool:
        """Forget everything decrypted for this user. True if there was anything."""
        with self._lock:
            self._bump(user_id)  # even with nothing cached: a load may be in flight
            return self._users.pop(user_id, None) is not None

    def clear(self) -> int:
        with self._lock:
            count = len(self._users)
            for user_id in set(self._epochs) | set(self._users):
                self._bump(user_id)
            self._users.clear()
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._users)

    # -------------------------------------------------------------- internal

    def _bump(self, user_id: int) -> None:
        self._epochs[user_id] = self._epochs.get(user_id, 0) + 1

    def _evict(self) -> None:
        while len(self._users) > self._max_users:
            user_id, _ = self._users.popitem(last=False)
            logger.info("Working set evicted least recently used user=%s", user_id)

    def __repr__(self) -> str:
        return f"WorkingSet(users={len(self)}, enabled={self._enabled})"


_working_set: Optional[WorkingSet] = None
_working_set_lock = threading.Lock()


def _on_key_dropped(user_id: int) -> None:
    """Keyring listener: a DEK was just zeroed, so the plaintext it opened goes too."""
    current = _working_set
    if current is not None:
        current.drop(user_id)


def get_working_set() -> WorkingSet:
    global _working_set
    with _working_set_lock:
        if _working_set is None:
            from app.core.config import settings
            from app.core.crypto.session_keys import get_session_keyring

            _working_set = WorkingSet(
                ttl_seconds=settings.CACHE_TTL_SECONDS,
                max_users=settings.CACHE_MAX_USERS,
                max_rows_per_user=settings.CACHE_MAX_ROWS_PER_USER,
                enabled=settings.CACHE_ENABLED,
            )
            get_session_keyring().add_drop_listener(_on_key_dropped)
        return _working_set


def set_working_set(working_set: Optional[WorkingSet]) -> None:
    """Swap the process working set - tests start every case from empty."""
    global _working_set
    with _working_set_lock:
        _working_set = working_set
