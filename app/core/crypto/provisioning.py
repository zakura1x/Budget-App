"""
Key material for a brand-new user: one DEK, wrapped under the master key.

There is no second wrap (ARCHITECTURE.md 5.2.1): losing .env is answered by the
server owner's offline copy of it, not by a phrase each user keeps.
"""

from dataclasses import dataclass, field

from app.core.crypto.dek import generate_dek, zero


@dataclass
class NewUserKeys:
    """Short-lived. Call wipe() as soon as the user row is written."""

    dek: bytearray = field(repr=False)

    def wipe(self) -> None:
        zero(self.dek)

    def __repr__(self) -> str:
        return "NewUserKeys(**********)"


def provision_user_keys() -> NewUserKeys:
    return NewUserKeys(dek=generate_dek())
