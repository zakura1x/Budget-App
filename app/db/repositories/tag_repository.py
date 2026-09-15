"""
tags - Shape B (TXN-10). Payload: name, colour.

A transaction names its tags by id inside ITS ciphertext (`tag_ids`), so SQL
cannot stop a tag being deleted out from under one. tag_service walks the
transactions on delete instead - the same rule category deletion keeps.
"""

from app.db.models import Tag
from app.db.repositories.encrypted_repository import EncryptedRepository


class TagRepository(EncryptedRepository):
    model = Tag
