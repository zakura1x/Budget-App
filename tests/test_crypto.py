"""
The crypto core - Phase 1 exit criteria. NEVER SKIPPED.

Everything else in the app writes through this layer. If a test here fails,
nothing built on top of it can be trusted, however green the rest looks.
"""

import inspect
import os
import random
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings as hsettings, strategies as st

from app.core.crypto import envelope
from app.core.crypto.dek import (
    RESERVED_KEY_VERSION,
    generate_dek,
    rewrap_dek,
    unwrap_dek,
    wrap_dek,
    wrapped_key_version,
    zero,
)
from app.core.crypto.envelope import (
    FORMAT_V1,
    HEADER_BYTES,
    MIN_ENVELOPE_BYTES,
    NONCE_BYTES,
    TAG_BYTES,
    decrypt,
    encrypt,
    envelope_key_version,
    row_aad,
)
from app.core.crypto.errors import DecryptionError, KeyNotAvailableError
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.user_cipher import UserCipher, dumps_payload

pytestmark = pytest.mark.security

KEY = os.urandom(32)
AAD = row_aad("transactions", 42, 7, 1)


def seal(plaintext: bytes, aad: bytes = AAD, key: bytes = KEY, version: int = 1) -> bytes:
    return encrypt(key, plaintext, aad=aad, key_version=version)


# ============================================================ round trips


def test_round_trip_10k_random_cases():
    rng = random.Random(20260914)
    for _ in range(10_000):
        size = rng.choice((0, 1, rng.randint(2, 64), rng.randint(65, 512), rng.randint(513, 4096)))
        plaintext = os.urandom(size)
        aad = row_aad(rng.choice(("transactions", "accounts")), rng.randint(1, 10**9), rng.randint(1, 50), 1)
        assert decrypt(KEY, seal(plaintext, aad), aad=aad) == plaintext


@hsettings(max_examples=400, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(plaintext=st.binary(min_size=0, max_size=65_536), row_id=st.integers(1, 2**62), user_id=st.integers(1, 2**31 - 1))
def test_round_trip_property(plaintext, row_id, user_id):
    aad = row_aad("transactions", row_id, user_id, 1)
    assert decrypt(KEY, seal(plaintext, aad), aad=aad) == plaintext


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 255, 256, 65_535, 1024 * 1024])
def test_round_trip_edge_sizes_including_empty_and_1mb(size):
    plaintext = os.urandom(size)
    blob = seal(plaintext)
    assert len(blob) == HEADER_BYTES + NONCE_BYTES + size + TAG_BYTES
    assert decrypt(KEY, blob, aad=AAD) == plaintext


def test_envelope_layout_matches_the_documented_bytes():
    blob = seal(b"x", version=7)
    assert blob[0] == FORMAT_V1
    assert blob[1] == 7
    assert envelope_key_version(blob) == 7
    assert len(blob) == MIN_ENVELOPE_BYTES + 1


# ================================================================= nonces


def test_there_is_no_nonce_parameter_anywhere():
    for fn in (envelope.encrypt, envelope.decrypt, UserCipher.seal, UserCipher.seal_bytes):
        assert "nonce" not in inspect.signature(fn).parameters, fn.__qualname__


@pytest.mark.slow
def test_one_million_encryptions_zero_nonce_collisions():
    seen = set()
    plaintext = b"same plaintext every time"
    for _ in range(1_000_000):
        blob = seal(plaintext)
        seen.add(blob[HEADER_BYTES:HEADER_BYTES + NONCE_BYTES])
    assert len(seen) == 1_000_000


def test_same_plaintext_never_produces_the_same_ciphertext():
    assert seal(b"coffee 150.00") != seal(b"coffee 150.00")


# ======================================================= failures raise


def test_wrong_key_raises_never_returns_garbage():
    blob = seal(b"rent")
    with pytest.raises(DecryptionError):
        decrypt(os.urandom(32), blob, aad=AAD)


@pytest.mark.parametrize(
    "other_aad",
    [
        row_aad("transactions", 43, 7, 1),  # another row: the coffee-over-rent swap
        row_aad("transactions", 42, 8, 1),  # another user
        row_aad("accounts", 42, 7, 1),  # another table
        row_aad("transactions", 42, 7, 2),  # another key version
        b"",
    ],
)
def test_wrong_aad_raises_proving_row_swap_protection(other_aad):
    blob = seal(b"PHP 50,000.00 rent")
    with pytest.raises(DecryptionError):
        decrypt(KEY, blob, aad=other_aad)


def test_every_flipped_byte_raises_header_nonce_ciphertext_and_tag():
    blob = seal(b"a short payload")
    for position in range(len(blob)):
        tampered = bytearray(blob)
        tampered[position] ^= 0x01
        with pytest.raises(DecryptionError):
            decrypt(KEY, bytes(tampered), aad=AAD)


def test_flipped_tag_byte_raises():
    blob = bytearray(seal(b"x" * 200))
    blob[-1] ^= 0x80
    with pytest.raises(DecryptionError):
        decrypt(KEY, bytes(blob), aad=AAD)


def test_header_is_authenticated():
    # Rewriting key_ver in a stored row must not be a way to steer decryption.
    blob = bytearray(seal(b"x"))
    blob[1] = 2
    with pytest.raises(DecryptionError):
        decrypt(KEY, bytes(blob), aad=AAD)


@pytest.mark.parametrize("blob", [b"", b"\x00", b"\x01", b"\x01\x01" + b"\x00" * 27, b"\x02" + b"\x00" * 40, None])
def test_malformed_envelopes_raise(blob):
    with pytest.raises(DecryptionError):
        decrypt(KEY, blob, aad=AAD)


