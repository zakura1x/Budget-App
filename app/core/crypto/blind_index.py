"""
The email blind index - the ONE deliberate exception to full-row encryption
(ARCHITECTURE.md section 5.4).

Login has to find a user row from an email address before any key has been
unwrapped, and a randomly-nonced ciphertext cannot be searched. So users carry
a deterministic HMAC of the normalised email, keyed by a pepper that lives
only in .env:

    email_bidx = HMAC-SHA256(BUDGET_BLIND_INDEX_PEPPER, normalise(email))

Without the pepper it is an opaque 64-character hash. With it, someone who can
guess your email can confirm which row is yours - which is why the pepper is
a secret, and why nothing else in the schema gets one of these.

Normalisation is fixed forever once the first account exists: changing it
changes every index, and every login stops finding its user.
"""

import hashlib
import hmac
import unicodedata
from functools import lru_cache

BIDX_HEX_LENGTH = 64


def normalize_email(email: str) -> str:
    """NFKC, trimmed, lower-cased. Nothing cleverer - no dot or plus folding."""
    return unicodedata.normalize("NFKC", email).strip().lower()


def compute(email: str, pepper: bytes) -> str:
    """The blind index for an email: 64 lowercase hex characters."""
    if not pepper:
        raise ValueError("blind index pepper is empty")
    return hmac.new(pepper, normalize_email(email).encode("utf-8"), hashlib.sha256).hexdigest()


def matches(email: str, stored_index: str, pepper: bytes) -> bool:
    """Constant-time comparison of an email against a stored index."""
    return hmac.compare_digest(compute(email, pepper), stored_index or "")


class BlindIndexer:
    """compute()/matches() bound to one pepper, so callers never hold it."""

    def __init__(self, pepper: bytes):
        if len(pepper) < 32:
            raise ValueError("blind index pepper must be at least 32 bytes")
        self._pepper = bytes(pepper)

    def email(self, email: str) -> str:
        return compute(email, self._pepper)

    def matches(self, email: str, stored_index: str) -> bool:
        return matches(email, stored_index, self._pepper)

    def __repr__(self) -> str:
        return "BlindIndexer(pepper=**********)"


@lru_cache(maxsize=1)
def get_blind_indexer() -> BlindIndexer:
    from app.core.config import settings

    return BlindIndexer(settings.blind_index_pepper_bytes)
