"""
Restoring a .budgetbak (DAT-07, DAT-13..16; ARCHITECTURE.md §12.2-12.4).

UNLOCKING. A backup opens with the DEK it was made under, unwrapped by the
master key (current or retired) - the only key there is (ARCHITECTURE.md
5.2.1). In the app that is allowed only for YOUR OWN backup: the file's user id
and email_bidx must match the signed-in account. Otherwise a stolen file plus
any login on this server would turn the app into a decryption oracle for it.
scripts/restore.py passes no owner: whoever runs it holds .env already, and it
is how a backup reaches an account on a new server.

RE-ENCRYPTION. Every backed-up row is opened under its ORIGINAL AAD (old id,
old user) and written through an EncryptedRepository under the TARGET account's
key - so the two-step insert stays in one place (invariant 2) and every row
gets a new id and a fresh seal. Receipts are re-sealed the same way.

    fresh    the target account must hold no data (its preferences excepted)
    merge    adds to what is there; a row whose content already exists maps to
             the existing row instead of being added (DAT-15). One budget and
             one preferences row per account, so an existing one is kept
    verify   decrypts everything, resolves every reference, compares the
             backup with the live data - and WRITES NOTHING

A reference that resolves to no row in the backup aborts a fresh or merge
restore before commit: restoring a transaction onto the wrong account is worse
than not restoring it. Everything happens in one database transaction; a
failure rolls back and deletes any receipt file already written.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.dek import unwrap_dek, zero
from app.core.crypto.errors import DecryptionError, KeyNotAvailableError
from app.core.crypto.keyring import MasterKeyring
from app.core.crypto.user_cipher import UserCipher
from app.core.crypto.working_set import get_working_set
from app.core.exceptions import BusinessRuleException, ConflictException, ValidationException
from app.db.models import ENCRYPTED_TABLES
from app.db.repositories.attachment_repository import FILE_TABLE, AttachmentRepository
from app.db.repositories.backup_repository import RawRow, open_blob, open_row
from app.db.repositories.encrypted_repository import EncryptedRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service
from app.services.backup_service import references
from app.services.backup_service.bundle import BackupFormatError, Bundle
from app.services.backup_service.references import ORDER

MODES = ("fresh", "merge", "verify")
SINGLETONS = ("budgets", "user_preferences")  # one per account
VOLATILE = {("attachments", "file_key_version")}  # differs by key version, not by content


@dataclass(frozen=True)
class TableReport:
    table: str
    in_backup: int
    restored: int
    skipped: int  # merge: already there


@dataclass(frozen=True)
class Difference:
    table: str
    only_in_backup: int
    only_in_live: int


@dataclass(frozen=True)
class RestoreReport:
    mode: str
    tables: List[TableReport]
    attachments: int
    missing_files: int
    unresolved: List[str] = field(default_factory=list)
    differences: List[Difference] = field(default_factory=list)
    ok: bool = True


class RestoreError(BusinessRuleException):
    code = "RESTORE_FAILED"


# ---------------------------------------------------------------- unlocking


def unlock_source(
    bundle: Bundle,
    *,
    keyring: MasterKeyring,
    owner: Optional[Tuple[int, str]] = None,
) -> UserCipher:
    """A cipher that opens the backup's rows. `owner` (user id, email_bidx) limits it to that account's own files."""
    keys = bundle.keys
    user_id = bundle.user_id
    if owner is not None and (owner[0] != user_id or owner[1] != keys.get("email_bidx")):
        raise BusinessRuleException(
            "This backup belongs to a different account. The server owner can restore it with scripts/restore.py",
            extra={"other_account": True},
        )
    try:
        dek = unwrap_dek(_unb64(keys["dek_wrapped"]), keyring, user_id)
    except (DecryptionError, KeyNotAvailableError):
        raise BusinessRuleException(
            "This server's key does not open this backup - it was made under a master key this server does not hold"
        ) from None
    try:
        # The source cipher only ever OPENS; each row's own key_version builds its AAD.
        return UserCipher(user_id, dek, 1)
    finally:
        zero(dek)


# ---------------------------------------------------------------- restoring


def restore(
    db: Session,
    bundle: Bundle,
    target: UserCipher,
    source: UserCipher,
    *,
    mode: str,
) -> RestoreReport:
    if mode not in MODES:
        raise ValidationException(f"mode must be one of: {', '.join(MODES)}")
    decoded = _decrypt_all(bundle, source)
    blobs = _decrypt_files(bundle, source, decoded["attachments"])
    missing_files = sum(1 for raw, _ in decoded["attachments"] if not raw.is_deleted and raw.id not in blobs)

    if mode == "verify":
        return _verify(db, target, decoded, len(blobs), missing_files)

    existing = {table: _repo(table, db, target).list(include_deleted=True) for table in ORDER}
    if mode == "fresh":
        occupied = [t for t in ORDER if t != "user_preferences" and any(not r.is_deleted for r in existing[t])]
        if occupied:
            raise ConflictException(
                "A fresh restore needs an account with nothing in it - use merge to add to what is here",
                extra={"tables": occupied},
            )

    maps: Dict[str, Dict[int, int]] = {table: {} for table in ORDER}
    second: Dict[str, List[Tuple[int, dict]]] = {table: [] for table in ORDER}
    written: List[int] = []
    unresolved: List[str] = []
    reports: List[TableReport] = []
    try:
        for table in ORDER:
            repo = _repo(table, db, target)
            immediate, deferred = references.split(table)
            live = [r for r in existing[table] if not r.is_deleted]
            index = _index(table, existing[table], deferred) if mode == "merge" else {}
            if mode == "fresh" and table == "user_preferences":
                for record in live:
                    repo.soft_delete(record.id)
            restored = skipped = 0

            for raw, data in decoded[table]:
                if mode == "merge" and table in SINGLETONS and live:
                    maps[table][raw.id] = live[-1].id
                    skipped += 1
                    continue
                first, missing = references.apply(table, data, maps, immediate)
                unresolved.extend(missing)
                first, _ = references.apply(table, first, maps, deferred, clear=True)
                if mode == "merge":
                    key = _key(table, raw.is_deleted, first, maps, data, deferred)
                    if key in index:
                        maps[table][raw.id] = index[key]
                        skipped += 1
                        continue
                if table == "attachments":
                    first["file_key_version"] = target.key_version
                record = repo.create(first)
                maps[table][raw.id] = record.id
                if table == "attachments" and raw.id in blobs:
                    repo.write_file(record.id, blobs[raw.id])
                    written.append(record.id)
                if deferred:
                    second[table].append((record.id, data))
                if raw.is_deleted:
                    repo.soft_delete(record.id)
                restored += 1
            reports.append(TableReport(table, len(decoded[table]), restored, skipped))

        # Deferred references, now that every row has its new id.
        for table in ORDER:
            immediate, deferred = references.split(table)
            repo = _repo(table, db, target)
            for new_id, data in second[table]:
                step, _ = references.apply(table, data, maps, immediate)
                full, missing = references.apply(table, step, maps, deferred)
                unresolved.extend(missing)
                if table == "attachments":
                    full["file_key_version"] = target.key_version
                repo.update(new_id, full)

        if unresolved:
            raise RestoreError(
                "The backup refers to rows it does not contain, so nothing was restored",
                extra={"unresolved": _summarise(unresolved)},
            )
        audit_service.record(
            db, audit_service.RESTORE, user_id=target.user_id, entity="backups", cipher=target,
            detail={"mode": mode,
                    "restored": {r.table: r.restored for r in reports}, "skipped": {r.table: r.skipped for r in reports}},
        )
        db.commit()
    except Exception:
        db.rollback()
        cleaner = AttachmentRepository(db, target)
        for attachment_id in written:
            cleaner.delete_file(attachment_id)
        raise
    finally:
        # Rows were written around the working set; it must reload, not guess.
        get_working_set().drop(target.user_id)

    return RestoreReport(mode, reports, len(written), missing_files)


def snapshot(tables: Dict[str, Sequence[Tuple[int, bool, dict]]]) -> Dict[str, List[str]]:
    """
    DAT-14. Every table as sorted canonical strings, with each reference
    replaced by the referenced row's POSITION in its table. Row ids may
    differ between two exports; nothing else may.
    """
    positions = {
        table: {row_id: f"#{i}" for i, row_id in enumerate(sorted(r[0] for r in rows))}
        for table, rows in tables.items()
    }
    result: Dict[str, List[str]] = {}
    for table, rows in tables.items():
        items = []
        for _, deleted, data in rows:
            mapped, _ = references.apply(table, data, positions, references.refs(table))
            for volatile_table, name in VOLATILE:
                if volatile_table == table:
                    mapped.pop(name, None)
            items.append(json.dumps({"deleted": deleted, "data": mapped}, sort_keys=True, default=str))
        result[table] = sorted(items)
    return result


# ---------------------------------------------------------------- internals


def _decrypt_all(bundle: Bundle, source: UserCipher) -> Dict[str, List[Tuple[RawRow, dict]]]:
    decoded: Dict[str, List[Tuple[RawRow, dict]]] = {}
    for table in ORDER:
        rows = []
        for raw in bundle.tables[table]:
            try:
                rows.append((raw, open_row(source, table, raw)))
            except DecryptionError:
                raise BackupFormatError(
                    "A row in this backup does not open with that key - the file is damaged or belongs to another account"
                ) from None
        decoded[table] = rows
    return decoded


def _decrypt_files(bundle: Bundle, source: UserCipher, rows: Sequence[Tuple[RawRow, dict]]) -> Dict[int, bytes]:
    blobs: Dict[int, bytes] = {}
    for raw, data in rows:
        blob = bundle.files.get(raw.id)
        if blob is None:
            continue
        try:
            blobs[raw.id] = open_blob(source, FILE_TABLE, raw.id, int(data.get("file_key_version") or raw.key_version), blob)
        except DecryptionError:
            raise BackupFormatError("A receipt in this backup does not open - the file is damaged") from None
    return blobs


def _verify(db, target, decoded, attachments, missing_files) -> RestoreReport:
    identity = {table: {raw.id: raw.id for raw, _ in decoded[table]} for table in ORDER}
    unresolved: List[str] = []
    for table in ORDER:
        for _, data in decoded[table]:
            _, missing = references.apply(table, data, identity, references.refs(table))
            unresolved.extend(missing)

    backup = snapshot({t: [(raw.id, raw.is_deleted, data) for raw, data in decoded[t]] for t in ORDER})
    live = snapshot({t: [(r.id, r.is_deleted, r.data) for r in _repo(t, db, target).list(include_deleted=True)]
                     for t in ORDER})
    differences = []
    for table in ORDER:
        ours, theirs = Counter(backup[table]), Counter(live[table])
        only_backup, only_live = sum((ours - theirs).values()), sum((theirs - ours).values())
        if only_backup or only_live:
            differences.append(Difference(table, only_backup, only_live))
    tables = [TableReport(t, len(decoded[t]), 0, 0) for t in ORDER]
    return RestoreReport("verify", tables, attachments, missing_files,
                         unresolved=_summarise(unresolved), differences=differences,
                         ok=not unresolved and not missing_files)


def _index(table: str, records, deferred) -> Dict[tuple, int]:
    """Existing rows by the key a merge recognises them by."""
    index: Dict[tuple, int] = {}
    for record in records:
        index.setdefault(_record_key(table, record.is_deleted, record.data, deferred), record.id)
    return index


def _key(table: str, deleted: bool, first: dict, maps, original: dict, deferred) -> tuple:
    """A backed-up row's merge key: its content with references mapped where they can be."""
    content = dict(first)
    for path, target in deferred:
        if (table, path) in references.LINKS or "[]" in path:
            continue
        if "." in path:
            # A reference inside a nested object (accounts.interest.category_id,
            # ACC-37): it has to go back where it came from, or this row's key
            # could never match the same row already restored.
            name, field = path.split(".", 1)
            nested = original.get(name)
            if isinstance(nested, dict) and nested.get(field) is not None:
                mapped = maps.get(target, {}).get(nested[field], f"?{nested[field]}")
                content[name] = {**(content.get(name) or {}), field: mapped}
            continue
        value = original.get(path)
        content[path] = maps.get(target, {}).get(value, f"?{value}") if value is not None else None
    return _record_key(table, deleted, content, deferred)


def _record_key(table: str, deleted: bool, data: dict, deferred) -> tuple:
    if table == "budget_allocations":
        return ("allocation", deleted, data.get("budget_id"), data.get("category_id"))
    content = {k: v for k, v in data.items() if (table, k) not in references.LINKS and (table, k) not in VOLATILE}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return ("content", deleted, digest)


_REPOS: Dict[str, type] = {}


def _repo(table: str, db: Session, cipher: UserCipher) -> EncryptedRepository:
    if table == "attachments":
        return AttachmentRepository(db, cipher)
    if table == "transactions":
        return TransactionRepository(db, cipher)
    if table not in _REPOS:
        model = ENCRYPTED_TABLES[table]
        _REPOS[table] = type(f"{model.__name__}RestoreRepository", (EncryptedRepository,), {"model": model})
    return _REPOS[table](db, cipher)


def _summarise(paths: List[str]) -> List[str]:
    return [f"{path} x{count}" for path, count in sorted(Counter(paths).items())]


def _unb64(value: str) -> bytes:
    import base64

    return base64.b64decode(value, validate=True)
