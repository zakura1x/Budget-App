"""
SEC-32. Sign-in activity: the devices signed in now, and recent sign-ins.

Reads Shape A tables only - refresh_tokens and login_attempts - so nothing
here needs the DEK, and nothing financial is involved.

    open sessions   live refresh-token families: started, last used, and the
                    coarse device label stored at sign-in (Unknown device for
                    one started before 2026-09-28). A family is named to the
                    client by its first token's row id - never by the family
                    id, which is the session id the keyring is keyed by.
    ending one      revokes the family through session_service, the same path
                    as signing out (SEC-24), so the keyring entry goes with it.
    recent sign-ins password sign-ins, unlocks and resets from login_attempts.
                    IPs are only ever stored hashed, so the most this can say
                    is "the same network as now" - raw IPs are never kept.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException
from app.db.models import LoginAttempt, RefreshToken
from app.db.types import utcnow
from app.services import audit_service
from app.services.auth_service import session_service

SIGN_IN_KINDS = ("login", "unlock", "reset")
SIGN_IN_DAYS = 30
SIGN_IN_LIMIT = 20
REVOKE_REASON = "user"


@dataclass(frozen=True)
class OpenSession:
    id: int  # the family's first token row - a handle, not the session id
    device: Optional[str]
    started: datetime
    last_active: datetime
    current: bool


@dataclass(frozen=True)
class SignIn:
    at: datetime
    kind: str  # login | unlock | reset
    success: bool
    same_network: bool


@dataclass
class _Family:
    handle: int
    family_id: str
    device: Optional[str]
    started: datetime
    last_active: datetime
    expires: datetime


def open_sessions(db: Session, user_id: int, current_session: str) -> List[OpenSession]:
    families = _live_families(db, user_id)
    sessions = [
        OpenSession(f.handle, f.device, f.started, f.last_active, f.family_id == current_session)
        for f in families.values()
    ]
    # This device first, then the most recently used.
    return sorted(sessions, key=lambda s: (not s.current, -s.last_active.timestamp()))


def end_session(db: Session, cipher: UserCipher, handle: int, current_session: str,
                ip_hash: Optional[str] = None) -> None:
    user_id = cipher.user_id
    family = next((f for f in _live_families(db, user_id).values() if f.handle == handle), None)
    if family is None:
        raise NotFoundException("That session has already ended")
    if family.family_id == current_session:
        raise BusinessRuleException("This is the device you are using - sign out instead")
    session_service.end_session(db, family.family_id, REVOKE_REASON)
    audit_service.record(db, audit_service.SESSION_END, user_id=user_id, ip_hash=ip_hash, cipher=cipher,
                         detail={"count": 1})
    db.commit()


def end_others(db: Session, cipher: UserCipher, current_session: str, ip_hash: Optional[str] = None) -> int:
    user_id = cipher.user_id
    ended = session_service.end_all(db, user_id, REVOKE_REASON, except_session=current_session)
    audit_service.record(db, audit_service.SESSION_END, user_id=user_id, ip_hash=ip_hash, cipher=cipher,
                         detail={"count": len(ended)})
    db.commit()
    return len(ended)


def recent_sign_ins(db: Session, user_id: int, ip_hash: Optional[str], *, now: Optional[datetime] = None) -> List[SignIn]:
    since = (now or utcnow()) - timedelta(days=SIGN_IN_DAYS)
    rows = db.execute(
        select(LoginAttempt)
        .where(LoginAttempt.user_id == user_id, LoginAttempt.kind.in_(SIGN_IN_KINDS),
               LoginAttempt.attempted_at > since)
        .order_by(LoginAttempt.attempted_at.desc(), LoginAttempt.id.desc())
        .limit(SIGN_IN_LIMIT)
    ).scalars()
    return [
        SignIn(row.attempted_at, row.kind, bool(row.success), bool(ip_hash) and row.ip_hash == ip_hash)
        for row in rows
    ]


def _live_families(db: Session, user_id: int) -> Dict[str, _Family]:
    """Every family of the user with a token nobody revoked and that has not expired."""
    now = utcnow()
    families: Dict[str, _Family] = {}
    rows = db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .order_by(RefreshToken.id)
    ).scalars()
    for row in rows:
        seen = max(row.issued_at, row.used_at) if row.used_at else row.issued_at
        family = families.get(row.family_id)
        if family is None:
            families[row.family_id] = _Family(row.id, row.family_id, row.device_label, row.issued_at, seen,
                                              row.expires_at)
            continue
        family.last_active = max(family.last_active, seen)
        family.expires = max(family.expires, row.expires_at)
        family.device = family.device or row.device_label
    return {key: f for key, f in families.items() if f.expires > now}
