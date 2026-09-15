"""
The account's own security (SEC-21..24; FEATURES.md §17; ARCHITECTURE.md §5.2.2).

Every operation here asks for the password again, however recently the user
unlocked: an unlocked phone left on a table must not be enough to change the
password, rotate the key or delete the account. A wrong password counts toward
the same lockout as a wrong unlock.

    change_password     a new password. The DEK is wrapped by the master key,
                        not the password, so no data is touched. Other
                        sessions end.
    rotate_dek          SEC-23: a NEW DEK. Every row, receipt, audit detail and
                        the profile re-sealed in one database transaction, then
                        wrapped under the master key. The real revoke.
    delete_account      SEC-21: every row, receipt, backup and the wrapped key,
                        gone. Confirmed by typing the account's email.

Rotation ends every OTHER session (SEC-24) and replaces the account's backups
on the server: a backup written before carries the old wrapped key, so it would
still open the old DEK (§17, "What neither can undo"). Copies already
downloaded are out of reach, and the screen says so.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.dek import wrap_dek, zero
from app.core.crypto.keyring import get_master_keyring
from app.core.crypto.provisioning import provision_user_keys
from app.core.crypto.session_keys import get_session_keyring
from app.core.crypto.user_cipher import UserCipher
from app.core.crypto.working_set import get_working_set
from app.core.exceptions import BusinessRuleException, InvalidCredentialsException, ValidationException
from app.db.models import ENCRYPTED_MODELS, User
from app.db.repositories.attachment_repository import AttachmentRepository
from app.db.repositories.attempt_repository import AttemptRepository
from app.db.repositories.rotation_repository import RotationRepository
from app.db.repositories.user_repository import UserRepository
from app.db.types import utcnow
from app.services import audit_service
from app.services.auth_service import session_service
from app.services.auth_service.passwords import hash_password, policy_problems, verify_password

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RotatedKey:
    sessions_ended: int
    backups_replaced: bool


# ---------------------------------------------------------------- the gate


def confirm_password(db: Session, user: User, password: str, ip_hash: Optional[str] = None) -> None:
    """The re-prompt. Raises INVALID_CREDENTIALS, and counts toward the unlock lockout."""
    from app.services.auth_service.auth_service import _check_lockout

    attempts = AttemptRepository(db)
    _check_lockout(attempts, user.email_bidx)
    if not verify_password(password or "", user.password_hash):
        attempts.record(kind="unlock", success=False, email_bidx=user.email_bidx, user_id=user.id, ip_hash=ip_hash)
        audit_service.record(db, audit_service.UNLOCK_FAILED, user_id=user.id, ip_hash=ip_hash)
        db.commit()
        raise InvalidCredentialsException("That password is not right")


# ------------------------------------------------------------- operations


def change_password(
    db: Session, user: User, session_id: str, cipher: UserCipher, current: str, new: str, *, ip_hash: Optional[str] = None
) -> int:
    confirm_password(db, user, current, ip_hash)
    problems = policy_problems(new)
    if problems:
        raise ValidationException("The new password needs " + ", ".join(problems))
    if verify_password(new, user.password_hash):
        raise BusinessRuleException("That is the password you already have")
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    ended = session_service.end_all(db, user.id, "password-change", except_session=session_id)
    audit_service.record(db, audit_service.PASSWORD_CHANGE, user_id=user.id, ip_hash=ip_hash, cipher=cipher,
                         detail={"sessions_ended": len(ended)})
    db.commit()
    return len(ended)


def rotate_dek(
    db: Session, user: User, session_id: str, password: str, *, ip_hash: Optional[str] = None
) -> RotatedKey:
    """SEC-23. A new data key for everything, in one transaction."""
    confirm_password(db, user, password, ip_hash)
    keyring = get_master_keyring()
    users = UserRepository(db)
    old_dek = users.unwrap_dek(user, keyring)
    old = UserCipher(user.id, old_dek, keyring.current_version)
    zero(old_dek)
    keys = provision_user_keys()
    new = UserCipher(user.id, keys.dek, keyring.current_version)
    repo = RotationRepository(db)

    pairs = []
    try:
        receipts = [(r.id, r.data) for r in AttachmentRepository(db, old).list(include_deleted=True)]
        pairs = repo.reseal_files(old, new, receipts)
        counts: Dict[str, int] = {}
        for model in ENCRYPTED_MODELS:
            transform = (lambda d: {**d, "file_key_version": new.key_version}) if model.__tablename__ == "attachments" else None
            counts[model.__tablename__] = repo.reseal_rows(model, old, new, transform)
        counts["audit_log"] = repo.reseal_audit(old, new)
        repo.reseal_profile(user, old, new)

        user.dek_wrapped = wrap_dek(keys.dek, keyring, user.id)
        user.key_version = keyring.current_version
        ended = session_service.end_all(db, user.id, "dek-rotated", except_session=session_id)
        audit_service.record(db, audit_service.DEK_ROTATE, user_id=user.id, ip_hash=ip_hash, cipher=new,
                             detail={"rows": sum(counts.values()), "receipts": len(pairs), "sessions_ended": len(ended)})
        db.commit()
    except Exception:
        db.rollback()
        for partial, _ in pairs:
            partial.unlink(missing_ok=True)
        keys.wipe()
        raise

    for partial, final in pairs:
        os.replace(partial, final)
    # The old key is gone from every session; this one carries on under the new key.
    keyring_ = get_session_keyring()
    keyring_.lock_user(user.id)
    keyring_.unlock(session_id, user.id, bytearray(keys.dek), keyring.current_version)
    get_working_set().drop(user.id)
    keys.wipe()
    logger.info("DEK rotated user=%s receipts=%d sessions_ended=%d", user.id, len(pairs), len(ended))
    return RotatedKey(len(ended), _replace_backups(db, user.id))


def delete_account(
    db: Session, user: User, cipher: UserCipher, password: str, confirm_email: str, *, ip_hash: Optional[str] = None
) -> Dict[str, int]:
    """SEC-21. Irreversible. The email typed must match the account's, exactly apart from case and spaces."""
    confirm_password(db, user, password, ip_hash)
    profile = UserRepository(db).read_profile(user, cipher)
    if (confirm_email or "").strip().casefold() != str(profile.get("email", "")).strip().casefold():
        raise ValidationException("Type this account's email address exactly to confirm")
    return purge_user(db, user.id, ip_hash=ip_hash, reason="self")


