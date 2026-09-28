"""
Account creation.

Phase 1 needs this for scripts/bootstrap_user.py; Phase 2 wraps it in the
registration-code gate, the rate limit and the audit trail (SEC-19/25/26).
The part that must be right from the first account onward is here already:

  * the DEK is created and wrapped under the master key in the same insert
  * MAX_USERS is enforced
  * the first account becomes admin when FIRST_USER_IS_ADMIN is set
  * the user's preferences row is written encrypted, through the same
    two-step insert every data row uses
"""

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.blind_index import BlindIndexer, get_blind_indexer
from app.core.crypto.keyring import MasterKeyring, get_master_keyring
from app.core.crypto.provisioning import provision_user_keys
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import BusinessRuleException, ConflictException, ValidationException
from app.db.repositories.preferences_repository import PreferencesRepository
from app.db.repositories.user_repository import UserRepository
from app.services.auth_service.passwords import hash_password, policy_problems

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class CreatedAccount:
    user_id: int
    is_admin: bool


def default_preferences() -> dict:
    """A new user's preferences, from the defaults in .env. No currency."""
    return {
        "theme": "system",
        "palette": "classic",
        "budget_period": settings.DEFAULT_BUDGET_PERIOD,
        "month_start_day": settings.DEFAULT_MONTH_START_DAY,
        "week_start_day": settings.DEFAULT_WEEK_START_DAY,
        "daily_allowance_mode": settings.DAILY_ALLOWANCE_MODE,
        "carry_over": settings.DEFAULT_CARRY_OVER_UNSPENT,
        "alert_warn_threshold_pct": settings.ALERT_WARN_THRESHOLD_PCT,
        "alert_pace_enabled": settings.ALERT_PACE_ENABLED,
        "auto_lock_minutes": settings.PIN_AUTO_LOCK_MINUTES,
        # BUD-17 (user, 2026-09-28): round suggestions up to PHP 100, and remind when spending drifts.
        "budget_round_step": 100,
        "budget_suggestion_nudge": True,
        # GOA-12 (user, 2026-09-28): offer to set money aside when income of PHP 5,000 or more lands.
        "payday_prompt_min": 5000,
        # UX-14 (2026-09-28): a short vibration on keys, saves and deletes, where the phone allows it.
        "haptics": True,
    }


def create_account(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: Optional[str] = None,
    keyring: Optional[MasterKeyring] = None,
    indexer: Optional[BlindIndexer] = None,
    bcrypt_rounds: Optional[int] = None,
) -> CreatedAccount:
    """Create a user, its keys and its preferences. The caller commits."""
    keyring = keyring or get_master_keyring()
    indexer = indexer or get_blind_indexer()
    email = email.strip()

    if not _EMAIL.match(email):
        raise ValidationException("That does not look like an email address")
    problems = policy_problems(password)
    if problems:
        raise ValidationException("The password needs " + ", ".join(problems))

    users = UserRepository(session)
    existing = users.count()
    if existing >= settings.MAX_USERS:
        raise BusinessRuleException(f"This installation is limited to {settings.MAX_USERS} accounts (MAX_USERS)")
    if users.get_by_email_bidx(indexer.email(email)) is not None:
        raise ConflictException("An account with that email already exists")

    is_admin = settings.FIRST_USER_IS_ADMIN and existing == 0
    keys = provision_user_keys()
    try:
        user = users.create(
            email=email,
            password_hash=hash_password(password, bcrypt_rounds),
            is_admin=is_admin,
            keys=keys,
            keyring=keyring,
            indexer=indexer,
            display_name=display_name,
        )
        cipher = UserCipher(user.id, keys.dek, keyring.current_version)
        PreferencesRepository(session, cipher).create(default_preferences())
    finally:
        keys.wipe()
    return CreatedAccount(user_id=user.id, is_admin=is_admin)


# ======================================================================
# Signup through the API - the registration-code gate (SEC-19/25/26)
# ======================================================================


def register(
    db: Session,
    *,
    email: str,
    password: str,
    registration_code: str,
    display_name: Optional[str] = None,
    ip_hash: Optional[str] = None,
    device: Optional[str] = None,
):
    """
    Create an account from the signup screen and sign it in.

    The registration code is the ONLY gate on signup, so it is treated like a
    secret: compared in constant time, limited to REGISTRATION_MAX_ATTEMPTS
    failures per IP per window, and every failure audited. MAX_USERS still
    caps the total, so a leaked code cannot create unlimited accounts.

    Returns (CreatedAccount, IssuedSession). The caller sets the cookies.
    """
    import hmac

    from app.db.repositories.attempt_repository import AttemptRepository, seconds_until_free
    from app.core.exceptions import PermissionDeniedException, RateLimitException
    from app.services import audit_service
    from app.services.auth_service import session_service

    if not settings.registration_open:
        raise PermissionDeniedException("Sign-up is closed on this server", extra={"reason": "REGISTRATION_CLOSED"})
    if settings.SINGLE_USER_MODE and UserRepository(db).count() >= 1:
        raise PermissionDeniedException("Sign-up is closed on this server", extra={"reason": "REGISTRATION_CLOSED"})

    attempts = AttemptRepository(db)
    window = settings.REGISTRATION_ATTEMPT_WINDOW_MINUTES
    failures = attempts.recent_failures(kinds=("register",), window_minutes=window, ip_hash=ip_hash)
    if len(failures) >= settings.REGISTRATION_MAX_ATTEMPTS:
        wait = seconds_until_free(failures, window)
        raise RateLimitException(
            f"Too many sign-up attempts. Try again in {max(1, round(wait / 60))} minute(s).",
            extra={"retry_after_seconds": wait},
        )

    expected = settings.REGISTRATION_CODE.get_secret_value().strip().encode("utf-8")
    given = (registration_code or "").strip().encode("utf-8")
    if not hmac.compare_digest(given, expected):
        attempts.record(kind="register", success=False, ip_hash=ip_hash)
        audit_service.record(db, audit_service.REGISTER_REJECTED, ip_hash=ip_hash)
        db.commit()
        raise PermissionDeniedException("That registration code is not valid", extra={"reason": "INVALID_CODE"})

    account = create_account(db, email=email, password=password, display_name=display_name)
    attempts.record(kind="register", success=True, user_id=account.user_id, ip_hash=ip_hash)

    users = UserRepository(db)
    user = users.get(account.user_id)
    keyring = get_master_keyring()
    dek = users.unwrap_dek(user, keyring)
    audit_service.record(db, audit_service.REGISTER, user_id=user.id, ip_hash=ip_hash,
                         cipher=UserCipher(user.id, dek, keyring.current_version),
                         detail={"admin": account.is_admin})
    issued = session_service.start_session(db, user, dek, keyring, device=device)
    db.commit()
    return account, issued
