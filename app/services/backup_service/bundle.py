"""
The .budgetbak file (DAT-06, DAT-12, DAT-16, DAT-17; ARCHITECTURE.md §12.1).

    budget-20260914T132045.budgetbak       a zip
    ├── manifest.json       PLAINTEXT - format, versions, time, user id, per-table
    │                       row counts, a SHA-256 per entry. Counts and hashes,
    │                       never a value.
    ├── keys.enc            dek_wrapped under the master key (+ email_bidx)
    ├── accounts.enc        every row as stored: id, key_version, is_deleted,
    ├── ...                   and the payload ciphertext, untouched
    └── attachments/<id>.enc   receipts, still encrypted

WRITING NEEDS NO KEY. Nothing is decrypted to make a backup, so it is exactly as
safe as the rows it copies, and it can run with nobody signed in (§12.6). The
`.enc` entries are JSON documents whose only sensitive contents are ciphertext.

READING VERIFIES BEFORE ANYTHING ASKS FOR A KEY: the format and version, every
entry present, every checksum, every row count. A damaged file is refused
whole - a restore that half-worked would be worse than one that did not start.

Files live in BACKUP_DIR/<user_id>/, one folder per user, because restoring one
needs that user's key. BACKUP_RETENTION_DAYS prunes old ones but the newest
three always stay, however old.
"""

import base64
import binascii
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundException, ValidationException
from app.db.repositories.attachment_repository import AttachmentRepository
from app.db.repositories.backup_repository import BackupRepository, RawRow
from app.services.backup_service.references import ORDER

logger = logging.getLogger(__name__)

FORMAT = "budgetbak"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
KEYS = "keys.enc"
NAME = re.compile(r"^budget-(\d{8}T\d{6})(?:-\d+)?\.budgetbak$")
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
KEEP_AT_LEAST = 3
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # a zip bomb stops here
UPLOAD_TTL = timedelta(hours=1)


class BackupFormatError(ValidationException):
    code = "BACKUP_INVALID"
    title = "Backup Not Readable"


@dataclass(frozen=True)
class BackupInfo:
    name: str
    created_at: datetime
    size: int
    rows: int  # live rows across every table
    attachments: int


@dataclass
class Bundle:
    manifest: dict
    keys: dict
    tables: Dict[str, List[RawRow]]
    files: Dict[int, bytes]

    @property
    def user_id(self) -> int:
        return int(self.keys["user_id"])

    @property
    def created_at(self) -> datetime:
        return datetime.fromisoformat(self.manifest["created_at"])

    @property
    def rows(self) -> int:
        return sum(int(t.get("live", 0)) for t in self.manifest.get("tables", {}).values())

    @property
    def attachments(self) -> int:
        return int(self.manifest.get("attachments", 0))


# ---------------------------------------------------------------- writing


def write_backup(
    db: Session, user_id: int, *, directory: Optional[Path] = None, now: Optional[datetime] = None
) -> BackupInfo:
    """Write one user's backup. Reads the database and the receipt files; decrypts nothing."""
    now = now or datetime.now(timezone.utc)
    repo = BackupRepository(db)
    keys = repo.user_keys(user_id)
    if keys is None:
        raise NotFoundException("No such user")

    entries: Dict[str, bytes] = {}
    counts: Dict[str, dict] = {}
    for table in ORDER:
        rows = repo.raw_rows(table, user_id)
        entries[f"{table}.enc"] = _dump_rows(table, rows)
        counts[table] = {"rows": len(rows), "live": sum(1 for r in rows if not r.is_deleted)}
        if table == "attachments" and settings.BACKUP_INCLUDE_ATTACHMENTS:
            for row in rows:
                blob = AttachmentRepository.raw_file(user_id, row.id)
                if blob is not None:
                    entries[f"attachments/{row.id}.enc"] = blob
    entries[KEYS] = json.dumps({
        "user_id": keys.user_id,
        "key_version": keys.key_version,
        "email_bidx": keys.email_bidx,
        "dek_wrapped": _b64(keys.dek_wrapped),
    }).encode("utf-8")

    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": settings.APP_VERSION,
        "created_at": now.isoformat(),
        "user_id": user_id,
        "key_version": keys.key_version,
        "tables": counts,
        "attachments": sum(1 for name in entries if name.startswith("attachments/")),
        "entries": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(entries.items())},
    }

    target = Path(directory) if directory else user_dir(user_id)
    target.mkdir(parents=True, exist_ok=True)
    name = _free_name(target, now)
    partial = target / f"{name}.part"
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for entry, data in entries.items():
                archive.writestr(entry, data)
        if settings.BACKUP_VERIFY_ON_WRITE:
            read_bundle(partial)  # a file that does not read back is not kept
        os.replace(partial, target / name)
    finally:
        partial.unlink(missing_ok=True)

    final = target / name
    _copy_offsite(final, user_id)
    prune(target, now)
    info = BackupInfo(name, now, final.stat().st_size, sum(c["live"] for c in counts.values()), manifest["attachments"])
    logger.info("Backup written user=%s rows=%d attachments=%d bytes=%d", user_id, info.rows, info.attachments, info.size)
    return info


