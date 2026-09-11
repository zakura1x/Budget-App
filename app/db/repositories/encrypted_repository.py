"""
EncryptedRepository - the one implementation of Shape B reads and writes.

Every data-table repository (accounts, transactions, ...) subclasses this.
Services hand it plaintext dicts and get plaintext Records back; they never
see a ciphertext and never hold a key - they hold a UserCipher, which cannot
give its key up.

Two properties hold for every subclass, because they live here and nowhere
else:

  * USER SCOPING IS NOT OPTIONAL. The cipher knows its user_id, and every
    query below filters by it. There is no method that takes a user id, so
    there is no call that can pass the wrong one (SEC-17).

  * THE TWO-STEP INSERT (ARCHITECTURE.md 5.3). A row's id is part of its AAD,
    so the id must exist before the payload can be sealed:

        INSERT (payload = PLACEHOLDER)  -> identity id
        seal with AAD "ZBDGT.{table}:{id}:{user}:v{ver}"
        UPDATE payload
        ... all inside the caller's one transaction

    The design doc placed this in transaction_repository.create(). It lives
    here instead so all eleven tables share one tested copy of it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Type

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.types import utcnow


@dataclass(frozen=True)
class Record:
    """A decrypted row. `data` is the payload, exactly as sealed."""

    id: int
    data: Dict[str, Any]
    row_created: datetime
    row_updated: datetime
    is_deleted: bool = False


class EncryptedRepository:
    model: ClassVar[Type] = None  # set by each subclass

    def __init__(self, session: Session, cipher: UserCipher):
        if self.model is None:
            raise TypeError(f"{type(self).__name__} must set `model`")
        self.session = session
        self.cipher = cipher

    @property
    def table(self) -> str:
        return self.model.__tablename__

    # ------------------------------------------------------------------ write

    def create(self, data: Mapping[str, Any]) -> Record:
        """Insert one row via the two-step insert. The caller commits."""
        now = utcnow()
        row = self.model(
            user_id=self.cipher.user_id,
            key_version=self.cipher.key_version,
            payload=PLACEHOLDER,
            is_deleted=False,
            row_created=now,
            row_updated=now,
        )
        self.session.add(row)
        self.session.flush()  # INSERT -> the identity id now exists
        row.payload = self.cipher.seal(self.table, row.id, data)
        self.session.flush()  # UPDATE, same transaction
        return Record(row.id, dict(data), row.row_created, row.row_updated, False)

    def update(self, row_id: int, data: Mapping[str, Any]) -> Optional[Record]:
        """
        Replace a row's payload. Re-sealed under the CURRENT key version, and
        key_version is updated with it - the AAD of the new ciphertext names
        the new version, so the column must too.
        """
        row = self._row(row_id)
        if row is None:
            return None
        row.key_version = self.cipher.key_version
        row.payload = self.cipher.seal(self.table, row.id, data)
        row.row_updated = utcnow()
        self.session.flush()
        return Record(row.id, dict(data), row.row_created, row.row_updated, row.is_deleted)

    def soft_delete(self, row_id: int) -> bool:
        result = self.session.execute(
            update(self.model)
            .where(self.model.id == row_id, self.model.user_id == self.cipher.user_id)
            .values(is_deleted=True, row_updated=utcnow())
        )
        return result.rowcount == 1

    # ------------------------------------------------------------------- read

    def get(self, row_id: int, include_deleted: bool = False) -> Optional[Record]:
        row = self._row(row_id)
        if row is None or (row.is_deleted and not include_deleted):
            return None
        return self._open(row.id, row.key_version, row.payload, row.row_created, row.row_updated, row.is_deleted)

    def list(self, include_deleted: bool = False) -> List[Record]:
        """
        Every row this user owns in this table, decrypted. This is the cold
        load the working-set cache (Phase 4) is built on: one index scan on
        (user_id, is_deleted), then decrypt in Python. Columns are selected
        directly rather than as ORM objects - at 10,000 rows the difference is
        most of the fetch time.
        """
        m = self.model
        query = select(m.id, m.key_version, m.payload, m.row_created, m.row_updated, m.is_deleted).where(
            m.user_id == self.cipher.user_id
        )
        if not include_deleted:
            query = query.where(m.is_deleted == False)  # noqa: E712 - SQL expression
        return [self._open(*row) for row in self.session.execute(query.order_by(m.id))]

    def count(self, include_deleted: bool = False) -> int:
        from sqlalchemy import func

        m = self.model
        query = select(func.count()).select_from(m).where(m.user_id == self.cipher.user_id)
        if not include_deleted:
            query = query.where(m.is_deleted == False)  # noqa: E712
        return self.session.execute(query).scalar_one()

    # --------------------------------------------------------------- internal

    def _row(self, row_id: int):
        return self.session.execute(
            select(self.model).where(self.model.id == row_id, self.model.user_id == self.cipher.user_id)
        ).scalar_one_or_none()

    def _open(self, row_id, key_version, payload, row_created, row_updated, is_deleted) -> Record:
        data = self.cipher.open(self.table, row_id, payload, key_version)
        return Record(row_id, data, row_created, row_updated, bool(is_deleted))
