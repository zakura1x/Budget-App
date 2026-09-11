"""
Sessions - one sign-in, one refresh-token family, one keyring entry.

    start_session   a fresh family, its first refresh token, an access token,
                    and the DEK placed in the in-memory keyring
    rotate          the refresh endpoint: use a token once, get its child.
                    Presenting a token that was ALREADY used ends the whole
                    family - that is what a stolen token being replayed looks
                    like (SEC-06)
    end_session     sign-out: family revoked, keyring entry zeroed
    end_all         every session of a user (recovery, and SEC-24 later)

Revoking a family in the database and dropping its keyring entry always happen
together here, so no code path can do one and forget the other.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.dek import wrap_dek
from app.core.crypto.keyring import MasterKeyring, get_master_keyring
from app.core.crypto.session_keys import get_session_keyring
from app.core.exceptions import AuthenticationException, SessionRevokedException
from app.db.models import User
from app.db.repositories.token_repository import TokenRepository
from app.db.types import utcnow
from app.services import audit_service
from app.services.auth_service.tokens import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    new_session_id,
)


@dataclass
class IssuedSession:
    user_id: int
    session_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


def _refresh_expiry():
    return utcnow() + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS)


def start_session(db: Session, user: User, dek: bytearray, keyring: Optional[MasterKeyring] = None) -> IssuedSession:
    """
    Open a session for a user whose DEK has just been unwrapped. TAKES the DEK:
    the keyring zeroes the caller's buffer.

    Also the lazy half of a master-key rotation: a DEK still wrapped under a
    retired version is re-wrapped under the current one here, at sign-in.
    """
    keyring = keyring or get_master_keyring()
    if user.key_version != keyring.current_version:
        user.dek_wrapped = wrap_dek(dek, keyring, user.id)
        user.key_version = keyring.current_version
    session_id = new_session_id()
    raw, token_hash = new_refresh_token()
    TokenRepository(db).add(user_id=user.id, token_hash=token_hash, family_id=session_id, expires_at=_refresh_expiry())
    get_session_keyring().unlock(session_id, user.id, dek, keyring.current_version)
    return IssuedSession(user.id, session_id, create_access_token(user.id, session_id), raw)


def unlock_session(session_id: str, user: User, dek: bytearray, keyring: Optional[MasterKeyring] = None) -> None:
    """Put an existing session's DEK back in the keyring (PIN / password unlock)."""
    keyring = keyring or get_master_keyring()
    get_session_keyring().unlock(session_id, user.id, dek, keyring.current_version)


def rotate(db: Session, raw_refresh: Optional[str], ip_hash: Optional[str] = None) -> IssuedSession:
    """Exchange a refresh token for a new pair. The caller commits."""
    if not raw_refresh:
        raise AuthenticationException("Sign in to continue")
    tokens = TokenRepository(db)
    row = tokens.by_hash(hash_refresh_token(raw_refresh))
    if row is None:
        raise AuthenticationException("Sign in to continue")
    if row.revoked_at is not None:
        raise SessionRevokedException("This session has ended - sign in again")
    if row.used_at is not None:
        # Replay of a token that was already exchanged: end every session it
        # could belong to, the legitimate one included. That is the point.
        if settings.REFRESH_TOKEN_REUSE_REVOKES_FAMILY:
            _end(db, row.family_id, "reuse")
            audit_service.record(db, audit_service.REFRESH_REUSE, user_id=row.user_id, ip_hash=ip_hash)
            db.commit()
        raise SessionRevokedException("This session has ended - sign in again")
    if row.expires_at <= utcnow():
        raise AuthenticationException("Sign in to continue")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthenticationException("Sign in to continue")

    row.used_at = utcnow()
    raw, token_hash = new_refresh_token()
    tokens.add(user_id=row.user_id, token_hash=token_hash, family_id=row.family_id,
               expires_at=_refresh_expiry(), parent_id=row.id)
    return IssuedSession(row.user_id, row.family_id, create_access_token(row.user_id, row.family_id), raw)


def family_of_refresh(db: Session, raw_refresh: Optional[str]) -> Optional[str]:
    if not raw_refresh:
        return None
    row = TokenRepository(db).by_hash(hash_refresh_token(raw_refresh))
    return row.family_id if row else None


def _end(db: Session, session_id: str, reason: str) -> None:
    TokenRepository(db).revoke_family(session_id, reason)
    get_session_keyring().lock(session_id)


def end_session(db: Session, session_id: str, reason: str = "logout") -> None:
    _end(db, session_id, reason)


def end_all(db: Session, user_id: int, reason: str, except_session: Optional[str] = None) -> List[str]:
    families = TokenRepository(db).revoke_user(user_id, reason, except_family=except_session)
    keyring = get_session_keyring()
    for family in families:
        keyring.lock(family)
    return families
