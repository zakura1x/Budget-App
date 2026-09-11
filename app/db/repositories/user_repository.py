"""
users - lookups, and the one place a user row and its wrapped keys are made.

Creating a user is a two-step insert like any Shape B row: the wraps bind the
user id into their AAD (crypto/dek.py), and the id does not exist until the
INSERT has run.
"""

from typing import Iterable, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto.blind_index import BlindIndexer
from app.core.crypto.dek import unwrap_dek, wrap_dek
from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.provisioning import NewUserKeys
from app.core.crypto.recovery import wrap_dek_with_key
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
        """Insert a user with both DEK wraps and a sealed profile. The caller commits."""
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
        self.session.flush()  # the id now exists; every wrap below binds it

        user.dek_wrapped = wrap_dek(keys.dek, keyring, user.id)
        user.dek_wrapped_recovery = wrap_dek_with_key(keys.dek, keys.recovery_key, user.id)
        user.recovery_created_at = now
        cipher = UserCipher(user.id, keys.dek, keyring.current_version)
        user.profile_enc = cipher.seal("users", user.id, {"email": email, "display_name": display_name})
        self.session.flush()
        return user

    def unwrap_dek(self, user: User, keyring: MasterKeyring) -> bytearray:
        """The user's DEK via the master key. Zero it when done."""
        return unwrap_dek(user.dek_wrapped, keyring, user.id)

    def cipher_for(self, user: User, keyring: MasterKeyring) -> UserCipher:
        """A UserCipher for scripts that run without a session keyring."""
        from app.core.crypto.dek import zero

        dek = self.unwrap_dek(user, keyring)
        try:
            return UserCipher(user.id, dek, keyring.current_version)
        finally:
            zero(dek)

    def read_profile(self, user: User, cipher: UserCipher) -> dict:
        if user.profile_enc is None:
            return {}
        return cipher.open("users", user.id, user.profile_enc, user.key_version)

    def recovery_candidates(self) -> List[Tuple[int, Optional[bytes]]]:
        """(id, dek_wrapped_recovery) for every user - find_user_by_phrase() input."""
        rows: Iterable = self.session.execute(select(User.id, User.dek_wrapped_recovery).order_by(User.id))
        return [(row[0], row[1]) for row in rows]
