"""
Audit trail - every security-relevant event and, from Phase 3 on, every
mutation (ARCHITECTURE.md section 8).

The verb and the entity are plaintext, so the log is useful to you. Anything
that would reveal a figure or a name goes in `detail`, which is sealed under
the acting user's DEK - the log must not become the side channel that leaks
what the data tables protect. Events with no unlocked user (a wrong password,
a wrong registration code) have no detail at all.
"""

from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.db.repositories.audit_repository import AuditRepository

# The verbs, in one place so they stay consistent.
REGISTER = "REGISTER"
REGISTER_REJECTED = "REGISTER_REJECTED"
LOGIN = "LOGIN"
LOGIN_FAILED = "LOGIN_FAILED"
LOGOUT = "LOGOUT"
UNLOCK = "UNLOCK"
UNLOCK_FAILED = "UNLOCK_FAILED"
PIN_SET = "PIN_SET"
PIN_LOCKOUT = "PIN_LOCKOUT"
REFRESH_REUSE = "REFRESH_REUSE"
RECOVERY = "RECOVERY"
RECOVERY_FAILED = "RECOVERY_FAILED"


def record(
    db: Session,
    action: str,
    *,
    user_id: Optional[int] = None,
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    ip_hash: Optional[str] = None,
    cipher: Optional[UserCipher] = None,
    detail: Optional[Mapping[str, Any]] = None,
) -> None:
    AuditRepository(db).add(
        action=action, user_id=user_id, entity=entity, entity_id=entity_id,
        ip_hash=ip_hash, cipher=cipher, detail=detail,
    )
