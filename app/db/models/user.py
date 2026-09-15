"""
users - Shape A. Operational columns, plus the DEK wrapped under the master key.

Nothing here is personal financial data, and the one personal identifier - the
email address - is present only as a blind index (email_bidx) and inside
profile_enc, which is sealed under the user's own DEK. profile_enc is what the
app reads the email back from, and what would let every email_bidx be rebuilt
if the pepper ever had to change.
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

    # The DEK, wrapped under the master key (section 5.2)
    key_version: Mapped[int] = mapped_column(TinyInt, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(EncryptedPayload(128), nullable=False)

    # The PIN guards the SESSION only; it never derives a key (section 6).
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pin_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    locked_until: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    # SEC-30: the pending password-reset link. Only the SHA-256 of its token is
    # kept; a newer request replaces it and using it clears both.
    reset_token_hash: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    reset_expires_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"User(id={self.id}, admin={self.is_admin}, active={self.is_active})"
