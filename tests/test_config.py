"""
The app refuses to start with a missing, short or malformed master key -
and never echoes the bad value while refusing.
"""

import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import ConfigurationError, load_settings

pytestmark = pytest.mark.security

ROOT = Path(__file__).resolve().parents[1]
GOOD_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
GOOD_PEPPER = base64.b64encode(secrets.token_bytes(32)).decode()


def build(**overrides):
    values = {"BUDGET_MASTER_KEY": GOOD_KEY, "BUDGET_BLIND_INDEX_PEPPER": GOOD_PEPPER}
    values.update(overrides)
    return load_settings(_env_file=None, **values)


def test_good_settings_load():
    s = build()
    assert len(s.master_key_bytes) == 32
    assert s.retired_master_keys == {}


@pytest.mark.parametrize(
    "bad_key, message",
    [
        ("", "not set"),
        ("   ", "not set"),
        (base64.b64encode(secrets.token_bytes(31)).decode(), "exactly 32 bytes"),
        (base64.b64encode(secrets.token_bytes(33)).decode(), "exactly 32 bytes"),
        ("this is not base64!!", "not valid base64"),
    ],
)
def test_bad_master_key_refused_without_echoing_it(bad_key, message):
    with pytest.raises(ConfigurationError) as info:
        build(BUDGET_MASTER_KEY=bad_key)
    text = str(info.value)
    assert message in text and "BUDGET_MASTER_KEY" in text
    if bad_key.strip():
        assert bad_key not in text
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_missing_or_short_pepper_refused():
    with pytest.raises(ConfigurationError, match="BUDGET_BLIND_INDEX_PEPPER"):
        build(BUDGET_BLIND_INDEX_PEPPER="")
    with pytest.raises(ConfigurationError, match="at least 32 bytes"):
        build(BUDGET_BLIND_INDEX_PEPPER=base64.b64encode(b"short").decode())


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"BUDGET_KEY_VERSION": 0}, "between 1 and 255"),
        ({"BUDGET_KEY_VERSION": 256}, "between 1 and 255"),
        ({"BUDGET_CIPHER": "AES-128-CBC"}, "fixed by the envelope"),
        ({"BUDGET_NONCE_BYTES": 16}, "fixed by the envelope"),
        ({"BUDGET_AAD_BIND_ROW": False}, "must be True"),
        ({"RECOVERY_PHRASE_WORDS": 13}, "RECOVERY_PHRASE_WORDS"),
        ({"DB_SCHEMA": "ZBDGT; DROP TABLE x"}, "plain SQL identifier"),
        ({"BUDGET_RETIRED_KEYS": "1:" + GOOD_KEY}, "must not contain the current"),
        ({"BUDGET_RETIRED_KEYS": "one:" + GOOD_KEY}, "version:base64key"),
        ({"BUDGET_RETIRED_KEYS": "2:" + base64.b64encode(b"x" * 16).decode()}, "exactly 32 bytes"),
        ({"API_PREFIX": "/OTHER/api/v1"}, "under BASE_URL"),
    ],
)
def test_other_fixed_or_structural_settings_refused(overrides, message):
    with pytest.raises(ConfigurationError, match=message):
        build(**overrides)


def test_retired_keys_parse():
    old = base64.b64encode(secrets.token_bytes(32)).decode()
    s = build(BUDGET_KEY_VERSION=2, BUDGET_RETIRED_KEYS=f" 1:{old} ")
    assert list(s.retired_master_keys) == [1]


def test_secrets_never_appear_in_repr():
    s = build(DB_PASSWORD="db-pass-123", JWT_SECRET_KEY="jwt-secret-456")
    text = repr(s)
    for secret in (GOOD_KEY, GOOD_PEPPER, "db-pass-123", "jwt-secret-456"):
        assert secret not in text


def test_database_url_carries_no_password():
    s = build(DB_PASSWORD="p@ss;word}with=odd chars", DB_SERVER=r"61.0.0.1\SQL2019")
    assert "p@ss" not in str(s.DATABASE_URL) and "p@ss" not in repr(s.DATABASE_URL)
    odbc = s.odbc_connection_string()
    assert r"SERVER=61.0.0.1\SQL2019;" in odbc
    assert "PWD={p@ss;word}}with=odd chars};" in odbc  # braced, '}' doubled


@pytest.mark.parametrize(
    "bad_key",
    ["", base64.b64encode(secrets.token_bytes(16)).decode(), "!!!not-base64!!!"],
    ids=["missing", "short", "malformed"],
)
def test_the_process_refuses_to_start(bad_key):
    """A real interpreter importing the real app, the way uvicorn would."""
    env = dict(os.environ, BUDGET_MASTER_KEY=bad_key, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode != 0
    assert "Refusing to start" in result.stderr
    assert "BUDGET_MASTER_KEY" in result.stderr
    if bad_key:
        assert bad_key not in result.stderr and bad_key not in result.stdout
