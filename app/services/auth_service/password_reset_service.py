"""
Password reset by email (SEC-30; ARCHITECTURE.md 5.2.1).

    request_reset   an email address -> if it belongs to an active account, a
                    one-time link mailed to that address. The answer is the
                    same either way, so the form cannot find accounts.
    complete_reset  the link's token + a new password -> signed in.

THE LINK: {APP_PUBLIC_URL}{BASE_URL}/reset#token=<43 random characters>

  * 32 bytes from the OS. Only the token's SHA-256 is stored, so someone
    reading the database cannot use a pending link.
  * The token rides in the URL FRAGMENT. A browser never sends the fragment
    to the server, so it never reaches the IIS access log, which records
    query strings. The page reads it and POSTs it in a JSON body.
  * It works once, for PASSWORD_RESET_LINK_MINUTES, and a newer request
    replaces it.
  * The origin is APP_PUBLIC_URL, never the request's Host header - which
    whoever sends the request controls.

The address mailed is the one typed into the form. It matched the account's
blind index, so it is the account's email - nothing is decrypted to send it.

WHY A RESET TOUCHES NO DATA: the DEK is wrapped by the master key, not by the
password (section 5.2), so a new password is a new bcrypt hash and nothing
else. The same fact is the cost: whoever controls the mailbox can take over the
account, and with it read the budget.
"""

import hashlib
import secrets
from datetime import timedelta
from html import escape
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.blind_index import get_blind_indexer
from app.core.crypto.keyring import get_master_keyring
from app.core.exceptions import (
    BusinessRuleException,
    PermissionDeniedException,
    RateLimitException,
    ServiceUnavailableException,
    ValidationException,
)
from app.db.models import User
from app.db.repositories.attempt_repository import AttemptRepository, seconds_until_free
from app.db.repositories.user_repository import UserRepository
from app.db.types import utcnow
from app.services import audit_service, email_service
from app.services.auth_service import session_service
from app.services.auth_service.passwords import hash_password, policy_problems

REQUEST_KIND = "reset_request"
RESET_KIND = "reset"


class ResetLinkInvalidException(BusinessRuleException):
    code = "RESET_LINK_INVALID"
    title = "Reset Link Not Valid"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_link(token: str) -> str:
    return f"{settings.APP_PUBLIC_URL}{settings.BASE_URL}/reset#token={token}"


def request_reset(db: Session, email: str, *, ip_hash: Optional[str] = None) -> Optional[email_service.Message]:
    """The message to send, or None. The caller sends it AFTER responding, so both answers take as long."""
    if not settings.email_enabled:
        raise ServiceUnavailableException("This server cannot send email, so a password cannot be reset by email")
    attempts = AttemptRepository(db)
    window = settings.PASSWORD_RESET_WINDOW_MINUTES
    if attempts.recent_count(kinds=(REQUEST_KIND,), window_minutes=window, ip_hash=ip_hash) >= settings.PASSWORD_RESET_MAX_PER_IP:
        raise RateLimitException("Too many reset requests. Try again later.")

    address = (email or "").strip()
    bidx = get_blind_indexer().email(address)
    mailed_lately = attempts.recent_count(kinds=(REQUEST_KIND,), window_minutes=window, email_bidx=bidx)
    user = UserRepository(db).get_by_email_bidx(bidx)
    # Past the per-address cap, the answer stays the same - the email just does not go.
    sendable = user is not None and user.is_active and mailed_lately < settings.PASSWORD_RESET_MAX_PER_EMAIL
    attempts.record(kind=REQUEST_KIND, success=sendable, email_bidx=bidx,
                    user_id=user.id if user else None, ip_hash=ip_hash)
    if not sendable:
        db.commit()
        return None

    token = secrets.token_urlsafe(32)
    user.reset_token_hash = token_hash(token)
    user.reset_expires_at = utcnow() + timedelta(minutes=settings.PASSWORD_RESET_LINK_MINUTES)
    audit_service.record(db, audit_service.PASSWORD_RESET_REQUEST, user_id=user.id, ip_hash=ip_hash)
    db.commit()
    return _message(address, reset_link(token))


