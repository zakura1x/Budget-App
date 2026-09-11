"""
Regenerate scripts/int_tables.sql from the alembic migrations.

    python scripts/generate_int_tables.py

The SQL is rendered offline (`alembic upgrade head --sql`): no database is
contacted. The result is the reference DDL QUOT's convention asks for, and
because it is produced from the migrations it cannot drift from them.

To use it instead of alembic (e.g. a DBA running it for you, the Phase 0
fallback), run it in SSMS against P8_NOAH_AI. It also creates the
alembic_version table and stamps it, so `alembic upgrade head` afterwards
carries on from where the script left off.
"""

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

HEADER = """\
-- ====================================================================
-- BUDGET APP - DATABASE SCHEMA (reference DDL)
-- Schema: {schema}      Database: {database}
-- ====================================================================
-- GENERATED from alembic/versions by scripts/generate_int_tables.py.
-- Do not edit by hand - change a migration and regenerate.
--
-- Fifteen tables:
--   Shape A (operational)  users, refresh_tokens, login_attempts, audit_log
--   Shape B (encrypted)    id, user_id, key_version, payload, is_deleted,
--                          row_created, row_updated - and nothing else.
--                          Every amount, date, name and category lives
--                          inside `payload`, encrypted by the application.
--
-- Run in SSMS, or let `alembic upgrade head` do the same thing.
-- ====================================================================

"""


def main() -> None:
    from alembic import command
    from alembic.config import Config

    from app.core.config import settings

    buffer = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
    command.upgrade(config, "head", sql=True)
    out = ROOT / "scripts" / "int_tables.sql"
    out.write_text(
        HEADER.format(schema=settings.DB_SCHEMA, database=settings.DB_NAME) + buffer.getvalue(),
        encoding="utf-8",
    )
    print(f"Wrote {out.relative_to(ROOT)} ({buffer.getvalue().count('CREATE TABLE')} CREATE TABLE statements)")


if __name__ == "__main__":
    main()
