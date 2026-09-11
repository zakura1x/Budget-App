"""
savings_goals - Shape B.

Payload: name, target, target date, linked account_id. Progress is derived
from real transfers into the linked account (GOA-06), never stored.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class SavingsGoal(EncryptedRowMixin, Base):
    __tablename__ = "savings_goals"
