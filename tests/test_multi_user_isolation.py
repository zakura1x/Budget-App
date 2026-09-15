"""SEC-17/18 - Bob must never see Alice's rows, and no admin can read anyone's."""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto.errors import DecryptionError
from app.core.crypto.session_keys import get_session_keyring
from app.db.models import User, UserPreference
from app.db.repositories.preferences_repository import PreferencesRepository

pytestmark = pytest.mark.security


def test_each_user_sees_only_their_own_profile(api):
    api.register(email="alice@example.com", name="Alice")
    alice_cookie = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    api.register(email="bob@example.com", name="Bob")
    assert api.get("/auth/me").json()["user"]["email"] == "bob@example.com"
    api.client.cookies.clear()
    api.set_cookie(settings.SESSION_COOKIE_NAME, alice_cookie, path=settings.SESSION_COOKIE_PATH)
    assert api.get("/auth/me").json()["user"]["email"] == "alice@example.com"


def test_every_user_has_their_own_key(api, session):
    api.register(email="alice@example.com")
    api.client.cookies.clear()
    api.register(email="bob@example.com")
    users = session.execute(select(User).order_by(User.id)).scalars().all()
    assert users[0].dek_wrapped != users[1].dek_wrapped


def test_the_admins_key_cannot_open_another_users_rows(api, session):
    """SEC-18: the first user is admin, and still cannot decrypt the second."""
    api.register(email="admin@example.com")
    admin_session = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.client.cookies.clear()
    api.register(email="bob@example.com")
    bob = session.execute(select(User).where(User.is_admin == False)).scalar_one()  # noqa: E712

    from app.services.auth_service.tokens import decode_access_token

    admin_cipher = get_session_keyring().cipher_for(decode_access_token(admin_session).session_id)
    bob_prefs = session.execute(select(UserPreference).where(UserPreference.user_id == bob.id)).scalar_one()
    with pytest.raises(DecryptionError):
        admin_cipher.open("user_preferences", bob_prefs.id, bob_prefs.payload, bob_prefs.key_version)
    # And the repository will not even fetch it.
    assert PreferencesRepository(session, admin_cipher).get(bob_prefs.id) is None
