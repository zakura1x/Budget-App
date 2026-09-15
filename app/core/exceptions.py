"""
Exceptions - one hierarchy, one handler, RFC 7807 problem responses.

Every error leaves as application/problem+json:

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "Account not found", "code": "NOT_FOUND"}

Three rules that differ from QUOT's handler, all because of what this app holds:

  1. DecryptionError NEVER returns detail. Which row failed, and why, is an
     oracle - it tells an attacker which of their tampering attempts got
     closest. The row id goes to the server log; the client gets a generic
     500 with a correlation id to find that log line by.

  2. An unhandled exception's text is never sent to the client, DEBUG or not.
     An exception message can carry plaintext (a ValueError quoting an amount)
     and this app runs on a shared host.

  3. Request-validation errors report field and type, never the rejected
     input, in the response or the log.
"""

import logging
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    KeyNotAvailableError,
)

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


# ============================================
# The hierarchy
# ============================================


class AppException(Exception):
    """Base for errors the API reports deliberately."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    title: str = "Internal Server Error"

    def __init__(self, detail: Optional[str] = None, *, extra: Optional[dict] = None):
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail or self.title)


class ValidationException(AppException):
    status_code = 422
    code = "VALIDATION_ERROR"
    title = "Validation Failed"


class BusinessRuleException(AppException):
    """A request that is well-formed but breaks a rule - e.g. splits that do not sum."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BUSINESS_RULE"
    title = "Request Not Allowed"


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    title = "Not Found"


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    title = "Conflict"


class BalanceDiffersException(ConflictException):
    """
    ACC-28. A typed balance differs from the derived one and the user has not
    said how to record the difference. A question, not a failure: the client
    reads `before`, `after` and `difference` off the body and asks.
    """

    code = "BALANCE_DIFFERS"
    title = "Balance Differs"


class AuthenticationException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTH_REQUIRED"
    title = "Authentication Required"


class InvalidCredentialsException(AuthenticationException):
    code = "INVALID_CREDENTIALS"


class TokenExpiredException(AuthenticationException):
    """The access token ran out - the client refreshes and retries."""

    code = "TOKEN_EXPIRED"


class SessionRevokedException(AuthenticationException):
    """Signed out elsewhere, a replayed refresh token, or too many wrong PINs."""

    code = "SESSION_REVOKED"
    title = "Signed Out"


class SessionLockedException(AuthenticationException):
    """
    Logged in, but the keys are not in memory - auto-lock, PIN lock, or a
    process restart (SEC-27). The client shows the PIN screen, not the login.
    """

    code = "SESSION_LOCKED"
    title = "Session Locked"


class AccountLockedException(AuthenticationException):
    status_code = status.HTTP_423_LOCKED
    code = "ACCOUNT_LOCKED"
    title = "Account Locked"


class PermissionDeniedException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    title = "Forbidden"


class RateLimitException(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    title = "Too Many Requests"


class ServiceUnavailableException(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "UNAVAILABLE"
    title = "Service Unavailable"


# ============================================
# Responses
# ============================================


def problem(
    status_code: int,
    title: str,
    code: str,
    detail: Optional[str] = None,
    **extra: Any,
) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status_code, "code": code}
    if detail:
        body["detail"] = detail
    body.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_JSON)


def _correlation_id() -> str:
    return uuid.uuid4().hex[:12]


def setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exception(request: Request, exc: AppException):
        if exc.status_code >= 500:
            logger.error("%s on %s %s", exc.code, request.method, request.url.path)
        else:
            logger.info("%s on %s %s", exc.code, request.method, request.url.path)
        return problem(exc.status_code, exc.title, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(DecryptionError)
    async def _decryption_error(request: Request, exc: DecryptionError):
        ref = _correlation_id()
        # Table and row id in the log, for you. Nothing in the response, for them.
        logger.error(
            "DECRYPTION FAILED ref=%s table=%s row=%s path=%s",
            ref, exc.table, exc.row_id, request.url.path,
        )
        return problem(500, "Internal Server Error", "INTERNAL_ERROR", ref=ref)

    @app.exception_handler(KeyNotAvailableError)
    async def _key_missing(request: Request, exc: KeyNotAvailableError):
        ref = _correlation_id()
        logger.critical("MASTER KEY VERSION %s NOT LOADED ref=%s", exc.version, ref)
        return problem(503, "Service Unavailable", "UNAVAILABLE", ref=ref)

    @app.exception_handler(CryptoError)
    async def _crypto_error(request: Request, exc: CryptoError):
        ref = _correlation_id()
        logger.error("CRYPTO ERROR ref=%s type=%s path=%s", ref, type(exc).__name__, request.url.path)
        return problem(500, "Internal Server Error", "INTERNAL_ERROR", ref=ref)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in err.get("loc", ())), "type": err.get("type")}
            for err in exc.errors()
        ]
        logger.info("Request validation failed on %s: %s", request.url.path, errors)
        return problem(
            422, "Validation Failed", "VALIDATION_ERROR",
            "One or more fields are invalid", errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        titles = {404: "Not Found", 405: "Method Not Allowed", 401: "Authentication Required"}
        title = titles.get(exc.status_code, "HTTP Error")
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail != title else None
        return problem(exc.status_code, title, f"HTTP_{exc.status_code}", detail)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        ref = _correlation_id()
        logger.error("Unhandled %s ref=%s on %s", type(exc).__name__, ref, request.url.path, exc_info=True)
        return problem(500, "Internal Server Error", "INTERNAL_ERROR", ref=ref)