def complete_reset(
    db: Session, token: str, new_password: str, *, ip_hash: Optional[str] = None
) -> session_service.IssuedSession:
    attempts = AttemptRepository(db)
    window = settings.PASSWORD_RESET_WINDOW_MINUTES
    failures = attempts.recent_failures(kinds=(RESET_KIND,), window_minutes=window, ip_hash=ip_hash)
    if len(failures) >= settings.LOGIN_MAX_ATTEMPTS:
        wait = seconds_until_free(failures, window)
        raise RateLimitException(
            f"Too many attempts. Try again in {max(1, round(wait / 60))} minute(s).",
            extra={"retry_after_seconds": wait},
        )

    user = db.execute(select(User).where(User.reset_token_hash == token_hash(token or ""))).scalar_one_or_none()
    if user is None or user.reset_expires_at is None or user.reset_expires_at <= utcnow():
        attempts.record(kind=RESET_KIND, success=False, user_id=user.id if user else None, ip_hash=ip_hash)
        db.commit()
        raise ResetLinkInvalidException("This link has expired or has already been used. Ask for a new one.")

    # A weak password does not spend the link - the user can try again.
    problems = policy_problems(new_password)
    if problems:
        raise ValidationException("The new password needs " + ", ".join(problems))
    user.reset_token_hash = None
    user.reset_expires_at = None
    if not user.is_active:
        db.commit()
        raise PermissionDeniedException("This account has been disabled")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.pin_failed_count = 0
    session_service.end_all(db, user.id, "password-reset")
    # Recorded against the email: a successful reset clears an earlier sign-in lockout.
    attempts.record(kind=RESET_KIND, success=True, email_bidx=user.email_bidx, user_id=user.id, ip_hash=ip_hash)
    audit_service.record(db, audit_service.PASSWORD_RESET, user_id=user.id, ip_hash=ip_hash)

    from app.services.auth_service.auth_service import _warm

    keyring = get_master_keyring()
    dek = UserRepository(db).unwrap_dek(user, keyring)
    issued = session_service.start_session(db, user, dek, keyring)
    _warm(db, issued.session_id)
    user.last_login_at = utcnow()
    db.commit()
    return issued


def _message(address: str, link: str) -> email_service.Message:
    app = settings.APP_NAME
    minutes = settings.PASSWORD_RESET_LINK_MINUTES
    text = (
        f"Someone - hopefully you - asked to reset the password for your {app} account.\n\n"
        f"Choose a new password here. The link works once, for {minutes} minutes:\n\n{link}\n\n"
        "If you did not ask for this, ignore this email and your password stays as it is.\n\n"
        "A reset never changes your budget, and nothing from it is ever sent by email.\n"
    )
    safe_link, safe_app = escape(link, quote=True), escape(app)
    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f5f5f4;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1c1917">
<div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;padding:28px">
<h1 style="font-size:20px;margin:0 0 12px">Reset your {safe_app} password</h1>
<p style="font-size:15px;line-height:1.5;margin:0 0 20px">Someone &mdash; hopefully you &mdash; asked to reset the password for your {safe_app} account.</p>
<p style="margin:0 0 20px"><a href="{safe_link}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600;padding:12px 20px;border-radius:12px">Choose a new password</a></p>
<p style="font-size:13px;line-height:1.5;color:#57534e;margin:0 0 12px">The link works once, for {minutes} minutes. If the button does not work, copy this into your browser:<br><span style="word-break:break-all">{safe_link}</span></p>
<p style="font-size:13px;line-height:1.5;color:#57534e;margin:0">If you did not ask for this, ignore this email and your password stays as it is. A reset never changes your budget, and nothing from it is ever sent by email.</p>
</div></body></html>
"""
    return email_service.Message(to=address, subject=f"Reset your {app} password", text=text, html=html)
