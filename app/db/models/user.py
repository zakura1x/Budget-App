"""
users - Shape A. Operational columns, plus the two wrapped copies of the DEK.

Nothing here is personal financial data, and the one personal identifier - the
email address - is present only as a blind index (email_bidx) and inside
profile_enc, which is sealed under the user's own DEK.

Why profile_enc exists: total loss of .env takes the blind-index pepper with
it, and a new pepper computes different indexes, so no email would find its
row again. Recovery finds the user by the phrase instead (crypto/recovery.py),
unwraps the DEK, reads the email back out of profile_enc, and rebuilds
email_bidx under the new pepper. Without it, recovery would restore the data
and lose the login.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CHAR, Integer, String, false, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import EncryptedPayload, TinyInt, UtcDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # HMAC-SHA256(pepper, normalised email) - the login lookup (section 5.4)
    email_bidx: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    # {"email", "display_name"} sealed under this user's DEK, AAD bound to the row
    profile_enc: Mapped[Optional[bytes]] = mapped_column(EncryptedPayload(), nullable=True)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # The DEK, wrapped twice (section 5.2). Either one opens it.
    key_version: Mapped[int] = mapped_column(TinyInt, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(EncryptedPayload(128), nullable=False)
    dek_wrapped_recovery: Mapped[Optional[bytes]] = mapped_column(EncryptedPayload(128), nullable=True)
    recovery_created_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)

    # The PIN guards the SESSION only; it never derives a key (section 6).
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pin_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    locked_until: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"User(id={self.id}, admin={self.is_admin}, active={self.is_active})"
