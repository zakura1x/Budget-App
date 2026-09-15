"""
Per-user Data Encryption Keys - generate, wrap, unwrap.

Each user has one 32-byte DEK. It encrypts every row they own, and it is
stored only wrapped, in users.dek_wrapped, under the master key.

The wrap uses the standard envelope and binds the user id into the AAD. That
stops a DBA copying one user's wrapped key onto another user's row: it fails to
unwrap rather than handing Bob's login Alice's key.

A plaintext DEK is a bytearray, never bytes, so it can be zeroed in place when
a session locks (session_keys.py). Python cannot promise no copy survives
elsewhere in memory - AESGCM keeps its own inside OpenSSL - so zeroing is
hygiene, not a guarantee. ARCHITECTURE.md 5.1 is honest that someone who can
read this process's memory is out of scope.
"""

import os

from app.core.crypto.envelope import (
    AAD_NAMESPACE,
    KEY_BYTES,
    decrypt,
    encrypt,
    envelope_key_version,
)
from app.core.crypto.errors import DecryptionError
from app.core.crypto.keyring import MasterKeyring

# Never a master key version (config.py enforces 1-255). The removed
# recovery-phrase wrap used it, and backups made before 2026-09-14 still carry
# one: it must never be taken for a master wrap.
RESERVED_KEY_VERSION = 0


def generate_dek() -> bytearray:
    """32 bytes from the OS CSPRNG, as a zeroable buffer."""
    return bytearray(os.urandom(KEY_BYTES))


def zero(buffer: bytearray) -> None:
    """Overwrite a key buffer in place. Best effort - see the module docstring."""
    for i in range(len(buffer)):
        buffer[i] = 0


def dek_wrap_aad(user_id: int) -> bytes:
    return f"{AAD_NAMESPACE}.users:{user_id}:dek-wrap".encode("ascii")


def wrap_dek(dek: bytearray, keyring: MasterKeyring, user_id: int) -> bytes:
    """Wrap a DEK under the CURRENT master key version."""
    _check_dek(dek)
    version = keyring.current_version
    return encrypt(
        keyring.wrapping_key(version), bytes(dek), aad=dek_wrap_aad(user_id), key_version=version
    )


def unwrap_dek(wrapped: bytes, keyring: MasterKeyring, user_id: int) -> bytearray:
    """
    Unwrap a DEK wrapped under ANY loaded master-key version - the envelope's
    key_ver byte says which. Raises KeyNotAvailableError if that version is not
    loaded, DecryptionError if it is loaded and the unwrap fails.
    """
    version = envelope_key_version(wrapped)
    if version == RESERVED_KEY_VERSION:
        # An old recovery wrap presented as a master wrap: never valid here.
        raise DecryptionError("users", user_id)
    try:
        dek = bytearray(decrypt(keyring.wrapping_key(version), wrapped, aad=dek_wrap_aad(user_id)))
    except DecryptionError:
        raise DecryptionError("users", user_id) from None
    _check_dek(dek)
    return dek


def rewrap_dek(wrapped: bytes, keyring: MasterKeyring, user_id: int) -> bytes:
    """Master-key rotation for one user: unwrap under its version, wrap under current."""
    dek = unwrap_dek(wrapped, keyring, user_id)
    try:
        return wrap_dek(dek, keyring, user_id)
    finally:
        zero(dek)


def wrapped_key_version(wrapped: bytes) -> int:
    """Which master-key version wrapped this DEK."""
    return envelope_key_version(wrapped)


def _check_dek(dek) -> None:
    if len(dek) != KEY_BYTES:
        raise ValueError(f"a DEK is {KEY_BYTES} bytes")
