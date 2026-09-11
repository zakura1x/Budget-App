"""
SEC-15 - recovery through the API, including the rehearsal the plan asks for
before Phase 3: write data, destroy the master key AND the pepper, recover
using only the 12 words, read the data back.
"""

import os

import pytest

from app.core.config import settings
from app.core.crypto.blind_index import BlindIndexer, set_blind_indexer
from app.core.crypto.keyring import MasterKeyring, set_master_keyring
from app.core.crypto.recovery import generate_phrase

pytestmark = pytest.mark.security

NEW_PASSWORD = "Brand-New-Pass-7!"


def test_end_to_end_recovery_rehearsal_with_a_brand_new_env(api):
    phrase = " ".join(api.register().json()["recovery_phrase"])
    assert api.post("/auth/pin", {"pin": "482913"}).status_code == 200
    before = api.get("/settings/preferences").json()
    api.post("/auth/logout")

    # ---- .env destroyed: a new master key AND a new pepper ----
    set_master_keyring(MasterKeyring(1, os.urandom(32)))
    set_blind_indexer(BlindIndexer(os.urandom(32)))
    assert api.login().status_code == 401  # the email no longer finds the row

    response = api.post("/auth/recover", {"phrase": phrase.upper(), "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "noah@example.com"
    assert body["pin_set"] is False  # the old PIN was peppered by the lost .env
    assert api.get("/settings/preferences").json() == before  # the data survived

    api.post("/auth/logout")
    assert api.login().status_code == 401  # old password gone
    assert api.login(password=NEW_PASSWORD).status_code == 200  # new one, under the new keys


def test_recovery_signs_out_every_other_session(api):
    phrase = " ".join(api.register().json()["recovery_phrase"])
    other_access = api.cookies.get(settings.SESSION_COOKIE_NAME)
    api.post("/auth/recover", {"phrase": phrase, "new_password": NEW_PASSWORD})
    api.set_cookie(settings.SESSION_COOKIE_NAME, other_access, path=settings.SESSION_COOKIE_PATH)
    assert api.get("/auth/me").json()["code"] == "SESSION_REVOKED"


def test_a_typo_is_explained_and_does_not_use_up_an_attempt(api):
    words = api.register().json()["recovery_phrase"]
    api.post("/auth/logout")
    words[4] = words[4] + "q"
    for _ in range(settings.RECOVERY_MAX_ATTEMPTS + 2):
        typo = api.post("/auth/recover", {"phrase": " ".join(words), "new_password": NEW_PASSWORD})
        assert typo.status_code == 422 and typo.json()["positions"] == [5]


def test_wrong_phrases_are_limited_hard(api):
    api.register()
    api.post("/auth/logout")
    for _ in range(settings.RECOVERY_MAX_ATTEMPTS):
        wrong = api.post("/auth/recover", {"phrase": generate_phrase(), "new_password": NEW_PASSWORD})
        assert wrong.status_code == 401
    assert api.post("/auth/recover", {"phrase": generate_phrase(), "new_password": NEW_PASSWORD}).status_code == 429


def test_recovery_needs_a_policy_password(api):
    phrase = " ".join(api.register().json()["recovery_phrase"])
    assert api.post("/auth/recover", {"phrase": phrase, "new_password": "weak"}).status_code == 422


def test_one_users_phrase_never_opens_another_account(api):
    alice_phrase = " ".join(api.register(email="alice@example.com", name="Alice").json()["recovery_phrase"])
    api.post("/auth/logout")
    api.register(email="bob@example.com", name="Bob")
    api.post("/auth/logout")
    body = api.post("/auth/recover", {"phrase": alice_phrase, "new_password": NEW_PASSWORD}).json()
    assert body["user"]["email"] == "alice@example.com"
