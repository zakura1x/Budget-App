"""
refresh_tokens - rotation and family revocation (SEC-05/06).
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import RefreshToken
from app.db.types import utcnow


class TokenRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, *, user_id: int, token_hash: str, family_id: str, expires_at: datetime,
            parent_id: Optional[int] = None) -> RefreshToken:
        row = RefreshToken(user_id=user_id, token_hash=token_hash, family_id=family_id,
                           parent_id=parent_id, issued_at=utcnow(), expires_at=expires_at)
        self.session.add(row)
        self.session.flush()
        return row

    def by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        return self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()

    def family_is_active(self, family_id: str) -> bool:
        """A session is alive while its family has a token nobody revoked."""
        return self.session.execute(
            select(RefreshToken.id).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)).limit(1)
        ).first() is not None

    def family_user(self, family_id: str) -> Optional[int]:
        return self.session.execute(
            select(RefreshToken.user_id).where(RefreshToken.family_id == family_id).limit(1)
        ).scalar_one_or_none()

    def revoke_family(self, family_id: str, reason: str) -> int:
        result = self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason)
        )
        return result.rowcount

    def active_families(self, user_id: int) -> List[str]:
        rows = self.session.execute(
            select(RefreshToken.family_id).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).distinct()
        )
        return [r[0] for r in rows]

    def revoke_user(self, user_id: int, reason: str, except_family: Optional[str] = None) -> List[str]:
        """Revoke every session of a user (optionally keeping one). Returns the families ended."""
        families = [f for f in self.active_families(user_id) if f != except_family]
        for family in families:
            self.revoke_family(family, reason)
        return families
