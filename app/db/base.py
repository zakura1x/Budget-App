"""
Declarative base - every table lives in the ZBDGT schema (DB_SCHEMA).
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

SCHEMA = settings.DB_SCHEMA

# Named constraints, so a migration can refer to one by name instead of by
# whatever SQL Server generated (PK__accounts__3213E83F1A2B...).
NAMING_CONVENTION = {
    "ix": "IX_%(table_name)s_%(column_0_N_name)s",
    "uq": "UQ_%(table_name)s_%(column_0_N_name)s",
    "ck": "CK_%(table_name)s_%(constraint_name)s",
    "fk": "FK_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "PK_%(table_name)s",
}

metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


def qualified(table: str) -> str:
    """ZBDGT.table - for ForeignKey targets and raw SQL."""
    return f"{SCHEMA}.{table}"
