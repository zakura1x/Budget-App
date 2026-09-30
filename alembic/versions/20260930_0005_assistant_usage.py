"""assistant_usage: the AI companion's per-user daily counts

Revision ID: 20260930_0005
Revises: 20260928_0004
Created: 2026-09-30

misc/AI, Phase A1 (AI-05). Shape A: how many questions, model calls, tokens
and template fallbacks each user had per day - counts only, never a question,
a reply or a figure, so nothing in it is encrypted. The daily question cap
reads it; account deletion removes a user's rows (RotationRepository.purge_user).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision: str = "20260930_0005"
down_revision: Union[str, None] = "20260928_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA


def upgrade() -> None:
    op.create_table(
        "assistant_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1, increment=1), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallbacks", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="PK_assistant_usage"),
        sa.UniqueConstraint("user_id", "day", name="UQ_assistant_usage_user_day"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("assistant_usage", schema=SCHEMA)
