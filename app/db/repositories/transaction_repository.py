"""
transactions - Shape B.

Phase 4 owns the write path (splits, transfers, the working-set cache). What
exists here in Phase 3 is the read side, because category_service cannot
safely delete a category without walking every transaction that might point at
it - including one level deeper, inside `splits[]` (CAT-08, TXN-16).
"""

from app.db.models import Transaction
from app.db.repositories.encrypted_repository import EncryptedRepository


class TransactionRepository(EncryptedRepository):
    model = Transaction
