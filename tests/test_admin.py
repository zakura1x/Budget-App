"""
The admin screen's API (UX-20, SEC-18): account management and nothing more -
no emails, no figures - and a disabled or deleted account is gone at once.
"""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import Account, User

pytestmark = pytest.mark.security
PASSWORD = "Correct-Horse-9!"


def admin_and_bob(api):
    api.register(email="admin@example.com", name="Admin")
    admin_cookie = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    api.register(email="bob@example.com", name="Bob")
    api.post("/accounts", {"name": "Bob's wallet", "type": "cash"})
    bob_cookie = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    api.set_cookie(settings.SESSION_COOKIE_NAME, admin_cookie, path=settings.SESSION_COOKIE_PATH)
    return admin_cookie, bob_cookie


def as_bob(api, bob_cookie, admin_cookie, path="/auth/me"):
    api.set_cookie(settings.SESSION_COOKIE_NAME, bob_cookie, path=settings.SESSION_COOKIE_PATH)
    status = api.get(path).status_code
    api.set_cookie(settings.SESSION_COOKIE_NAME, admin_cookie, path=settings.SESSION_COOKIE_PATH)
    return status


def test_the_admin_sees_rows_and_never_data(api):
    admin_and_bob(api)
    users = api.get("/admin/users")
    assert users.status_code == 200
    assert [u["id"] for u in users.json()] == [1, 2]
    assert "bob@example.com" not in users.text and "Bob" not in users.text
    status = api.get("/admin/status").json()
    assert (status["users"], status["rows"]["accounts"]) == (2, 1)


def test_only_the_admin(api):
    admin_cookie, bob_cookie = admin_and_bob(api)
    assert as_bob(api, bob_cookie, admin_cookie, "/admin/users") == 403


def test_disabling_signs_someone_out_everywhere(api):
    admin_cookie, bob_cookie = admin_and_bob(api)
    assert api.post("/admin/users/2/active", {"active": False}).json()["is_active"] is False
    assert as_bob(api, bob_cookie, admin_cookie) == 401
    assert api.post("/admin/users/1/active", {"active": False}).status_code == 400  # not yourself
    assert api.post("/admin/users/2/active", {"active": True}).json()["is_active"] is True


def test_deleting_someone_needs_their_number_and_your_password(api, session):
    admin_cookie, bob_cookie = admin_and_bob(api)
    assert api.post("/admin/users/2/delete", {"confirm_user_id": 2, "password": "wrong"}).status_code == 401
    assert api.post("/admin/users/2/delete", {"confirm_user_id": 3, "password": PASSWORD}).status_code == 422
    assert api.post("/admin/users/2/delete", {"confirm_user_id": 2, "password": PASSWORD}).status_code == 204
    session.expire_all()
    assert session.execute(select(func.count()).select_from(User)).scalar_one() == 1
    assert session.execute(select(func.count()).select_from(Account)).scalar_one() == 0
    assert as_bob(api, bob_cookie, admin_cookie) == 401
