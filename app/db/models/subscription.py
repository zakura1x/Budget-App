"""
subscriptions - Shape B. Metadata for a recurring_rule of kind 'subscription'.

Payload: recurring_rule_id, service name, reminder lead days, cancellation
URL, price history. NO SCHEDULE: the rule it points at owns that, so there is
exactly one engine that can post a Netflix charge.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Subscription(EncryptedRowMixin, Base):
    __tablename__ = "subscriptions"