def user_dir(user_id: int) -> Path:
    return Path(settings.BACKUP_DIR) / str(int(user_id))


def list_backups(user_id: int, directory: Optional[Path] = None) -> List[BackupInfo]:
    """Newest first. Reads only each file's manifest."""
    folder = Path(directory) if directory else user_dir(user_id)
    found: List[BackupInfo] = []
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        if not NAME.match(path.name):
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read(MANIFEST))
            found.append(BackupInfo(
                name=path.name, created_at=datetime.fromisoformat(manifest["created_at"]), size=path.stat().st_size,
                rows=sum(int(t.get("live", 0)) for t in manifest.get("tables", {}).values()),
                attachments=int(manifest.get("attachments", 0)),
            ))
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            logger.warning("Skipping an unreadable backup file in the list user=%s", user_id)
    return sorted(found, key=lambda b: (b.created_at, b.name), reverse=True)


def latest_backup_at(user_id: int, directory: Optional[Path] = None) -> Optional[datetime]:
    """From file names alone - cheap enough to ask at every sign-in."""
    folder = Path(directory) if directory else user_dir(user_id)
    if not folder.is_dir():
        return None
    stamps = [datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
              for m in (NAME.match(p.name) for p in folder.iterdir()) if m]
    return max(stamps) if stamps else None


def path_for(user_id: int, name: str) -> Path:
    if not NAME.match(name or ""):
        raise NotFoundException("Backup not found")
    path = user_dir(user_id) / name
    if not path.is_file():
        raise NotFoundException("Backup not found")
    return path


def prune(directory: Path, now: Optional[datetime] = None) -> int:
    """Delete backups older than BACKUP_RETENTION_DAYS - never the newest KEEP_AT_LEAST."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    dated = []
    for path in Path(directory).iterdir():
        match = NAME.match(path.name)
        if match:
            dated.append((datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc), path))
        elif path.suffix == ".part" and now.timestamp() - path.stat().st_mtime > 3600:
            path.unlink(missing_ok=True)
    dated.sort(reverse=True)
    removed = 0
    for stamp, path in dated[KEEP_AT_LEAST:]:
        if stamp < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


# ---------------------------------------------------------------- uploads


def save_upload(user_id: int, content: bytes) -> Tuple[str, Bundle]:
    """A backup file brought to the server for a restore - checked, kept for an hour, then discarded."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise BackupFormatError(f"A backup to restore is at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    bundle = read_bundle(content)
    folder = _upload_dir(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).timestamp()
    for old in folder.glob("*.budgetbak"):
        if now - old.stat().st_mtime > UPLOAD_TTL.total_seconds():
            old.unlink(missing_ok=True)
    upload_id = secrets.token_hex(16)
    (folder / f"{upload_id}.budgetbak").write_bytes(content)
    return upload_id, bundle


def load_upload(user_id: int, upload_id: str) -> Bundle:
    path = _upload_path(user_id, upload_id)
    return read_bundle(path)


def discard_upload(user_id: int, upload_id: str) -> None:
    try:
        _upload_path(user_id, upload_id).unlink(missing_ok=True)
    except NotFoundException:
        pass


# ---------------------------------------------------------------- reading


