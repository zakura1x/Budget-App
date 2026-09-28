"""
transactions - Shape B, and the one table read through the working set.

Reads: `cached()` returns every live transaction for this user from the
working set, loading it with `list()` on a miss. Every list, filter, total and
search in transaction_service is a loop over that.

Writes: create, update and soft_delete are the base class's, so the two-step
insert still lives in exactly one place (invariant 2). What this adds is
WRITE-THROUGH, and it is deliberately deferred to the COMMIT:

    write  ->  queued on session.info
    commit ->  applied to the working set
    rollback -> the user's working set is dropped instead

Applying at flush would be wrong: a service that raises after writing rolls
the database back, and the cache would keep a row the database never had. A
dropped cache is merely cold; a wrong one is a lie on every screen.

Category deletion rewrites transactions through this same repository
(CAT-08), so its reassignment reaches the cache the same way - there is no
second write path to forget.
"""

from datetime import datetime
from typing import Any, List, Mapping, Optional

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.crypto.working_set import get_working_set
from app.db.models import Transaction
from app.db.repositories.encrypted_repository import EncryptedRepository, Record

TABLE = "transactions"
_PENDING = "zbdgt_working_set_pending"


class TransactionRepository(EncryptedRepository):
    model = Transaction

    def cached(self) -> List[Record]:
        """Every live transaction this user owns, from the working set."""
        return get_working_set().rows(self.cipher.user_id, TABLE, self.list)

    def deleted_since(self, cutoff: datetime) -> List[Record]:
        """
        TXN-25. Soft-deleted rows touched on or after `cutoff`, oldest first.
        Never cached - the working set holds live rows only. `row_updated` is
        plaintext and a soft delete sets it, so SQL can narrow this to recent
        deletions before anything is decrypted; the service decides which of
        them the user actually deleted.
        """
        m = self.model
        query = (
            select(m.id, m.key_version, m.payload, m.row_created, m.row_updated, m.is_deleted)
            .where(m.user_id == self.cipher.user_id, m.is_deleted == True, m.row_updated >= cutoff)  # noqa: E712
            .order_by(m.id)
        )
        return [self._open(*row) for row in self.session.execute(query)]

    def create(self, data: Mapping[str, Any]) -> Record:
        record = super().create(data)
        self._queue("put", record)
        return record

    def update(self, row_id: int, data: Mapping[str, Any]) -> Optional[Record]:
        record = super().update(row_id, data)
        if record is not None:
            self._queue("remove" if record.is_deleted else "put", record)
        return record

    def soft_delete(self, row_id: int) -> bool:
        deleted = super().soft_delete(row_id)
        if deleted:
            self._queue("remove", row_id)
        return deleted

    def undelete(self, row_id: int) -> bool:
        restored = super().undelete(row_id)
        if restored:
            record = self.get(row_id)
            if record is not None:
                self._queue("put", record)
        return restored

    def _queue(self, op: str, value: Any) -> None:
        self.session.info.setdefault(_PENDING, []).append((self.cipher.user_id, op, value))


@event.listens_for(Session, "after_commit")
def _apply_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    working_set = get_working_set()
    for user_id, op, value in pending:
        if op == "put":
            working_set.put(user_id, TABLE, value)
        else:
            working_set.remove(user_id, TABLE, value if isinstance(value, int) else value.id)


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    working_set = get_working_set()
    for user_id in {user_id for user_id, _, _ in pending}:
        working_set.drop(user_id)
