"""drop the recovery-phrase wrap from users

Revision ID: 20260914_0002
Revises: 20260914_0001
Created: 2026-09-14

The 12-word recovery phrase is gone (ARCHITECTURE.md 5.2.1, FEATURES.md
SEC-14): the server owner's offline copy of .env replaces it. Its two columns
go with it.

Dropping them destroys every recovery wrap for good - words already handed out
stop opening anything, which is the point. Downgrade puts the columns back,
empty; the wraps cannot come back.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from app.core.config import settings

revision: str = "20260914_0002"
down_revision: Union[str, None] = "20260914_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA


def upgrade() -> None:
    op.drop_column("users", "recovery_created_at", schema=SCHEMA)
    op.drop_column("users", "dek_wrapped_recovery", schema=SCHEMA)


def downgrade() -> None:
    op.add_column("users", sa.Column("dek_wrapped_recovery", mssql.VARBINARY(128), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("recovery_created_at", mssql.DATETIME2(), nullable=True), schema=SCHEMA)
