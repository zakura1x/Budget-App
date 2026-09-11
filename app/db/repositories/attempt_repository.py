"""
login_attempts - the ledger behind every lockout and signup/recovery limit.

Lockouts are computed from this table, not from counters on users, so they
apply to email addresses that have no account as well. A counter on a user row
would lock only real accounts - and "this email gets locked, that one never
does" would tell an attacker which emails are registered.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LoginAttempt
from app.db.types import utcnow


class AttemptRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(self, *, kind: str, success: bool, email_bidx: Optional[str] = None,
               user_id: Optional[int] = None, ip_hash: Optional[str] = None) -> None:
        self.session.add(LoginAttempt(kind=kind, success=success, email_bidx=email_bidx,
                                      user_id=user_id, ip_hash=ip_hash, attempted_at=utcnow()))
        self.session.flush()

    def recent_failures(self, *, kinds: Sequence[str], window_minutes: int,
                        email_bidx: Optional[str] = None, ip_hash: Optional[str] = None) -> list:
        """
        Failure timestamps inside the window and after the most recent success
        for the same key - a correct sign-in wipes the slate.
        """
        since = utcnow() - timedelta(minutes=window_minutes)
        key = []
        if email_bidx is not None:
            key.append(LoginAttempt.email_bidx == email_bidx)
        if ip_hash is not None:
            key.append(LoginAttempt.ip_hash == ip_hash)
        last_success = self.session.execute(
            select(func.max(LoginAttempt.attempted_at)).where(
                LoginAttempt.kind.in_(kinds), LoginAttempt.success == True, *key  # noqa: E712
            )
        ).scalar()
        if last_success is not None and last_success > since:
            since = last_success
        rows = self.session.execute(
            select(LoginAttempt.attempted_at).where(
                LoginAttempt.kind.in_(kinds), LoginAttempt.success == False,  # noqa: E712
                LoginAttempt.attempted_at > since, *key,
            ).order_by(LoginAttempt.attempted_at)
        )
        return [r[0] for r in rows]


def seconds_until_free(failures: list, window_minutes: int) -> int:
    """How long until the oldest counted failure leaves the window."""
    if not failures:
        return 0
    oldest: datetime = failures[0]
    remaining = (oldest + timedelta(minutes=window_minutes) - utcnow()).total_seconds()
    return max(1, int(remaining))
