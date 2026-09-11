"""
audit_log - Shape A with one encrypted column.

The verb and entity are plaintext so the log is useful ("user 1 UPDATE
transactions 4211"). The detail - what changed, which would include amounts -
is sealed under the user's DEK, so the audit trail is not a side channel that
leaks the very figures the data tables protect.

user_id has no foreign key on purpose: an account deletion (SEC-21) is itself
audited, and that record has to outlive the user row it describes.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, BigInteger, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import BigIntPK, EncryptedPayload, TinyInt, UtcDateTime, utcnow


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("IX_audit_log_user", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    key_version: Mapped[Optional[int]] = mapped_column(TinyInt, nullable=True)
    detail_enc: Mapped[Optional[bytes]] = mapped_column(EncryptedPayload(), nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
