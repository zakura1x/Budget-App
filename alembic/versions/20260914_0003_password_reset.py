"""password reset by email: the pending link on users

Revision ID: 20260914_0003
Revises: 20260914_0002
Created: 2026-09-14

SEC-30. A reset link's token is never stored - only its SHA-256, with the time
the link stops working. Both are NULL whenever no reset is pending.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from app.core.config import settings

revision: str = "20260914_0003"
down_revision: Union[str, None] = "20260914_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA


def upgrade() -> None:
    op.add_column("users", sa.Column("reset_token_hash", sa.CHAR(64), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("reset_expires_at", mssql.DATETIME2(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("users", "reset_expires_at", schema=SCHEMA)
    op.drop_column("users", "reset_token_hash", schema=SCHEMA)
