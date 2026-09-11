"""
The in-memory session keyring: where an unlocked DEK lives, and dies.

An empty keyring must read as LOCKED, never as an error - that is what makes
an IIS idle-stop or recycle look like an ordinary auto-lock (SEC-27).
"""

import pytest

from app.core.crypto.dek import generate_dek
from app.core.crypto.session_keys import SessionKeyring

pytestmark = pytest.mark.security


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_unlock_then_cipher_round_trips():
    ring = SessionKeyring(idle_timeout_seconds=300)
    ring.unlock("s1", user_id=1, dek=generate_dek(), key_version=1)
    cipher = ring.cipher_for("s1")
    assert cipher is not None and cipher.user_id == 1
    blob = cipher.seal("tags", 1, {"name": "food"})
    assert ring.cipher_for("s1").open("tags", 1, blob, 1) == {"name": "food"}


def test_unknown_session_is_locked_not_an_error():
    ring = SessionKeyring(idle_timeout_seconds=300)
    assert ring.cipher_for("never-seen") is None
    assert not ring.is_unlocked("never-seen")


def test_a_fresh_process_is_a_locked_process():
    # A restart builds a new, empty keyring. Every existing session is locked.
    before = SessionKeyring(idle_timeout_seconds=300)
    before.unlock("s1", 1, generate_dek(), 1)
    after_restart = SessionKeyring(idle_timeout_seconds=300)
    assert after_restart.cipher_for("s1") is None


def test_unlock_takes_ownership_and_zeroes_the_callers_buffer():
    ring = SessionKeyring(idle_timeout_seconds=300)
    dek = generate_dek()
    ring.unlock("s1", 1, dek, 1)
    assert dek == bytearray(32)
    assert ring.cipher_for("s1") is not None


def test_lock_drops_and_zeroes():
    ring = SessionKeyring(idle_timeout_seconds=300)
    ring.unlock("s1", 1, generate_dek(), 1)
    stored = ring._entries["s1"].dek
    assert ring.lock("s1") is True
    assert stored == bytearray(32)
    assert ring.cipher_for("s1") is None
    assert ring.lock("s1") is False


def test_idle_auto_lock_is_enforced_server_side():
    clock = FakeClock()
    ring = SessionKeyring(idle_timeout_seconds=300, clock=clock)
    ring.unlock("s1", 1, generate_dek(), 1)
    stored = ring._entries["s1"].dek

    clock.now += 299
    assert ring.cipher_for("s1") is not None  # activity resets the timer
    clock.now += 299
    assert ring.cipher_for("s1") is not None
    clock.now += 301
    assert ring.cipher_for("s1") is None
    assert stored == bytearray(32)


def test_sweep_drops_only_idle_sessions():
    clock = FakeClock()
    ring = SessionKeyring(idle_timeout_seconds=300, clock=clock)
    ring.unlock("old", 1, generate_dek(), 1)
    clock.now += 200
    ring.unlock("new", 2, generate_dek(), 1)
    clock.now += 150
    assert ring.sweep() == 1
    assert ring.cipher_for("old") is None and ring.cipher_for("new") is not None


def test_lock_user_drops_every_session_of_that_user_only():
    ring = SessionKeyring(idle_timeout_seconds=None)
    ring.unlock("a1", 1, generate_dek(), 1)
    ring.unlock("a2", 1, generate_dek(), 1)
    ring.unlock("b1", 2, generate_dek(), 1)
    assert ring.lock_user(1) == 2
    assert ring.cipher_for("a1") is None and ring.cipher_for("a2") is None
    assert ring.cipher_for("b1") is not None
    assert ring.lock_all() == 1 and len(ring) == 0


def test_reunlocking_a_session_zeroes_the_previous_key():
    ring = SessionKeyring(idle_timeout_seconds=None)
    ring.unlock("s1", 1, generate_dek(), 1)
    previous = ring._entries["s1"].dek
    ring.unlock("s1", 1, generate_dek(), 1)
    assert previous == bytearray(32)


def test_repr_shows_no_keys():
    ring = SessionKeyring(idle_timeout_seconds=None)
    dek = generate_dek()
    hex_key = dek.hex()
    ring.unlock("s1", 1, dek, 1)
    assert hex_key not in repr(ring)
