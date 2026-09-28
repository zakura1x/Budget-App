"""
refresh_tokens - Shape A. Stored hashed; rotated on every use.

family_id groups every token descended from one login, and doubles as the
session id the in-memory keyring is keyed by. Presenting a token that was
already used revokes the whole family (section 6): that is the signature of a
stolen token being replayed.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, qualified
from app.db.types import BigIntPK, UtcDateTime, utcnow


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("IX_refresh_tokens_family", "family_id"),
        Index("IX_refresh_tokens_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey(qualified("users") + ".id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    family_id: Mapped[str] = mapped_column(CHAR(32), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigIntPK, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # SEC-32 - "Chrome on Android", from the User-Agent at sign-in; never the raw string
    device_label: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
