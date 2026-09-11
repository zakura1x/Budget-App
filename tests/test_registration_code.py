"""SEC-19/25/26 - the registration code is the only gate on signup."""

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import AuditLog, User

pytestmark = pytest.mark.security


def test_no_code_no_account(api, session):
    response = api.register(code="not-the-code")
    assert response.status_code == 403 and response.json()["reason"] == "INVALID_CODE"
    assert session.execute(select(func.count()).select_from(User)).scalar() == 0


def test_wrong_codes_are_audited(api, session):
    api.register(code="guess-1")
    rows = session.execute(select(AuditLog.action, AuditLog.user_id, AuditLog.ip_hash)).all()
    assert rows == [("REGISTER_REJECTED", None, rows[0][2])] and len(rows[0][2]) == 64


def test_five_wrong_codes_per_ip_then_blocked_even_with_the_right_one(api):
    for n in range(settings.REGISTRATION_MAX_ATTEMPTS):
        assert api.register(code=f"guess-{n}").status_code == 403
    blocked = api.register()
    assert blocked.status_code == 429 and blocked.json()["retry_after_seconds"] > 0


def test_code_comparison_ignores_surrounding_whitespace_only(api):
    code = settings.REGISTRATION_CODE.get_secret_value()
    assert api.register(code=code.upper() if code.upper() != code else code + "x").status_code == 403
    assert api.register(code=f"  {code}  ").status_code == 201


def test_changing_the_code_invalidates_old_invitations(api, monkeypatch):
    old = settings.REGISTRATION_CODE.get_secret_value()
    monkeypatch.setattr(settings, "REGISTRATION_CODE", SecretStr("a-brand-new-code-2026"))
    assert api.register(code=old).status_code == 403
    assert api.register(code="a-brand-new-code-2026").status_code == 201


def test_empty_code_means_signup_is_closed(api, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_CODE", SecretStr(""))
    assert api.get("/auth/config").json()["registration_open"] is False
    response = api.register(code="anything")
    assert response.status_code == 403 and response.json()["reason"] == "REGISTRATION_CLOSED"


def test_max_users_caps_even_a_valid_code(api, monkeypatch):
    monkeypatch.setattr(settings, "MAX_USERS", 2)
    assert api.register(email="a@example.com").status_code == 201
    api.post("/auth/logout")
    assert api.register(email="b@example.com").status_code == 201
    api.post("/auth/logout")
    capped = api.register(email="c@example.com")
    assert capped.status_code == 400 and "MAX_USERS" in capped.json()["detail"]


def test_single_user_mode_closes_signup_after_the_first(api, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_USER_MODE", True)
    assert api.register(email="a@example.com").status_code == 201
    api.post("/auth/logout")
    assert api.register(email="b@example.com").json()["reason"] == "REGISTRATION_CLOSED"


def test_weak_password_and_duplicate_email_refused(api):
    assert api.register(password="short").status_code == 422
    assert api.register().status_code == 201
    api.post("/auth/logout")
    assert api.register(email="NOAH@example.com").status_code == 409
