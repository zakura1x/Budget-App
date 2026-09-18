"""
The SPA shell - the only server-rendered page (ARCHITECTURE.md section 2).

Jinja renders templates/index.html for /ZBDGT and for every client-side route
under it, so a refresh on /ZBDGT/stats still lands in the app. It injects
three things and nothing else:

  * the CSP nonce for this request
  * the hashed bundle filenames, read from dist/.vite/manifest.json - Vite
    names files index-[hash].js, so the template cannot hard-code them
  * BASE_URL and API_PREFIX, so the bundle does not hard-code them either

The manifest is re-read when its modification time changes, so a fresh
`npm run build` is picked up without restarting uvicorn.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

router = APIRouter(include_in_schema=False)

_ENTRY = "index.html"
_manifest_cache = {"mtime": None, "entry": None}


def _dist_dir() -> Path:
    path = Path(settings.FRONTEND_DIST_DIR)
    return path if path.is_absolute() else PROJECT_ROOT / path


def bundle_entry() -> Optional[dict]:
    """{'js': 'assets/index-abc.js', 'css': [...]} or None if not built."""
    manifest = _dist_dir() / ".vite" / "manifest.json"
    try:
        mtime = manifest.stat().st_mtime
    except OSError:
        return None
    if _manifest_cache["mtime"] != mtime:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            chunk = data[_ENTRY]
            _manifest_cache["entry"] = {"js": chunk["file"], "css": list(chunk.get("css", []))}
            _manifest_cache["mtime"] = mtime
        except (OSError, ValueError, KeyError) as exc:
            logger.error("Unreadable Vite manifest: %s", type(exc).__name__)
            return None
    return _manifest_cache["entry"]


# UX-05. The one preference kept in the browser, by the user's choice
# (2026-09-16): the light/dark word, so a lock screen opened after the app was
# closed looks the way they chose - their real preferences are encrypted and
# cannot be read until they unlock. Only these two values are ever echoed back
# into the page; anything else is the device's own setting.
THEME_COOKIE = "zbdgt_theme"
_THEMES = ("light", "dark")


def _render_shell(request: Request) -> HTMLResponse:
    base = settings.BASE_URL_CLEAN
    theme = request.cookies.get(THEME_COOKIE)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "nonce": getattr(request.state, "csp_nonce", ""),
            "entry": bundle_entry(),
            "dist_url": f"{base}/static/dist",
            "base_url": base,
            "api_prefix": settings.API_PREFIX,
            "app_name": settings.APP_NAME,
            "theme": theme if theme in _THEMES else None,
        },
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/")
async def root():
    return RedirectResponse(url=settings.BASE_URL_CLEAN + "/")


@router.get(settings.BASE_URL_CLEAN, response_class=HTMLResponse)
@router.get(settings.BASE_URL_CLEAN + "/", response_class=HTMLResponse)
async def shell(request: Request):
    return _render_shell(request)


@router.get(settings.BASE_URL_CLEAN + "/manifest.webmanifest")
async def manifest():
    """UX-09 - what "Add to Home Screen" reads. Figures never appear in it."""
    base = settings.BASE_URL_CLEAN
    icons = f"{base}/static/icons"
    return JSONResponse(
        {
            "name": settings.APP_NAME,
            "short_name": "Budget",
            "id": f"{base}/",
            "start_url": f"{base}/",
            "scope": f"{base}/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#f6f1e4",  # the classic palette's ground (2026-09-18)
            "theme_color": "#4f54aa",
            "icons": [
                {"src": f"{icons}/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": f"{icons}/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": f"{icons}/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get(settings.BASE_URL_CLEAN + "/sw.js")
async def service_worker():
    """
    The service worker, served from the app's root so its scope is the whole
    app - a worker under /static/dist/ could only control /static/dist/.
    app/web/static/sw.js is hand-written and committed; it caches the shell
    and the bundle, and never an API response (SEC-29).
    """
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": f"{settings.BASE_URL_CLEAN}/"},
    )


@router.get(settings.BASE_URL_CLEAN + "/{path:path}", response_class=HTMLResponse)
async def spa_fallback(request: Request, path: str):
    # A missing API route or static file must 404 as itself, not come back
    # as the app shell with a 200.
    if not settings.SPA_FALLBACK or path.startswith(("api/", "static/")) or path in ("api", "static"):
        raise HTTPException(status_code=404)
    return _render_shell(request)
