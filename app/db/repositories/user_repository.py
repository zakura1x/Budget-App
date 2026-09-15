"""
users - lookups, and the one place a user row and its wrapped key are made.

Creating a user is a two-step insert like any Shape B row: the wrap binds the
user id into its AAD (crypto/dek.py), and the id does not exist until the
INSERT has run.
"""

from typing import Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto.blind_index import BlindIndexer
from app.core.crypto.dek import rewrap_dek, unwrap_dek, wrap_dek, wrapped_key_version, zero
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.provisioning import NewUserKeys
from app.core.crypto.user_cipher import UserCipher
from app.db.models import User
from app.db.types import utcnow


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def count(self, active_only: bool = False) -> int:
        query = select(func.count()).select_from(User)
        if active_only:
            query = query.where(User.is_active == True)  # noqa: E712
        return self.session.execute(query).scalar_one()

    def get(self, user_id: int) -> Optional[User]:
        return self.session.get(User, user_id)

    def get_by_email_bidx(self, email_bidx: str) -> Optional[User]:
        return self.session.execute(select(User).where(User.email_bidx == email_bidx)).scalar_one_or_none()

    def create(
        self,
        *,
        email: str,
        password_hash: str,
        is_admin: bool,
        keys: NewUserKeys,
        keyring: MasterKeyring,
        indexer: BlindIndexer,
        display_name: Optional[str] = None,
    ) -> User:
        """Insert a user with its wrapped DEK and a sealed profile. The caller commits."""
        now = utcnow()
        user = User(
            email_bidx=indexer.email(email),
            password_hash=password_hash,
            key_version=keyring.current_version,
            dek_wrapped=PLACEHOLDER,
            is_admin=is_admin,
            is_active=True,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(user)
        self.session.flush()  # the id now exists; the wrap below binds it

        user.dek_wrapped = wrap_dek(keys.dek, keyring, user.id)
        cipher = UserCipher(user.id, keys.dek, keyring.current_version)
        user.profile_enc = cipher.seal("users", user.id, {"email": email, "display_name": display_name})
        self.session.flush()
        return user

    def unwrap_dek(self, user: User, keyring: MasterKeyring) -> bytearray:
        """The user's DEK via the master key. Zero it when done."""
        return unwrap_dek(user.dek_wrapped, keyring, user.id)

    def wrap_versions(self) -> Dict[int, int]:
        """How many accounts have their DEK wrapped under each master-key version."""
        counts: Dict[int, int] = {}
        for (wrapped,) in self.session.execute(select(User.dek_wrapped)):
            version = wrapped_key_version(bytes(wrapped))
            counts[version] = counts.get(version, 0) + 1
        return dict(sorted(counts.items()))

    def rewrap_dek(self, user: User, keyring: MasterKeyring) -> bool:
        """
        Master-key rotation for one account (scripts/rotate_keys.py): the SAME
        DEK, re-wrapped under the current version. False if it already is.

        users.key_version is left alone: it names the version profile_enc was
        sealed under (part of its AAD), not the version of the wrap. The new
        wrap is opened before it replaces the old one. The caller commits.
        """
        if wrapped_key_version(bytes(user.dek_wrapped)) == keyring.current_version:
            return False
        rewrapped = rewrap_dek(bytes(user.dek_wrapped), keyring, user.id)
        zero(unwrap_dek(rewrapped, keyring, user.id))
        user.dek_wrapped = rewrapped
        self.session.flush()
        return True

    def cipher_for(self, user: User, keyring: MasterKeyring) -> UserCipher:
        """A UserCipher for scripts that run without a session keyring."""
        dek = self.unwrap_dek(user, keyring)
        try:
            return UserCipher(user.id, dek, keyring.current_version)
        finally:
            zero(dek)

    def read_profile(self, user: User, cipher: UserCipher) -> dict:
        if user.profile_enc is None:
            return {}
        return cipher.open("users", user.id, user.profile_enc, user.key_version)
