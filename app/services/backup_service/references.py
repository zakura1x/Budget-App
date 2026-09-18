"""
Every reference that lives inside a ciphertext, in one place (DAT-13,
ARCHITECTURE.md §12.3) - the highest-risk code in the project.

No foreign key can see an `account_id` inside a payload, so nothing but this
map knows that restoring a transaction means rewriting it. A restore inserts
rows under NEW ids and rewrites every reference through `export_id -> new_id`
maps built as it goes. A reference this map does not list is restored
pointing at the OLD id - the wrong row, silently.

    ANY NEW ENTITY, OR ANY NEW REFERENCE FIELD, MUST BE ADDED HERE.
    tests/test_backup.py fails if ORDER stops covering every encrypted table.

Paths:
    "account_id"              a single id
    "tag_ids[]"               a list of ids
    "splits[].category_id"    a field on every item of a list
    "interest.category_id"    a field inside a nested object

ORDER is the insert order the dependencies force. A reference to a table at or
after its own position (a category's parent, a transfer's other leg, a
transaction's receipt) is DEFERRED: the row is inserted with it cleared, and
filled in once every row exists - still inside the one database transaction,
so no half-linked row is ever committed. Inserting in the rows' original id
order within each table keeps their relative order, which is what lets two
exports be compared position for position (DAT-14).
"""

import copy
from typing import Any, Dict, List, Mapping, Tuple

Ref = Tuple[str, str]

ORDER: Tuple[str, ...] = (
    "accounts",
    "categories",
    "tags",
    "budgets",
    "budget_allocations",
    "recurring_rules",
    "subscriptions",
    "savings_goals",
    "user_preferences",
    "transactions",
    "attachments",
)

REFERENCES: Mapping[str, Tuple[Ref, ...]] = {
    # ACC-37. Where a savings account's daily interest lands. Deferred:
    # categories are inserted after accounts, so it is cleared and filled in.
    "accounts": (
        ("interest.category_id", "categories"),
        # ACC-35. What a card's saved bill list already covers. Deferred like
        # the category: plans and transactions are inserted after accounts.
        ("bills_cover_transactions[]", "transactions"),
        ("bills_cover_rules[]", "recurring_rules"),
    ),
    "categories": (("parent_id", "categories"),),
    "tags": (),
    "budgets": (),
    "budget_allocations": (("budget_id", "budgets"), ("category_id", "categories")),
    "recurring_rules": (
        ("account_id", "accounts"),
        ("counter_account_id", "accounts"),
        ("category_id", "categories"),
        ("interest_category_id", "categories"),
        ("tag_ids[]", "tags"),
    ),
    "subscriptions": (("recurring_rule_id", "recurring_rules"),),
    "savings_goals": (("account_id", "accounts"),),
    "user_preferences": (),
    "transactions": (
        ("account_id", "accounts"),
        ("counter_account_id", "accounts"),
        ("splits[].category_id", "categories"),
        ("tag_ids[]", "tags"),
        ("recurring_id", "recurring_rules"),
        # TXN-22. Where a purchase's cashback lands, and the two rows' link.
        ("cashback.account_id", "accounts"),
        ("cashback.category_id", "categories"),
        ("cashback_id", "transactions"),
        ("cashback_of", "transactions"),
        ("pair_id", "transactions"),
        ("attachment_id", "attachments"),
    ),
    "attachments": (("transaction_id", "transactions"),),
}

# Links that say WHICH row, not what a row IS - left out of a merge's
# duplicate check, or a transfer's legs (and a purchase and its cashback)
# could never recognise each other.
LINKS = {("transactions", "pair_id"), ("transactions", "attachment_id"),
         ("transactions", "cashback_id"), ("transactions", "cashback_of")}


def refs(table: str) -> Tuple[Ref, ...]:
    return REFERENCES[table]


def split(table: str) -> Tuple[Tuple[Ref, ...], Tuple[Ref, ...]]:
    """(immediate, deferred) references of a table."""
    position = ORDER.index(table)
    immediate = tuple(r for r in refs(table) if ORDER.index(r[1]) < position)
    deferred = tuple(r for r in refs(table) if ORDER.index(r[1]) >= position)
    return immediate, deferred


def apply(
    table: str,
    data: Mapping[str, Any],
    maps: Mapping[str, Mapping[Any, Any]],
    references: Tuple[Ref, ...],
    *,
    clear: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    A copy of `data` with each listed reference rewritten through `maps`
    (or cleared). Returns it with the "table.path" of every reference that
    had no entry in its map - a reference to a row the backup does not hold.
    """
    result: Dict[str, Any] = copy.deepcopy(dict(data))
    missing: List[str] = []

    for path, target in references:
        lookup = maps.get(target, {})

        def convert(value: Any) -> Any:
            if value is None or clear:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or value not in lookup:
                missing.append(f"{table}.{path}")
                return value
            return lookup[value]

        if path.endswith("[]"):
            name = path[:-2]
            if isinstance(result.get(name), list):
                result[name] = [] if clear else [convert(v) for v in result[name]]
        elif "[]." in path:
            name, field = path.split("[].", 1)
            for item in result.get(name) or []:
                if isinstance(item, dict) and field in item:
                    item[field] = convert(item[field])
        elif "." in path:
            name, field = path.split(".", 1)
            nested = result.get(name)
            if isinstance(nested, dict) and field in nested:
                nested[field] = convert(nested[field])
        elif path in result:
            result[path] = convert(result[path])
    return result, missing
