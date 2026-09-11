"""
audit_log - plaintext verb and entity, encrypted detail.

The detail is sealed under the acting user's DEK with AAD bound to the audit
row, so it needs the same two-step insert as a data row. Events with no
unlocked user (a failed sign-in, a wrong registration code) carry no detail.
"""

from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import AuditLog
from app.db.types import utcnow


class AuditRepository:
    TABLE = "audit_log"

    def __init__(self, session: Session):
        self.session = session

    def add(self, *, action: str, user_id: Optional[int] = None, entity: Optional[str] = None,
            entity_id: Optional[int] = None, ip_hash: Optional[str] = None,
            cipher: Optional[UserCipher] = None, detail: Optional[Mapping[str, Any]] = None) -> AuditLog:
        if detail is not None and cipher is None:
            raise ValueError("audit detail is encrypted - it needs the user's cipher")
        if cipher is not None and user_id is not None and cipher.user_id != user_id:
            raise ValueError("audit detail must be sealed under the acting user's own key")
        row = AuditLog(action=action, user_id=user_id, entity=entity, entity_id=entity_id,
                       ip_hash=ip_hash, created_at=utcnow(),
                       detail_enc=PLACEHOLDER if detail is not None else None,
                       key_version=cipher.key_version if detail is not None else None)
        self.session.add(row)
        self.session.flush()
        if detail is not None:
            row.detail_enc = cipher.seal(self.TABLE, row.id, detail)
            self.session.flush()
        return row

    def read_detail(self, row: AuditLog, cipher: UserCipher) -> Optional[dict]:
        if row.detail_enc is None:
            return None
        return cipher.open(self.TABLE, row.id, row.detail_enc, row.key_version)
