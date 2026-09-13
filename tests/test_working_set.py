"""
The working set - decrypted rows held between requests (ARCHITECTURE.md 5.5/5.6).

Two families of property, and the second matters more:

  * it is a cache: one load, write-through, TTL, LRU, a row cap
  * it never serves plaintext it should not have: a stale load cannot land
    after a write or a lock, and the moment a DEK is dropped - by the lock
    button, idle expiry, logout or a sweep - that user's rows go with it
"""

from dataclasses import dataclass

import pytest

from app.core.crypto.dek import generate_dek
from app.core.crypto.session_keys import SessionKeyring
from app.core.crypto.working_set import WorkingSet, _on_key_dropped, set_working_set


@dataclass(frozen=True)
class Row:
    id: int
    value: str = ""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Loader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return list(self.rows)


def make(clock=None, **overrides):
    options = dict(ttl_seconds=900, max_users=8, max_rows_per_user=1000, enabled=True)
    options.update(overrides)
    return WorkingSet(clock=clock or Clock(), **options)


# ----------------------------------------------------------------- the cache


def test_loads_once_then_serves_from_memory():
    ws, loader = make(), Loader([Row(1), Row(2)])
    assert [r.id for r in ws.rows(1, "t", loader)] == [1, 2]
    assert [r.id for r in ws.rows(1, "t", loader)] == [1, 2]
    assert loader.calls == 1


def test_expires_after_the_ttl():
    clock = Clock()
    ws, loader = make(clock, ttl_seconds=900), Loader([Row(1)])
    ws.rows(1, "t", loader)
    clock.now += 901
    ws.rows(1, "t", loader)
    assert loader.calls == 2


def test_write_through_updates_a_warm_table_without_a_reload():
    ws, loader = make(), Loader([Row(1, "old")])
    ws.rows(1, "t", loader)
    ws.put(1, "t", Row(1, "new"))
    ws.put(1, "t", Row(2, "added"))
    ws.remove(1, "t", 1)
    assert ws.rows(1, "t", loader) == [Row(2, "added")]
    assert loader.calls == 1


def test_a_write_to_a_cold_user_is_ignored():
    ws = make()
    ws.put(1, "t", Row(1))
    assert not ws.is_warm(1, "t")


def test_least_recently_used_user_is_evicted():
    ws = make(max_users=2)
    for user in (1, 2):
        ws.rows(user, "t", Loader([Row(user)]))
    ws.rows(1, "t", Loader([]))  # touch user 1, so 2 is now oldest
    ws.rows(3, "t", Loader([Row(3)]))
    assert ws.is_warm(1, "t") and ws.is_warm(3, "t")
    assert not ws.is_warm(2, "t")


def test_too_many_rows_are_served_but_not_kept():
    ws, loader = make(max_rows_per_user=2), Loader([Row(1), Row(2), Row(3)])
    assert len(ws.rows(1, "t", loader)) == 3
    ws.rows(1, "t", loader)
    assert loader.calls == 2


def test_disabled_always_loads():
    ws, loader = make(enabled=False), Loader([Row(1)])
    ws.rows(1, "t", loader)
    ws.rows(1, "t", loader)
    assert loader.calls == 2


# --------------------------------------------------------- never stale, never late


@pytest.mark.security
def test_a_load_overtaken_by_a_write_is_not_kept():
    """A slow cold load must not overwrite a write that landed while it ran."""
    ws = make()

    def slow_loader():
        ws.put(1, "t", Row(9, "written meanwhile"))  # arrives mid-load
        return [Row(1)]

    ws.rows(1, "t", slow_loader)
    assert not ws.is_warm(1, "t")


@pytest.mark.security
def test_a_load_overtaken_by_a_lock_is_not_kept():
    """The user locked while their rows were being decrypted: keep none of them."""
    ws = make()

    def slow_loader():
        ws.drop(1)
        return [Row(1, "plaintext")]

    ws.rows(1, "t", slow_loader)
    assert not ws.is_warm(1, "t")
    assert len(ws) == 0


@pytest.mark.security
def test_drop_forgets_one_user_only():
    ws = make()
    ws.rows(1, "t", Loader([Row(1)]))
    ws.rows(2, "t", Loader([Row(2)]))
    assert ws.drop(1) is True
    assert not ws.is_warm(1, "t") and ws.is_warm(2, "t")
    assert ws.drop(1) is False


# ------------------------------------------------ dropped together with the key


@pytest.fixture
def wired():
    """A keyring on a fake clock, wired to a fresh working set the way production wires them."""
    clock = Clock()
    ws = make(clock)
    set_working_set(ws)
    keyring = SessionKeyring(idle_timeout_seconds=300, clock=clock)
    keyring.add_drop_listener(_on_key_dropped)
    return ws, keyring, clock


def warm(ws, keyring, session="s1", user=7):
    keyring.unlock(session, user, generate_dek(), 1)
    ws.rows(user, "transactions", Loader([Row(1, "₱3,500 SM Supermarket")]))
    assert ws.is_warm(user, "transactions")


@pytest.mark.security
def test_the_lock_button_drops_the_working_set(wired):
    ws, keyring, _ = wired
    warm(ws, keyring)
    keyring.lock("s1")
    assert not ws.is_warm(7, "transactions")


@pytest.mark.security
def test_idle_expiry_drops_the_working_set(wired):
    ws, keyring, clock = wired
    warm(ws, keyring)
    clock.now += 301
    assert keyring.cipher_for("s1") is None
    assert not ws.is_warm(7, "transactions")


@pytest.mark.security
def test_sweep_and_lock_all_drop_the_working_set(wired):
    ws, keyring, clock = wired
    warm(ws, keyring, "s1", 7)
    warm(ws, keyring, "s2", 8)
    clock.now += 301
    keyring.sweep()
    assert not ws.is_warm(7, "transactions") and not ws.is_warm(8, "transactions")

    warm(ws, keyring, "s3", 9)
    keyring.lock_all()
    assert not ws.is_warm(9, "transactions")


def test_adding_the_same_listener_twice_is_harmless(wired):
    ws, keyring, _ = wired
    keyring.add_drop_listener(_on_key_dropped)
    warm(ws, keyring)
    keyring.lock("s1")
    assert not ws.is_warm(7, "transactions")


def test_a_failing_listener_does_not_stop_the_lock(wired):
    ws, keyring, _ = wired

    def broken(_user_id):
        raise RuntimeError("listener bug")

    keyring.add_drop_listener(broken)
    warm(ws, keyring)
    assert keyring.lock("s1") is True
    assert keyring.cipher_for("s1") is None
    assert not ws.is_warm(7, "transactions")
