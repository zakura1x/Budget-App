"""
transactions - Shape B. The table the whole design is built around.

Payload (ARCHITECTURE.md 4.1):

    {"txn_date": "2026-09-08", "type": "expense", "amount": "3500.00",
     "account_id": 3, "merchant": "SM Supermarket", "notes": "weekly run",
     "splits": [{"category_id": 11, "amount": "2800.00", "note": "groceries"},
                {"category_id": 19, "amount": "700.00",  "note": "household"}],
     "tag_ids": [2, 7], "recurring_id": null, "attachment_id": null}

EVERY transaction carries a non-empty `splits` array, and amount equals the
Decimal-exact sum of the splits (TXN-16/20). transaction_service enforces
both; the database cannot see either.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Transaction(EncryptedRowMixin, Base):
    __tablename__ = "transactions"