def read_bundle(source: Union[Path, str, bytes]) -> Bundle:
    try:
        archive = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    except (zipfile.BadZipFile, OSError):
        raise BackupFormatError("This is not a backup file") from None

    with archive:
        infos = {info.filename: info for info in archive.infolist()}
        if sum(info.file_size for info in infos.values()) > MAX_UNCOMPRESSED_BYTES:
            raise BackupFormatError("This file is too large to be a backup")
        if MANIFEST not in infos:
            raise BackupFormatError("This is not a backup file - it has no manifest")
        try:
            manifest = json.loads(archive.read(MANIFEST))
        except ValueError:
            raise BackupFormatError("The backup's manifest is damaged") from None
        if manifest.get("format") != FORMAT:
            raise BackupFormatError("This is not a backup file")
        if not isinstance(manifest.get("format_version"), int) or manifest["format_version"] > FORMAT_VERSION:
            raise BackupFormatError("This backup was made by a newer version of the app")

        expected = manifest.get("entries") or {}
        unexpected = set(infos) - set(expected) - {MANIFEST}
        if unexpected:
            raise BackupFormatError("The backup contains files it does not list")
        contents: Dict[str, bytes] = {}
        for name, digest in expected.items():
            if name not in infos:
                raise BackupFormatError("The backup is incomplete")
            try:
                data = archive.read(name)
            except (zipfile.BadZipFile, OSError, zlib_error()):
                raise BackupFormatError("The backup is damaged") from None
            if hashlib.sha256(data).hexdigest() != digest:
                raise BackupFormatError("The backup is damaged - a part of it does not match its checksum")
            contents[name] = data

    if KEYS not in contents:
        raise BackupFormatError("The backup is incomplete - it carries no keys")
    try:
        keys = json.loads(contents[KEYS])
        int(keys["user_id"])
    except (ValueError, KeyError, TypeError):
        raise BackupFormatError("The backup's keys are damaged") from None

    tables: Dict[str, List[RawRow]] = {}
    for table in ORDER:
        entry = f"{table}.enc"
        if entry not in contents:
            raise BackupFormatError("The backup is incomplete")
        rows = _load_rows(contents[entry], table)
        if len(rows) != int((manifest.get("tables", {}).get(table) or {}).get("rows", -1)):
            raise BackupFormatError("The backup is damaged - a row count does not match")
        tables[table] = rows

    files: Dict[int, bytes] = {}
    for name, data in contents.items():
        if name.startswith("attachments/"):
            match = re.fullmatch(r"attachments/(\d+)\.enc", name)
            if not match:
                raise BackupFormatError("The backup contains a file it cannot place")
            files[int(match.group(1))] = data
    return Bundle(manifest=manifest, keys=keys, tables=tables, files=files)


# ---------------------------------------------------------------- internals


def zlib_error():
    import zlib

    return zlib.error


def _dump_rows(table: str, rows: List[RawRow]) -> bytes:
    return json.dumps({
        "table": table,
        "rows": [{"id": r.id, "key_version": r.key_version, "is_deleted": r.is_deleted, "payload": _b64(r.payload)}
                 for r in rows],
    }).encode("utf-8")


def _load_rows(raw: bytes, table: str) -> List[RawRow]:
    try:
        document = json.loads(raw)
        if document.get("table") != table:
            raise ValueError
        return [
            RawRow(int(row["id"]), int(row["key_version"]), bool(row["is_deleted"]),
                   base64.b64decode(row["payload"], validate=True))
            for row in document["rows"]
        ]
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise BackupFormatError("The backup is damaged - a table cannot be read") from None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _free_name(folder: Path, now: datetime) -> str:
    base = f"budget-{now.astimezone(timezone.utc):%Y%m%dT%H%M%S}"
    name, n = f"{base}.budgetbak", 1
    while (folder / name).exists():
        name, n = f"{base}-{n}.budgetbak", n + 1
    return name


def _copy_offsite(path: Path, user_id: int) -> None:
    if not settings.BACKUP_OFFSITE_DIR:
        return
    try:
        target = Path(settings.BACKUP_OFFSITE_DIR) / str(int(user_id))
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / path.name)
    except OSError:
        logger.exception("Off-site backup copy failed user=%s - the local copy is kept", user_id)


def _upload_dir(user_id: int) -> Path:
    return Path(settings.TEMP_DIR) / "backup-uploads" / str(int(user_id))


def _upload_path(user_id: int, upload_id: str) -> Path:
    if not UPLOAD_ID.match(upload_id or ""):
        raise NotFoundException("That upload has expired - choose the file again")
    path = _upload_dir(user_id) / f"{upload_id}.budgetbak"
    if not path.is_file():
        raise NotFoundException("That upload has expired - choose the file again")
    return path
