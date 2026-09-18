"""
The account's own security (SEC-21..24) and the preferences Phase 8b opens.

The guarantees: every operation asks for the password again; changing the
password ends every OTHER session; rotating the key leaves every row, receipt and audit detail readable under the
new key and NONE under the old; and deleting an account leaves nothing of it
but its audit trail.
"""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.crypto.errors import DecryptionError
from app.core.crypto.session_keys import get_session_keyring
from app.db.models import Account, AuditLog, RefreshToken, Transaction, User
from app.services.auth_service.tokens import decode_access_token

pytestmark = pytest.mark.security
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"pixels " * 50
PASSWORD = "Correct-Horse-9!"


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "TEMP_DIR", str(tmp_path / "temp"))
    return tmp_path


def two_sessions(api):
    """Register (session A), then sign in again (session B, current). Returns A's cookie."""
    assert api.register().status_code == 201
    first = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    assert api.login().status_code == 200
    return first


def as_session(api, cookie):
    current = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.set_cookie(settings.SESSION_COOKIE_NAME, cookie, path=settings.SESSION_COOKIE_PATH)
    status = api.get("/auth/me").status_code
    api.set_cookie(settings.SESSION_COOKIE_NAME, current, path=settings.SESSION_COOKIE_PATH)
    return status


def test_every_operation_asks_for_the_password_again(api):
    api.register()
    for path, body in (("/security/password", {"current_password": "wrong", "new_password": "Another-Horse-9!"}),
                       ("/security/rotate-key", {"password": "wrong"}),
                       ("/security/delete-account", {"password": "wrong", "confirm_email": "noah@example.com"})):
        response = api.post(path, body)
        assert (response.status_code, response.json()["code"]) == (401, "INVALID_CREDENTIALS"), path


def test_changing_the_password_ends_other_sessions(api):
    other = two_sessions(api)
    response = api.post("/security/password", {"current_password": PASSWORD, "new_password": "Another-Horse-9!"})
    assert response.json() == {"sessions_ended": 1}
    assert as_session(api, other) == 401
    assert api.get("/auth/me").status_code == 200
    api.client.cookies.clear()
    assert api.login(password=PASSWORD).status_code == 401
    assert api.login(password="Another-Horse-9!").status_code == 200


def test_the_phrase_is_gone_from_the_api(api):
    body = api.register().json()
    assert "recovery_phrase" not in body
    assert api.post("/security/phrase", {"password": PASSWORD}).status_code in (404, 405)
    assert api.post("/auth/recover", {"phrase": "x", "new_password": "Old-Words-Horse-9!"}).status_code in (404, 405)


def test_rotating_the_key_ends_other_sessions(api):
    other = two_sessions(api)
    rotated = api.post("/security/rotate-key", {"password": PASSWORD})
    assert rotated.json()["sessions_ended"] == 1
    assert as_session(api, other) == 401


def test_rotating_the_key_reseals_everything(api, session):
    api.register()
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "5000.00"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    txn = api.post("/transactions", {"type": "expense", "amount": "321.00", "account_id": wallet,
                                     "category_id": food, "merchant": "Bakery"}).json()["transactions"][0]["id"]
    api.post(f"/transactions/{txn}/attachment", content=JPEG, headers={"X-Filename": "r.jpg"})
    attachment = api.get(f"/transactions/{txn}").json()["attachment_id"]

    session_id = decode_access_token(api.cookies.get(settings.SESSION_COOKIE_NAME)).session_id
    old_cipher = get_session_keyring().cipher_for(session_id)
    old_wrap = session.execute(select(User.dek_wrapped)).scalar_one()

    rotated = api.post("/security/rotate-key", {"password": PASSWORD})
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["backups_replaced"] is True

    # This session carries on, under the new key.
    assert api.get(f"/transactions/{txn}").json()["merchant"] == "Bakery"
    assert api.get(f"/attachments/{attachment}").content == JPEG
    session.expire_all()
    assert session.execute(select(User.dek_wrapped)).scalar_one() != old_wrap

    # And the old key opens nothing any more.
    row = session.execute(select(Transaction).where(Transaction.id == txn)).scalar_one()
    with pytest.raises(DecryptionError):
        old_cipher.open("transactions", row.id, row.payload, row.key_version)
    new_cipher = get_session_keyring().cipher_for(session_id)
    detail_rows = session.execute(select(AuditLog).where(AuditLog.detail_enc.is_not(None))).scalars().all()
    for audit in detail_rows:
        new_cipher.open("audit_log", audit.id, audit.detail_enc, audit.key_version)  # every detail still reads

    # A fresh sign-in unwraps the NEW key from the master-key wrap.
    api.client.cookies.clear()
    assert api.login().status_code == 200
    assert api.get(f"/transactions/{txn}").json()["merchant"] == "Bakery"


def test_deleting_the_account_leaves_only_its_audit_trail(api, session, folders):
    api.register()
    wallet = api.post("/accounts", {"name": "Wallet", "type": "cash"}).json()["id"]
    food = api.post("/categories", {"name": "Food"}).json()["id"]
    txn = api.post("/transactions", {"type": "expense", "amount": "10.00", "account_id": wallet,
                                     "category_id": food}).json()["transactions"][0]["id"]
    api.post(f"/transactions/{txn}/attachment", content=JPEG, headers={"X-Filename": "r.jpg"})
    api.post("/backups")

    wrong = api.post("/security/delete-account", {"password": PASSWORD, "confirm_email": "someone@else.com"})
    assert wrong.status_code == 422
    done = api.post("/security/delete-account", {"password": PASSWORD, "confirm_email": " NOAH@example.com "})
    assert done.status_code == 204, done.text

    session.expire_all()
    for model in (User, Account, Transaction, RefreshToken):
        assert session.execute(select(func.count()).select_from(model)).scalar_one() == 0, model
    assert session.execute(select(AuditLog.action).where(AuditLog.action == "ACCOUNT_DELETE")).scalar_one()
    assert not (folders / "uploads" / "1").exists() and not (folders / "backups" / "1").exists()
    assert api.get("/auth/me").status_code == 401


def test_the_new_preferences(api):
    api.register()
    changed = api.patch("/settings/preferences", {"theme": "dark", "week_start_day": 7, "month_start_day": 25,
                                                   "budget_period": "weekly", "auto_lock_minutes": 2})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["theme"], changed.json()["week_start_day"]) == ("dark", 7)
    too_long = api.patch("/settings/preferences", {"auto_lock_minutes": settings.PIN_AUTO_LOCK_MINUTES + 1})
    assert too_long.status_code == 422
    assert api.patch("/settings/preferences", {"theme": "neon"}).status_code == 422

    # A new budget starts from those defaults.
    budget = api.post("/budgets?today=2026-09-14", {"amount": "5000.00"}).json()
    assert budget["period"] == "weekly" and budget["week_start_day"] == 7


def test_the_palette_is_a_preference_of_its_own(api):
    """UX-05, 2026-09-18: four palettes, each light and dark - so the palette never touches the theme."""
    api.register()
    assert api.get("/settings/preferences").json()["palette"] == "classic"
    changed = api.patch("/settings/preferences", {"palette": "lime", "theme": "dark"}).json()
    assert (changed["palette"], changed["theme"]) == ("lime", "dark")
    assert api.patch("/settings/preferences", {"palette": "candy"}).json()["theme"] == "dark"
    assert api.patch("/settings/preferences", {"palette": "neon"}).status_code == 422
    assert api.get("/settings/preferences").json()["palette"] == "candy"
