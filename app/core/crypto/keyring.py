"""
The master keyring - BUDGET_MASTER_KEY, its retired predecessors, and HKDF.

The master key never encrypts a row. It is the input to HKDF, which derives a
wrapping key per key version, and the wrapping key wraps each user's DEK
(ARCHITECTURE.md section 5.2). Rotating the master key therefore rewraps one
row per user instead of re-encrypting everything.

Retired keys are held so a rotation can be resumed: a DEK still wrapped under
version 1 stays readable while version 2 is current, until rotate_keys.py has
moved every one of them.
"""

from functools import lru_cache
from typing import Dict, Iterable, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.crypto.envelope import KEY_BYTES
from app.core.crypto.errors import KeyNotAvailableError


def hkdf_sha256(key_material: bytes, info: str, length: int = KEY_BYTES) -> bytes:
    """
    HKDF-SHA256 with no salt. The inputs here are uniformly random keys (or a
    BIP-39 seed), which is the case HKDF's extract step does not need a salt
    for. The info string is the domain separation.
    """
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=None, info=info.encode("ascii")
    ).derive(bytes(key_material))


def wrap_info(version: int) -> str:
    """HKDF info for the DEK-wrapping key of one master-key version."""
    return f"budget:dek-wrap:v{version}"


class MasterKeyring:
    """
    Every master key this process can use, by version.

    Holds raw key bytes, so nothing outside app/core/crypto/ gets one of these
    - see get_master_keyring(). The repr never shows a key.
    """

    def __init__(
        self,
        current_version: int,
        current_key: bytes,
        retired: Optional[Dict[int, bytes]] = None,
    ):
        if not 1 <= current_version <= 255:
            raise ValueError("master key version must be 1-255")
        keys = {current_version: bytes(current_key)}
        for version, key in (retired or {}).items():
            if version == current_version:
                raise ValueError("a retired key cannot share the current version")
            keys[version] = bytes(key)
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"master key version {version} is not {KEY_BYTES} bytes")
        self._current_version = current_version
        self._keys = keys
        self._wrapping_keys: Dict[int, bytes] = {}

    @classmethod
    def from_settings(cls, settings) -> "MasterKeyring":
        return cls(
            current_version=settings.BUDGET_KEY_VERSION,
            current_key=settings.master_key_bytes,
            retired=settings.retired_master_keys,
        )

    @property
    def current_version(self) -> int:
        return self._current_version

    @property
    def versions(self) -> Iterable[int]:
        return sorted(self._keys)

    def has_version(self, version: int) -> bool:
        return version in self._keys

    def wrapping_key(self, version: Optional[int] = None) -> bytes:
        """The DEK-wrapping key for a version (default: current)."""
        version = self._current_version if version is None else version
        if version not in self._keys:
            raise KeyNotAvailableError(version)
        cached = self._wrapping_keys.get(version)
        if cached is None:
            cached = hkdf_sha256(self._keys[version], wrap_info(version))
            self._wrapping_keys[version] = cached
        return cached

    def __repr__(self) -> str:
        return f"MasterKeyring(current_version={self._current_version}, versions={list(self.versions)})"


@lru_cache(maxsize=1)
def get_master_keyring() -> MasterKeyring:
    """The process-wide keyring, built from settings on first use."""
    from app.core.config import settings

    return MasterKeyring.from_settings(settings)
