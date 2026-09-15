"""
The integrity check - what no foreign key can see (Phase 9; ARCHITECTURE.md §4, §12.3).

Every reference inside a payload is invisible to the database, so drift - a
transaction pointing at an account that is gone, a receipt row whose file is
missing, a row that no longer decrypts - is found only by opening everything.
This does, one account at a time, and changes nothing.

    unreadable        a row whose ciphertext does not open
    broken            a live row whose reference names no row at all
    to_deleted        a live row whose reference names a soft-deleted row -
                      reported, not failed: history can point there
    missing_files     a live receipt row with no file on disk
    unreadable_files  a receipt file that does not open
    stray_files       a file in the account's upload folder no receipt row claims

The references come from backup_service/references.py - the one list the
restore uses - so a reference added there is checked here too.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.errors import DecryptionError, KeyNotAvailableError
from app.core.crypto.keyring import MasterKeyring
from app.db.models import User
from app.db.repositories.attachment_repository import AttachmentRepository
from app.db.repositories.backup_repository import BackupRepository, open_row
from app.db.repositories.user_repository import UserRepository
from app.services.backup_service import references
from app.services.backup_service.references import ORDER


@dataclass
class UserReport:
    user_id: int
    key_ok: bool = True
    profile_ok: bool = True
    rows: Dict[str, int] = field(default_factory=dict)
    unreadable: Dict[str, List[int]] = field(default_factory=dict)
    broken: Dict[str, List[int]] = field(default_factory=dict)
    to_deleted: Dict[str, List[int]] = field(default_factory=dict)
    missing_files: List[int] = field(default_factory=list)
    unreadable_files: List[int] = field(default_factory=list)
    stray_files: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.key_ok and self.profile_ok
                and not (self.unreadable or self.broken or self.missing_files or self.unreadable_files))


def check_user(db: Session, user: User, keyring: MasterKeyring) -> UserReport:
    report = UserReport(user.id)
    users = UserRepository(db)
    try:
        cipher = users.cipher_for(user, keyring)
    except (DecryptionError, KeyNotAvailableError):
        report.key_ok = False
        return report
    try:
        users.read_profile(user, cipher)
    except DecryptionError:
        report.profile_ok = False

    stored = BackupRepository(db)
    opened: Dict[str, list] = {}
    every_id: Dict[str, Dict[int, int]] = {}
    live_id: Dict[str, Dict[int, int]] = {}
    for table in ORDER:
        rows = stored.raw_rows(table, user.id)
        report.rows[table] = len(rows)
        every_id[table] = {row.id: row.id for row in rows}
        live_id[table] = {row.id: row.id for row in rows if not row.is_deleted}
        opened[table] = []
        for row in rows:
            try:
                opened[table].append((row.id, row.is_deleted, open_row(cipher, table, row)))
            except DecryptionError:
                report.unreadable.setdefault(table, []).append(row.id)

    for table in ORDER:
        for row_id, deleted, data in opened[table]:
            if deleted:
                continue
            _, gone = references.apply(table, data, every_id, references.refs(table))
            _, not_live = references.apply(table, data, live_id, references.refs(table))
            for path in sorted(set(gone)):
                report.broken.setdefault(path, []).append(row_id)
            for path in sorted(set(not_live) - set(gone)):
                report.to_deleted.setdefault(path, []).append(row_id)

    files = AttachmentRepository(db, cipher)
    for row_id, deleted, data in opened["attachments"]:
        if deleted:
            continue
        try:
            files.read_file(row_id, int(data.get("file_key_version") or 1))
        except FileNotFoundError:
            report.missing_files.append(row_id)
        except DecryptionError:
            report.unreadable_files.append(row_id)

    claimed = {f"{attachment_id}.enc" for attachment_id in every_id["attachments"]}
    folder = Path(settings.UPLOAD_DIR) / str(user.id)
    if folder.is_dir():
        report.stray_files = sorted(p.name for p in folder.iterdir() if p.is_file() and p.name not in claimed)
    return report


def check_all(db: Session, keyring: MasterKeyring) -> List[UserReport]:
    return [check_user(db, user, keyring) for user in db.execute(select(User).order_by(User.id)).scalars().all()]
