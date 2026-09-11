"""
Database sessions - session_scope() for services and scripts, get_db() for
FastAPI dependencies.

expire_on_commit=False: repositories hand back decrypted records built from
the row, and a commit must not turn those into lazy loads against a closed
session.
"""

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
_bound = False


def rebind(engine: Optional[Engine]) -> None:
    global _bound
    _SessionLocal.configure(bind=engine)
    _bound = engine is not None


def _factory() -> sessionmaker:
    if not _bound:
        from app.db.connection import get_engine

        rebind(get_engine())
    return _SessionLocal


def get_session() -> Session:
    return _factory()()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """One unit of work: commit on success, roll back on any exception."""
    session = _factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. The endpoint's service decides when to commit."""
    session = _factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
