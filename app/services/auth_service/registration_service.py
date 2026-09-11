"""
Account creation.

Phase 1 needs this for scripts/bootstrap_user.py; Phase 2 wraps it in the
registration-code gate, the rate limit and the audit trail (SEC-19/25/26).
The part that must be right from the first account onward is here already:

  * the DEK and its recovery phrase are created together - no DEK ever
    exists without its second wrap (SEC-14)
  * MAX_USERS is enforced
  * the first account becomes admin when FIRST_USER_IS_ADMIN is set
  * the user's preferences row is written encrypted, through the same
    two-step insert every data row uses
"""

import re
from dataclasses import dataclass, field
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
    # Shown ONCE, then gone. Nothing stores it.
    recovery_phrase: str = field(repr=False)


def default_preferences() -> dict:
    """A new user's preferences, from the defaults in .env. No currency."""
    return {
        "theme": "system",
        "budget_period": settings.DEFAULT_BUDGET_PERIOD,
        "month_start_day": settings.DEFAULT_MONTH_START_DAY,
        "week_start_day": settings.DEFAULT_WEEK_START_DAY,
        "daily_allowance_mode": settings.DAILY_ALLOWANCE_MODE,
        "carry_over": settings.DEFAULT_CARRY_OVER_UNSPENT,
        "alert_warn_threshold_pct": settings.ALERT_WARN_THRESHOLD_PCT,
        "alert_pace_enabled": settings.ALERT_PACE_ENABLED,
        "auto_lock_minutes": settings.PIN_AUTO_LOCK_MINUTES,
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
    keys = provision_user_keys(settings.RECOVERY_PHRASE_WORDS, settings.RECOVERY_PHRASE_LANGUAGE)
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
        phrase = keys.phrase
    finally:
        keys.wipe()
    return CreatedAccount(user_id=user.id, is_admin=is_admin, recovery_phrase=phrase)
