"""
Security headers - set by the app, not by IIS (web.config explains why).

On every response:
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: no-referrer
    Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
    Cross-Origin-Opener-Policy: same-origin

Content-Security-Policy depends on what the response is:
    the SPA shell (HTML)   a per-request nonce, no 'unsafe-inline' anywhere
    everything else        default-src 'none' - JSON and assets need nothing
    /docs in DEBUG only    none, so Swagger UI can load its CDN assets

Cache-Control: no-store on every API response unless the route set its own.
An API response here is decrypted financial data, and the browser's HTTP
cache is origin-wide storage that every app on this host can reach
(ARCHITECTURE.md 10.3, SEC-29).

NO Strict-Transport-Security. HSTS applies to the whole host, and this app
shares delca.noahapplication.com with QUOT and ~90 others. That is the host
owner's decision, not this app's.

Pure ASGI rather than BaseHTTPMiddleware: it only edits headers, and it must
not buffer or re-wrap streamed responses (CSV export, backup download).
"""

import secrets
from typing import Iterable

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ALWAYS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

NON_HTML_CSP = "default-src 'none'; frame-ancestors 'none'"


def shell_csp(nonce: str) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            "style-src 'self'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "manifest-src 'self'",
            "worker-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, api_prefix: str, csp_exempt_paths: Iterable[str] = ()):
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self.csp_exempt = tuple(csp_exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(18)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path = scope.get("path", "")
        is_api = path == self.api_prefix or path.startswith(self.api_prefix + "/")
        exempt = any(path == p or path.startswith(p + "/") for p in self.csp_exempt)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in ALWAYS.items():
                    headers[name] = value
                if not exempt:
                    content_type = headers.get("content-type", "")
                    headers["Content-Security-Policy"] = (
                        shell_csp(nonce) if content_type.startswith("text/html") else NON_HTML_CSP
                    )
                if is_api and "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
