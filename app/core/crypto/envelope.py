"""
The ciphertext envelope - ARCHITECTURE.md section 5.3.

Every encrypted value in this system, whether a row payload or a wrapped DEK,
is one byte string laid out like this:

    +--------+-------------+-------------+------------------+----------+
    | fmt(1) | key_ver (1) | nonce (12)  | ciphertext (n)   | tag (16) |
    +--------+-------------+-------------+------------------+----------+

AESGCM.encrypt() returns ciphertext||tag, so the layout falls out naturally.

Two properties this module guarantees, and the tests hold it to:

  1. THERE IS NO NONCE PARAMETER. Every call draws 12 fresh bytes from the OS.
     Reusing a nonce under one key is the single mistake that breaks GCM
     catastrophically - it leaks the XOR of both plaintexts and the
     authentication key - so no caller is given the chance to make it.

  2. THE HEADER IS AUTHENTICATED. The two header bytes are prepended to the
     associated data, so flipping fmt or key_ver fails the tag exactly like
     flipping a ciphertext byte does.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.crypto.errors import DecryptionError

FORMAT_V1 = 0x01
HEADER_BYTES = 2
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
MIN_ENVELOPE_BYTES = HEADER_BYTES + NONCE_BYTES + TAG_BYTES

# Written into a payload column for the instant between INSERT and UPDATE in
# the two-step insert (section 5.3). Format byte 0x00 is not a format: nothing
# will ever decrypt it, and a row still holding it after commit is an orphan
# that verify_integrity.py reports.
PLACEHOLDER = b"\x00"

# The namespace every AAD string starts with. A CONSTANT, not the configured
# DB_SCHEMA: a restore into the scratch schema ZBDGT_VERIFY must produce the
# same AAD as the live schema, or verify mode could never decrypt anything.
AAD_NAMESPACE = "ZBDGT"


def row_aad(table: str, row_id: int, user_id: int, key_version: int) -> bytes:
    """
    Associated data binding a ciphertext to its own row.

    Without it, someone with write access could copy the ciphertext of a
    PHP 5.00 coffee over a PHP 50,000.00 rent payment. They could read neither,
    but the swap would decrypt happily. With the row id in the AAD, it fails.
    """
    return f"{AAD_NAMESPACE}.{table}:{row_id}:{user_id}:v{key_version}".encode("ascii")


def encrypt(key, plaintext: bytes, *, aad: bytes, key_version: int, aead: AESGCM = None) -> bytes:
    """
    Seal plaintext under key. Returns the full envelope.

    `aead` lets a caller that encrypts many rows under one key pass a prepared
    AESGCM object instead of rebuilding it per call. It is never a way to
    influence the nonce.
    """
    if not 0 <= key_version <= 255:
        raise ValueError("key_version must fit in one byte")
    header = bytes((FORMAT_V1, key_version))
    nonce = os.urandom(NONCE_BYTES)
    cipher = aead if aead is not None else AESGCM(key)
    return header + nonce + cipher.encrypt(nonce, plaintext, header + aad)


def decrypt(key, envelope: bytes, *, aad: bytes, aead: AESGCM = None) -> bytes:
    """
    Open an envelope. Raises DecryptionError on ANY failure - wrong key, wrong
    AAD, a flipped byte anywhere, truncation, an unknown format. Never returns
    garbage, and never says which of those it was.
    """
    if envelope is None or len(envelope) < MIN_ENVELOPE_BYTES or envelope[0] != FORMAT_V1:
        raise DecryptionError()
    header = bytes(envelope[:HEADER_BYTES])
    nonce = bytes(envelope[HEADER_BYTES:HEADER_BYTES + NONCE_BYTES])
    body = bytes(envelope[HEADER_BYTES + NONCE_BYTES:])
    cipher = aead if aead is not None else AESGCM(key)
    try:
        return cipher.decrypt(nonce, body, header + aad)
    except InvalidTag:
        raise DecryptionError() from None


def envelope_key_version(envelope: bytes) -> int:
    """
    The key_ver byte of an envelope. Unauthenticated until decrypt succeeds -
    use it to CHOOSE a key, never to trust anything.
    """
    if envelope is None or len(envelope) < MIN_ENVELOPE_BYTES or envelope[0] != FORMAT_V1:
        raise DecryptionError()
    return envelope[1]


def is_envelope(value) -> bool:
    """True for bytes shaped like a v1 envelope. Shape only; proves nothing."""
    return (
        isinstance(value, (bytes, bytearray, memoryview))
        and len(value) >= MIN_ENVELOPE_BYTES
        and value[0] == FORMAT_V1
    )
