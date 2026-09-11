"""
recurring_rules - Shape B. THE ONLY THING THAT EXPANDS INTO TRANSACTIONS.

Payload: template transaction (account_id, splits, tag_ids...), frequency,
interval, next run, end condition, and kind - standard | subscription |
installment. Installment terms (total, payments, amount, start) live here too
(ARCHITECTURE.md 4.4); the remaining balance is derived, never stored.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class RecurringRule(EncryptedRowMixin, Base):
    __tablename__ = "recurring_rules"
