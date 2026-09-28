"""
Sign-in, lock and unlock - ARCHITECTURE.md section 6.

    Password    guards the account     bcrypt, lockout after 5 failures / 15 min
    PIN         guards the SCREEN      unlocks an already-signed-in session
    DEK         guards the DATA        in memory only while unlocked

Three states a signed-in browser can be in, and what each request gets:

    unlocked    valid access token + keyring entry   -> data
    locked      valid access token, no keyring entry -> 401 SESSION_LOCKED,
                                                        PIN screen
    signed out  no valid session                     -> 401, login screen

"Locked" covers the auto-lock, the lock button AND a process restart (SEC-27):
IIS stopping the app empties the keyring but leaves the cookies valid, so the
next request simply finds the session locked.

Unlocking - by PIN or by password - makes the server unwrap the DEK again with
the master key. Neither secret derives anything.
"""

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.blind_index import get_blind_indexer
from app.core.crypto.keyring import get_master_keyring
from app.core.crypto.session_keys import get_session_keyring
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    AccountLockedException,
    AuthenticationException,
    BusinessRuleException,
    InvalidCredentialsException,
    PermissionDeniedException,
    SessionRevokedException,
)
from app.db.models import User
from app.db.repositories.attempt_repository import AttemptRepository, seconds_until_free
from app.db.repositories.user_repository import UserRepository
from app.db.types import utcnow
from app.services import audit_service, transaction_service
from app.services.auth_service import passkey_service, session_service
from app.services.auth_service.passwords import hash_password, verify_password
from app.services.auth_service.pin_service import hash_pin, verify_pin

logger = logging.getLogger(__name__)

# Password-checking kinds that share one lockout per email. A successful
# password reset (SEC-30) counts as a success, so it clears the lockout.
PASSWORD_KINDS = ("login", "unlock", "reset")

_dummy_hash: Optional[str] = None


