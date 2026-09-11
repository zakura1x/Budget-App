"""
FastAPI dependencies - where "who is this, and are they unlocked?" is decided.

AuthMiddleware only notes who a request claims to be; ENFORCEMENT is here, as
in QUOT. Two levels:

    get_session_context    signed in: a valid access token, an active user,
                           and a session nobody has revoked. Locked is fine.
    get_unlocked_context   ...and the DEK is in memory. Every endpoint that
                           touches financial data depends on this one, and
                           gets a UserCipher - the only way to read a row.
"""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.blind_index import get_blind_indexer
from app.core.crypto.session_keys import get_session_keyring
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    AuthenticationException,
    SessionLockedException,
    SessionRevokedException,
    TokenExpiredException,
)
from app.db.models import User
from app.db.repositories.token_repository import TokenRepository
from app.db.session import get_db
from app.services.auth_service.tokens import TokenExpired, TokenInvalid, decode_access_token


@dataclass
class SessionContext:
    user: User
    session_id: str


@dataclass
class UnlockedContext(SessionContext):
    cipher: UserCipher


def client_ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers behind IIS, so this is the real client.
    return request.client.host if request.client else ""


def get_ip_hash(request: Request) -> str:
    return get_blind_indexer().ip(client_ip(request))


def get_session_context(request: Request, db: Session = Depends(get_db)) -> SessionContext:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise AuthenticationException("Sign in to continue")
    try:
        claims = decode_access_token(token)
    except TokenExpired:
        raise TokenExpiredException("Your session needs refreshing") from None
    except TokenInvalid:
        raise AuthenticationException("Sign in to continue") from None

    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationException("Sign in to continue")
    if not TokenRepository(db).family_is_active(claims.session_id):
        # Signed out elsewhere, or a replay ended the family. An access token
        # that is still inside its 30 minutes must not outlive its session.
        get_session_keyring().lock(claims.session_id)
        raise SessionRevokedException("This session has ended - sign in again")
    return SessionContext(user=user, session_id=claims.session_id)


def get_unlocked_context(ctx: SessionContext = Depends(get_session_context)) -> UnlockedContext:
    cipher = get_session_keyring().cipher_for(ctx.session_id)
    if cipher is None or cipher.user_id != ctx.user.id:
        # Auto-lock, the lock button, or the process restarted (SEC-27).
        raise SessionLockedException("Enter your PIN to continue")
    return UnlockedContext(user=ctx.user, session_id=ctx.session_id, cipher=cipher)
