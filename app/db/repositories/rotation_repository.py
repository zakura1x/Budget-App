"""
Re-sealing and removing everything one user owns (SEC-21, SEC-23).

Both jobs touch every row a user has, and both live here because repositories
are the only layer that handles a ciphertext (invariant 1).

  * ROTATION re-seals each row under a NEW DEK. Row ids do not change, so the
    AAD stays valid: it is open-with-old, seal-with-new, row by row, inside
    the caller's one database transaction (ARCHITECTURE.md §5.2.2). Receipts
    are re-sealed into `.rotating` files beside the originals; the service
    swaps them in only after COMMIT, so a failed rotation leaves every file as
    it was.

  * DELETION removes every row with the user's id - hard, not soft: the point
    of SEC-21 is that nothing remains. The audit log is the one exception; its
    rows outlive the user by design, and their details are sealed under a key
    that no longer exists.
"""

from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.crypto.envelope import PLACEHOLDER
from app.core.crypto.user_cipher import UserCipher
from app.db.models import ENCRYPTED_MODELS, AuditLog, LoginAttempt, RefreshToken, User
from app.db.repositories.attachment_repository import FILE_TABLE, AttachmentRepository


class RotationRepository:
    def __init__(self, session: Session):
        self.session = session

    def reseal_rows(
        self,
        model,
        old: UserCipher,
        new: UserCipher,
        transform: Optional[Callable[[dict], dict]] = None,
    ) -> int:
        table = model.__tablename__
        rows = self.session.execute(select(model).where(model.user_id == old.user_id)).scalars().all()
        for row in rows:
            if row.payload == PLACEHOLDER:
                continue
            data = old.open(table, row.id, row.payload, row.key_version)
            if transform is not None:
                data = transform(data)
            row.payload = new.seal(table, row.id, data)
            row.key_version = new.key_version
        self.session.flush()
        return len(rows)

    def reseal_audit(self, old: UserCipher, new: UserCipher) -> int:
        rows = self.session.execute(
            select(AuditLog).where(AuditLog.user_id == old.user_id, AuditLog.detail_enc.is_not(None))
        ).scalars().all()
        for row in rows:
            if row.detail_enc == PLACEHOLDER:
                continue
            detail = old.open("audit_log", row.id, row.detail_enc, row.key_version)
            row.detail_enc = new.seal("audit_log", row.id, detail)
            row.key_version = new.key_version
        self.session.flush()
        return len(rows)

    def reseal_profile(self, user: User, old: UserCipher, new: UserCipher) -> None:
        if user.profile_enc is not None:
            profile = old.open("users", user.id, user.profile_enc, user.key_version)
            user.profile_enc = new.seal("users", user.id, profile)
        self.session.flush()

    @staticmethod
    def reseal_files(old: UserCipher, new: UserCipher, attachments: List[Tuple[int, Mapping]]) -> List[Tuple[Path, Path]]:
        """Write re-sealed copies next to each receipt. Returns (partial, final) pairs to swap in after commit."""
        pairs: List[Tuple[Path, Path]] = []
        for attachment_id, data in attachments:
            final = AttachmentRepository.file_path(old.user_id, attachment_id)
            if not final.is_file():
                continue
            content = old.open_bytes(FILE_TABLE, attachment_id, final.read_bytes(), int(data.get("file_key_version") or 1))
            partial = final.with_suffix(".rotating")
            partial.write_bytes(new.seal_bytes(FILE_TABLE, attachment_id, content))
            pairs.append((partial, final))
        return pairs

    def purge_user(self, user_id: int) -> Dict[str, int]:
        """Delete every row of this user except their audit trail. The caller commits."""
        counts: Dict[str, int] = {}
        for model in ENCRYPTED_MODELS:
            counts[model.__tablename__] = self.session.execute(delete(model).where(model.user_id == user_id)).rowcount
        counts["refresh_tokens"] = self.session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id)).rowcount
        counts["login_attempts"] = self.session.execute(delete(LoginAttempt).where(LoginAttempt.user_id == user_id)).rowcount
        counts["users"] = self.session.execute(delete(User).where(User.id == user_id)).rowcount
        self.session.flush()
        return counts