def _burn_a_bcrypt(password: str) -> None:
    """Spend the same time as a real check, so 'no such email' is not faster."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("an unused password to compare against")
    verify_password(password, _dummy_hash)


def _check_lockout(attempts: AttemptRepository, email_bidx: str) -> None:
    failures = attempts.recent_failures(
        kinds=PASSWORD_KINDS, window_minutes=settings.LOGIN_LOCKOUT_MINUTES, email_bidx=email_bidx
    )
    if len(failures) >= settings.LOGIN_MAX_ATTEMPTS:
        wait = seconds_until_free(failures, settings.LOGIN_LOCKOUT_MINUTES)
        raise AccountLockedException(
            f"Too many attempts. Try again in {max(1, round(wait / 60))} minute(s).",
            extra={"retry_after_seconds": wait},
        )


@dataclass
class Profile:
    user_id: int
    is_admin: bool
    pin_set: bool
    locked: bool
    email: Optional[str] = None
    passkey_set: bool = False  # SEC-12 - the lock screen offers the passkey
    display_name: Optional[str] = None


def login(db: Session, email: str, password: str, ip_hash: Optional[str] = None,
          device: Optional[str] = None) -> session_service.IssuedSession:
    indexer = get_blind_indexer()
    bidx = indexer.email(email)
    attempts = AttemptRepository(db)
    _check_lockout(attempts, bidx)

    user = UserRepository(db).get_by_email_bidx(bidx)
    if user is None:
        _burn_a_bcrypt(password)
        ok = False
    else:
        ok = verify_password(password, user.password_hash)

    if not ok:
        attempts.record(kind="login", success=False, email_bidx=bidx,
                        user_id=user.id if user else None, ip_hash=ip_hash)
        audit_service.record(db, audit_service.LOGIN_FAILED, user_id=user.id if user else None, ip_hash=ip_hash)
        db.commit()
        raise InvalidCredentialsException("That email and password do not match")

    if not user.is_active:
        db.commit()
        raise PermissionDeniedException("This account has been disabled")

    attempts.record(kind="login", success=True, email_bidx=bidx, user_id=user.id, ip_hash=ip_hash)
    keyring = get_master_keyring()
    dek = UserRepository(db).unwrap_dek(user, keyring)
    issued = session_service.start_session(db, user, dek, keyring, device=device)
    _warm(db, issued.session_id)
    user.last_login_at = utcnow()
    user.pin_failed_count = 0
    audit_service.record(db, audit_service.LOGIN, user_id=user.id, ip_hash=ip_hash)
    db.commit()
    return issued


def lock(session_id: str) -> None:
    """The lock button, the idle timer and blur all end up here."""
    get_session_keyring().lock(session_id)


def unlock_with_pin(db: Session, user: User, session_id: str, pin: str, ip_hash: Optional[str] = None) -> None:
    if not settings.PIN_ENABLED or not user.pin_hash:
        raise BusinessRuleException("No PIN is set - unlock with your password")
    if get_session_keyring().is_unlocked(session_id):
        return
    if not verify_pin(pin, user.pin_hash):
        user.pin_failed_count = (user.pin_failed_count or 0) + 1
        audit_service.record(db, audit_service.UNLOCK_FAILED, user_id=user.id, ip_hash=ip_hash)
        if user.pin_failed_count >= settings.PIN_MAX_ATTEMPTS:
            # Five wrong PINs: the PIN stops being an option for this session.
            # The session ends and only the password can start a new one.
            user.pin_failed_count = 0
            session_service.end_session(db, session_id, "pin_lockout")
            audit_service.record(db, audit_service.PIN_LOCKOUT, user_id=user.id, ip_hash=ip_hash)
            db.commit()
            raise SessionRevokedException("Too many wrong PINs. Sign in with your password.")
        remaining = settings.PIN_MAX_ATTEMPTS - user.pin_failed_count
        db.commit()
        raise InvalidCredentialsException(
            f"Wrong PIN. {remaining} attempt{'s' if remaining != 1 else ''} left.",
            extra={"attempts_left": remaining},
        )
    user.pin_failed_count = 0
    _reunlock(db, user, session_id, ip_hash)


def unlock_with_passkey(db: Session, user: User, session_id: str, answer: Mapping[str, str],
                        ip_hash: Optional[str] = None) -> None:
    """
    SEC-12. The passkey only DECIDES, like the PIN: once it verifies, the DEK
    comes back through the same _reunlock, unwrapped with the master key.
    """
    if get_session_keyring().is_unlocked(session_id):
        return
    try:
        passkey_service.verify(user, session_id, **answer)
    except InvalidCredentialsException:
        audit_service.record(db, audit_service.UNLOCK_FAILED, user_id=user.id, ip_hash=ip_hash)
        db.commit()
        raise
    user.pin_failed_count = 0
    _reunlock(db, user, session_id, ip_hash)


def unlock_with_password(db: Session, user: User, session_id: str, password: str, ip_hash: Optional[str] = None) -> None:
    attempts = AttemptRepository(db)
    _check_lockout(attempts, user.email_bidx)
    if get_session_keyring().is_unlocked(session_id):
        return
    if not verify_password(password, user.password_hash):
        attempts.record(kind="unlock", success=False, email_bidx=user.email_bidx, user_id=user.id, ip_hash=ip_hash)
        audit_service.record(db, audit_service.UNLOCK_FAILED, user_id=user.id, ip_hash=ip_hash)
        db.commit()
        raise InvalidCredentialsException("Wrong password")
    attempts.record(kind="unlock", success=True, email_bidx=user.email_bidx, user_id=user.id, ip_hash=ip_hash)
    user.pin_failed_count = 0
    _reunlock(db, user, session_id, ip_hash)


def _reunlock(db: Session, user: User, session_id: str, ip_hash: Optional[str]) -> None:
    keyring = get_master_keyring()
    dek = UserRepository(db).unwrap_dek(user, keyring)
    session_service.unlock_session(session_id, user, dek, keyring)
    _warm(db, session_id)
    audit_service.record(db, audit_service.UNLOCK, user_id=user.id, ip_hash=ip_hash)
    db.commit()


def _warm(db: Session, session_id: str) -> None:
    """
    Decrypt the working set now, while the user is still on the unlock screen,
    so the first screen after it is a warm read (ARCHITECTURE.md 5.6). Never
    fatal: a failed warm-up only means the first read loads it instead.
    """
    cipher = get_session_keyring().cipher_for(session_id)
    if cipher is None:
        return
    try:
        # DAT-08: a backup at sign-in when the newest is over BACKUP_INTERVAL_HOURS old.
        from app.services.backup_service.scheduler import get_scheduler

        get_scheduler().on_sign_in(cipher.user_id)
    except Exception:
        logger.exception("Could not check the backup age at sign-in")
    if not settings.CACHE_WARM_ON_LOGIN:
        return
    try:
        transaction_service.warm(db, cipher)
    except Exception:
        logger.exception("Working set warm-up failed; the first read will load it")


def set_pin(db: Session, user: User, cipher: UserCipher, pin: str, current_password: Optional[str] = None,
            ip_hash: Optional[str] = None) -> None:
    """
    Set the PIN. Changing an existing one needs the password: an unlocked
    phone left on a table should not be enough to replace the PIN.
    """
    if not settings.PIN_ENABLED:
        raise BusinessRuleException("PIN lock is turned off on this server")
    if user.pin_hash:
        if not current_password or not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsException("Enter your password to change the PIN")
    user.pin_hash = hash_pin(pin)
    user.pin_failed_count = 0
    audit_service.record(db, audit_service.PIN_SET, user_id=user.id, ip_hash=ip_hash, cipher=cipher,
                         detail={"changed": bool(current_password)})
    db.commit()


def audit_passkey(db: Session, ctx: Any, *, added: bool, ip_hash: Optional[str] = None) -> None:
    """SEC-12. Commits the passkey change with its audit entry."""
    audit_service.record(db, audit_service.PASSKEY_ADD if added else audit_service.PASSKEY_REMOVE,
                         user_id=ctx.user.id, ip_hash=ip_hash)
    db.commit()


def logout(db: Session, session_id: Optional[str], user_id: Optional[int] = None, ip_hash: Optional[str] = None) -> None:
    if session_id:
        session_service.end_session(db, session_id, "logout")
        audit_service.record(db, audit_service.LOGOUT, user_id=user_id, ip_hash=ip_hash)
        db.commit()


def profile(db: Session, user: User, session_id: str) -> Profile:
    """
    What /auth/me returns. While locked, only the id and flags: the email and
    name live in profile_enc, sealed under the DEK that is not in memory.
    """
    cipher = get_session_keyring().cipher_for(session_id)
    result = Profile(
        user_id=user.id, is_admin=user.is_admin, pin_set=bool(user.pin_hash and settings.PIN_ENABLED),
        locked=cipher is None, passkey_set=passkey_service.has_passkeys(user),
    )
    if cipher is not None:
        data = UserRepository(db).read_profile(user, cipher)
        result.email = data.get("email")
        result.display_name = data.get("display_name")
    return result


def require_active(user: Optional[User]) -> User:
    if user is None or not user.is_active:
        raise AuthenticationException("Sign in to continue")
    return user
