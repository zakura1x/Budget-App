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


@pytest.fixture(autouse=True)
def _fresh_working_set():
    """
    The working set is process-wide, and in-memory SQLite hands out user id 1
    to every test - so a cache left over from one test would be served to the
    next. Every test starts, and ends, with it empty.
    """
    from app.core.crypto.working_set import set_working_set

    set_working_set(None)
    yield
    set_working_set(None)


@pytest.fixture
def owner(session):
    """
    A real users row and a cipher for it. Service-level tests need both: the
    cipher to seal with, and the row because user_id carries a real foreign
    key even on a Shape B table.
    """
    from app.core.crypto.envelope import PLACEHOLDER
    from app.db.models import User
    from app.db.types import utcnow

    now = utcnow()
    user = User(
        email_bidx="o" * 64, password_hash="x", key_version=1,
        dek_wrapped=PLACEHOLDER, created_at=now, updated_at=now,
    )
    session.add(user)
    session.flush()
    return UserCipher(user.id, generate_dek(), 1)


@pytest.fixture
def session(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        yield s


# ---------------------------------------------------------------- the API



class ApiClient:
    """TestClient plus the header every real request carries, and helpers."""

    def __init__(self, client, prefix):
        self.client = client
        self.prefix = prefix
        self.headers = {"X-Requested-With": "fetch"}

    def get(self, path, **kw):
        return self.client.get(self.prefix + path, headers=self.headers, **kw)

    def post(self, path, json=None, **kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return self.client.post(self.prefix + path, json=json, headers=headers, **kw)

    def patch(self, path, json=None, **kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return self.client.patch(self.prefix + path, json=json, headers=headers, **kw)

    def delete(self, path, **kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return self.client.delete(self.prefix + path, headers=headers, **kw)

    @property
    def cookies(self):
        return self.client.cookies

    def set_cookie(self, name, value, path):
        """Replace a cookie the way a browser holds it - one per name and path.
        (httpx keeps server cookies under 'testserver.local'; a bare set() would
        add a second copy beside it.)"""
        for cookie in list(self.client.cookies.jar):
            if cookie.name == name and cookie.path == path:
                self.client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
        self.client.cookies.set(name, value, domain="testserver.local", path=path)

    def register(self, email="noah@example.com", password="Correct-Horse-9!", code=None, name="Noah"):
        from app.core.config import settings

        code = code if code is not None else settings.REGISTRATION_CODE.get_secret_value()
        return self.post("/auth/register", {"email": email, "password": password,
                                            "registration_code": code, "display_name": name})

    def login(self, email="noah@example.com", password="Correct-Horse-9!"):
        return self.post("/auth/login", {"email": email, "password": password})


@pytest.fixture
def api(engine, monkeypatch):
    """The real app, on in-memory SQLite, with fresh keyrings and limits."""
    from fastapi.testclient import TestClient

    import app.api.v1.endpoints.health as health_module
    import app.main as main_module
    from app.core.config import settings
    from app.core.crypto.blind_index import set_blind_indexer
    from app.core.crypto.keyring import set_master_keyring
    from app.core.crypto.session_keys import get_session_keyring
    from app.core.middleware.rate_limit import limiter
    from app.db.connection import set_engine

    ok = {"reachable": True, "schema_present": True}
    monkeypatch.setattr(health_module, "check_database", lambda: dict(ok))
    monkeypatch.setattr(main_module, "check_database", lambda: dict(ok))
    set_engine(engine)
    set_master_keyring(None)
    set_blind_indexer(None)
    get_session_keyring().lock_all()
    limiter.reset()
    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        yield ApiClient(client, settings.API_PREFIX)
    get_session_keyring().lock_all()
    set_master_keyring(None)
    set_blind_indexer(None)
    set_engine(None)
