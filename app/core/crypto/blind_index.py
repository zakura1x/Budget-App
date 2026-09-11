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
from typing import Optional

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
        # A separate subkey for IP addresses, so an IP hash and an email index
        # can never be compared with each other.
        from app.core.crypto.keyring import hkdf_sha256

        self._ip_key = hkdf_sha256(self._pepper, "budget:ip-hash")

    def email(self, email: str) -> str:
        return compute(email, self._pepper)

    def ip(self, address: str) -> str:
        """
        Keyed hash of a client IP for login_attempts and audit_log. Keyed,
        because an unkeyed hash of an IPv4 address is reversed by trying all
        four billion of them.
        """
        return hmac.new(self._ip_key, (address or "").strip().encode("utf-8"), hashlib.sha256).hexdigest()

    def matches(self, email: str, stored_index: str) -> bool:
        return matches(email, stored_index, self._pepper)

    def __repr__(self) -> str:
        return "BlindIndexer(pepper=**********)"


_process_indexer: Optional[BlindIndexer] = None


def get_blind_indexer() -> BlindIndexer:
    global _process_indexer
    if _process_indexer is None:
        from app.core.config import settings

        _process_indexer = BlindIndexer(settings.blind_index_pepper_bytes)
    return _process_indexer


def set_blind_indexer(indexer: Optional[BlindIndexer]) -> None:
    """Replace the process indexer - tests simulating a new .env."""
    global _process_indexer
    _process_indexer = indexer
