"""
Shape B - the layout every data table shares (ARCHITECTURE.md section 4.1).

    id           BIGINT IDENTITY   plaintext surrogate; part of the AAD
    user_id      INT               plaintext; the only thing SQL can filter on
    key_version  TINYINT           master-key version current when the row was
                                   sealed; part of the AAD
    payload      VARBINARY(MAX)    ENCRYPTED - everything else about the row
    is_deleted   BIT               plaintext soft delete
    row_created  DATETIME2         server clock at insert, NOT the txn date
    row_updated  DATETIME2

user_id carries a real foreign key to users.id - it is plaintext, so the
database can check it. Every reference INSIDE a payload (account_id,
splits[].category_id, parent_id...) has no FK and never can; the service
layer and scripts/verify_integrity.py own those.
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, false
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import qualified
from app.db.types import BigIntPK, EncryptedPayload, TinyInt, UtcDateTime, utcnow


class EncryptedRowMixin:
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    key_version: Mapped[int] = mapped_column(TinyInt, nullable=False)
    payload: Mapped[bytes] = mapped_column(EncryptedPayload(), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    row_created: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    row_updated: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey(qualified("users") + ".id"), nullable=False)

    @declared_attr.directive
    def __table_args__(cls):
        # The ONLY useful index a Shape B table can have (section 4.3).
        return (Index(f"IX_{cls.__tablename__}_user", "user_id", "is_deleted"),)
