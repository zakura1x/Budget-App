"""
categories - Shape B (CAT-01..CAT-08).

`parent_id` lives inside the ciphertext, so SQL cannot enforce that a parent
exists, that it is not itself a child, or that deleting one does not orphan
its children. category_service owns all three.
"""

from app.db.models import Category
from app.db.repositories.encrypted_repository import EncryptedRepository


class CategoryRepository(EncryptedRepository):
    model = Category