def test_truncation_raises():
    blob = seal(b"x" * 100)
    for cut in (1, 16, 50):
        with pytest.raises(DecryptionError):
            decrypt(KEY, blob[:-cut], aad=AAD)


def test_decryption_error_message_carries_no_detail():
    blob = seal(b"secret amount 18500.00")
    with pytest.raises(DecryptionError) as info:
        decrypt(os.urandom(32), blob, aad=AAD)
    assert "18500" not in str(info.value)
    assert "tag" not in str(info.value).lower()


# ==================================================================== DEK


def test_dek_wrap_unwrap_round_trips_under_the_master_key(keyring):
    dek = generate_dek()
    wrapped = wrap_dek(dek, keyring, user_id=3)
    assert wrapped_key_version(wrapped) == 1
    assert unwrap_dek(wrapped, keyring, user_id=3) == dek


def test_dek_is_zeroable_bytearray():
    dek = generate_dek()
    assert isinstance(dek, bytearray) and len(dek) == 32
    zero(dek)
    assert dek == bytearray(32)


def test_dek_wrap_is_bound_to_the_user(keyring):
    wrapped = wrap_dek(generate_dek(), keyring, user_id=1)
    with pytest.raises(DecryptionError):
        unwrap_dek(wrapped, keyring, user_id=2)


def test_dek_unwrap_with_a_different_master_key_raises(keyring):
    wrapped = wrap_dek(generate_dek(), keyring, user_id=1)
    stranger = MasterKeyring(1, os.urandom(32))
    with pytest.raises(DecryptionError):
        unwrap_dek(wrapped, stranger, user_id=1)


def test_retired_key_still_unwraps_and_rewrap_moves_to_current():
    old_key, new_key = os.urandom(32), os.urandom(32)
    v1 = MasterKeyring(1, old_key)
    dek = generate_dek()
    wrapped_v1 = wrap_dek(dek, v1, user_id=5)

    rotated = MasterKeyring(2, new_key, retired={1: old_key})
    assert unwrap_dek(wrapped_v1, rotated, user_id=5) == dek
    wrapped_v2 = rewrap_dek(wrapped_v1, rotated, user_id=5)
    assert wrapped_key_version(wrapped_v2) == 2

    only_new = MasterKeyring(2, new_key)
    assert unwrap_dek(wrapped_v2, only_new, user_id=5) == dek
    with pytest.raises(KeyNotAvailableError):
        unwrap_dek(wrapped_v1, only_new, user_id=5)


def test_wrapping_keys_differ_per_version_even_for_the_same_master_key():
    key = os.urandom(32)
    assert MasterKeyring(1, key).wrapping_key() != MasterKeyring(2, key).wrapping_key()


def test_keyring_repr_never_shows_a_key(keyring):
    text = repr(keyring)
    assert "current_version=1" in text
    assert keyring.wrapping_key().hex() not in text


def test_an_old_recovery_wrap_is_never_accepted_as_a_master_wrap(keyring):
    # key_ver 0 is reserved (old backups carry recovery wraps under it); unwrap_dek refuses it outright.
    fake = bytes((FORMAT_V1, RESERVED_KEY_VERSION)) + os.urandom(12 + 32 + 16)
    with pytest.raises(DecryptionError):
        unwrap_dek(fake, keyring, user_id=1)


# ============================================================ UserCipher


def test_user_cipher_round_trips_a_payload_with_decimals():
    cipher = UserCipher(7, generate_dek(), 1)
    payload = {
        "txn_date": "2026-09-08",
        "amount": Decimal("3500.00"),
        "splits": [{"category_id": 11, "amount": Decimal("2800.00")}, {"category_id": 19, "amount": Decimal("700.00")}],
    }
    blob = cipher.seal("transactions", 42, payload)
    opened = cipher.open("transactions", 42, blob, 1)
    assert opened["amount"] == "3500.00"
    assert [s["amount"] for s in opened["splits"]] == ["2800.00", "700.00"]


def test_user_cipher_refuses_floats_anywhere_in_a_payload():
    cipher = UserCipher(7, generate_dek(), 1)
    with pytest.raises(TypeError, match="float"):
        cipher.seal("transactions", 1, {"splits": [{"amount": 700.0}]})


def test_user_cipher_refuses_non_objects_and_non_finite_decimals():
    with pytest.raises(TypeError):
        dumps_payload(["not", "an", "object"])
    with pytest.raises(TypeError):
        dumps_payload({"amount": Decimal("NaN")})


def test_user_cipher_binds_its_user_id():
    dek = generate_dek()
    alice, bob = UserCipher(1, dek, 1), UserCipher(2, dek, 1)
    blob = alice.seal("accounts", 9, {"name": "BPI"})
    with pytest.raises(DecryptionError):
        bob.open("accounts", 9, blob, 1)


def test_user_cipher_opens_rows_written_under_an_older_key_version():
    dek = generate_dek()
    old = UserCipher(1, dek, 1).seal("tags", 3, {"name": "food"})
    current = UserCipher(1, dek, 2)
    assert current.open("tags", 3, old, 1) == {"name": "food"}


def test_user_cipher_does_not_expose_its_key():
    dek = generate_dek()
    cipher = UserCipher(1, dek, 1)
    assert not any(bytes(dek) == getattr(cipher, attr, None) for attr in dir(cipher) if not attr.startswith("__"))
    assert dek.hex() not in repr(cipher)
