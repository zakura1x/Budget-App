"""
Recovery with the 12-word phrase - SEC-15, ARCHITECTURE.md section 5.2.1.

Recovering the key without resetting the password would be an ornament: you
would hold the key and still have no way to sign in. So one call does both:

    phrase -> finds the account (no email needed - works with .env lost)
           -> unwraps the DEK
           -> re-wraps it under the CURRENT master key        (new .env ok)
           -> reads the email back out of profile_enc and
              rebuilds email_bidx under the CURRENT pepper      (new .env ok)
           -> sets the new password, clears the PIN
           -> ends every other session of that account
           -> signs this browser in

It bypasses the password, so it is rate-limited hard: RECOVERY_MAX_ATTEMPTS
wrong phrases per IP per RECOVERY_LOCKOUT_MINUTES. A MALFORMED phrase (a
typo, a wrong word count) is rejected before any account is tried and does
not use up an attempt - it reveals nothing about any account.

The PIN is cleared because its hash is peppered with PIN_PEPPER from .env:
after a .env loss the old PIN could never verify again. The user sets a new
one straight after.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.blind_index import get_blind_indexer
from app.core.crypto.dek import wrap_dek
from app.core.crypto.keyring import get_master_keyring
from app.core.crypto.recovery import find_user_by_phrase, validate_phrase
from app.core.crypto.session_keys import get_session_keyring
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import (
    InvalidCredentialsException,
    PermissionDeniedException,
    RateLimitException,
    ValidationException,
)
from app.db.repositories.attempt_repository import AttemptRepository, seconds_until_free
from app.db.repositories.user_repository import UserRepository
from app.db.types import utcnow
from app.services import audit_service
from app.services.auth_service import session_service
from app.services.auth_service.passwords import hash_password, policy_problems


def recover(db: Session, *, phrase: str, new_password: str, ip_hash: Optional[str] = None) -> session_service.IssuedSession:
    attempts = AttemptRepository(db)
    window = settings.RECOVERY_LOCKOUT_MINUTES
    failures = attempts.recent_failures(kinds=("recovery",), window_minutes=window, ip_hash=ip_hash)
    if len(failures) >= settings.RECOVERY_MAX_ATTEMPTS:
        wait = seconds_until_free(failures, window)
        raise RateLimitException(
            f"Too many recovery attempts. Try again in {max(1, round(wait / 60))} minute(s).",
            extra={"retry_after_seconds": wait},
        )

    validate_phrase(phrase, settings.RECOVERY_PHRASE_LANGUAGE)  # typo -> 422, no attempt used
    problems = policy_problems(new_password)
    if problems:
        raise ValidationException("The new password needs " + ", ".join(problems))

    users = UserRepository(db)
    found = find_user_by_phrase(phrase, users.recovery_candidates(), settings.RECOVERY_PHRASE_LANGUAGE)
    if found is None:
        attempts.record(kind="recovery", success=False, ip_hash=ip_hash)
        audit_service.record(db, audit_service.RECOVERY_FAILED, ip_hash=ip_hash)
        db.commit()
        raise InvalidCredentialsException("That phrase does not match any account")

    user_id, dek = found
    user = users.get(user_id)
    if not user.is_active:
        # A disabled account stays disabled - the phrase is not a way around the admin.
        db.commit()
        raise PermissionDeniedException("This account has been disabled")
    keyring = get_master_keyring()
    cipher = UserCipher(user.id, dek, keyring.current_version)
    profile = users.read_profile(user, cipher)

    # Re-home the account under whatever .env is loaded now.
    user.dek_wrapped = wrap_dek(dek, keyring, user.id)
    user.key_version = keyring.current_version
    if profile.get("email"):
        user.email_bidx = get_blind_indexer().email(profile["email"])
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.pin_hash = None
    user.pin_failed_count = 0

    # Whoever else is signed in to this account is signed out.
    session_service.end_all(db, user.id, "recovery")
    get_session_keyring().lock_user(user.id)

    attempts.record(kind="recovery", success=True, user_id=user.id, ip_hash=ip_hash)
    audit_service.record(db, audit_service.RECOVERY, user_id=user.id, ip_hash=ip_hash, cipher=cipher,
                         detail={"rewrapped": True})
    issued = session_service.start_session(db, user, dek, keyring)
    db.commit()
    return issued
