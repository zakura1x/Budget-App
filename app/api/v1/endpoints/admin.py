"""
/admin - account management, and deliberately nothing more (UX-20, SEC-18).

The admin sees each account's row - active or not, when it was made and last
used, its key version - and can disable, re-enable or delete it. The admin
cannot see an email address, a name or a single figure: all of those are
sealed under the user's own key, and no key on this server opens them.
Deleting someone else's account needs no key for the same reason: it removes
ciphertext without reading it.
"""

from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.schemas.settings import ActiveIn, AdminDeleteIn, AdminStatusOut, AdminUserOut
from app.core.config import settings
from app.core.crypto.keyring import get_master_keyring
from app.core.crypto.session_keys import get_session_keyring
from app.core.crypto.working_set import get_working_set
from app.core.deps import UnlockedContext, get_ip_hash, get_unlocked_context
from app.core.exceptions import BusinessRuleException, NotFoundException, PermissionDeniedException, ValidationException
from app.db.models import ENCRYPTED_MODELS, User
from app.db.session import get_db
from app.services import audit_service
from app.services.auth_service import security_service, session_service

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(ctx: UnlockedContext = Depends(get_unlocked_context)) -> UnlockedContext:
    if not ctx.user.is_admin:
        raise PermissionDeniedException("Only the admin can do that")
    return ctx


@router.get("/users", response_model=List[AdminUserOut])
def list_users(ctx: UnlockedContext = Depends(require_admin), db: Session = Depends(get_db)) -> List[AdminUserOut]:
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return [AdminUserOut(id=u.id, is_admin=u.is_admin, is_active=u.is_active, created_at=u.created_at,
                         last_login_at=u.last_login_at, key_version=u.key_version) for u in users]


@router.post("/users/{user_id}/active", response_model=AdminUserOut)
def set_active(user_id: int, body: ActiveIn, ctx: UnlockedContext = Depends(require_admin),
               db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> AdminUserOut:
    user = _other_user(db, ctx, user_id)
    user.is_active = body.active
    if not body.active:
        # A disabled account is signed out everywhere, now.
        session_service.end_all(db, user.id, "disabled")
        get_session_keyring().lock_user(user.id)
    audit_service.record(db, audit_service.USER_ENABLE if body.active else audit_service.USER_DISABLE,
                         user_id=user.id, entity="users", entity_id=ctx.user.id, ip_hash=ip_hash)
    db.commit()
    return AdminUserOut(id=user.id, is_admin=user.is_admin, is_active=user.is_active, created_at=user.created_at,
                        last_login_at=user.last_login_at, key_version=user.key_version)


@router.post("/users/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, body: AdminDeleteIn, ctx: UnlockedContext = Depends(require_admin),
                db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> Response:
    user = _other_user(db, ctx, user_id)
    security_service.confirm_password(db, ctx.user, body.password, ip_hash)
    if body.confirm_user_id != user.id:
        raise ValidationException("Type the account number exactly to confirm")
    security_service.purge_user(db, user.id, ip_hash=ip_hash, reason=f"admin:{ctx.user.id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/status", response_model=AdminStatusOut)
def server_status(ctx: UnlockedContext = Depends(require_admin), db: Session = Depends(get_db)) -> AdminStatusOut:
    """What /health will not say to an unauthenticated caller: key version, sessions, row counts."""
    keyring = get_master_keyring()
    return AdminStatusOut(
        users=db.execute(select(func.count()).select_from(User)).scalar_one(),
        active_users=db.execute(select(func.count()).select_from(User).where(User.is_active == True)).scalar_one(),  # noqa: E712
        max_users=settings.MAX_USERS,
        master_key_version=keyring.current_version,
        master_key_versions_loaded=len(list(keyring.versions)),
        unlocked_sessions=len(get_session_keyring()),
        cached_users=len(get_working_set()),
        rows={m.__tablename__: db.execute(select(func.count()).select_from(m)).scalar_one() for m in ENCRYPTED_MODELS},
    )


def _other_user(db: Session, ctx: UnlockedContext, user_id: int) -> User:
    if user_id == ctx.user.id:
        raise BusinessRuleException("Manage your own account from Settings")
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundException("No such account")
    return user
