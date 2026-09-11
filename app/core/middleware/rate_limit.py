"""
Rate limiting - an in-process sliding window (ARCHITECTURE.md section 8).

Two budgets:

  credentials   RATE_LIMIT_LOGIN_REQUESTS per RATE_LIMIT_LOGIN_WINDOW_SECONDS,
                per IP, on the endpoints that accept a secret: login,
                register, recover, PIN, password unlock. Per IP, because the
                per-account lockout cannot see one IP trying one password
                against many accounts.
  everything    RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW_SECONDS on the API,
                per ACCOUNT when signed in (SEC-17: users behind one office
                NAT must not share a budget), per IP otherwise.

Static files and the SPA shell are not counted. In-process is correct here
because there is exactly one worker (web.config); QUOT has to divide its
budget across workers, this app does not.

This is the coarse, fast layer. The durable limits - 5 wrong passwords per
account, 5 signup codes and 3 recovery phrases per IP - live in the database
(login_attempts) and survive a restart.
"""

import math
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.middleware.identity import client_host, identify

CREDENTIAL_PATHS = ("/auth/login", "/auth/register", "/auth/recover", "/auth/pin/verify", "/auth/unlock")


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, key: str, limit: int, window: float) -> Tuple[bool, int]:
        """Record a request. (allowed, seconds until the next one would be)."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, math.ceil(hits[0] + window - now))
            hits.append(now)
            if now - self._last_sweep > 300:
                self._sweep(now, window)
            return True, 0

    def _sweep(self, now: float, window: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
            del self._hits[key]
        self._last_sweep = now

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, api_prefix: str):
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self.credential_paths = tuple(self.api_prefix + p for p in CREDENTIAL_PATHS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED or not path.startswith(self.api_prefix + "/"):
            await self.app(scope, receive, send)
            return

        ip = client_host(scope)
        if path in self.credential_paths:
            key, limit, window = f"cred:{ip}", settings.RATE_LIMIT_LOGIN_REQUESTS, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS
        else:
            claims = identify(scope)
            key = f"user:{claims.user_id}" if claims else f"ip:{ip}"
            limit, window = settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_WINDOW_SECONDS

        allowed, retry_after = limiter.hit(key, limit, window)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                media_type="application/problem+json",
                headers={"Retry-After": str(retry_after)},
                content={
                    "type": "about:blank", "title": "Too Many Requests", "status": 429,
                    "code": "RATE_LIMITED", "detail": "Slow down a little and try again.",
                    "retry_after_seconds": retry_after,
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
