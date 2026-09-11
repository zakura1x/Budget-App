"""
app/core/crypto - NOTHING OUTSIDE THIS PACKAGE AND app/db/repositories/ EVER
SEES A CIPHERTEXT, AND NOTHING OUTSIDE THIS PACKAGE EVER SEES A RAW KEY.

    envelope.py      AES-256-GCM, the fmt|ver|nonce|ct|tag byte layout
    keyring.py       master key, retired keys, HKDF
    dek.py           per-user DEK generate / wrap / unwrap
    recovery.py      BIP-39 phrase -> second DEK wrap (SEC-14)
    blind_index.py   HMAC email lookup, the one exception
    user_cipher.py   one user's DEK, sealing and opening their rows
    session_keys.py  unlocked DEKs in memory, zeroed on lock
    self_test.py     proves the loaded key works, at startup

ARCHITECTURE.md section 5 is the design this implements.
"""

from app.core.crypto.blind_index import BlindIndexer, get_blind_indexer
from app.core.crypto.dek import generate_dek, unwrap_dek, wrap_dek, zero
from app.core.crypto.envelope import PLACEHOLDER, is_envelope
from app.core.crypto.errors import (
    CryptoError,
    DecryptionError,
    InvalidRecoveryPhraseError,
    KeyNotAvailableError,
)
from app.core.crypto.keyring import MasterKeyring, get_master_keyring
from app.core.crypto.recovery import (
    find_user_by_phrase,
    generate_phrase,
    unwrap_dek_with_phrase,
    validate_phrase,
    wrap_dek_for_recovery,
)
from app.core.crypto.session_keys import SessionKeyring, get_session_keyring
from app.core.crypto.user_cipher import UserCipher

__all__ = [
    "BlindIndexer",
    "CryptoError",
    "DecryptionError",
    "InvalidRecoveryPhraseError",
    "KeyNotAvailableError",
    "MasterKeyring",
    "PLACEHOLDER",
    "SessionKeyring",
    "UserCipher",
    "find_user_by_phrase",
    "generate_dek",
    "generate_phrase",
    "get_blind_indexer",
    "get_master_keyring",
    "get_session_keyring",
    "is_envelope",
    "unwrap_dek",
    "unwrap_dek_with_phrase",
    "validate_phrase",
    "wrap_dek",
    "wrap_dek_for_recovery",
    "zero",
]
