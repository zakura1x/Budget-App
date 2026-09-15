"""
Automatic backup, triggered by use (DAT-08, ARCHITECTURE.md §12.6).

Never on a clock: IIS stops this app after 20 idle minutes, so a 02:00 job
would almost never run. Data only changes while someone is using the app, so:

    after a commit that changed a user's data   a backup BACKUP_DEBOUNCE_MINUTES
                                                later; every further change
                                                pushes it back, so a burst of
                                                edits makes one backup
    at sign-in                                  one within seconds, if the
                                                newest is older than
                                                BACKUP_INTERVAL_HOURS

The five-minute delay always falls inside the twenty minutes IIS keeps the
process alive after a request. Writing a backup needs no key, so the timer
runs with no session at all. One uvicorn worker (invariant 7) means one timer
per user, never two racing.

EncryptedRepository marks the session on every write; the after-commit hook
below reads the mark. A rollback clears it - nothing that did not happen is
backed up.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Set

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories.encrypted_repository import CHANGED_USERS

logger = logging.getLogger(__name__)

SIGN_IN_DELAY_SECONDS = 5


class BackupScheduler:
    def __init__(
        self,
        *,
        enabled: bool,
        debounce_seconds: float,
        interval_hours: float,
        writer: Callable[[int], Any],
        latest: Callable[[int], Optional[datetime]],
        timer_factory: Callable[..., Any] = threading.Timer,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._enabled = enabled
        self._debounce = debounce_seconds
        self._interval = timedelta(hours=interval_hours)
        self._writer = writer
        self._latest = latest
        self._timer_factory = timer_factory
        self._clock = clock
        self._timers: Dict[int, Any] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def note_change(self, user_id: int) -> None:
        if self._enabled:
            self._schedule(user_id, self._debounce)

    def on_sign_in(self, user_id: int) -> None:
        if not self._enabled:
            return
        latest = self._latest(user_id)
        if latest is not None and self._clock() - latest <= self._interval:
            return
        with self._lock:
            if user_id in self._timers:
                return  # one is already on its way
        self._schedule(user_id, SIGN_IN_DELAY_SECONDS)

    def pending(self) -> Set[int]:
        with self._lock:
            return set(self._timers)

    def cancel(self, user_id: int) -> None:
        """A deleted account must not have a backup written for it five minutes later."""
        with self._lock:
            timer = self._timers.pop(user_id, None)
        if timer is not None:
            timer.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def run_now(self, user_id: int) -> None:
        """What a timer does when it fires - public so a test can fire one."""
        with self._lock:
            self._timers.pop(user_id, None)
        try:
            self._writer(user_id)
        except Exception:
            logger.exception("Automatic backup failed user=%s - the next change or sign-in tries again", user_id)

    def _schedule(self, user_id: int, delay: float) -> None:
        with self._lock:
            existing = self._timers.pop(user_id, None)
            if existing is not None:
                existing.cancel()
            timer = self._timer_factory(delay, self.run_now, args=(user_id,))
            timer.daemon = True
            self._timers[user_id] = timer
            timer.start()


def _write(user_id: int) -> None:
    from app.db.session import session_scope
    from app.services.backup_service.bundle import write_backup

    with session_scope() as session:
        write_backup(session, user_id)


def _latest(user_id: int) -> Optional[datetime]:
    from app.services.backup_service.bundle import latest_backup_at

    return latest_backup_at(user_id)


_scheduler: Optional[BackupScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> BackupScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackupScheduler(
                enabled=(settings.BACKUP_ENABLED and settings.BACKUP_TRIGGER == "activity"
                         and settings.ENVIRONMENT != "test"),
                debounce_seconds=settings.BACKUP_DEBOUNCE_MINUTES * 60,
                interval_hours=settings.BACKUP_INTERVAL_HOURS,
                writer=_write,
                latest=_latest,
            )
        return _scheduler


def set_scheduler(scheduler: Optional[BackupScheduler]) -> None:
    """Swap the process scheduler - tests use a fake timer."""
    global _scheduler
    with _scheduler_lock:
        _scheduler = scheduler


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    users = session.info.pop(CHANGED_USERS, None)
    if not users:
        return
    scheduler = get_scheduler()
    for user_id in users:
        scheduler.note_change(user_id)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(CHANGED_USERS, None)
