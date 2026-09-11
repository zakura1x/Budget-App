"""The email blind index - the one deliberate exception to full encryption."""

import os

import pytest

from app.core.crypto.blind_index import BIDX_HEX_LENGTH, BlindIndexer, compute, matches, normalize_email

pytestmark = pytest.mark.security

PEPPER = os.urandom(32)


def test_deterministic_64_hex():
    first = compute("noah@example.com", PEPPER)
    assert first == compute("noah@example.com", PEPPER)
    assert len(first) == BIDX_HEX_LENGTH and all(c in "0123456789abcdef" for c in first)


def test_differs_with_a_different_pepper():
    assert compute("noah@example.com", PEPPER) != compute("noah@example.com", os.urandom(32))


def test_differs_for_different_emails():
    assert compute("a@example.com", PEPPER) != compute("b@example.com", PEPPER)


@pytest.mark.parametrize(
    "variant",
    ["Noah@Example.com", "  noah@example.com ", "NOAH@EXAMPLE.COM", "\tnoah@example.com\n", "ｎｏａｈ@example.com"],
)
def test_normalisation_case_space_and_width(variant):
    assert compute(variant, PEPPER) == compute("noah@example.com", PEPPER)


def test_no_clever_folding():
    # Dots and plus-tags are NOT folded - that would be a policy, not a normalisation.
    assert normalize_email("no.ah+x@example.com") == "no.ah+x@example.com"


def test_matches_is_constant_time_comparison_and_correct():
    stored = compute("noah@example.com", PEPPER)
    assert matches("NOAH@example.com", stored, PEPPER)
    assert not matches("someone@example.com", stored, PEPPER)
    assert not matches("noah@example.com", "", PEPPER)


def test_indexer_hides_its_pepper():
    indexer = BlindIndexer(PEPPER)
    assert indexer.email("x@y.z") == compute("x@y.z", PEPPER)
    assert PEPPER.hex() not in repr(indexer)


def test_short_pepper_refused():
    with pytest.raises(ValueError):
        BlindIndexer(b"short")
