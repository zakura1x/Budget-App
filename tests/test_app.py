"""
The HTTP surface in Phase 1: /health, the headers, the SPA shell, and the
error handlers. The database check is replaced, so nothing here needs SQL
Server.
"""

import re

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import app.api.v1.endpoints.health as health_module
import app.main as main_module
from app.core.config import settings
from app.core.crypto.errors import DecryptionError

API = settings.API_PREFIX
BASE = settings.BASE_URL_CLEAN

_probe = APIRouter()


@_probe.get("/_test/decryption-error")
async def _raise_decryption_error():
    raise DecryptionError("transactions", 4211)


@_probe.get("/_test/crash")
async def _crash():
    raise ValueError("could not post 18500.00 to account BPI Savings")


# Put the probes ahead of the SPA fallback, which would otherwise match first.
_before = len(main_module.app.router.routes)
main_module.app.include_router(_probe, prefix=API)
_added = main_module.app.router.routes[_before:]
del main_module.app.router.routes[_before:]
main_module.app.router.routes[0:0] = _added


@pytest.fixture
def db_status(monkeypatch):
    status = {"reachable": True, "schema_present": True}
    monkeypatch.setattr(health_module, "check_database", lambda: dict(status))
    monkeypatch.setattr(main_module, "check_database", lambda: dict(status))
    health_module._db_cache.update(at=0.0, result=None)
    return status


@pytest.fixture
def client(db_status):
    with TestClient(main_module.app, raise_server_exceptions=False) as c:  # runs the lifespan
        yield c


def test_health_reports_db_and_key_and_nothing_else(client):
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "database": {"reachable": True, "schema_present": True},
        "encryption": {"master_key_loaded": True},
    }
    text = response.text
    assert settings.BUDGET_MASTER_KEY.get_secret_value() not in text
    assert settings.DB_SERVER not in text and "key_version" not in text


def test_health_is_503_when_the_database_is_down(client, db_status):
    db_status.update(reachable=False, schema_present=False)
    health_module._db_cache.update(at=0.0, result=None)
    response = client.get(f"{API}/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_security_headers_on_every_response_and_no_hsts(client):
    for path in (f"{API}/health", f"{BASE}/", f"{API}/nope"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in headers
        assert "content-security-policy" in headers


def test_api_responses_are_never_cached(client):
    assert client.get(f"{API}/health").headers["cache-control"] == "no-store"


def test_shell_csp_nonce_matches_the_script_tag_and_changes_per_request(client):
    first = client.get(f"{BASE}/")
    second = client.get(f"{BASE}/stats")
    assert first.status_code == 200 and second.status_code == 200
    nonces = []
    for response in (first, second):
        csp = response.headers["content-security-policy"]
        assert "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        if 'type="module"' in response.text:
            assert f'nonce="{nonce}"' in response.text
        nonces.append(nonce)
    assert nonces[0] != nonces[1]


def test_json_responses_get_the_strict_csp(client):
    assert client.get(f"{API}/health").headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_spa_fallback_does_not_swallow_api_404s(client):
    response = client.get(f"{API}/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert client.get(f"{BASE}/static/nope.js").status_code == 404


def test_root_redirects_to_the_app(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307) and response.headers["location"] == f"{BASE}/"


def test_decryption_error_returns_no_detail(client):
    response = client.get(f"{API}/_test/decryption-error")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"type", "title", "status", "code", "ref"}
    assert "4211" not in response.text and "transactions" not in response.text


def test_unhandled_exception_text_never_reaches_the_client(client):
    response = client.get(f"{API}/_test/crash")
    assert response.status_code == 500
    assert "18500" not in response.text and "BPI" not in response.text


def test_docs_are_off_outside_debug(client):
    assert client.get(f"{API}/docs").status_code == 404
