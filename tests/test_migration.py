"""
The migration and the models describe the same fifteen tables.

Autogenerate needs a live database to compare against, and the tests never
touch one. So the migration is rendered offline to T-SQL, and every model
column is checked against it: present, same nullability, same SQL Server
type. A model changed without a migration fails here, not at first deploy.
"""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import mssql

from app.core.config import settings
from app.db.base import Base
import app.db.models  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = settings.DB_SCHEMA


@pytest.fixture(scope="module")
def offline_sql() -> str:
    buffer = io.StringIO()
    command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=buffer), "head", sql=True)
    return buffer.getvalue()


def create_blocks(sql: str) -> dict:
    blocks = {}
    for match in re.finditer(rf"CREATE TABLE \[{SCHEMA}\]\.(\w+) \((.*?)\n\);", sql, re.S):
        blocks[match.group(1)] = match.group(2)
    # Columns added by a later migration count as part of their table.
    for match in re.finditer(rf"ALTER TABLE \[{SCHEMA}\]\.(\w+) ADD (\w+ [^;]+);", sql):
        blocks[match.group(1)] += "\n    " + match.group(2)
    return blocks


def test_schema_is_created_before_the_version_table(offline_sql):
    assert offline_sql.index("CREATE SCHEMA") < offline_sql.index("alembic_version")
    assert f"CREATE TABLE [{SCHEMA}].alembic_version" in offline_sql


def test_all_fifteen_tables_are_created(offline_sql):
    blocks = create_blocks(offline_sql)
    model_tables = {t.name for t in Base.metadata.sorted_tables}
    assert len(model_tables) == 15
    assert model_tables <= set(blocks)


def test_every_model_column_matches_the_migration(offline_sql):
    blocks = create_blocks(offline_sql)
    dialect = mssql.dialect()
    for table in Base.metadata.sorted_tables:
        block = blocks[table.name]
        for column in table.columns:
            line = re.search(rf"^\s*{column.name} (.+?),?\s*$", block, re.M)
            assert line, f"{table.name}.{column.name} missing from the migration"
            ddl = line.group(1)
            expected_type = column.type.compile(dialect=dialect)
            assert ddl.startswith(expected_type), f"{table.name}.{column.name}: {ddl!r} vs {expected_type!r}"
            nullable = " NOT NULL" not in ddl
            assert nullable == column.nullable, f"{table.name}.{column.name} nullability differs"


def test_every_model_index_and_unique_is_in_the_migration(offline_sql):
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            assert f"CREATE INDEX [{index.name}]" in offline_sql, index.name
        for constraint in table.constraints:
            if constraint.__class__.__name__ in ("UniqueConstraint", "ForeignKeyConstraint") and constraint.name:
                assert f"[{constraint.name}]" in offline_sql, constraint.name


def test_int_tables_sql_is_up_to_date(offline_sql):
    committed = (ROOT / "scripts" / "int_tables.sql").read_text(encoding="utf-8")
    assert offline_sql in committed, "run: python scripts/generate_int_tables.py"


def test_the_baseline_refuses_to_downgrade():
    import importlib.util

    path = next((ROOT / "alembic" / "versions").glob("*_0001_baseline_budget_schema.py"))
    spec = importlib.util.spec_from_file_location("baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="Refusing"):
        module.downgrade()
