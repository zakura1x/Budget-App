"""
budget_allocations - Shape B.

Payload: budget_id, category_id, allocated amount. Both ids are inside the
ciphertext - the backup importer remaps them (ARCHITECTURE.md 12.3).
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class BudgetAllocation(EncryptedRowMixin, Base):
    __tablename__ = "budget_allocations"
