"""
login_attempts - Shape A. The lockout and rate-limit ledger.

kind is login | pin | recovery | register, so one table serves the account
lockout (SEC-05), the PIN limit, the recovery limit and the registration-code
limit (SEC-25). The IP is stored only as a keyed hash: an unkeyed hash of an
IPv4 address is reversible by trying all four billion.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CHAR, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK, UtcDateTime, utcnow


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("IX_login_attempts_bidx", "email_bidx", "attempted_at"),
        Index("IX_login_attempts_ip", "ip_hash", "attempted_at"),
        Index("IX_login_attempts_user", "user_id", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    email_bidx: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
