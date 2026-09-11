"""
The 12-word recovery phrase (SEC-14).

The headline test is test_total_env_loss_recover_by_phrase_alone: write data,
lose .env entirely - master key AND blind-index pepper - then get everything
back with nothing but the twelve words.
"""

import os
import unicodedata

import pytest
from mnemonic import Mnemonic

from app.core.crypto.blind_index import BlindIndexer
from app.core.crypto.dek import generate_dek, unwrap_dek, wrap_dek, zero
from app.core.crypto.errors import DecryptionError, InvalidRecoveryPhraseError
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.recovery import (
    derive_recovery_key,
    find_user_by_phrase,
    generate_phrase,
    normalize_phrase,
    unwrap_dek_with_phrase,
    validate_phrase,
    wrap_dek_for_recovery,
)
from app.core.crypto.user_cipher import UserCipher
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.db.models import Transaction
from app.db.repositories.preferences_repository import PreferencesRepository
from app.db.repositories.user_repository import UserRepository
from app.services.auth_service.registration_service import create_account

pytestmark = pytest.mark.security

WORDLIST = set(Mnemonic("english").wordlist)


class TransactionRepo(EncryptedRepository):
    model = Transaction


# ================================================================ the phrase


def test_generated_phrase_is_exactly_12_valid_bip39_words():
    for _ in range(50):
        phrase = generate_phrase()
        words = phrase.split(" ")
        assert len(words) == 12
        assert all(w in WORDLIST for w in words)
        assert validate_phrase(phrase) == phrase


def test_phrases_are_unique():
    assert len({generate_phrase() for _ in range(200)}) == 200


def test_phrase_unwraps_the_same_dek_as_the_master_key(keyring):
    dek = generate_dek()
    phrase = generate_phrase()
    by_master = unwrap_dek(wrap_dek(dek, keyring, 4), keyring, 4)
    by_phrase = unwrap_dek_with_phrase(wrap_dek_for_recovery(dek, phrase, 4), phrase, 4)
    assert by_master == by_phrase == dek


def test_one_wrong_word_is_a_clear_checksum_error_not_a_decrypt_failure():
    words = generate_phrase().split()
    # Swap the last word for another valid word: every word is in the list,
    # but the BIP-39 checksum will (almost always) fail.
    replacement = next(w for w in sorted(WORDLIST) if w != words[-1] and not Mnemonic("english").check(" ".join(words[:-1] + [w])))
    wrong = " ".join(words[:-1] + [replacement])
    with pytest.raises(InvalidRecoveryPhraseError, match="does not check out"):
        validate_phrase(wrong)


def test_misspelt_words_are_reported_by_position_never_by_word():
    words = generate_phrase().split()
    words[3] = words[3] + "x"
    words[8] = "zzzz"
    with pytest.raises(InvalidRecoveryPhraseError) as info:
        validate_phrase(" ".join(words))
    assert info.value.positions == (4, 9)
    assert words[3] not in str(info.value) and "zzzz" not in str(info.value)


@pytest.mark.parametrize("count", [0, 11, 13, 25])
def test_wrong_word_counts_rejected(count):
    words = (generate_phrase().split() * 3)[:count]
    with pytest.raises(InvalidRecoveryPhraseError):
        validate_phrase(" ".join(words))


def test_case_spacing_numbering_and_unicode_forms_all_give_the_same_key():
    phrase = generate_phrase()
    words = phrase.split()
    variants = [
        phrase.upper(),
        "   " + "  \t ".join(words) + "\n",
        " ".join(w.capitalize() for w in words),
        " ".join(f"{i}. {w}" for i, w in enumerate(words, 1)),
        ", ".join(words),
        unicodedata.normalize("NFKC", "　".join(words)),  # ideographic spaces
        " ".join(words),  # non-breaking spaces
    ]
    expected = derive_recovery_key(phrase)
    for variant in variants:
        assert normalize_phrase(variant) == phrase
        assert derive_recovery_key(variant) == expected


def test_a_different_valid_phrase_fails_never_returns_garbage():
    dek = generate_dek()
    wrapped = wrap_dek_for_recovery(dek, generate_phrase(), 1)
    with pytest.raises(DecryptionError):
        unwrap_dek_with_phrase(wrapped, generate_phrase(), 1)


def test_recovery_wrap_is_bound_to_the_user():
    phrase = generate_phrase()
    wrapped = wrap_dek_for_recovery(generate_dek(), phrase, user_id=1)
    with pytest.raises(DecryptionError):
        unwrap_dek_with_phrase(wrapped, phrase, user_id=2)


