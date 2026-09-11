"""
budgets - Shape B.

Payload: period type (weekly | monthly | custom), start day, amount,
carry-over flag, active range.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Budget(EncryptedRowMixin, Base):
    __tablename__ = "budgets"