def purge_user(db: Session, user_id: int, *, ip_hash: Optional[str] = None, reason: str) -> Dict[str, int]:
    """Remove a user completely - by themselves or by the admin. Needs no key: it decrypts nothing."""
    from app.services.backup_service import bundle
    from app.services.backup_service.scheduler import get_scheduler

    get_scheduler().cancel(user_id)
    counts = RotationRepository(db).purge_user(user_id)
    # Plaintext verb, no detail: the key a detail would be sealed under is being destroyed.
    audit_service.record(db, audit_service.ACCOUNT_DELETE, user_id=user_id, entity="users", entity_id=user_id,
                         ip_hash=ip_hash)
    db.commit()

    get_session_keyring().lock_user(user_id)
    get_working_set().drop(user_id)
    for folder in (Path(settings.UPLOAD_DIR) / str(user_id), bundle.user_dir(user_id),
                   Path(settings.TEMP_DIR) / "backup-uploads" / str(user_id)):
        shutil.rmtree(folder, ignore_errors=True)
    logger.info("Account deleted user=%s reason=%s rows=%d", user_id, reason, sum(counts.values()))
    return counts


def _replace_backups(db: Session, user_id: int) -> bool:
    """After a key change: a fresh backup, then the older ones (carrying the old wrapped key) deleted."""
    from app.services.backup_service import bundle

    try:
        latest = bundle.write_backup(db, user_id)
        folder = bundle.user_dir(user_id)
        for path in folder.iterdir():
            if path.name != latest.name and bundle.NAME.match(path.name):
                path.unlink(missing_ok=True)
        return True
    except Exception:
        logger.exception("Could not replace old backups after a key change user=%s - delete them by hand", user_id)
        return False