def test_master_key_rotation_does_not_touch_the_recovery_wrap():
    # dek_wrapped and dek_wrapped_recovery wrap the SAME DEK under unrelated
    # keys; rotating the master key rewraps only the first (Phase 9 relies on it).
    dek, phrase = generate_dek(), generate_phrase()
    recovery_wrap = wrap_dek_for_recovery(dek, phrase, 1)
    old = os.urandom(32)
    wrap_v1 = wrap_dek(dek, MasterKeyring(1, old), 1)
    rotated = MasterKeyring(2, os.urandom(32), retired={1: old})
    wrap_v2 = wrap_dek(unwrap_dek(wrap_v1, rotated, 1), rotated, 1)
    assert unwrap_dek(wrap_v2, rotated, 1) == dek
    assert unwrap_dek_with_phrase(recovery_wrap, phrase, 1) == dek


# ===================================================== finding the user


def test_find_user_by_phrase_picks_the_right_user_among_many():
    users = {uid: (generate_dek(), generate_phrase()) for uid in range(1, 9)}
    candidates = [(uid, wrap_dek_for_recovery(dek, phrase, uid)) for uid, (dek, phrase) in users.items()]
    candidates.append((99, None))  # a user with recovery disabled
    for uid, (dek, phrase) in users.items():
        found_id, found_dek = find_user_by_phrase(phrase, candidates)
        assert found_id == uid and found_dek == dek
    assert find_user_by_phrase(generate_phrase(), candidates) is None


# ================================================== the headline test


def test_total_env_loss_recover_by_phrase_alone(session):
    """
    1. Register with the ORIGINAL .env (master key A, pepper A) and write a row.
    2. Lose .env completely. A new one has master key B and pepper B.
    3. With nothing but the phrase: find the user, unwrap the DEK, read the row.
    4. Re-wrap the DEK under master key B and rebuild the email index under
       pepper B, so a normal login works again afterwards.
    """
    keyring_a = MasterKeyring(1, os.urandom(32))
    indexer_a = BlindIndexer(os.urandom(32))
    email = "noah@example.com"

    account = create_account(
        session, email=email, password="Correct-Horse-9", display_name="Noah",
        keyring=keyring_a, indexer=indexer_a, bcrypt_rounds=4,
    )
    phrase = account.recovery_phrase
    users = UserRepository(session)
    user = users.get(account.user_id)
    dek_a = users.unwrap_dek(user, keyring_a)
    txn = TransactionRepo(session, UserCipher(user.id, dek_a, 1)).create(
        {"txn_date": "2026-09-15", "type": "expense", "amount": "5000.00",
         "splits": [{"category_id": 1, "amount": "5000.00"}], "merchant": "Motorcycle installment 1/36"}
    )
    session.commit()
    zero(dek_a)
    del keyring_a, indexer_a  # ---- .env is gone ----

    keyring_b = MasterKeyring(1, os.urandom(32))
    indexer_b = BlindIndexer(os.urandom(32))

    # The old email index is useless under the new pepper...
    assert users.get_by_email_bidx(indexer_b.email(email)) is None
    # ...and the old master wrap is useless under the new key.
    with pytest.raises(DecryptionError):
        users.unwrap_dek(user, keyring_b)

    # The phrase finds the user and the DEK on its own.
    found = find_user_by_phrase(phrase, users.recovery_candidates())
    assert found is not None
    user_id, dek = found
    assert user_id == account.user_id

    cipher = UserCipher(user_id, dek, keyring_b.current_version)
    row = TransactionRepo(session, cipher).get(txn.id)
    assert row.data["amount"] == "5000.00"
    assert row.data["merchant"] == "Motorcycle installment 1/36"
    assert PreferencesRepository(session, cipher).current() is not None

    # Re-home the account under the new .env.
    profile = users.read_profile(user, cipher)
    assert profile == {"email": email, "display_name": "Noah"}
    user.dek_wrapped = wrap_dek(dek, keyring_b, user_id)
    user.key_version = keyring_b.current_version
    user.email_bidx = indexer_b.email(profile["email"])
    session.commit()

    again = users.get_by_email_bidx(indexer_b.email("NOAH@example.com"))
    assert again is not None and again.id == user_id
    assert users.unwrap_dek(again, keyring_b) == dek
    zero(dek)
