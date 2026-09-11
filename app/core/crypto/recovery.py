"""
The 12-word recovery phrase - SEC-14, ARCHITECTURE.md section 5.2.1.

A BIP-39 mnemonic (128 bits of entropy) wraps a SECOND copy of the user's DEK.
.env and the phrase are two independent ways into the same data: lose one and
the other still opens it; lose both and it is gone.

    phrase --> BIP-39 seed (PBKDF2-HMAC-SHA512, 2048 rounds)
           --> HKDF-SHA256, info="budget:recovery-wrap"
           --> 32-byte recovery key --> unwraps users.dek_wrapped_recovery

This has to exist before the first row is written. A row encrypted under a DEK
that was never wrapped under a phrase can only ever be reached through .env.

Finding the user without .env
-----------------------------
Total .env loss takes the blind-index pepper with it, so an email address can
no longer find its user row. The phrase finds it instead: find_user_by_phrase()
tries the derived key against each user's recovery wrap, and exactly one
authenticates. The expensive step (PBKDF2) runs once; each attempt after it is
one AES-GCM open of 62 bytes, so even MAX_USERS in the hundreds costs
milliseconds.
"""

import re
import unicodedata
from typing import Iterable, Optional, Tuple

from mnemonic import Mnemonic

from app.core.crypto.dek import RECOVERY_KEY_VERSION, dek_recovery_aad, zero
from app.core.crypto.envelope import KEY_BYTES, decrypt, encrypt, envelope_key_version
from app.core.crypto.errors import DecryptionError, InvalidRecoveryPhraseError
from app.core.crypto.keyring import hkdf_sha256

RECOVERY_WRAP_INFO = "budget:recovery-wrap"

# BIP-39: 32 bits of entropy per 3 words. 12 words = 128 bits.
_ENTROPY_BITS = {12: 128, 15: 160, 18: 192, 21: 224, 24: 256}

_mnemonics: dict = {}


def _mnemonic(language: str) -> Mnemonic:
    if language not in _mnemonics:
        _mnemonics[language] = Mnemonic(language)
    return _mnemonics[language]


def generate_phrase(words: int = 12, language: str = "english") -> str:
    """A fresh phrase from the OS CSPRNG, words separated by single spaces."""
    if words not in _ENTROPY_BITS:
        raise ValueError(f"a phrase has one of {tuple(_ENTROPY_BITS)} words")
    return _mnemonic(language).generate(strength=_ENTROPY_BITS[words])


def normalize_phrase(text: str, language: str = "english") -> str:
    """
    Make every reasonable way of typing the phrase produce the same string.

    NFKD (the BIP-39 form), lower case, whitespace collapsed. For the English
    list - whose words are plain a-z - accents are stripped and anything that
    is not a letter is treated as a separator, so "1. Abandon, 2. ability" and
    "abandon ability" normalise identically.
    """
    text = unicodedata.normalize("NFKD", text or "").lower()
    if language == "english":
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z]+", " ", text)
    return " ".join(text.split())


def validate_phrase(text: str, language: str = "english") -> str:
    """
    Normalise and check a phrase. Returns the normalised phrase.

    Raises InvalidRecoveryPhraseError - naming positions, never words - for a
    wrong word count, words not in the list, or a failed checksum. This is
    what makes a typo fail fast and clearly instead of looking like a wrong
    phrase after an unwrap attempt.
    """
    phrase = normalize_phrase(text, language)
    words = phrase.split()
    if len(words) not in _ENTROPY_BITS:
        raise InvalidRecoveryPhraseError(
            f"A recovery phrase has 12 words; this has {len(words)}"
            if len(words) < 12
            else f"A recovery phrase has 12 to 24 words; this has {len(words)}"
        )
    wordlist = set(_mnemonic(language).wordlist)
    unknown = [i for i, word in enumerate(words, start=1) if word not in wordlist]
    if unknown:
        listed = ", ".join(str(p) for p in unknown)
        noun = "Word" if len(unknown) == 1 else "Words"
        verb = "is" if len(unknown) == 1 else "are"
        raise InvalidRecoveryPhraseError(
            f"{noun} {listed} {verb} not in the recovery word list - check the spelling",
            positions=unknown,
        )
    if not _mnemonic(language).check(phrase):
        raise InvalidRecoveryPhraseError(
            "Every word is valid but the phrase does not check out - one word is "
            "probably wrong or out of order"
        )
    return phrase


def derive_recovery_key(text: str, language: str = "english") -> bytes:
    """phrase -> BIP-39 seed -> HKDF -> 32-byte recovery key. Validates first."""
    phrase = validate_phrase(text, language)
    seed = Mnemonic.to_seed(phrase, passphrase="")
    return hkdf_sha256(seed, RECOVERY_WRAP_INFO, KEY_BYTES)


def wrap_dek_with_key(dek: bytearray, recovery_key: bytes, user_id: int) -> bytes:
    """Wrap a DEK under an already-derived recovery key."""
    if len(dek) != KEY_BYTES:
        raise ValueError(f"a DEK is {KEY_BYTES} bytes")
    return encrypt(
        recovery_key, bytes(dek), aad=dek_recovery_aad(user_id), key_version=RECOVERY_KEY_VERSION
    )


def wrap_dek_for_recovery(dek: bytearray, phrase: str, user_id: int, language: str = "english") -> bytes:
    """The value for users.dek_wrapped_recovery."""
    return wrap_dek_with_key(dek, derive_recovery_key(phrase, language), user_id)


def unwrap_dek_with_key(wrapped: bytes, recovery_key: bytes, user_id: int) -> bytearray:
    if envelope_key_version(wrapped) != RECOVERY_KEY_VERSION:
        raise DecryptionError("users", user_id)
    try:
        dek = bytearray(decrypt(recovery_key, wrapped, aad=dek_recovery_aad(user_id)))
    except DecryptionError:
        raise DecryptionError("users", user_id) from None
    if len(dek) != KEY_BYTES:
        zero(dek)
        raise DecryptionError("users", user_id)
    return dek


def unwrap_dek_with_phrase(wrapped: bytes, phrase: str, user_id: int, language: str = "english") -> bytearray:
    """
    Unwrap users.dek_wrapped_recovery. A malformed phrase raises
    InvalidRecoveryPhraseError; a valid phrase that is not THIS user's raises
    DecryptionError. Never returns garbage.
    """
    return unwrap_dek_with_key(wrapped, derive_recovery_key(phrase, language), user_id)


def find_user_by_phrase(
    phrase: str,
    candidates: Iterable[Tuple[int, Optional[bytes]]],
    language: str = "english",
) -> Optional[Tuple[int, bytearray]]:
    """
    Which user does this phrase belong to? Returns (user_id, dek) or None.

    `candidates` is (user_id, dek_wrapped_recovery) for every user. Works with
    no .env at all - this is the path that survives total key loss. Every
    candidate is tried even after a match, so the time taken does not reveal
    where in the table the match sat; with a CSPRNG-generated 128-bit phrase a
    second match cannot happen.
    """
    recovery_key = derive_recovery_key(phrase, language)
    found: Optional[Tuple[int, bytearray]] = None
    for user_id, wrapped in candidates:
        if not wrapped:
            continue
        try:
            dek = unwrap_dek_with_key(wrapped, recovery_key, user_id)
        except DecryptionError:
            continue
        if found is None:
            found = (user_id, dek)
        else:
            zero(dek)
    return found
