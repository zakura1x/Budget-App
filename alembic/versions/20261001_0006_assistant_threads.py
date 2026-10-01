"""assistant_threads: saved AI companion conversations, encrypted

Revision ID: 20261001_0006
Revises: 20260930_0005
Created: 2026-10-01

misc/AI, Phase A6 (AI-60). Shape B, laid out exactly like the baseline's
encrypted tables: plaintext id, user_id, key_version, is_deleted and the row
timestamps, and one sealed payload holding the conversation. Rows exist only
for a user who chose to keep conversations (`assistant_history_days`).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from app.core.config import settings

revision: str = "20261001_0006"
down_revision: Union[str, None] = "20260930_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA
NAME = "assistant_threads"


def upgrade() -> None:
    op.create_table(
        NAME,
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, increment=1), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key_version", mssql.TINYINT(), nullable=False),
        sa.Column("payload", mssql.VARBINARY("max"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("row_created", mssql.DATETIME2(), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.Column("row_updated", mssql.DATETIME2(), nullable=False, server_default=sa.text("SYSUTCDATETIME()")),
        sa.PrimaryKeyConstraint("id", name=f"PK_{NAME}"),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], name=f"FK_{NAME}_user_id_users"),
        schema=SCHEMA,
    )
    # The only useful index a Shape B table can have (ARCHITECTURE.md 4.3).
    op.create_index(f"IX_{NAME}_user", NAME, ["user_id", "is_deleted"], schema=SCHEMA)


def downgrade() -> None:
    # Saved conversations only - nothing else reads this table. Dropping it loses them.
    op.drop_index(f"IX_{NAME}_user", table_name=NAME, schema=SCHEMA)
    op.drop_table(NAME, schema=SCHEMA)
