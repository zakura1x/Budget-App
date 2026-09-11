"""
Test fixtures.

THE TESTS NEVER USE YOUR REAL KEYS, AND NEVER TOUCH THE COMPANY DATABASE.

Environment variables beat .env in pydantic-settings, so the throwaway keys
set below - before anything under app/ is imported - are what every test
sees. The database for repository tests is in-memory SQLite, with a schema
attached under the same name (ZBDGT) the models use. Tests marked `db` are
the only ones that reach SQL Server, and they are skipped unless
ZBDGT_DB_TESTS=1 is set on purpose.
"""

import base64
import os
import secrets
import tempfile

_TEST_ENV = {
    "BUDGET_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    "BUDGET_KEY_VERSION": "1",
    "BUDGET_RETIRED_KEYS": "",
    "BUDGET_BLIND_INDEX_PEPPER": base64.b64encode(secrets.token_bytes(32)).decode(),
    "JWT_SECRET_KEY": secrets.token_urlsafe(48),
    "PIN_PEPPER": base64.b64encode(secrets.token_bytes(32)).decode(),
    "SESSION_SECRET": secrets.token_urlsafe(32),
    "REGISTRATION_CODE": secrets.token_urlsafe(12),
    "ENVIRONMENT": "test",
    "DEBUG": "False",
    "LOG_LEVEL": "DEBUG",
    "LOG_DIR": tempfile.mkdtemp(prefix="zbdgt-test-logs-"),
    "BCRYPT_ROUNDS": "4",
}
if os.environ.get("ZBDGT_DB_TESTS") != "1":
    # Point the default engine somewhere harmless too, so a test that forgets
    # to use the SQLite fixture fails instead of reaching a real server.
    _TEST_ENV["DB_SERVER"] = "zbdgt-tests-must-not-connect.invalid"
os.environ.update(_TEST_ENV)

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.crypto.blind_index import BlindIndexer  # noqa: E402
from app.core.crypto.dek import generate_dek  # noqa: E402
from app.core.crypto.keyring import MasterKeyring  # noqa: E402
from app.core.crypto.user_cipher import UserCipher  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ZBDGT_DB_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="reaches SQL Server; set ZBDGT_DB_TESTS=1 to run")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def random_key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def keyring() -> MasterKeyring:
    return MasterKeyring(current_version=1, current_key=random_key())


@pytest.fixture
def indexer() -> BlindIndexer:
    return BlindIndexer(secrets.token_bytes(32))


@pytest.fixture
def cipher() -> UserCipher:
    return UserCipher(user_id=1, dek=generate_dek(), key_version=1)


def make_sqlite_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _attach_schema(dbapi_connection, _record):
        from app.core.config import settings

        dbapi_connection.execute(f"ATTACH DATABASE ':memory:' AS {settings.DB_SCHEMA}")
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    from app.db.base import Base
    import app.db.models  # noqa: F401 - registers every table

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def engine():
    engine = make_sqlite_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        yield s
