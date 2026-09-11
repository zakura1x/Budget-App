"""
user_preferences - one encrypted row per user.
"""

from typing import Optional

from app.db.models import UserPreference
from app.db.repositories.encrypted_repository import EncryptedRepository, Record


class PreferencesRepository(EncryptedRepository):
    model = UserPreference

    def current(self) -> Optional[Record]:
        rows = self.list()
        return rows[0] if rows else None
