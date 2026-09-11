"""
AuthMiddleware - attaches identity, does NOT block on it (as in QUOT).

Enforcement lives in the get_session_context / get_unlocked_context
dependencies, so a failed sign-in still reaches its endpoint and gets audited
with its IP.

It does block one thing: a state-changing API request (POST, PUT, PATCH,
DELETE) without the `X-Requested-With: fetch` header that lib/api.ts always
sends. A plain HTML form on another site cannot add a custom header, and a
cross-origin script that tries triggers a CORS preflight this app does not
grant. SameSite=Lax already stops cross-SITE forms; this also stops the
same-site ones - every *.noahapplication.com app counts as same-site.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.middleware.identity import identify

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class AuthMiddleware:
    def __init__(self, app: ASGIApp, *, api_prefix: str):
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        claims = identify(scope)
        state = scope.setdefault("state", {})
        state["user_id"] = claims.user_id if claims else None
        state["session_id"] = claims.session_id if claims else None

        path = scope.get("path", "")
        if scope.get("method") in UNSAFE and (path == self.api_prefix or path.startswith(self.api_prefix + "/")):
            headers = dict(scope.get("headers", ()))
            if headers.get(b"x-requested-with", b"").lower() != b"fetch":
                response = JSONResponse(
                    status_code=403,
                    media_type="application/problem+json",
                    content={"type": "about:blank", "title": "Forbidden", "status": 403, "code": "CSRF_HEADER_MISSING"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
