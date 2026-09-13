"""
budgets and budget_allocations - Shape B.

A user has one live budget row. Its allocations are rows of their own, each
naming the budget and a category inside the ciphertext - references no foreign
key can check, which is why budget_service owns their integrity and category
deletion calls back into it (CAT-08).
"""

from typing import List

from app.db.models import Budget, BudgetAllocation
from app.db.repositories.encrypted_repository import EncryptedRepository, Record


class BudgetRepository(EncryptedRepository):
    model = Budget


class BudgetAllocationRepository(EncryptedRepository):
    model = BudgetAllocation

    def for_budget(self, budget_id: int) -> List[Record]:
        return [record for record in self.list() if record.data.get("budget_id") == budget_id]
