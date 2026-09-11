-- ====================================================================
-- BUDGET APP - DATABASE SCHEMA (reference DDL)
-- Schema: ZBDGT      Database: P8_NOAH_AI
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

BEGIN TRANSACTION;

IF SCHEMA_ID(N'ZBDGT') IS NULL EXEC(N'CREATE SCHEMA [ZBDGT]');

GO

CREATE TABLE [ZBDGT].alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

GO

-- Running upgrade  -> 20260914_0001

IF SCHEMA_ID(N'ZBDGT') IS NULL EXEC(N'CREATE SCHEMA [ZBDGT]');

GO

CREATE TABLE [ZBDGT].users (
    id INTEGER NOT NULL IDENTITY(1,1), 
    email_bidx CHAR(64) NOT NULL, 
    profile_enc VARBINARY(max) NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    key_version TINYINT NOT NULL, 
    dek_wrapped VARBINARY(128) NOT NULL, 
    dek_wrapped_recovery VARBINARY(128) NULL, 
    recovery_created_at DATETIME2 NULL, 
    pin_hash VARCHAR(255) NULL, 
    pin_failed_count INTEGER NOT NULL DEFAULT 0, 
    is_admin BIT NOT NULL DEFAULT 0, 
    is_active BIT NOT NULL DEFAULT 1, 
    failed_login_count INTEGER NOT NULL DEFAULT 0, 
    locked_until DATETIME2 NULL, 
    last_login_at DATETIME2 NULL, 
    password_changed_at DATETIME2 NULL, 
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_users] PRIMARY KEY (id), 
    CONSTRAINT [UQ_users_email_bidx] UNIQUE (email_bidx)
);

GO

CREATE TABLE [ZBDGT].refresh_tokens (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    token_hash CHAR(64) NOT NULL, 
    family_id CHAR(32) NOT NULL, 
    parent_id BIGINT NULL, 
    issued_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    expires_at DATETIME2 NOT NULL, 
    used_at DATETIME2 NULL, 
    revoked_at DATETIME2 NULL, 
    revoke_reason VARCHAR(40) NULL, 
    CONSTRAINT [PK_refresh_tokens] PRIMARY KEY (id), 
    CONSTRAINT [UQ_refresh_tokens_token_hash] UNIQUE (token_hash), 
    CONSTRAINT [FK_refresh_tokens_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_refresh_tokens_family] ON [ZBDGT].refresh_tokens (family_id);

GO

CREATE INDEX [IX_refresh_tokens_user] ON [ZBDGT].refresh_tokens (user_id);

GO

CREATE TABLE [ZBDGT].login_attempts (
    id BIGINT NOT NULL IDENTITY(1,1), 
    kind VARCHAR(16) NOT NULL, 
    email_bidx CHAR(64) NULL, 
    user_id INTEGER NULL, 
    ip_hash CHAR(64) NULL, 
    success BIT NOT NULL, 
    attempted_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_login_attempts] PRIMARY KEY (id)
);

GO

CREATE INDEX [IX_login_attempts_bidx] ON [ZBDGT].login_attempts (email_bidx, attempted_at);

GO

CREATE INDEX [IX_login_attempts_ip] ON [ZBDGT].login_attempts (ip_hash, attempted_at);

GO

CREATE INDEX [IX_login_attempts_user] ON [ZBDGT].login_attempts (user_id, attempted_at);

GO

CREATE TABLE [ZBDGT].audit_log (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NULL, 
    action VARCHAR(50) NOT NULL, 
    entity VARCHAR(50) NULL, 
    entity_id BIGINT NULL, 
    key_version TINYINT NULL, 
    detail_enc VARBINARY(max) NULL, 
    ip_hash CHAR(64) NULL, 
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_audit_log] PRIMARY KEY (id)
);

GO

CREATE INDEX [IX_audit_log_user] ON [ZBDGT].audit_log (user_id, created_at);

GO

CREATE TABLE [ZBDGT].accounts (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_accounts] PRIMARY KEY (id), 
    CONSTRAINT [FK_accounts_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_accounts_user] ON [ZBDGT].accounts (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].categories (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_categories] PRIMARY KEY (id), 
    CONSTRAINT [FK_categories_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_categories_user] ON [ZBDGT].categories (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].tags (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_tags] PRIMARY KEY (id), 
    CONSTRAINT [FK_tags_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_tags_user] ON [ZBDGT].tags (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].budgets (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_budgets] PRIMARY KEY (id), 
    CONSTRAINT [FK_budgets_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_budgets_user] ON [ZBDGT].budgets (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].budget_allocations (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_budget_allocations] PRIMARY KEY (id), 
    CONSTRAINT [FK_budget_allocations_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_budget_allocations_user] ON [ZBDGT].budget_allocations (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].recurring_rules (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_recurring_rules] PRIMARY KEY (id), 
    CONSTRAINT [FK_recurring_rules_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_recurring_rules_user] ON [ZBDGT].recurring_rules (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].subscriptions (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_subscriptions] PRIMARY KEY (id), 
    CONSTRAINT [FK_subscriptions_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_subscriptions_user] ON [ZBDGT].subscriptions (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].savings_goals (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_savings_goals] PRIMARY KEY (id), 
    CONSTRAINT [FK_savings_goals_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_savings_goals_user] ON [ZBDGT].savings_goals (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].transactions (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_transactions] PRIMARY KEY (id), 
    CONSTRAINT [FK_transactions_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_transactions_user] ON [ZBDGT].transactions (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].attachments (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_attachments] PRIMARY KEY (id), 
    CONSTRAINT [FK_attachments_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_attachments_user] ON [ZBDGT].attachments (user_id, is_deleted);

GO

CREATE TABLE [ZBDGT].user_preferences (
    id BIGINT NOT NULL IDENTITY(1,1), 
    user_id INTEGER NOT NULL, 
    key_version TINYINT NOT NULL, 
    payload VARBINARY(max) NOT NULL, 
    is_deleted BIT NOT NULL DEFAULT 0, 
    row_created DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    row_updated DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), 
    CONSTRAINT [PK_user_preferences] PRIMARY KEY (id), 
    CONSTRAINT [UQ_user_preferences_user] UNIQUE (user_id), 
    CONSTRAINT [FK_user_preferences_user_id_users] FOREIGN KEY(user_id) REFERENCES [ZBDGT].users (id)
);

GO

CREATE INDEX [IX_user_preferences_user] ON [ZBDGT].user_preferences (user_id, is_deleted);

GO

INSERT INTO [ZBDGT].alembic_version (version_num) OUTPUT inserted.version_num VALUES ('20260914_0001');

GO

COMMIT;

GO

