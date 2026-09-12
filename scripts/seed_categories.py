"""
Write the default category set for a user (CAT-07).

    python scripts/seed_categories.py --user-id 1
    python scripts/seed_categories.py --user-id 1 --dry-run
    python scripts/seed_categories.py --user-id 1 --kind income

Needs the master key, because the rows it writes are encrypted like any
other: it unwraps the user's DEK the way decrypt_query.py does, then goes in
through category_service, so the parent/child rule and the name checks are the
same ones the API applies. Nothing is inserted as plaintext.

Safe to re-run: a category whose name already exists under the same parent is
skipped rather than duplicated.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# (name, icon, colour, [children])
EXPENSE = [
    ("Food & Drink", "restaurant", "#E8734A", ["Groceries", "Eating out", "Coffee", "Delivery"]),
    ("Transport", "car", "#4A90D9", ["Fuel", "Ride-hailing", "Fares", "Parking", "Maintenance"]),
    ("Bills & Utilities", "bolt", "#F2B544", ["Electricity", "Water", "Internet", "Mobile"]),
    ("Home", "home", "#8B6FD4", ["Rent", "Furnishings", "Repairs", "Help"]),
    ("Shopping", "bag", "#E05A8A", ["Clothes", "Electronics", "Household"]),
    ("Health", "heart", "#D64C40", ["Medicine", "Doctor", "Fitness", "Insurance"]),
    ("Entertainment", "play", "#5BB3A6", ["Streaming", "Games", "Events", "Hobbies"]),
    ("Education", "book", "#3F8FA3", ["Tuition", "Books", "Courses"]),
    ("Family & Gifts", "gift", "#C86FB0", ["Gifts", "Donations", "Support"]),
    ("Financial", "bank", "#6E7B8B", ["Bank fees", "Interest", "Taxes"]),
    ("Travel", "plane", "#3FA37A", ["Flights", "Stays", "Local transport"]),
    ("Other", "dots", "#8E8E93", []),
]

INCOME = [
    ("Salary", "wallet", "#2C9669", ["Regular pay", "13th month", "Overtime"]),
    ("Business", "briefcase", "#3F8FA3", []),
    ("Freelance", "laptop", "#4A90D9", []),
    ("Investments", "chart", "#8B6FD4", ["Dividends", "Interest"]),
    ("Gifts received", "gift", "#C86FB0", []),
    ("Refunds", "undo", "#6E7B8B", []),
    ("Other income", "dots", "#8E8E93", []),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--kind", choices=("expense", "income", "both"), default="both")
    parser.add_argument("--dry-run", action="store_true", help="print what it would write, write nothing")
    args = parser.parse_args()

    from app.core.crypto.keyring import get_master_keyring
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import session_scope
    from app.services import category_service

    groups = []
    if args.kind in ("expense", "both"):
        groups.append(("expense", EXPENSE))
    if args.kind in ("income", "both"):
        groups.append(("income", INCOME))

    if args.dry_run:
        for kind, tree in groups:
            for name, icon, colour, children in tree:
                print(f"{kind:<8} {name}  [{icon} {colour}]")
                for child in children:
                    print(f"{'':<8}   - {child}")
        return 0

    written = skipped = 0
    with session_scope() as session:
        users = UserRepository(session)
        user = users.get(args.user_id)
        if user is None:
            print(f"No user {args.user_id}.", file=sys.stderr)
            return 1
        cipher = users.cipher_for(user, get_master_keyring())

        for kind, tree in groups:
            for order, (name, icon, colour, children) in enumerate(tree):
                parent = _create(
                    session, cipher, category_service,
                    {"name": name, "kind": kind, "icon": icon, "colour": colour, "sort_order": order},
                )
                if parent is None:
                    skipped += 1
                    parent_id = _find(session, cipher, category_service, name, kind, None)
                else:
                    written += 1
                    parent_id = parent.id
                if parent_id is None:
                    continue
                for child_order, child in enumerate(children):
                    made = _create(
                        session, cipher, category_service,
                        {"name": child, "kind": kind, "parent_id": parent_id,
                         "icon": icon, "colour": colour, "sort_order": child_order},
                    )
                    written += made is not None
                    skipped += made is None

    print(f"{written} categories written, {skipped} already there.")
    return 0 if written or skipped else 1


def _create(session, cipher, service, payload):
    """Create one, or None if a category by that name is already there."""
    from app.core.exceptions import BusinessRuleException

    try:
        return service.create_category(session, cipher, payload)
    except BusinessRuleException:
        session.rollback()
        return None


def _find(session, cipher, service, name, kind, parent_id):
    for view in service.list_categories(session, cipher, kind=kind):
        if view.name.casefold() == name.casefold() and view.parent_id == parent_id:
            return view.id
    return None


if __name__ == "__main__":
    sys.exit(main())
