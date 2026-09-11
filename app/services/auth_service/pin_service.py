"""
The 6-digit PIN (SEC-07) - the Face ID equivalent.

It re-locks a session that is already signed in. It NEVER derives or wraps a
key: a 6-digit secret has a million values, which is nothing to an offline
attack, so it must never be the thing standing between an attacker and the
data (ARCHITECTURE.md section 6). Unlocking with it makes the SERVER unwrap
the DEK again with the master key; the PIN only decides whether to.

Stored as bcrypt(HMAC-SHA256(PIN_PEPPER, pin)). The pepper lives in .env, so a
copy of the users table alone cannot even start guessing.
"""

import base64
import hashlib
import hmac

import bcrypt

from app.core.config import settings
from app.core.exceptions import ValidationException

SCHEME = "bcrypt-hmac$"


def check_format(pin: str) -> None:
    if not isinstance(pin, str) or len(pin) != settings.PIN_LENGTH or not pin.isdigit():
        raise ValidationException(f"The PIN is {settings.PIN_LENGTH} digits")
    if len(set(pin)) == 1 or pin in "01234567890" or pin in "98765432109":
        raise ValidationException("Choose a PIN that is not a run or a repeated digit")


def _prehash(pin: str) -> bytes:
    return base64.b64encode(hmac.new(settings.pin_pepper_bytes, pin.encode("ascii"), hashlib.sha256).digest())


def hash_pin(pin: str) -> str:
    check_format(pin)
    return SCHEME + bcrypt.hashpw(_prehash(pin), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("ascii")


def verify_pin(pin: str, stored: str) -> bool:
    if not stored or not stored.startswith(SCHEME) or not isinstance(pin, str) or not pin.isdigit():
        return False
    try:
        return bcrypt.checkpw(_prehash(pin), stored[len(SCHEME):].encode("ascii"))
    except (ValueError, TypeError):
        return False
