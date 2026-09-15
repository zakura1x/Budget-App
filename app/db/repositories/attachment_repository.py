"""
attachments - Shape B rows, and the encrypted files they describe
(TXN-15, DAT-17, DAT-19).

The row's payload holds the filename, type and size. The receipt itself is a
file at uploads/<user_id>/<attachment_id>.enc, sealed with the user's DEK
under the AAD `ZBDGT.attachment_files:<attachment_id>:<user_id>:v<n>` - so a
file copied over another receipt's name fails to open, exactly as a row
payload would. Per-user folders keep two users' receipts from colliding.

`file_key_version` in the payload records the key version the FILE was sealed
under; a later update of the row re-seals the payload, not the file.
"""

import os
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.db.models import Attachment
from app.db.repositories.encrypted_repository import EncryptedRepository

FILE_TABLE = "attachment_files"


class AttachmentRepository(EncryptedRepository):
    model = Attachment

    @staticmethod
    def file_path(user_id: int, attachment_id: int) -> Path:
        return Path(settings.UPLOAD_DIR) / str(int(user_id)) / f"{int(attachment_id)}.enc"

    def write_file(self, attachment_id: int, content: bytes) -> int:
        """Seal and write the file; returns the key version it was sealed under."""
        sealed = self.cipher.seal_bytes(FILE_TABLE, attachment_id, content)
        path = self.file_path(self.cipher.user_id, attachment_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_bytes(sealed)
        os.replace(partial, path)  # never a half-written receipt under the real name
        return self.cipher.key_version

    def read_file(self, attachment_id: int, file_key_version: int) -> bytes:
        """The decrypted file. FileNotFoundError if it is gone; DecryptionError if it was tampered with."""
        path = self.file_path(self.cipher.user_id, attachment_id)
        return self.cipher.open_bytes(FILE_TABLE, attachment_id, path.read_bytes(), file_key_version)

    def delete_file(self, attachment_id: int) -> None:
        self.file_path(self.cipher.user_id, attachment_id).unlink(missing_ok=True)

    @staticmethod
    def raw_file(user_id: int, attachment_id: int) -> Optional[bytes]:
        """The file as stored - ciphertext - for a backup, which needs no key."""
        path = AttachmentRepository.file_path(user_id, attachment_id)
        return path.read_bytes() if path.is_file() else None
