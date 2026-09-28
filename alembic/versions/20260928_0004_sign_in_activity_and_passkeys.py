"""sign-in activity and passkeys: device_label on refresh_tokens, passkeys on users

Revision ID: 20260928_0004
Revises: 20260914_0003
Created: 2026-09-28

SEC-32. A coarse label for the device a session was started on ("Chrome on
Android"), parsed from the User-Agent at sign-in - never the raw string. Every
token of a family carries its first token's label. Sessions started before
this migration have none and show "Unknown device".

SEC-12. The passkeys that may unlock this account's lock screen: a JSON list
of credential ids and PUBLIC keys. Nothing secret - a public key opens
nothing, and a passkey only decides whether the server unwraps the DEK again
with the master key, exactly as the PIN does.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision: str = "20260928_0004"
down_revision: Union[str, None] = "20260914_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("device_label", sa.String(60), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("passkeys", sa.UnicodeText(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("users", "passkeys", schema=SCHEMA)
    op.drop_column("refresh_tokens", "device_label", schema=SCHEMA)
