"""
Bulk access for backup and restore (DAT-06, DAT-13; ARCHITECTURE.md §12).

Two jobs, and the reason they live here: repositories are the only layer that
handles a ciphertext (invariant 1).

  * READING ROWS AS STORED. A backup copies each row exactly as it sits in the
    database - id, key_version, is_deleted and the payload ciphertext,
    untouched. Nothing is decrypted, so writing a backup needs no key.

  * OPENING ROWS FROM A FILE. A restore decrypts each backed-up row with the
    AAD it was written under - its ORIGINAL id and user - and hands plaintext
    to the service, which writes it back through an EncryptedRepository under
    the target account's key and a new id.
"""

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import ENCRYPTED_TABLES, User


@dataclass(frozen=True)
class RawRow:
    """One Shape B row as stored. `payload` is ciphertext."""

    id: int
    key_version: int
    is_deleted: bool
    payload: bytes


@dataclass(frozen=True)
class UserKeys:
    """What a backup carries to be standalone (DAT-16): the DEK wrapped under the master key."""

    user_id: int
    key_version: int
    email_bidx: str
    dek_wrapped: bytes


class BackupRepository:
    def __init__(self, session: Session):
        self.session = session

    def raw_rows(self, table: str, user_id: int) -> List[RawRow]:
        """Every row this user owns in `table`, soft-deleted ones too, in id order."""
        model = ENCRYPTED_TABLES[table]
        query = (
            select(model.id, model.key_version, model.is_deleted, model.payload)
            .where(model.user_id == user_id)
            .order_by(model.id)
        )
        return [
            RawRow(int(row[0]), int(row[1]), bool(row[2]), bytes(row[3]))
            for row in self.session.execute(query)
            # A placeholder can only survive a failed two-step insert, which
            # rolls back - it is never data, and it could never be restored.
            if bytes(row[3]) != PLACEHOLDER
        ]

    def user_keys(self, user_id: int) -> Optional[UserKeys]:
        user = self.session.get(User, user_id)
        if user is None:
            return None
        return UserKeys(
            user_id=user.id,
            key_version=int(user.key_version),
            email_bidx=user.email_bidx,
            dek_wrapped=bytes(user.dek_wrapped),
        )


def open_row(cipher: UserCipher, table: str, row: RawRow) -> dict:
    """Decrypt a backed-up row under the AAD it was sealed with. Raises DecryptionError."""
    return cipher.open(table, row.id, row.payload, row.key_version)


def open_blob(cipher: UserCipher, table: str, row_id: int, key_version: int, blob: bytes) -> bytes:
    """Decrypt backed-up file bytes (a receipt) under their original AAD."""
    return cipher.open_bytes(table, row_id, blob, key_version)
