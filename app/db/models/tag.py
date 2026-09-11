"""
tags - Shape B. Payload: name, colour.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Tag(EncryptedRowMixin, Base):
    __tablename__ = "tags"
