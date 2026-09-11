"""
The whole Phase 2 flow against the company SQL Server. SKIPPED unless
ZBDGT_DB_TESTS=1.

SQLite runs everything else; this proves the same code on SQL Server's
dialect - IDENTITY on the two-step inserts, BIT comparisons, DISTINCT, the
lockout queries. One throwaway account, and EVERY row it causes is deleted
afterwards, whatever happens - its audit and attempt rows included.
"""

import os

import pytest
from sqlalchemy import delete, or_, select

from app.core.config import settings
from app.core.crypto.blind_index import get_blind_indexer
from app.db.models import ENCRYPTED_MODELS, AuditLog, LoginAttempt, RefreshToken, User

pytestmark = [pytest.mark.db, pytest.mark.security]

PASSWORD = "Correct-Horse-9!"


@pytest.fixture
def mssql_api(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.core.crypto.session_keys import get_session_keyring
    from app.core.middleware.rate_limit import limiter
    from app.db.connection import create_db_engine, set_engine
    from tests.conftest import ApiClient

    engine = create_db_engine()
    set_engine(engine)
    limiter.reset()
    email = f"zbdgt-test-{os.urandom(6).hex()}@example.invalid"
    bidx = get_blind_indexer().email(email)
    try:
        with TestClient(main_module.app, raise_server_exceptions=False) as client:
            yield ApiClient(client, settings.API_PREFIX), email
    finally:
        get_session_keyring().lock_all()
        from sqlalchemy.orm import Session

        with Session(engine) as db:
            user_ids = db.execute(select(User.id).where(User.email_bidx == bidx)).scalars().all()
            # Recovery rebuilds the index under the same pepper here, so the bidx still finds it.
            for uid in user_ids:
                for model in ENCRYPTED_MODELS:
                    db.execute(delete(model).where(model.user_id == uid))
                db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
                db.execute(delete(AuditLog).where(AuditLog.user_id == uid))
            db.execute(delete(LoginAttempt).where(or_(LoginAttempt.email_bidx == bidx,
                                                      LoginAttempt.user_id.in_(user_ids or [-1]))))
            db.execute(delete(User).where(User.email_bidx == bidx))
            db.commit()
            assert db.execute(select(User.id).where(User.email_bidx == bidx)).first() is None
        set_engine(None)
        engine.dispose()


def test_full_auth_flow_on_sql_server(mssql_api):
    api, email = mssql_api
    reg = api.register(email=email, name="DB Test")
    assert reg.status_code == 201, reg.text
    phrase = " ".join(reg.json()["recovery_phrase"])

    assert api.post("/auth/pin", {"pin": "482913"}).status_code == 200
    assert api.get("/settings/preferences").status_code == 200

    assert api.post("/auth/lock").status_code == 204
    assert api.get("/settings/preferences").json()["code"] == "SESSION_LOCKED"
    assert api.post("/auth/pin/verify", {"pin": "111222"}).status_code == 401
    assert api.post("/auth/pin/verify", {"pin": "482913"}).status_code == 200

    stolen = api.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert api.post("/auth/refresh").status_code == 200
    api.set_cookie(settings.REFRESH_COOKIE_NAME, stolen, path=f"{settings.API_PREFIX}/auth")
    assert api.post("/auth/refresh").json()["code"] == "SESSION_REVOKED"

    assert api.login(email=email, password="Wrong-Password-1!").status_code == 401
    assert api.login(email=email).status_code == 200

    recovered = api.post("/auth/recover", {"phrase": phrase, "new_password": "Brand-New-Pass-7!"})
    assert recovered.status_code == 200 and recovered.json()["user"]["email"] == email
    assert api.get("/settings/preferences").status_code == 200
    assert api.post("/auth/logout").status_code == 204
