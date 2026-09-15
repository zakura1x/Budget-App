"""
SEC-30 - password reset by an emailed link.

The guarantees: the form answers the same whether or not an account exists;
only a hash of the token is stored; the link lives in the URL fragment, points
at APP_PUBLIC_URL whatever Host the request claims, works once and expires; a
newer link replaces an older one; mail per address is capped silently; the
reset signs the user in, ends every other session, and leaves the data as it
was. And no test can send a real email.
"""

import re
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditLog, User
from app.db.types import utcnow
from app.services import email_service

pytestmark = pytest.mark.security

PASSWORD = "Correct-Horse-9!"
NEW = "Brand-New-Horse-7!"


@pytest.fixture
def mail(monkeypatch):
    """SMTP 'configured', so the feature is on - but ENVIRONMENT=test keeps every message in OUTBOX."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_USER", "sender@example.test")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", SecretStr("not-a-real-password"))
    email_service.OUTBOX.clear()
    yield email_service.OUTBOX
    email_service.OUTBOX.clear()


def token_of(message) -> str:
    return re.search(r"/reset#token=([A-Za-z0-9_-]+)", message.text).group(1)


def forgot(api, email="noah@example.com", **kw):
    return api.post("/auth/forgot-password", {"email": email}, **kw)


def reset(api, token, password=NEW):
    return api.post("/auth/reset-password", {"token": token, "password": password})


def signed_out_account(api):
    assert api.register().status_code == 201
    cookie = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    return cookie


def test_without_smtp_the_feature_is_off(api):
    assert api.get("/auth/config").json()["password_reset_enabled"] is False
    assert forgot(api).status_code == 503


def test_the_answer_is_the_same_whether_or_not_the_account_exists(api, mail):
    signed_out_account(api)
    assert api.get("/auth/config").json()["password_reset_enabled"] is True
    known = forgot(api, " Noah@Example.com ")
    unknown = forgot(api, "nobody@example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"link_minutes": settings.PASSWORD_RESET_LINK_MINUTES}
    assert [m.to for m in mail] == ["Noah@Example.com"]


def test_the_link_resets_the_password_signs_in_and_works_once(api, mail, session):
    api.register()
    api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "5000.00"})
    old_session = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()

    assert forgot(api).status_code == 202
    message = mail[0]
    link = f"{settings.APP_PUBLIC_URL}{settings.BASE_URL}/reset#token="
    assert link in message.text and link in message.html
    assert "?token" not in message.text  # the fragment, never a query string IIS would log
    token = token_of(message)
    stored = session.execute(select(User.reset_token_hash)).scalar_one()
    assert stored and stored != token and token not in stored  # only a hash is kept

    done = reset(api, token)
    assert done.status_code == 200, done.text
    assert done.json()["locked"] is False and done.json()["user"]["email"] == "noah@example.com"
    assert api.get("/settings/preferences").status_code == 200  # the data opens: nothing was re-encrypted
    assert "Wallet" in api.get("/accounts").text

    # The session from before the reset is over.
    current = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.set_cookie(settings.SESSION_COOKIE_NAME, old_session, path=settings.SESSION_COOKIE_PATH)
    assert api.get("/auth/me").status_code == 401
    api.set_cookie(settings.SESSION_COOKIE_NAME, current, path=settings.SESSION_COOKIE_PATH)

    api.client.cookies.clear()
    assert api.login(password=PASSWORD).status_code == 401
    assert api.login(password=NEW).status_code == 200
    again = reset(api, token, "Another-Horse-9!x")
    assert (again.status_code, again.json()["code"]) == (400, "RESET_LINK_INVALID")
    session.expire_all()
    actions = session.execute(select(AuditLog.action)).scalars().all()
    assert "PASSWORD_RESET_REQUEST" in actions and "PASSWORD_RESET" in actions


def test_an_expired_link_is_refused(api, mail, session):
    signed_out_account(api)
    forgot(api)
    token = token_of(mail[0])
    user = session.execute(select(User)).scalar_one()
    user.reset_expires_at = utcnow() - timedelta(minutes=1)
    session.commit()
    assert reset(api, token).json()["code"] == "RESET_LINK_INVALID"


def test_a_newer_link_replaces_the_older_one(api, mail):
    signed_out_account(api)
    forgot(api)
    forgot(api)
    first, second = token_of(mail[0]), token_of(mail[1])
    assert first != second
    assert reset(api, first).json()["code"] == "RESET_LINK_INVALID"
    assert reset(api, second).status_code == 200


def test_a_weak_password_does_not_spend_the_link(api, mail):
    signed_out_account(api)
    forgot(api)
    token = token_of(mail[0])
    assert reset(api, token, "short").status_code == 422
    assert reset(api, token).status_code == 200


def test_mail_per_address_is_capped_without_saying_so(api, mail):
    signed_out_account(api)
    for _ in range(settings.PASSWORD_RESET_MAX_PER_EMAIL + 1):
        assert forgot(api).status_code == 202
    assert len(mail) == settings.PASSWORD_RESET_MAX_PER_EMAIL


def test_a_disabled_account_gets_no_email(api, mail, session):
    signed_out_account(api)
    user = session.execute(select(User)).scalar_one()
    user.is_active = False
    session.commit()
    assert forgot(api).status_code == 202
    assert mail == []


def test_the_link_ignores_the_host_the_request_claims(api, mail):
    signed_out_account(api)
    forgot(api, headers={"Host": "evil.example"})
    assert "evil.example" not in mail[0].text
    assert f"{settings.APP_PUBLIC_URL}{settings.BASE_URL}/reset#token=" in mail[0].text


def test_a_made_up_token_is_refused(api, mail):
    signed_out_account(api)
    assert reset(api, "x" * 43).json()["code"] == "RESET_LINK_INVALID"


def test_send_uses_starttls_login_and_the_configured_sender(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, msg):
            calls.append(("send", msg["From"], msg["To"], msg["Subject"]))

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", "sender@example.test")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", SecretStr("app-password"))
    monkeypatch.setattr(settings, "SMTP_FROM", "sender@example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "Budget App")
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)

    assert email_service.send(email_service.Message("noah@example.com", "Hello", "text", "<p>html</p>")) is True
    assert calls == [
        ("connect", "smtp.gmail.com", 587),
        ("starttls",),
        ("login", "sender@example.test", "app-password"),
        ("send", "Budget App <sender@example.test>", "noah@example.com", "Hello"),
    ]
