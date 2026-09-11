"""
Phase 2 - sign-in, sessions, lock and unlock, through the real API.

The Phase 2 exit checks live here:
  * replaying a used refresh token ends every session of that family
  * locking drops the keys: a data call answers SESSION_LOCKED until the PIN
  * a process restart mid-session shows the PIN screen, not an error (SEC-27)
  * cookies are scoped to /ZBDGT and named zbdgt_* (SEC-28)
"""

import re

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto.session_keys import get_session_keyring
from app.db.models import AuditLog, LoginAttempt, User

pytestmark = pytest.mark.security

PASSWORD = "Correct-Horse-9!"


def set_cookie_headers(response):
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def signed_up(api, **kw):
    response = api.register(**kw)
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================== sign-up


def test_register_returns_the_phrase_once_and_signs_in(api):
    body = signed_up(api)
    assert len(body["recovery_phrase"]) == 12
    assert body["locked"] is False and body["pin_set"] is False
    assert body["user"]["email"] == "noah@example.com" and body["user"]["display_name"] == "Noah"
    assert body["user"]["is_admin"] is True  # first account
    me = api.get("/auth/me").json()
    assert "recovery_phrase" not in me  # never again
    assert api.get("/settings/preferences").json()["carry_over"] is False


def test_second_account_is_not_admin(api):
    signed_up(api)
    api.post("/auth/logout")
    body = signed_up(api, email="ana@example.com", name="Ana")
    assert body["user"]["is_admin"] is False


def test_cookies_are_scoped_to_this_app(api):
    response = api.register()
    cookies = set_cookie_headers(response)
    session = next(c for c in cookies if c.startswith(settings.SESSION_COOKIE_NAME + "="))
    refresh = next(c for c in cookies if c.startswith(settings.REFRESH_COOKIE_NAME + "="))
    for cookie in (session, refresh):
        assert "HttpOnly" in cookie and re.search(r"SameSite=lax", cookie, re.I)
        assert "Domain=" not in cookie
    assert "Path=/ZBDGT;" in session or session.endswith("Path=/ZBDGT")
    assert f"Path={settings.API_PREFIX}/auth" in refresh
    assert settings.SESSION_COOKIE_NAME.startswith("zbdgt_") and settings.REFRESH_COOKIE_NAME.startswith("zbdgt_")


def test_config_is_public_and_carries_the_policy(api):
    body = api.get("/auth/config").json()
    assert body["registration_open"] is True and body["pin_length"] == 6
    assert body["password_policy"]["min_length"] == 12


def test_state_changing_requests_need_the_fetch_header(api):
    response = api.client.post(settings.API_PREFIX + "/auth/login", json={"email": "a@b.co", "password": "x"})
    assert response.status_code == 403 and response.json()["code"] == "CSRF_HEADER_MISSING"


# ============================================================== sign-in


def test_login_logout_round_trip(api):
    signed_up(api)
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/auth/me").status_code == 401
    response = api.login()
    assert response.status_code == 200 and response.json()["user"]["email"] == "noah@example.com"
    assert api.get("/settings/preferences").status_code == 200


