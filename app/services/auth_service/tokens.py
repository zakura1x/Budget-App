"""
Session tokens (SEC-04/05/06).

  access token   JWT HS256, 30 minutes, in the zbdgt_session cookie. Carries
                 the user id and the session id - nothing else, and never a key.
  refresh token  256 random bits, in the zbdgt_refresh cookie. Stored only as
                 its SHA-256, so the refresh_tokens table is useless to a DBA.

The session id IS the refresh-token family id: every token descended from one
sign-in shares it, and the in-memory keyring is keyed by it.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Tuple

from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings

ACCESS_TYPE = "access"


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    session_id: str


def new_session_id() -> str:
    return uuid.uuid4().hex


def create_access_token(user_id: int, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "sid": session_id,
        "typ": ACCESS_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],  # a list of one: no alg confusion
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
    except ExpiredSignatureError:
        raise TokenExpired() from None
    except JWTError:
        raise TokenInvalid() from None
    if claims.get("typ") != ACCESS_TYPE or not claims.get("sid") or not str(claims.get("sub", "")).isdigit():
        raise TokenInvalid()
    return AccessClaims(user_id=int(claims["sub"]), session_id=str(claims["sid"]))


def new_refresh_token() -> Tuple[str, str]:
    """(raw token for the cookie, hash for the database)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # Plain SHA-256 is enough: the input is 256 random bits, not a password.
    return hashlib.sha256(raw.encode("ascii", errors="ignore")).hexdigest()
