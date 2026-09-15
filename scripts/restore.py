"""
Restore a .budgetbak into an EXISTING account (DAT-07, DAT-15, DAT-16).

    python scripts/restore.py FILE --target-user-id 3 --verify
    python scripts/restore.py FILE --target-user-id 3 --fresh
    python scripts/restore.py FILE --target-user-id 3 --merge

The backup opens with the master key in .env (current or retired). On a new
server: put the offline copy of .env in place, sign up so the account exists
with its own key, then run this. The rows are re-encrypted under the target
account's key, with new row ids. Unlike the app's Restore screen, this opens
any account's backup - whoever can run it holds .env already.

    --verify   decrypt everything, resolve every reference, compare with the
               target's live data. Writes nothing.
    --fresh    the target must be empty
    --merge    add to the target, skipping what is already there
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
    parser.add_argument("file")
    parser.add_argument("--target-user-id", type=int, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_const", const="verify", dest="mode")
    mode.add_argument("--fresh", action="store_const", const="fresh", dest="mode")
    mode.add_argument("--merge", action="store_const", const="merge", dest="mode")
    args = parser.parse_args()

    from app.core.crypto.keyring import get_master_keyring
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import get_session
    from app.services.backup_service.bundle import read_bundle
    from app.services.backup_service.restore_service import restore, unlock_source

    found = read_bundle(Path(args.file))
    print(f"[restore] backup of user {found.user_id} from {found.created_at.isoformat()}: "
          f"{found.rows} rows, {found.attachments} receipts - checksums OK", file=sys.stderr)

    session = get_session()
    try:
        users = UserRepository(session)
        target = users.get(args.target_user_id)
        if target is None:
            print(f"No user {args.target_user_id} - sign up on this server first.", file=sys.stderr)
            return 1
        keyring = get_master_keyring()
        source = unlock_source(found, keyring=keyring)
        report = restore(session, found, users.cipher_for(target, keyring), source, mode=args.mode)
    finally:
        session.close()

    print(json.dumps({
        "mode": report.mode, "ok": report.ok,
        "tables": {t.table: {"in_backup": t.in_backup, "restored": t.restored, "skipped": t.skipped} for t in report.tables},
        "receipts": report.attachments, "missing_receipt_files": report.missing_files,
        "unresolved": report.unresolved,
        "differences": {d.table: {"only_in_backup": d.only_in_backup, "only_in_live": d.only_in_live}
                        for d in report.differences},
    }, indent=2))
    return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
