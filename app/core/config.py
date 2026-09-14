"""
Configuration Management

Loads settings from environment variables and .env, and REFUSES TO START when
the encryption material is missing or malformed (ARCHITECTURE.md section 8).

A budget app that silently falls back to storing plaintext is worse than one
that will not boot. So the master key and the blind-index pepper are validated
here, at import time, and a bad value raises ConfigurationError before any
route, engine or logger exists to do damage with it.

Two rules for this file:

  1. Secrets are SecretStr. Their repr is '**********', so a settings object
     that ends up in a log line or a traceback does not carry the key with it.
  2. A validation failure never echoes the value it rejected. pydantic's own
     ValidationError prints `input_value=...`, which for a 31-byte master key
     is 31 bytes of the real key. load_settings() strips that out.
"""

import base64
import binascii
import re
from functools import cached_property
from pathlib import Path
from typing import Dict, List

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# The project root, so .env is found no matter which directory uvicorn, alembic
# or a script was started from. IIS does not promise a working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# The envelope format (app/core/crypto/envelope.py) fixes these. They are in
# .env so the choice is visible, not so it can be changed: a different value
# would mean a different byte layout, and every existing row would stop
# decrypting. Validated below so a well-meaning edit fails at startup instead.
_FIXED_CIPHER = "AES-256-GCM"
_FIXED_NONCE_BYTES = 12
_FIXED_TAG_BYTES = 16

# Interpolated into DDL (CREATE SCHEMA, the alembic version table), so it must
# be a plain identifier and nothing else.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

_VALID_PHRASE_WORDS = (12, 15, 18, 21, 24)


class ConfigurationError(RuntimeError):
    """The application is misconfigured and must not start."""


def _decode_key(value: str, name: str) -> bytes:
    """Strict base64 decode. The message names the setting, never the value."""
    try:
        return base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"{name} is not valid base64") from None


