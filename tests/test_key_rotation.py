"""
Master-key rotation (SEC-11; ARCHITECTURE.md 5.2.2) - scripts/rotate_keys.py.

The guarantees: --new-key retires the old key instead of losing it and prints
no key; --rewrap moves every DEK to the current version without changing the
DEK, so every row and profile still opens; it resumes after an interruption and
a second run does nothing; a dry run changes nothing; an account whose key
cannot be opened is reported, not half-moved; and a backup written before the
rotation still restores - but only while the retired key is kept.
"""

import base64
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto.dek import wrapped_key_version
from app.core.crypto.keyring import MasterKeyring, set_master_keyring
from app.core.exceptions import BusinessRuleException
from app.db.models import User
from app.db.repositories.user_repository import UserRepository
from app.services.backup_service import bundle, restore_service

pytestmark = pytest.mark.security
ROOT = Path(__file__).resolve().parents[1]


def rotate_keys():
    spec = importlib.util.spec_from_file_location("rotate_keys", ROOT / "scripts" / "rotate_keys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def key(n: int) -> str:
    return base64.b64encode(bytes([n]) * 32).decode()


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(settings, "TEMP_DIR", str(tmp_path / "temp"))
    return tmp_path


def signed_up(api, email):
    assert api.register(email=email, name="X").status_code == 201
    api.post("/accounts", {"name": "Wallet", "type": "cash", "opening_balance": "100.00"})
    api.client.cookies.clear()


# ---------------------------------------------------------------- --new-key


def test_new_key_retires_the_old_one_instead_of_losing_it():
    rk = rotate_keys()
    text = f"# keys\nBUDGET_MASTER_KEY={key(1)}\nBUDGET_KEY_VERSION=1\nBUDGET_RETIRED_KEYS=\nDB_NAME=P8\n"
    rotated, old, new = rk.plan_new_env(text, key(2))
    assert (old, new) == (1, 2)
    assert f"BUDGET_MASTER_KEY={key(2)}\n" in rotated and "BUDGET_KEY_VERSION=2\n" in rotated
    assert f"BUDGET_RETIRED_KEYS=1:{key(1)}\n" in rotated
    assert "# keys" in rotated and "DB_NAME=P8" in rotated

    again, old, new = rk.plan_new_env(rotated, key(3))
    assert (old, new) == (2, 3) and f"BUDGET_RETIRED_KEYS=1:{key(1)},2:{key(2)}" in again


def test_new_key_refuses_what_it_cannot_do_safely():
    rk = rotate_keys()
    with pytest.raises(rk.RotationError):
        rk.plan_new_env("BUDGET_MASTER_KEY=\n", key(2))
    with pytest.raises(rk.RotationError):
        rk.plan_new_env(f"BUDGET_MASTER_KEY={key(1)}\nBUDGET_KEY_VERSION=255\n", key(2))
    with pytest.raises(rk.RotationError):
        rk.plan_new_env(f"BUDGET_MASTER_KEY={key(1)}\nBUDGET_KEY_VERSION=1\nBUDGET_RETIRED_KEYS=2:{key(9)}\n", key(2))


def test_new_key_dry_run_changes_nothing_and_no_key_is_printed(tmp_path, capsys):
    rk = rotate_keys()
    env = tmp_path / ".env"
    original = f"BUDGET_MASTER_KEY={key(1)}\nBUDGET_KEY_VERSION=1\n"
    env.write_text(original, encoding="utf-8")
    assert rk.main(["--new-key", "--dry-run", "--env", str(env)]) == 0
    assert env.read_text(encoding="utf-8") == original

    assert rk.main(["--new-key", "--env", str(env)]) == 0
    text = env.read_text(encoding="utf-8")
    assert "BUDGET_KEY_VERSION=2" in text and f"BUDGET_RETIRED_KEYS=1:{key(1)}" in text
    new_key = rk._get(text, "BUDGET_MASTER_KEY")
    out = capsys.readouterr().out
    assert key(1) not in out and new_key not in out
    assert not list(tmp_path.glob("*.rotating"))


# ------------------------------------------------------------------ --rewrap


def test_rewrap_moves_every_dek_resumes_and_keeps_old_backups_open(api, session, folders):
    rk = rotate_keys()
    signed_up(api, "alice@example.com")
    signed_up(api, "bob@example.com")
    info = bundle.write_backup(session, 1, directory=folders / "before")
    old_backup = bundle.read_bundle(folders / "before" / info.name)

    v2 = MasterKeyring(current_version=2, current_key=bytes(range(32)), retired={1: settings.master_key_bytes})
    set_master_keyring(v2)  # the app, restarted on the rotated .env
    users = UserRepository(session)

    dry = rk.rewrap_all(session, v2, dry_run=True)
    assert (dry["pending"], dry["moved"], dry["failed"]) == (2, 0, [])
    session.expire_all()
    assert users.wrap_versions() == {1: 2}

    # Interrupted after the first account...
    assert users.rewrap_dek(users.get(1), v2) is True
    session.commit()
    assert users.wrap_versions() == {1: 1, 2: 1}
    # ...run again, it carries on - and a third run has nothing to do.
    result = rk.rewrap_all(session, v2, dry_run=False)
    assert (result["moved"], result["current"], result["failed"]) == (1, 1, [])
    assert rk.rewrap_all(session, v2, dry_run=False)["moved"] == 0
    session.expire_all()
    assert users.wrap_versions() == {2: 2}
    assert [u.key_version for u in session.execute(select(User).order_by(User.id)).scalars()] == [1, 1]

    # The app on version 2 signs both in and opens their profile and their rows.
    for email in ("alice@example.com", "bob@example.com"):
        api.client.cookies.clear()
        signed_in = api.login(email=email)
        assert signed_in.status_code == 200 and signed_in.json()["user"]["email"] == email
        assert "Wallet" in api.get("/accounts").text

    # A backup written BEFORE the rotation still opens, through the retired key...
    target = users.cipher_for(users.get(1), v2)
    source = restore_service.unlock_source(old_backup, keyring=v2)
    assert restore_service.restore(session, old_backup, target, source, mode="verify").ok
    # ...and without that retired key it cannot. Never drop one while such a backup is wanted.
    with pytest.raises(BusinessRuleException):
        restore_service.unlock_source(old_backup, keyring=MasterKeyring(current_version=2, current_key=bytes(range(32))))


def test_signing_in_after_a_rotation_rewraps_lazily_and_the_profile_still_opens(api, session):
    """The sign-in half of rotation must move the WRAP only - users.key_version is the profile's AAD version."""
    signed_up(api, "alice@example.com")
    set_master_keyring(MasterKeyring(current_version=2, current_key=bytes(range(32)),
                                     retired={1: settings.master_key_bytes}))
    for _ in range(2):  # the first sign-in re-wraps; the second must still read the profile
        api.client.cookies.clear()
        signed_in = api.login(email="alice@example.com")
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["user"]["email"] == "alice@example.com"
    session.expire_all()
    user = session.get(User, 1)
    assert wrapped_key_version(bytes(user.dek_wrapped)) == 2 and user.key_version == 1


def test_an_account_whose_key_cannot_be_opened_is_reported_not_moved(api, session):
    rk = rotate_keys()
    signed_up(api, "alice@example.com")
    stranger = MasterKeyring(current_version=3, current_key=bytes(range(32)))  # version 1 not loaded
    assert rk.rewrap_all(session, stranger, dry_run=True)["failed"] == [1]
    assert rk.rewrap_all(session, stranger, dry_run=False)["failed"] == [1]
    session.expire_all()
    assert wrapped_key_version(bytes(session.get(User, 1).dek_wrapped)) == 1
