"""
Installable, and never a place figures are kept (UX-09, UX-10, SEC-29).
"""

import pytest

from app.core.config import settings
from app.web.router import STATIC_DIR

BASE = settings.BASE_URL_CLEAN


def test_the_manifest(api):
    response = api.client.get(f"{BASE}/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    body = response.json()
    assert (body["start_url"], body["scope"], body["display"]) == (f"{BASE}/", f"{BASE}/", "standalone")
    for icon in body["icons"]:
        path = STATIC_DIR / "icons" / icon["src"].rsplit("/", 1)[-1]
        assert path.is_file() and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", icon["src"]


def test_the_service_worker_can_control_the_whole_app(api):
    response = api.client.get(f"{BASE}/sw.js")
    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == f"{BASE}/"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert "javascript" in response.headers["content-type"]


def test_the_service_worker_never_caches_the_api():
    source = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    assert "/api/`)) return;" in source  # API requests leave before any cache is consulted


def test_the_shell_links_the_manifest_and_icons(api):
    html = api.client.get(f"{BASE}/").text
    assert f'rel="manifest" href="{BASE}/manifest.webmanifest"' in html
    assert "apple-touch-icon" in html
    assert api.client.get(f"{BASE}/static/icons/icon-192.png").status_code == 200


def test_the_shell_opens_in_the_remembered_theme(api):
    """UX-05, 2026-09-16: a lock screen reopened after the app closed keeps the theme the user chose."""
    api.client.cookies.set("zbdgt_theme", "dark", domain="testserver.local", path=BASE)
    assert '<html lang="en" data-theme="dark">' in api.client.get(f"{BASE}/stats").text


@pytest.mark.security
def test_only_light_or_dark_ever_reaches_the_page(api):
    """The cookie is the browser's to change; nothing but the two words may be echoed into the shell."""
    api.client.cookies.set("zbdgt_theme", '"><script>alert(1)</script>', domain="testserver.local", path=BASE)
    html = api.client.get(f"{BASE}/").text
    assert "data-theme" not in html.split("<head>")[0]
    assert "alert(1)" not in html


def test_no_cookie_leaves_the_theme_to_the_device(api):
    assert '<html lang="en">' in api.client.get(f"{BASE}/").text
