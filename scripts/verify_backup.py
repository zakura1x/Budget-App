"""
Round-trip fidelity check for one user (DAT-14) - a backup you have never
restored is not a backup.

    python scripts/verify_backup.py --user-id 1

Writes a fresh backup to a temporary folder, reads it back (every checksum),
opens every row with the master key, resolves every reference, and compares
it with the live data. Writes nothing to the database. Exit 0 only if all of
it holds.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()

    from app.core.crypto.keyring import get_master_keyring
    from app.db.repositories.user_repository import UserRepository
    from app.db.session import get_session
    from app.services.backup_service.bundle import read_bundle, write_backup
    from app.services.backup_service.restore_service import restore, unlock_source

    session = get_session()
    try:
        with tempfile.TemporaryDirectory(prefix="zbdgt-verify-") as folder:
            info = write_backup(session, args.user_id, directory=Path(folder))
            found = read_bundle(Path(folder) / info.name)
            keyring = get_master_keyring()
            user = UserRepository(session).get(args.user_id)
            source = unlock_source(found, keyring=keyring)
            report = restore(session, found, UserRepository(session).cipher_for(user, keyring), source,
                             mode="verify")
    finally:
        session.close()

    print(f"rows={info.rows} receipts={info.attachments} bytes={info.size}")
    for line in report.unresolved:
        print(f"UNRESOLVED {line}")
    for diff in report.differences:
        print(f"DIFFERS {diff.table}: only_in_backup={diff.only_in_backup} only_in_live={diff.only_in_live}")
    if report.missing_files:
        print(f"MISSING receipt files: {report.missing_files}")
    ok = report.ok and not report.differences
    print("OK - the backup restores, and matches the live data" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
