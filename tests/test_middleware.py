"""Rate limiting, request logging, and the identity peek."""

import logging

import pytest

from app.core.config import settings
from app.core.middleware.rate_limit import SlidingWindowLimiter


def test_credential_endpoints_are_limited_per_ip(api):
    for _ in range(settings.RATE_LIMIT_LOGIN_REQUESTS):
        assert api.login(email="x@example.com", password="whatever").status_code in (401, 423)
    limited = api.login(email="x@example.com", password="whatever")
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert limited.headers["x-frame-options"] == "DENY"  # headers still applied to a 429


def test_general_budget_is_separate_from_the_credential_one(api):
    for _ in range(settings.RATE_LIMIT_LOGIN_REQUESTS):
        api.login(email="x@example.com", password="whatever")
    assert api.get("/auth/config").status_code == 200


def test_sliding_window_frees_up():
    now = [1000.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    assert limiter.hit("k", 2, 60) == (True, 0)
    now[0] += 10
    assert limiter.hit("k", 2, 60)[0] is True
    allowed, retry = limiter.hit("k", 2, 60)
    assert allowed is False and retry == 50  # the first hit leaves the window in 50 s
    now[0] += 51
    assert limiter.hit("k", 2, 60)[0] is True


def test_request_log_has_user_and_timing_but_no_query(api, caplog):
    api.register()
    with caplog.at_level(logging.INFO, logger="app.request"):
        api.get("/settings/preferences?q=Jollibee")
    lines = [r.getMessage() for r in caplog.records if r.name == "app.request"]
    assert lines and "GET /ZBDGT/api/v1/settings/preferences 200" in lines[-1]
    assert "elapsed_ms=" in lines[-1] and "user=1" in lines[-1]
    assert "Jollibee" not in " ".join(lines)


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_unsafe_method_needs_the_fetch_header(api, method):
    response = getattr(api.client, method)(settings.API_PREFIX + "/auth/lock")
    assert response.status_code == 403
