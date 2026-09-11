"""
The only window into the data - it needs the master key, which it reads from
.env like the app does.

    python scripts/decrypt_query.py --user-id 1 --table transactions
    python scripts/decrypt_query.py --user-id 1 --table accounts --id 4
    python scripts/decrypt_query.py --user-id 1 --profile
    python scripts/decrypt_query.py --list-tables

Prints decrypted rows as JSON to stdout. Treat that output exactly as you would
the data itself: it is plaintext, on whatever screen or file it lands in.
Read-only - it never writes.

Note what this demonstrates: the master key alone opens any user's data,
without their password. That is the design (ARCHITECTURE.md 5.1) - an app-
server administrator is out of scope - and it is why .env must be guarded as
closely as the database is not.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--table")
    parser.add_argument("--id", type=int, dest="row_id")
    parser.add_argument("--include-deleted", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--profile", action="store_true", help="show the user's email and display name")
    parser.add_argument("--list-tables", action="store_true")
    args = parser.parse_args()

    from app.db.models import ENCRYPTED_TABLES

    if args.list_tables:
        print("\n".join(sorted(ENCRYPTED_TABLES)))
        return 0
    if args.user_id is None or not (args.table or args.profile):
        parser.error("--user-id and one of --table / --profile are required")
    if args.table and args.table not in ENCRYPTED_TABLES:
        parser.error(f"unknown table; one of: {', '.join(sorted(ENCRYPTED_TABLES))}")

    from app.core.crypto.keyring import get_master_keyring
    from app.db.repositories.encrypted_repository import EncryptedRepository
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import session_scope

    print("[decrypt_query] printing PLAINTEXT financial data", file=sys.stderr)
    with session_scope() as session:
        users = UserRepository(session)
        user = users.get(args.user_id)
        if user is None:
            print(f"No user {args.user_id}.", file=sys.stderr)
            return 1
        cipher = users.cipher_for(user, get_master_keyring())

        if args.profile:
            print(json.dumps(users.read_profile(user, cipher), indent=2, ensure_ascii=False))
            return 0

        repo_class = type("Repo", (EncryptedRepository,), {"model": ENCRYPTED_TABLES[args.table]})
        repo = repo_class(session, cipher)
        if args.row_id is not None:
            record = repo.get(args.row_id, include_deleted=args.include_deleted)
            records = [record] if record else []
        else:
            records = repo.list(include_deleted=args.include_deleted)[: args.limit]
        output = [
            {"id": r.id, "is_deleted": r.is_deleted, "row_created": r.row_created.isoformat(), "data": r.data}
            for r in records
        ]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