class Settings(BaseSettings):
    """Application settings loaded from environment, then .env"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ============================================
    # Database - company SQL Server, schema ZBDGT
    # ============================================
    DB_SERVER: str = "localhost"
    DB_NAME: str = "P8_NOAH_AI"
    DB_SCHEMA: str = "ZBDGT"
    DB_USER: str = "sa"
    DB_PASSWORD: SecretStr = SecretStr("")
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"
    DB_TRUSTED_CONNECTION: bool = False
    DB_ENCRYPT: bool = True
    DB_TRUST_SERVER_CERTIFICATE: bool = True
    DB_CONNECTION_TIMEOUT: int = 30
    DB_COMMAND_TIMEOUT: int = 60
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800

    # ============================================
    # Application-level encryption (ARCHITECTURE.md section 5)
    # ============================================
    BUDGET_MASTER_KEY: SecretStr = SecretStr("")
    BUDGET_KEY_VERSION: int = 1
    BUDGET_RETIRED_KEYS: SecretStr = SecretStr("")
    BUDGET_BLIND_INDEX_PEPPER: SecretStr = SecretStr("")
    BUDGET_CIPHER: str = _FIXED_CIPHER
    BUDGET_NONCE_BYTES: int = _FIXED_NONCE_BYTES
    BUDGET_TAG_BYTES: int = _FIXED_TAG_BYTES
    BUDGET_AAD_BIND_ROW: bool = True
    BUDGET_ENCRYPT_UPLOADS: bool = True

    # ============================================
    # Recovery phrase (SEC-14)
    # ============================================
    RECOVERY_PHRASE_ENABLED: bool = True
    RECOVERY_PHRASE_WORDS: int = 12
    RECOVERY_PHRASE_LANGUAGE: str = "english"
    RECOVERY_MAX_ATTEMPTS: int = 3
    RECOVERY_LOCKOUT_MINUTES: int = 60
    RECOVERY_PHRASE_VIEWABLE: bool = True
    RECOVERY_PHRASE_REGENERATE_ENABLED: bool = True
    DEK_ROTATION_ENABLED: bool = True
    ROTATION_REVOKES_OTHER_SESSIONS: bool = True

    # ============================================
    # Decrypted working-set cache (Phase 4)
    # ============================================
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 900
    CACHE_MAX_USERS: int = 8
    CACHE_MAX_ROWS_PER_USER: int = 50000
    CACHE_WARM_ON_LOGIN: bool = True

    # ============================================
    # JWT / session cookies (Phase 2)
    # ============================================
    JWT_SECRET_KEY: SecretStr = SecretStr("")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 30
    JWT_REFRESH_EXPIRATION_DAYS: int = 30
    JWT_ISSUER: str = "budget-app"
    JWT_AUDIENCE: str = "budget-api"
    REFRESH_TOKEN_ROTATION: bool = True
    REFRESH_TOKEN_REUSE_REVOKES_FAMILY: bool = True

    SESSION_COOKIE_NAME: str = "zbdgt_session"
    # The refresh token's cookie is narrower still: it is only ever sent to
    # {API_PREFIX}/auth, so no other request carries the long-lived token.
    REFRESH_COOKIE_NAME: str = "zbdgt_refresh"
    SESSION_COOKIE_PATH: str = "/ZBDGT"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"
    SESSION_SECRET: SecretStr = SecretStr("")

    # ============================================
    # Password & device lock
    # ============================================
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SYMBOL: bool = True
    BCRYPT_ROUNDS: int = 12
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    PIN_ENABLED: bool = True
    PIN_LENGTH: int = 6
    PIN_PEPPER: SecretStr = SecretStr("")
    PIN_MAX_ATTEMPTS: int = 5
    PIN_AUTO_LOCK_MINUTES: int = 5
    BIOMETRIC_WEBAUTHN_ENABLED: bool = False

    # ============================================
    # Application
    # ============================================
    APP_NAME: str = "Budget App"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"
    LOG_MAX_SIZE: int = 10485760
    LOG_BACKUP_COUNT: int = 5
    API_PREFIX: str = "/ZBDGT/api/v1"
    BASE_URL: str = "/ZBDGT"
    TZ: str = "Asia/Manila"

    SINGLE_USER_MODE: bool = False
    FIRST_USER_IS_ADMIN: bool = True
    MAX_USERS: int = 5

    REGISTRATION_MODE: str = "code"
    REGISTRATION_CODE: SecretStr = SecretStr("")
    REGISTRATION_MAX_ATTEMPTS: int = 5
    REGISTRATION_ATTEMPT_WINDOW_MINUTES: int = 60

    # ============================================
    # Budget defaults - PHP only (ACC-11)
    # ============================================
    DEFAULT_CURRENCY: str = "PHP"
    CURRENCY_SYMBOL: str = "PHP"
    CURRENCY_DECIMALS: int = 2
    DEFAULT_LOCALE: str = "en_PH"
    DEFAULT_BUDGET_PERIOD: str = "monthly"
    DEFAULT_MONTH_START_DAY: int = 1
    DEFAULT_WEEK_START_DAY: int = 1
    DAILY_ALLOWANCE_MODE: str = "remaining_over_days_left"
    DEFAULT_CARRY_OVER_UNSPENT: bool = False

    # ============================================
    # Alerts - in-app only
    # ============================================
    ALERT_ENABLED: bool = True
    ALERT_WARN_THRESHOLD_PCT: int = 80
    ALERT_PACE_ENABLED: bool = True
    ALERT_PACE_TOLERANCE_PCT: int = 10
    ALERT_CATEGORY_LEVEL: bool = True
    CREDIT_DUE_ALERT_DAYS: int = 5
    # ACC-26. The window a NEW card starts with: purchases this many days
    # before a statement closes are marked "may be on next statement". Each
    # card keeps its own, editable in the account sheet. Most cards post
    # within 1-3 banking days.
    CARD_POSTING_LAG_DAYS: int = Field(default=3, ge=0, le=10)

    # ============================================
    # Frontend
    # ============================================
    FRONTEND_DIST_DIR: str = "./app/web/static/dist"
    FRONTEND_DEV_SERVER: str = "http://localhost:5173"
    VITE_PROXY_ENABLED: bool = True
    SPA_FALLBACK: bool = True
    PWA_ENABLED: bool = True

    CORS_ORIGINS_STR: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000",
        validation_alias="CORS_ORIGINS",
    )

    # ============================================
    # Uploads
    # ============================================
    MAX_UPLOAD_SIZE: int = 10485760
    ALLOWED_EXTENSIONS: str = ".jpg,.jpeg,.png,.heic,.pdf,.csv"
    UPLOAD_DIR: str = "./uploads"
    TEMP_DIR: str = "./temp_uploads"

    # ============================================
    # Rate limiting (Phase 2)
    # ============================================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 200
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_LOGIN_REQUESTS: int = 10
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 300

    # ============================================
    # Backup (Phase 8a)
    # ============================================
    BACKUP_ENABLED: bool = True
    BACKUP_DIR: str = "./backups"
    BACKUP_RETENTION_DAYS: int = 90
    BACKUP_FORMAT: str = "budgetbak"
    BACKUP_INCLUDE_ATTACHMENTS: bool = True
    BACKUP_TRIGGER: str = "activity"
    BACKUP_DEBOUNCE_MINUTES: int = 5
    BACKUP_INTERVAL_HOURS: int = 24
    BACKUP_OFFSITE_DIR: str = ""
    BACKUP_VERIFY_ON_WRITE: bool = True

    # ============================================
    # Validators - the encryption material
    # ============================================
    @field_validator("BUDGET_MASTER_KEY")
    @classmethod
    def _master_key_is_32_bytes(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw.strip():
            raise ValueError(
                "BUDGET_MASTER_KEY is not set. Generate one with "
                "scripts/generate_keys.py - and if this is an existing install, "
                "restore the ORIGINAL key from your backup instead: a new key "
                "cannot read rows written under the old one"
            )
        if len(_decode_key(raw, "BUDGET_MASTER_KEY")) != 32:
            raise ValueError("BUDGET_MASTER_KEY must decode to exactly 32 bytes")
        return v

    @field_validator("BUDGET_BLIND_INDEX_PEPPER")
    @classmethod
    def _pepper_is_set(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw.strip():
            raise ValueError(
                "BUDGET_BLIND_INDEX_PEPPER is not set. Without it no user can be "
                "found at login. Restore it from your .env backup"
            )
        if len(_decode_key(raw, "BUDGET_BLIND_INDEX_PEPPER")) < 32:
            raise ValueError("BUDGET_BLIND_INDEX_PEPPER must decode to at least 32 bytes")
        return v

    @field_validator("BUDGET_KEY_VERSION")
    @classmethod
    def _key_version_fits_a_byte(cls, v: int) -> int:
        # Version 0 is reserved: the recovery-phrase wrap uses it (crypto/dek.py)
        if not 1 <= v <= 255:
            raise ValueError("BUDGET_KEY_VERSION must be between 1 and 255")
        return v

    @field_validator("BUDGET_CIPHER")
    @classmethod
    def _cipher_is_fixed(cls, v: str) -> str:
        if v != _FIXED_CIPHER:
            raise ValueError(f"BUDGET_CIPHER must be {_FIXED_CIPHER}; it is fixed by the envelope format")
        return v

    @field_validator("BUDGET_NONCE_BYTES")
    @classmethod
    def _nonce_is_fixed(cls, v: int) -> int:
        if v != _FIXED_NONCE_BYTES:
            raise ValueError(f"BUDGET_NONCE_BYTES must be {_FIXED_NONCE_BYTES}; it is fixed by the envelope format")
        return v

    @field_validator("BUDGET_TAG_BYTES")
    @classmethod
    def _tag_is_fixed(cls, v: int) -> int:
        if v != _FIXED_TAG_BYTES:
            raise ValueError(f"BUDGET_TAG_BYTES must be {_FIXED_TAG_BYTES}; it is fixed by the envelope format")
        return v

    @field_validator("BUDGET_AAD_BIND_ROW")
    @classmethod
    def _aad_binding_is_on(cls, v: bool) -> bool:
        # Every row IS bound to its id; the envelope has no unbound mode. A False
        # here would be a setting that lies about what the code does.
        if not v:
            raise ValueError(
                "BUDGET_AAD_BIND_ROW must be True. Row binding is what stops a "
                "ciphertext being swapped onto another row (ARCHITECTURE.md 5.3)"
            )
        return v

    @field_validator("RECOVERY_PHRASE_WORDS")
    @classmethod
    def _phrase_length_is_bip39(cls, v: int) -> int:
        if v not in _VALID_PHRASE_WORDS:
            raise ValueError(f"RECOVERY_PHRASE_WORDS must be one of {_VALID_PHRASE_WORDS}")
        return v

    @field_validator("DB_SCHEMA")
    @classmethod
    def _schema_is_identifier(cls, v: str) -> str:
        if not _IDENTIFIER.match(v):
            raise ValueError("DB_SCHEMA must be a plain SQL identifier")
        return v

    @field_validator("BASE_URL", "API_PREFIX", "SESSION_COOKIE_PATH")
    @classmethod
    def _path_is_absolute(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("/"):
            raise ValueError("must start with '/'")
        return v.rstrip("/") or "/"

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _jwt_secret_is_strong(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value().strip()) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be set (32+ characters). Generate one with scripts/generate_keys.py"
            )
        return v

    @field_validator("SESSION_COOKIE_NAME", "REFRESH_COOKIE_NAME")
    @classmethod
    def _cookie_is_app_scoped(cls, v: str) -> str:
        # SEC-28: the host is shared with QUOT; a generic name could overwrite
        # another app's cookie.
        if not v.startswith("zbdgt_"):
            raise ValueError("session cookie names must start with 'zbdgt_' (SEC-28)")
        return v

    @field_validator("SESSION_COOKIE_SAMESITE")
    @classmethod
    def _samesite_is_known(cls, v: str) -> str:
        v = v.lower()
        if v not in ("lax", "strict"):
            raise ValueError("SESSION_COOKIE_SAMESITE must be lax or strict")
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> "Settings":
        if not (self.SESSION_COOKIE_PATH == self.BASE_URL or self.SESSION_COOKIE_PATH.startswith(self.BASE_URL + "/")):
            raise ValueError("SESSION_COOKIE_PATH must be BASE_URL or under it (SEC-28)")
        if self.PIN_ENABLED:
            pepper = self.PIN_PEPPER.get_secret_value().strip()
            if not pepper or len(_decode_key(pepper, "PIN_PEPPER")) < 32:
                raise ValueError("PIN_PEPPER must be set (base64, 32+ bytes) while PIN_ENABLED is true")
        if self.PIN_LENGTH < 4 or self.PIN_LENGTH > 12:
            raise ValueError("PIN_LENGTH must be between 4 and 12")
        # Parse eagerly so a malformed retired-key list fails at startup, not
        # in the middle of a rotation.
        retired = self.retired_master_keys
        if self.BUDGET_KEY_VERSION in retired:
            raise ValueError(
                "BUDGET_RETIRED_KEYS must not contain the current BUDGET_KEY_VERSION"
            )
        if not self.API_PREFIX.startswith(self.BASE_URL):
            raise ValueError("API_PREFIX must sit under BASE_URL")
        return self

    # ============================================
    # Derived values
    # ============================================
    @cached_property
    def master_key_bytes(self) -> bytes:
        return _decode_key(self.BUDGET_MASTER_KEY.get_secret_value(), "BUDGET_MASTER_KEY")

    @cached_property
    def blind_index_pepper_bytes(self) -> bytes:
        return _decode_key(
            self.BUDGET_BLIND_INDEX_PEPPER.get_secret_value(), "BUDGET_BLIND_INDEX_PEPPER"
        )

    @cached_property
    def pin_pepper_bytes(self) -> bytes:
        return _decode_key(self.PIN_PEPPER.get_secret_value(), "PIN_PEPPER")

    @property
    def registration_open(self) -> bool:
        """Signup needs a code (SEC-19); no code configured means closed."""
        return self.REGISTRATION_MODE == "code" and bool(self.REGISTRATION_CODE.get_secret_value().strip())

    @cached_property
    def retired_master_keys(self) -> Dict[int, bytes]:
        """BUDGET_RETIRED_KEYS as {version: key}. Format: "1:base64,2:base64"."""
        raw = self.BUDGET_RETIRED_KEYS.get_secret_value().strip()
        keys: Dict[int, bytes] = {}
        if not raw:
            return keys
        for n, entry in enumerate(raw.split(","), start=1):
            version_text, sep, key_text = entry.strip().partition(":")
            if not sep or not version_text.strip().isdigit():
                raise ValueError(f"BUDGET_RETIRED_KEYS entry {n} must look like 'version:base64key'")
            version = int(version_text)
            if not 1 <= version <= 255:
                raise ValueError(f"BUDGET_RETIRED_KEYS entry {n} has a version outside 1-255")
            key = _decode_key(key_text, f"BUDGET_RETIRED_KEYS entry {n}")
            if len(key) != 32:
                raise ValueError(f"BUDGET_RETIRED_KEYS entry {n} must decode to exactly 32 bytes")
            keys[version] = key
        return keys

    @property
    def CORS_ORIGINS(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS_STR.split(",") if o.strip()]

    @property
    def BASE_URL_CLEAN(self) -> str:
        return self.BASE_URL.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def odbc_connection_string(self) -> str:
        """
        A raw ODBC connection string, passed to pyodbc through odbc_connect.

        Built this way rather than as a mssql+pyodbc://user:pass@host URL
        because the server name carries a backslash instance (SERVER\\SQL2019)
        and the password may carry anything: URL escaping of either is a quiet
        way to get a login failure that looks like a wrong password. Values
        that may contain separators are brace-quoted, with '}' doubled, which
        is the ODBC rule.
        """

        def braced(value: str) -> str:
            return "{" + value.replace("}", "}}") + "}"

        parts = [
            f"DRIVER={braced(self.DB_DRIVER)}",
            f"SERVER={self.DB_SERVER}",
            f"DATABASE={braced(self.DB_NAME)}",
            f"Encrypt={'yes' if self.DB_ENCRYPT else 'no'}",
            f"TrustServerCertificate={'yes' if self.DB_TRUST_SERVER_CERTIFICATE else 'no'}",
        ]
        if self.DB_TRUSTED_CONNECTION:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={braced(self.DB_USER)}")
            parts.append(f"PWD={braced(self.DB_PASSWORD.get_secret_value())}")
        return ";".join(parts) + ";"

    @property
    def DATABASE_URL(self) -> URL:
        """
        The SQLAlchemy URL - dialect only, deliberately WITHOUT credentials.

        The engine connects through a creator function that hands pyodbc the
        connection string above (app/db/connection.py). An odbc_connect URL
        would carry the password in its query string, and SQLAlchemy masks the
        password field of a URL but not its query: the engine's repr, and any
        log line that printed it, would show the database password.
        """
        return URL.create("mssql+pyodbc")


def load_settings(**overrides) -> Settings:
    """
    Build Settings, converting a validation failure into a ConfigurationError
    that names every bad setting and quotes none of their values.

    Keyword overrides are for tests. `_env_file=None` among them skips .env.
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for err in exc.errors(include_input=False, include_url=False, include_context=False):
            where = ".".join(str(p) for p in err["loc"]) or "settings"
            message = err["msg"].removeprefix("Value error, ")
            problems.append(f"  - {where}: {message}")
        # `from None` drops the original exception from the traceback, because
        # its text includes the rejected input values.
        raise ConfigurationError(
            "Refusing to start - the configuration is invalid:\n" + "\n".join(problems)
        ) from None


# HARD FAIL at import. Nothing below this line runs with a bad master key.
settings = load_settings()
