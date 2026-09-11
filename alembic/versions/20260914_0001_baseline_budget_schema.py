"""baseline budget schema - the fifteen tables of ZBDGT

Revision ID: 20260914_0001
Revises:
Created: 2026-09-14

Unlike QUOT's baseline, this one is NOT empty: this project starts from an
empty schema, so the first `alembic upgrade head` creates everything, and it
is also the proof that the database login can create tables in ZBDGT.

scripts/int_tables.sql is generated FROM this file (alembic upgrade head
--sql), so the reference DDL and the migration cannot drift apart. Regenerate
it rather than editing it by hand.

Column order follows ARCHITECTURE.md 4.1: id, user_id, key_version, payload,
is_deleted, row_created, row_updated. Timestamps default to SYSUTCDATETIME()
on the server as a backstop; the application also sets them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from app.core.config import settings

revision: str = "20260914_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = settings.DB_SCHEMA

# The eleven Shape B tables, in the backup importer's insert order
# (ARCHITECTURE.md 12.3), then user_preferences.
SHAPE_B = (
    "accounts",
    "categories",
    "tags",
    "budgets",
    "budget_allocations",
    "recurring_rules",
    "subscriptions",
    "savings_goals",
    "transactions",
    "attachments",
    "user_preferences",
)


def _now():
    return sa.text("SYSUTCDATETIME()")


def _zero():
    return sa.text("0")


def _identity(big: bool = True):
    return sa.Column("id", sa.BigInteger() if big else sa.Integer(), sa.Identity(start=1, increment=1), nullable=False)


def upgrade() -> None:
    op.execute(f"IF SCHEMA_ID(N'{SCHEMA}') IS NULL EXEC(N'CREATE SCHEMA [{SCHEMA}]')")

    # ------------------------------------------------------------ Shape A
    op.create_table(
        "users",
        _identity(big=False),
        sa.Column("email_bidx", sa.CHAR(64), nullable=False),
        sa.Column("profile_enc", mssql.VARBINARY("max"), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("key_version", mssql.TINYINT(), nullable=False),
        sa.Column("dek_wrapped", mssql.VARBINARY(128), nullable=False),
        sa.Column("dek_wrapped_recovery", mssql.VARBINARY(128), nullable=True),
        sa.Column("recovery_created_at", mssql.DATETIME2(), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column("pin_failed_count", sa.Integer(), nullable=False, server_default=_zero()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=_zero()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=_zero()),
        sa.Column("locked_until", mssql.DATETIME2(), nullable=True),
        sa.Column("last_login_at", mssql.DATETIME2(), nullable=True),
        sa.Column("password_changed_at", mssql.DATETIME2(), nullable=True),
        sa.Column("created_at", mssql.DATETIME2(), nullable=False, server_default=_now()),
        sa.Column("updated_at", mssql.DATETIME2(), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("id", name="PK_users"),
        sa.UniqueConstraint("email_bidx", name="UQ_users_email_bidx"),
        schema=SCHEMA,
    )

    op.create_table(
        "refresh_tokens",
        _identity(),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("family_id", sa.CHAR(32), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_at", mssql.DATETIME2(), nullable=False, server_default=_now()),
        sa.Column("expires_at", mssql.DATETIME2(), nullable=False),
        sa.Column("used_at", mssql.DATETIME2(), nullable=True),
        sa.Column("revoked_at", mssql.DATETIME2(), nullable=True),
        sa.Column("revoke_reason", sa.String(40), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="UQ_refresh_tokens_token_hash"),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], name="FK_refresh_tokens_user_id_users"),
        schema=SCHEMA,
    )
    op.create_index("IX_refresh_tokens_family", "refresh_tokens", ["family_id"], schema=SCHEMA)
    op.create_index("IX_refresh_tokens_user", "refresh_tokens", ["user_id"], schema=SCHEMA)

    op.create_table(
        "login_attempts",
        _identity(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("email_bidx", sa.CHAR(64), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", mssql.DATETIME2(), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("id", name="PK_login_attempts"),
        schema=SCHEMA,
    )
    op.create_index("IX_login_attempts_bidx", "login_attempts", ["email_bidx", "attempted_at"], schema=SCHEMA)
    op.create_index("IX_login_attempts_ip", "login_attempts", ["ip_hash", "attempted_at"], schema=SCHEMA)
    op.create_index("IX_login_attempts_user", "login_attempts", ["user_id", "attempted_at"], schema=SCHEMA)

    op.create_table(
        "audit_log",
        _identity(),
        sa.Column("user_id", sa.Integer(), nullable=True),  # no FK: outlives a deleted user
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("key_version", mssql.TINYINT(), nullable=True),
        sa.Column("detail_enc", mssql.VARBINARY("max"), nullable=True),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column("created_at", mssql.DATETIME2(), nullable=False, server_default=_now()),
        sa.PrimaryKeyConstraint("id", name="PK_audit_log"),
        schema=SCHEMA,
    )
    op.create_index("IX_audit_log_user", "audit_log", ["user_id", "created_at"], schema=SCHEMA)

    # ------------------------------------------------------------ Shape B
    for name in SHAPE_B:
        extra = ()
        if name == "user_preferences":
            extra = (sa.UniqueConstraint("user_id", name="UQ_user_preferences_user"),)
        op.create_table(
            name,
            _identity(),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("key_version", mssql.TINYINT(), nullable=False),
            sa.Column("payload", mssql.VARBINARY("max"), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=_zero()),
            sa.Column("row_created", mssql.DATETIME2(), nullable=False, server_default=_now()),
            sa.Column("row_updated", mssql.DATETIME2(), nullable=False, server_default=_now()),
            sa.PrimaryKeyConstraint("id", name=f"PK_{name}"),
            sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], name=f"FK_{name}_user_id_users"),
            *extra,
            schema=SCHEMA,
        )
        # The only useful index a Shape B table can have (ARCHITECTURE.md 4.3).
        op.create_index(f"IX_{name}_user", name, ["user_id", "is_deleted"], schema=SCHEMA)


def downgrade() -> None:
    """
    Refused. Downgrading the baseline means dropping every table in the
    schema - every encrypted row you own. That is a restore-from-backup
    decision, not a migration, and this file will not make it for you.
    """
    raise RuntimeError(
        "Refusing to drop the ZBDGT schema's tables. If you really mean to "
        "destroy all data, do it deliberately in SSMS after taking a backup."
    )