def test_wrong_password_and_unknown_email_look_the_same(api):
    signed_up(api)
    api.post("/auth/logout")
    wrong = api.login(password="Wrong-Password-1!")
    unknown = api.login(email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_lockout_after_five_failures_even_with_the_right_password(api):
    signed_up(api)
    api.post("/auth/logout")
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        assert api.login(password="Wrong-Password-1!").status_code == 401
    locked = api.login()
    assert locked.status_code == 423 and locked.json()["retry_after_seconds"] > 0


def test_lockout_applies_to_emails_with_no_account(api):
    # Otherwise "this email gets locked, that one does not" reveals who is registered.
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        api.login(email="ghost@example.com")
    assert api.login(email="ghost@example.com").status_code == 423


def test_ip_is_stored_hashed(api, session):
    signed_up(api)
    api.post("/auth/logout")
    api.login(password="Wrong-Password-1!")
    rows = session.execute(select(LoginAttempt.ip_hash)).scalars().all()
    assert rows and all(h and len(h) == 64 and "testclient" not in h for h in rows)


# ============================================================== tokens


def test_refresh_rotates_the_token(api):
    signed_up(api)
    old = api.cookies.get(settings.REFRESH_COOKIE_NAME)
    response = api.post("/auth/refresh")
    assert response.status_code == 200
    assert api.cookies.get(settings.REFRESH_COOKIE_NAME) != old


def test_replaying_a_used_refresh_token_ends_the_whole_family(api):
    """THE Phase 2 check: a stolen token being replayed ends every session."""
    signed_up(api)
    stolen = api.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert api.post("/auth/refresh").status_code == 200  # the legitimate use
    good_access = api.cookies.get(settings.SESSION_COOKIE_NAME)

    api.set_cookie(settings.REFRESH_COOKIE_NAME, stolen, path=f"{settings.API_PREFIX}/auth")
    replay = api.post("/auth/refresh")
    assert replay.status_code == 401 and replay.json()["code"] == "SESSION_REVOKED"

    api.set_cookie(settings.SESSION_COOKIE_NAME, good_access, path=settings.SESSION_COOKIE_PATH)
    after = api.get("/auth/me")
    assert after.status_code == 401 and after.json()["code"] == "SESSION_REVOKED"


def test_logout_zeroes_the_key_and_kills_the_access_token(api):
    signed_up(api)
    access = api.cookies.get(settings.SESSION_COOKIE_NAME)
    assert len(get_session_keyring()) == 1
    api.post("/auth/logout")
    assert len(get_session_keyring()) == 0
    api.set_cookie(settings.SESSION_COOKIE_NAME, access, path=settings.SESSION_COOKIE_PATH)
    assert api.get("/settings/preferences").status_code == 401


def test_expired_access_token_says_so(api, monkeypatch):
    from app.services.auth_service.tokens import create_access_token, decode_access_token

    signed_up(api)
    claims = decode_access_token(api.cookies.get(settings.SESSION_COOKIE_NAME))
    monkeypatch.setattr(settings, "JWT_EXPIRATION_MINUTES", -1)
    expired = create_access_token(claims.user_id, claims.session_id)
    api.set_cookie(settings.SESSION_COOKIE_NAME, expired, path=settings.SESSION_COOKIE_PATH)
    response = api.get("/auth/me")
    assert response.status_code == 401 and response.json()["code"] == "TOKEN_EXPIRED"
    # ...and the refresh token still gets a fresh one.
    monkeypatch.setattr(settings, "JWT_EXPIRATION_MINUTES", 30)
    assert api.post("/auth/refresh").status_code == 200
    assert api.get("/auth/me").status_code == 200


# ============================================================== lock & PIN


def test_lock_drops_the_keys_until_the_pin(api):
    signed_up(api)
    assert api.post("/auth/pin", {"pin": "482913"}).json()["pin_set"] is True
    assert api.post("/auth/lock").status_code == 204

    blocked = api.get("/settings/preferences")
    assert blocked.status_code == 401 and blocked.json()["code"] == "SESSION_LOCKED"
    me = api.get("/auth/me").json()
    assert me["locked"] is True and me["user"]["email"] is None  # the email lives under the DEK

    assert api.post("/auth/pin/verify", {"pin": "482913"}).json()["locked"] is False
    assert api.get("/settings/preferences").status_code == 200


def test_a_restart_mid_session_looks_like_a_lock(api):
    """SEC-27: IIS recycles the process; the next request gets the PIN screen."""
    signed_up(api)
    api.post("/auth/pin", {"pin": "482913"})
    get_session_keyring().lock_all()  # the process restarted: memory is empty
    response = api.get("/settings/preferences")
    assert response.status_code == 401 and response.json()["code"] == "SESSION_LOCKED"
    assert api.get("/auth/me").status_code == 200  # still signed in
    api.post("/auth/pin/verify", {"pin": "482913"})
    assert api.get("/settings/preferences").status_code == 200


def test_password_unlock_works_without_a_pin(api):
    signed_up(api)
    api.post("/auth/lock")
    assert api.post("/auth/pin/verify", {"pin": "482913"}).status_code == 400  # no PIN set
    assert api.post("/auth/unlock", {"password": "nope"}).status_code == 401
    assert api.post("/auth/unlock", {"password": PASSWORD}).json()["locked"] is False


def test_five_wrong_pins_end_the_session(api):
    signed_up(api)
    api.post("/auth/pin", {"pin": "482913"})
    api.post("/auth/lock")
    for left in range(settings.PIN_MAX_ATTEMPTS - 1, 0, -1):
        wrong = api.post("/auth/pin/verify", {"pin": "111222"})
        assert wrong.status_code == 401 and wrong.json()["attempts_left"] == left
    final = api.post("/auth/pin/verify", {"pin": "111222"})
    assert final.status_code == 401 and final.json()["code"] == "SESSION_REVOKED"
    assert api.post("/auth/pin/verify", {"pin": "482913"}).status_code == 401  # the right one is too late
    assert api.login().status_code == 200  # the password still works


def test_weak_or_malformed_pins_refused(api):
    signed_up(api)
    for pin in ("123", "abcdef", "111111", "123456", "654321"):
        assert api.post("/auth/pin", {"pin": pin}).status_code == 422, pin


def test_changing_the_pin_needs_the_password(api):
    signed_up(api)
    api.post("/auth/pin", {"pin": "482913"})
    assert api.post("/auth/pin", {"pin": "705318"}).status_code == 401
    assert api.post("/auth/pin", {"pin": "705318", "current_password": PASSWORD}).status_code == 200


def test_the_pin_is_stored_peppered_and_hashed(api, session):
    signed_up(api)
    api.post("/auth/pin", {"pin": "482913"})
    pin_hash = session.execute(select(User.pin_hash)).scalar_one()
    assert "482913" not in pin_hash and pin_hash.startswith("bcrypt-hmac$")


def test_setting_a_pin_needs_an_unlocked_session(api):
    signed_up(api)
    api.post("/auth/lock")
    assert api.post("/auth/pin", {"pin": "482913"}).json()["code"] == "SESSION_LOCKED"


# ============================================================== audit


def test_audit_trail_has_plaintext_verbs_and_encrypted_detail(api, session):
    signed_up(api)
    api.post("/auth/logout")
    api.login(password="Wrong-Password-1!")
    api.login()
    rows = session.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    actions = [r.action for r in rows]
    assert actions[:4] == ["REGISTER", "LOGOUT", "LOGIN_FAILED", "LOGIN"]
    register = rows[0]
    assert register.detail_enc is not None and b"admin" not in register.detail_enc
    assert rows[2].detail_enc is None  # nothing unlocked to seal it with
