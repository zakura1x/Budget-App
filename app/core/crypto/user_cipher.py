"""
UserCipher - one user's DEK, able to seal and open that user's rows, and
unable to give the key back.

This is the object repositories are handed. It holds a prepared AES-GCM
context, never the key bytes, and it knows its own user_id - so a repository
built on it filters by that id and binds it into every AAD without being told
to. A service passes it along without ever seeing a key.

Payloads are JSON objects, serialised with orjson. Decimal is written as its
string form ("3500.00"), never as a float: money never passes through a binary
float anywhere in this system, including on the way into a ciphertext.
"""

from decimal import Decimal
from typing import Any, Mapping

import orjson
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.crypto.envelope import KEY_BYTES, decrypt, encrypt, row_aad
from app.core.crypto.errors import DecryptionError


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("non-finite Decimal in a payload")
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not serialisable into a payload")


def _reject_floats(value: Any, path: str = "payload") -> None:
    """
    orjson writes a float without consulting `default`, so the Decimal rule
    above cannot catch one. This walk does: a float anywhere in a payload is
    refused at the point of sealing, before it can become a stored balance.
    """
    if isinstance(value, float):
        raise TypeError(f"float at {path} - money is Decimal, never float")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for i, item in enumerate(value):
            _reject_floats(item, f"{path}[{i}]")


def dumps_payload(data: Mapping[str, Any]) -> bytes:
    if not isinstance(data, Mapping):
        raise TypeError("a payload is a JSON object")
    _reject_floats(data)
    return orjson.dumps(dict(data), default=_json_default)


def loads_payload(raw: bytes) -> dict:
    data = orjson.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("a payload is a JSON object")
    return data


class UserCipher:
    """Seals and opens one user's rows. Holds no retrievable key."""

    __slots__ = ("_user_id", "_key_version", "_aead")

    def __init__(self, user_id: int, dek: bytearray, key_version: int):
        if len(dek) != KEY_BYTES:
            raise ValueError(f"a DEK is {KEY_BYTES} bytes")
        if not 1 <= key_version <= 255:
            raise ValueError("key_version must be 1-255")
        self._user_id = int(user_id)
        self._key_version = key_version
        self._aead = AESGCM(dek)

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def key_version(self) -> int:
        """Stamped on every row this cipher writes (Shape B key_version)."""
        return self._key_version

    def seal(self, table: str, row_id: int, data: Mapping[str, Any]) -> bytes:
        """Encrypt a payload for (table, row_id) owned by this user."""
        return self.seal_bytes(table, row_id, dumps_payload(data))

    def open(self, table: str, row_id: int, envelope: bytes, key_version: int) -> dict:
        """
        Decrypt a payload. `key_version` is the row's STORED key_version column,
        which rebuilds the AAD the row was written with. Raises DecryptionError
        naming the table and row, for the server log.
        """
        raw = self.open_bytes(table, row_id, envelope, key_version)
        try:
            return loads_payload(raw)
        except (ValueError, orjson.JSONDecodeError):
            # Authenticated but not a JSON object: written by something that
            # was not this code. Treat it like any other bad row.
            raise DecryptionError(table, row_id) from None

    def seal_bytes(self, table: str, row_id: int, plaintext: bytes) -> bytes:
        aad = row_aad(table, row_id, self._user_id, self._key_version)
        return encrypt(None, plaintext, aad=aad, key_version=self._key_version, aead=self._aead)

    def open_bytes(self, table: str, row_id: int, envelope: bytes, key_version: int) -> bytes:
        aad = row_aad(table, row_id, self._user_id, key_version)
        try:
            return decrypt(None, envelope, aad=aad, aead=self._aead)
        except DecryptionError:
            raise DecryptionError(table, row_id) from None

    def __repr__(self) -> str:
        return f"UserCipher(user_id={self._user_id}, key_version={self._key_version})"
