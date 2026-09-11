"""
One line per API request: method, path WITHOUT the query string, status,
elapsed milliseconds as an integer (so the redaction filter leaves it alone),
and the user id. Replaces uvicorn's access log, which printed query strings
- and search terms travel in the query.
"""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.middleware.identity import identify

logger = logging.getLogger("app.request")


class LoggingMiddleware:
    def __init__(self, app: ASGIApp, *, api_prefix: str):
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 500}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            path = scope.get("path", "")
            claims = identify(scope)
            level = logging.INFO if path.startswith(self.api_prefix) else logging.DEBUG
            if status["code"] >= 500:
                level = logging.ERROR
            logger.log(
                level, "%s %s %s elapsed_ms=%d user=%s",
                scope.get("method"), path, status["code"], elapsed, claims.user_id if claims else "-",
            )
