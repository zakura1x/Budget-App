"""
user_preferences - Shape B, one row per user.

Payload: theme, week start day, month start day, budget period, daily
allowance mode, carry-over toggle (BUD-11, default off), alert thresholds.
No currency - PHP only.
"""

from sqlalchemy import Index, UniqueConstraint

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class UserPreference(EncryptedRowMixin, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        Index("IX_user_preferences_user", "user_id", "is_deleted"),
        UniqueConstraint("user_id", name="UQ_user_preferences_user"),
    )
