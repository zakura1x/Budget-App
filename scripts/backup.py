"""
Write the full encrypted backup (DAT-06) - needs the database, never a key.

    python scripts/backup.py --user-id 1
    python scripts/backup.py --all

Files go to BACKUP_DIR/<user_id>/budget-<UTC time>.budgetbak, the same place
the app's own backups go. Nothing is decrypted: this is what Windows Task
Scheduler can run with nobody signed in (DAT-20).
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", type=int)
    group.add_argument("--all", action="store_true", help="every active user")
    parser.add_argument("--dir", help="write here instead of BACKUP_DIR/<user_id>")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import session_scope
    from app.services.backup_service.bundle import write_backup

    with session_scope() as session:
        if args.all:
            user_ids = session.execute(select(User.id).where(User.is_active == True).order_by(User.id)).scalars().all()  # noqa: E712
        else:
            user_ids = [args.user_id]
        for user_id in user_ids:
            directory = Path(args.dir) / str(user_id) if args.dir else None
            info = write_backup(session, user_id, directory=directory)
            print(f"user {user_id}: {info.name}  rows={info.rows} receipts={info.attachments} bytes={info.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
