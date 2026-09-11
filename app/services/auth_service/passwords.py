"""
Password hashing and policy.

bcrypt directly, not through passlib. The venv has bcrypt 5, and passlib 1.7's
startup self-test hashes a password longer than 72 bytes, which bcrypt 5
rejects - passlib then fails on first use. QUOT still imports passlib; this
app does not need it.

bcrypt only reads the first 72 bytes of its input, and bcrypt 5 raises on
anything longer. So the password is pre-hashed: SHA-256, base64 - 44 bytes,
every character of the password counted. Stored with a scheme prefix so a
future change of algorithm can tell old hashes from new.
"""

import base64
import hashlib
import re
from typing import List

import bcrypt

from app.core.config import settings

SCHEME = "bcrypt-sha256$"


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str, rounds: int = None) -> str:
    rounds = rounds or settings.BCRYPT_ROUNDS
    return SCHEME + bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    """Constant-time (bcrypt.checkpw). False for any malformed stored value."""
    if not stored or not stored.startswith(SCHEME):
        return False
    try:
        return bcrypt.checkpw(_prehash(password), stored[len(SCHEME):].encode("ascii"))
    except (ValueError, TypeError):
        return False


def policy_problems(password: str) -> List[str]:
    """Every way a password falls short of the policy in .env. Empty = fine."""
    problems = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r"[A-Z]", password):
        problems.append("an upper-case letter")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password):
        problems.append("a digit")
    if settings.PASSWORD_REQUIRE_SYMBOL and not re.search(r"[^A-Za-z0-9]", password):
        problems.append("a symbol")
    return problems
