"""
attachments - Shape B.

Payload: filename, mime type, size, on-disk reference. The file itself is
encrypted on disk as well, at uploads/<user_id>/<attachment_id>.enc (DAT-19).
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Attachment(EncryptedRowMixin, Base):
    __tablename__ = "attachments"
