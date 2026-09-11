"""
Database connection - the SQLAlchemy engine for the company SQL Server.

Unlike QUOT's, the engine is created LAZILY, on first use, not at import. The
crypto layer, the test suite and several scripts import this package without
wanting a database; an import that silently opened a connection to a shared
company server would be a surprise every time.

The connection string is handed to pyodbc by a creator function, so neither
the engine's URL nor its repr ever contains the password (config.py,
DATABASE_URL).
"""

import logging
import threading
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_engine_lock = threading.Lock()


def create_db_engine(poolclass=None) -> Engine:
    """
    Build an engine for the configured SQL Server. `poolclass=NullPool` for
    one-shot callers such as alembic and the scripts.
    """
    import pyodbc  # imported here so a machine without the driver can still run the tests

    connection_string = settings.odbc_connection_string()

    def creator():
        connection = pyodbc.connect(connection_string, timeout=settings.DB_CONNECTION_TIMEOUT)
        connection.timeout = settings.DB_COMMAND_TIMEOUT  # per-query timeout, seconds
        return connection

    options = dict(creator=creator, pool_pre_ping=True, echo=False)
    if poolclass is not None:
        options["poolclass"] = poolclass
    else:
        options.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
    return create_engine(settings.DATABASE_URL, **options)


def get_engine() -> Engine:
    global _engine
    with _engine_lock:
        if _engine is None:
            logger.info("Creating database engine for %s (schema %s)", settings.DB_NAME, settings.DB_SCHEMA)
            _engine = create_db_engine()
        return _engine


def set_engine(engine: Optional[Engine]) -> None:
    """Swap the process engine - tests use this to point at SQLite."""
    global _engine
    with _engine_lock:
        _engine = engine
    from app.db import session as session_module

    session_module.rebind(engine)


def dispose_engine() -> None:
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None


def check_database(engine: Optional[Engine] = None) -> dict:
    """
    {'reachable': bool, 'schema_present': bool}. Never raises, and never
    returns the driver's error text - it names servers and logins, and /health
    is unauthenticated. The detail goes to the log.
    """
    result = {"reachable": False, "schema_present": False}
    try:
        engine = engine or get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            result["reachable"] = True
            if engine.dialect.name == "mssql":
                schema_id = connection.execute(
                    text("SELECT SCHEMA_ID(:schema)"), {"schema": settings.DB_SCHEMA}
                ).scalar()
                result["schema_present"] = schema_id is not None
            else:
                result["schema_present"] = True
    except (SQLAlchemyError, OSError, ImportError) as exc:
        logger.error("Database check failed: %s", type(exc).__name__)
        logger.debug("Database check failure detail", exc_info=True)
    return result
