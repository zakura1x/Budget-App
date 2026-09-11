"""
Alembic environment.

Connects through the application's own engine factory (app/db/connection.py),
so migrations always run against the database the app is configured for and
no credential sits in a tracked file.

Everything lives in schema DB_SCHEMA (ZBDGT). That needs saying three times:

  1. The schema is created here, BEFORE Alembic creates its version table in
     it. QUOT never hit this because its schema came from int_tables.sql; this
     project's first `alembic upgrade head` starts from nothing.
  2. Reflection is limited to this schema (include_name). The database hosts
     ~90 other schemas, one of them named with a dot ([P8].[fn_Monthly_...]),
     which makes the MSSQL dialect issue `use [P8]` and fail. QUOT found that
     out the hard way; the same guard is copied here.
  3. Nothing outside this schema can ever appear in a generated migration
     (include_object) - on a shared database, the cost of being wrong is
     dropping someone else's table.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text

import app.db.models  # noqa: F401 - registers every table on Base.metadata
from app.core.config import settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
SCHEMA = settings.DB_SCHEMA  # validated as a plain identifier by config.py

ENSURE_SCHEMA = f"IF SCHEMA_ID(N'{SCHEMA}') IS NULL EXEC(N'CREATE SCHEMA [{SCHEMA}]')"


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == SCHEMA
    return True


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return (obj.schema or SCHEMA) == SCHEMA
    return True


def _configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=SCHEMA,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` - emits T-SQL, touches no database."""
    _configure(url=settings.DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.execute(ENSURE_SCHEMA)
        context.run_migrations()


def run_migrations_online() -> None:
    from app.db.connection import create_db_engine

    engine = create_db_engine(poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Before configure(): the version table is created inside this schema.
        connection.execute(text(ENSURE_SCHEMA))
        connection.commit()
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
