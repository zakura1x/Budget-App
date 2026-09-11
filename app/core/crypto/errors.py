"""
Crypto errors.

Kept free of FastAPI so the crypto package can be imported by scripts and
tests without the web stack. app/core/exceptions.py maps these to responses.

None of these messages ever carries key material, plaintext, or the words of a
recovery phrase. They may reach a log line, and a log line is not a safe place.
"""

from typing import Optional, Sequence


class CryptoError(Exception):
    """Base class for everything the crypto layer raises."""


class DecryptionError(CryptoError):
    """
    A ciphertext failed to authenticate or could not be parsed.

    Deliberately vague. Wrong key, wrong row, tampered byte and truncated blob
    all look the same from outside, because telling them apart is an oracle.
    `table` and `row_id` are for the server log only - exceptions.py never
    puts them in a response.
    """

    def __init__(self, table: Optional[str] = None, row_id: Optional[int] = None):
        self.table = table
        self.row_id = row_id
        where = f" ({table} row {row_id})" if table is not None else ""
        super().__init__(f"Decryption failed{where}")


class KeyNotAvailableError(CryptoError):
    """A ciphertext names a master-key version this process does not hold."""

    def __init__(self, version: int):
        self.version = version
        super().__init__(
            f"Master key version {version} is not loaded. If a rotation is in "
            f"progress, add it to BUDGET_RETIRED_KEYS"
        )


class InvalidRecoveryPhraseError(CryptoError):
    """
    The phrase is malformed: wrong word count, unknown words, or bad checksum.

    Raised BEFORE any unwrap is attempted, so a typo gets a clear message
    instead of looking like the wrong phrase. `positions` holds the 1-based
    positions of unrecognised words; the words themselves are never included.
    """

    def __init__(self, message: str, positions: Sequence[int] = ()):
        self.positions = tuple(positions)
        super().__init__(message)
