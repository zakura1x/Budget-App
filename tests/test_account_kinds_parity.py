"""
The account-type rules live once on each side: account_service on the server,
frontend/src/lib/accounts.ts on the client, under the same names. Nothing
generates one from the other, so this reads the TypeScript source and fails
the moment the two disagree (architecture review 2026-10-12, candidate 4).
"""

import re
from pathlib import Path

import pytest

from app.services import account_service

SOURCE = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "accounts.ts").read_text(encoding="utf-8")


def _ts_list(name: str) -> set:
    found = re.search(rf"export const {name}: readonly AccountType\[\] = \[([^\]]*)\]", SOURCE)
    assert found, f"{name} is missing from lib/accounts.ts"
    return set(re.findall(r"'(\w+)'", found.group(1)))


@pytest.mark.parametrize("name", ["OWES", "LOANS", "EARNS_INTEREST", "GIVES_CASHBACK", "CHECKABLE"])
def test_a_type_list_is_the_same_on_both_sides(name):
    assert _ts_list(name) == set(getattr(account_service, name))


def test_the_cash_on_hand_defaults_are_the_same_on_both_sides():
    found = re.search(r"export const COUNTS_IN_CASH_ON_HAND_DEFAULT[^=]*= \{([^}]*)\}", SOURCE)
    assert found, "COUNTS_IN_CASH_ON_HAND_DEFAULT is missing from lib/accounts.ts"
    client = {k: v == "true" for k, v in re.findall(r"(\w+): (true|false)", found.group(1))}
    assert client == dict(account_service.COUNTS_IN_CASH_ON_HAND_DEFAULT)
    assert set(client) == set(account_service.TYPES)
