"""
categories - Shape B.

Payload: name, parent_id (one level of sub-categories), icon, colour, kind
(expense | income), sort order. parent_id is inside the ciphertext, so the
parent/child rule is enforced by category_service, not by a foreign key.
"""

from app.db.base import Base
from app.db.models.encrypted_row import EncryptedRowMixin


class Category(EncryptedRowMixin, Base):
    __tablename__ = "categories"
