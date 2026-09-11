"""
Key material for a brand-new user: a DEK and a recovery phrase, created
together because a DEK must never exist without its second wrap (SEC-14).

The recovery key is derived once here (PBKDF2, the slow step) and reused for
the wrap, which can only happen after the user row has an id.
"""

from dataclasses import dataclass, field

from app.core.crypto.dek import generate_dek, zero
from app.core.crypto.recovery import derive_recovery_key, generate_phrase


@dataclass
class NewUserKeys:
    """Short-lived. Call wipe() as soon as the user row is written."""

    phrase: str = field(repr=False)
    dek: bytearray = field(repr=False)
    recovery_key: bytes = field(repr=False)

    def wipe(self) -> None:
        zero(self.dek)
        self.recovery_key = b""
        # The phrase is a str and cannot be zeroed; dropping the reference is
        # all Python allows. It has to reach the user's screen once regardless.
        self.phrase = ""

    def __repr__(self) -> str:
        return "NewUserKeys(**********)"


def provision_user_keys(words: int = 12, language: str = "english") -> NewUserKeys:
    phrase = generate_phrase(words, language)
    return NewUserKeys(phrase=phrase, dek=generate_dek(), recovery_key=derive_recovery_key(phrase, language))
