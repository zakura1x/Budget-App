"""
/security - the account's own key and password (SEC-21..24).

Every route asks for the password again in its body. Deleting the account also
clears this browser's session cookies.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import clear_session_cookies
from app.api.v1.schemas.settings import (
    ChangePasswordIn,
    DeleteAccountIn,
    ReauthIn,
    RotatedKeyOut,
    SessionsEndedOut,
)
from app.core.deps import UnlockedContext, get_ip_hash, get_unlocked_context
from app.db.session import get_db
from app.services.auth_service import security_service

router = APIRouter(prefix="/security", tags=["security"])


@router.post("/password", response_model=SessionsEndedOut)
def change_password(body: ChangePasswordIn, ctx: UnlockedContext = Depends(get_unlocked_context),
                    db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> SessionsEndedOut:
    ended = security_service.change_password(db, ctx.user, ctx.session_id, ctx.cipher, body.current_password,
                                             body.new_password, ip_hash=ip_hash)
    return SessionsEndedOut(sessions_ended=ended)


@router.post("/rotate-key", response_model=RotatedKeyOut)
def rotate_key(body: ReauthIn, ctx: UnlockedContext = Depends(get_unlocked_context),
               db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> RotatedKeyOut:
    """SEC-23 - a new key for everything."""
    result = security_service.rotate_dek(db, ctx.user, ctx.session_id, body.password, ip_hash=ip_hash)
    return RotatedKeyOut.model_validate(result)


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(body: DeleteAccountIn, ctx: UnlockedContext = Depends(get_unlocked_context),
                   db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> Response:
    """SEC-21 - irreversible."""
    security_service.delete_account(db, ctx.user, ctx.cipher, body.password, body.confirm_email, ip_hash=ip_hash)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(out)
    return out
