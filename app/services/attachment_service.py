"""
attachment_service - a receipt photo on a transaction (TXN-15, DAT-17, DAT-19).

One receipt per transaction - and a transfer's two legs share ONE (2026-09-30),
so attaching or removing from either leg does it for both. The file is checked twice before anything is
written - by its extension and by its first bytes, which must agree - and is
never trusted for anything beyond being stored and handed back. It is sealed
with the user's DEK and written to uploads/<user_id>/<id>.enc
(AttachmentRepository); the row names the transaction and the transaction
names the row, both inside ciphertext, and the backup remaps both (§12.3).

Replacing a receipt soft-deletes the old row and removes its file only after
the new one has committed, so a failure midway never leaves a transaction
pointing at nothing.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, NotFoundException, ValidationException
from app.db.repositories.attachment_repository import AttachmentRepository
from app.db.repositories.transaction_repository import TransactionRepository
from app.services import audit_service

MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".pdf": "application/pdf",
}
NAME_MAX = 120


@dataclass(frozen=True)
class AttachmentView:
    id: int
    transaction_id: int
    filename: str
    mime: str
    size: int


def sniff(content: bytes) -> Optional[str]:
    """The type the bytes actually are - not what the name claims."""
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:5] == b"%PDF-":
        return "application/pdf"
    if content[4:8] == b"ftyp" and content[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
        return "image/heic"
    return None


def _legs(transactions: TransactionRepository, record: Any) -> List[Any]:
    """
    The rows a receipt belongs on: the transaction, and for a transfer its other
    leg too (2026-09-30, user: a screenshot of a payment to a loan). A transfer
    is ONE movement of money, so its proof shows from either account's page.
    """
    legs = [record]
    pair_id = record.data.get("pair_id") if record.data.get("type") == "transfer" else None
    if pair_id:
        pair = transactions.get(int(pair_id))
        if pair is not None:
            legs.append(pair)
    return legs


def attach(db: Session, cipher: UserCipher, transaction_id: int, filename: str, content: bytes) -> AttachmentView:
    name, mime = _check(filename, content)
    transactions = TransactionRepository(db, cipher)
    record = transactions.get(transaction_id)
    if record is None:
        raise NotFoundException("Transaction not found")
    if record.data.get("type") == "adjustment":
        raise BusinessRuleException("A balance adjustment has no receipt")

    repo = AttachmentRepository(db, cipher)
    legs = _legs(transactions, record)
    # Before 2026-09-30 a transfer's legs could each carry a receipt of their own.
    previous = sorted({int(leg.data["attachment_id"]) for leg in legs if leg.data.get("attachment_id")})
    row = repo.create({
        "transaction_id": transaction_id, "filename": name, "mime": mime, "size": len(content),
        "file_key_version": cipher.key_version, "uploaded_on": date.today().isoformat(),
    })
    written = False
    try:
        repo.write_file(row.id, content)
        written = True
        for old in previous:
            repo.soft_delete(old)
        for leg in legs:
            transactions.update(leg.id, {**leg.data, "attachment_id": row.id})
        audit_service.record(
            db, audit_service.CREATE, user_id=cipher.user_id, entity="attachments", entity_id=row.id,
            cipher=cipher, detail={"transaction_id": transaction_id, "size": len(content)},
        )
        db.commit()
    except Exception:
        db.rollback()
        if written:
            repo.delete_file(row.id)
        raise
    for old in previous:
        repo.delete_file(old)
    return AttachmentView(row.id, transaction_id, name, mime, len(content))


def read(db: Session, cipher: UserCipher, attachment_id: int) -> Tuple[AttachmentView, bytes]:
    repo = AttachmentRepository(db, cipher)
    record = repo.get(attachment_id)
    if record is None:
        raise NotFoundException("Receipt not found")
    data = record.data
    try:
        content = repo.read_file(attachment_id, int(data.get("file_key_version") or 1))
    except FileNotFoundError:
        raise NotFoundException("The receipt file is missing from the server") from None
    view = AttachmentView(record.id, int(data["transaction_id"]), str(data.get("filename", "receipt")),
                          str(data.get("mime", "application/octet-stream")), int(data.get("size", len(content))))
    return view, content


def remove(db: Session, cipher: UserCipher, transaction_id: int) -> None:
    transactions = TransactionRepository(db, cipher)
    record = transactions.get(transaction_id)
    if record is None:
        raise NotFoundException("Transaction not found")
    legs = _legs(transactions, record)
    ids = sorted({int(leg.data["attachment_id"]) for leg in legs if leg.data.get("attachment_id")})
    if not ids:
        raise NotFoundException("This transaction has no receipt")
    repo = AttachmentRepository(db, cipher)
    for attachment_id in ids:
        repo.soft_delete(attachment_id)
        audit_service.record(
            db, audit_service.DELETE, user_id=cipher.user_id, entity="attachments", entity_id=attachment_id,
            cipher=cipher, detail={"transaction_id": transaction_id},
        )
    for leg in legs:
        if leg.data.get("attachment_id"):
            transactions.update(leg.id, {**leg.data, "attachment_id": None})
    db.commit()
    for attachment_id in ids:
        repo.delete_file(attachment_id)


def _check(filename: str, content: bytes) -> Tuple[str, str]:
    if not content:
        raise ValidationException("The file is empty")
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise ValidationException(f"A receipt is at most {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB")
    name = re.sub(r"[\x00-\x1f\x7f]", "", PurePath(str(filename or "receipt").replace("\\", "/")).name).strip()
    name = name[:NAME_MAX] or "receipt"
    extension = PurePath(name.lower()).suffix
    allowed = {e.strip().lower() for e in settings.ALLOWED_EXTENSIONS.split(",") if e.strip()}
    if extension not in MIME_BY_EXTENSION or extension not in allowed:
        raise ValidationException("A receipt is a JPEG, PNG, HEIC photo or a PDF")
    mime = MIME_BY_EXTENSION[extension]
    if sniff(content) != mime:
        raise ValidationException("That file is not the kind of file its name says")
    return name, mime
