"""
Who a request CLAIMS to be, read once from the access cookie and remembered
on the request scope - so the rate limiter, the logger and the auth middleware
share one JWT decode. This is identification, not authentication: nothing here
lets a request through. app/core/deps.py enforces.
"""

from typing import Optional

from starlette.requests import cookie_parser
from starlette.types import Scope

from app.core.config import settings
from app.services.auth_service.tokens import AccessClaims, TokenExpired, TokenInvalid, decode_access_token

_KEY = "identity"


def identify(scope: Scope) -> Optional[AccessClaims]:
    state = scope.setdefault("state", {})
    if _KEY in state:
        return state[_KEY]
    claims = None
    for name, value in scope.get("headers", ()):
        if name == b"cookie":
            token = cookie_parser(value.decode("latin-1")).get(settings.SESSION_COOKIE_NAME)
            if token:
                try:
                    claims = decode_access_token(token)
                except (TokenExpired, TokenInvalid):
                    claims = None
            break
    state[_KEY] = claims
    return claims


def client_host(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else ""
