"""
Find what no foreign key can: rows that do not decrypt, references to rows that
are gone, receipts without files (Phase 9; app/services/integrity_service.py).

    python scripts/verify_integrity.py                every account
    python scripts/verify_integrity.py --user-id 3
    python scripts/verify_integrity.py --json

READ-ONLY. Prints table names and row ids, never a value. Needs the master key
from .env. Exit code 0 = clean, 2 = something to look at.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ids(ids, limit: int = 20) -> str:
    shown = ", ".join(str(i) for i in ids[:limit])
    return shown + (f" (+{len(ids) - limit} more)" if len(ids) > limit else "")


def describe(report) -> str:
    if not report.key_ok:
        return f"Account {report.user_id}: PROBLEMS - its key does not open with the loaded master keys"
    total = sum(report.rows.values())
    lines = [f"Account {report.user_id}: {'OK' if report.ok else 'PROBLEMS'} - "
             f"{total} rows, {report.rows.get('attachments', 0)} receipts"]
    if not report.profile_ok:
        lines.append("  unreadable     the profile (email and name)")
    for table, ids in report.unreadable.items():
        lines.append(f"  unreadable     {table}: {_ids(ids)}")
    for path, ids in report.broken.items():
        lines.append(f"  broken         {path}: {_ids(ids)}")
    if report.missing_files:
        lines.append(f"  missing file   receipts {_ids(report.missing_files)}")
    if report.unreadable_files:
        lines.append(f"  unreadable     receipt files {_ids(report.unreadable_files)}")
    for path, ids in report.to_deleted.items():
        lines.append(f"  note           points at a deleted row - {path}: {_ids(ids)}")
    if report.stray_files:
        lines.append(f"  note           files no receipt claims: {', '.join(report.stray_files)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    from app.core.crypto.keyring import get_master_keyring
    from app.db.models import User
    from app.db.session import get_session
    from app.services import integrity_service

    session = get_session()
    try:
        keyring = get_master_keyring()
        if args.user_id is not None:
            user = session.get(User, args.user_id)
            if user is None:
                print(f"No user {args.user_id}.", file=sys.stderr)
                return 1
            reports = [integrity_service.check_user(session, user, keyring)]
        else:
            reports = integrity_service.check_all(session, keyring)
    finally:
        session.rollback()  # read-only, and says so
        session.close()

    if args.json:
        print(json.dumps([{**asdict(r), "ok": r.ok} for r in reports], indent=2))
    else:
        print("\n".join(describe(r) for r in reports) or "No accounts.")
    return 0 if all(r.ok for r in reports) else 2


if __name__ == "__main__":
    sys.exit(main())
