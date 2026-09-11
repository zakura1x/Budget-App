"""
/auth - sign-up, sign-in, lock, unlock, refresh, recovery.

Endpoints validate and delegate; the services decide. What this file owns is
the cookies, because they are an HTTP concern:

    zbdgt_session   access JWT     HttpOnly, SameSite=Lax, Path=/ZBDGT
    zbdgt_refresh   refresh token  HttpOnly, SameSite=Lax, Path=/ZBDGT/api/v1/auth

Both scoped to this app (SEC-28): the host is shared with QUOT, and an
unscoped cookie would be sent to every app on it. Secure comes from
SESSION_COOKIE_SECURE (true in production, via web.config).
"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.v1.schemas.auth import (
    AuthConfigOut,
    LoginRequest,
    PasswordPolicy,
    PasswordRequest,
    PinRequest,
    RecoverRequest,
    RegisterOut,
    RegisterRequest,
    SessionOut,
    SetPinRequest,
    UserOut,
)
from app.core.config import settings
from app.core.deps import (
    SessionContext,
    UnlockedContext,
    get_ip_hash,
    get_session_context,
    get_unlocked_context,
)
from app.core.exceptions import AppException, problem
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import auth_service, recovery_service, registration_service, session_service
from app.services.auth_service.session_service import IssuedSession
from app.services.auth_service.tokens import decode_access_token, TokenExpired, TokenInvalid

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_PATH = f"{settings.API_PREFIX}/auth"


# ------------------------------------------------------------------ cookies


def _cookie_args(path: str) -> dict:
    return dict(
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path=path,
    )


def set_session_cookies(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME, issued.access_token,
        max_age=settings.JWT_EXPIRATION_MINUTES * 60, **_cookie_args(settings.SESSION_COOKIE_PATH),
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME, issued.refresh_token,
        max_age=settings.JWT_REFRESH_EXPIRATION_DAYS * 86400, **_cookie_args(REFRESH_PATH),
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE_NAME, **_cookie_args(settings.SESSION_COOKIE_PATH))
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, **_cookie_args(REFRESH_PATH))


def _session_out(db: Session, user: User, session_id: str) -> SessionOut:
    p = auth_service.profile(db, user, session_id)
    return SessionOut(
        user=UserOut(id=p.user_id, is_admin=p.is_admin, email=p.email, display_name=p.display_name),
        locked=p.locked,
        pin_set=p.pin_set,
        auto_lock_minutes=settings.PIN_AUTO_LOCK_MINUTES,
    )


# ---------------------------------------------------------------- endpoints


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    """What the sign-in and sign-up screens need to know. Public; no secrets."""
    return AuthConfigOut(
        registration_open=settings.registration_open,
        pin_enabled=settings.PIN_ENABLED,
        pin_length=settings.PIN_LENGTH,
        recovery_words=settings.RECOVERY_PHRASE_WORDS,
        password_policy=PasswordPolicy(
            min_length=settings.PASSWORD_MIN_LENGTH,
            require_upper=settings.PASSWORD_REQUIRE_UPPER,
            require_digit=settings.PASSWORD_REQUIRE_DIGIT,
            require_symbol=settings.PASSWORD_REQUIRE_SYMBOL,
        ),
    )


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db),
             ip_hash: str = Depends(get_ip_hash)) -> RegisterOut:
    account, issued = registration_service.register(
        db, email=body.email, password=body.password, registration_code=body.registration_code,
        display_name=(body.display_name or "").strip() or None, ip_hash=ip_hash,
    )
    set_session_cookies(response, issued)
    session = _session_out(db, db.get(User, issued.user_id), issued.session_id)
    return RegisterOut(**session.model_dump(), recovery_phrase=account.recovery_phrase.split())


@router.post("/login", response_model=SessionOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db),
          ip_hash: str = Depends(get_ip_hash)) -> SessionOut:
    issued = auth_service.login(db, body.email, body.password, ip_hash)
    set_session_cookies(response, issued)
    return _session_out(db, db.get(User, issued.user_id), issued.session_id)


@router.post("/refresh", response_model=SessionOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db),
            ip_hash: str = Depends(get_ip_hash)):
    try:
        issued = session_service.rotate(db, request.cookies.get(settings.REFRESH_COOKIE_NAME), ip_hash)
    except AppException as exc:
        # Built here rather than raised, so the dead cookies are cleared on
        # the way out - a raised exception would replace this response.
        failed = problem(exc.status_code, exc.title, exc.code, exc.detail)
        clear_session_cookies(failed)
        return failed
    db.commit()
    set_session_cookies(response, issued)
    return _session_out(db, db.get(User, issued.user_id), issued.session_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> Response:
    """Works with an expired access token too - the refresh cookie names the session."""
    session_id, user_id = None, None
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        try:
            claims = decode_access_token(token)
            session_id, user_id = claims.session_id, claims.user_id
        except (TokenExpired, TokenInvalid):
            pass
    if session_id is None:
        session_id = session_service.family_of_refresh(db, request.cookies.get(settings.REFRESH_COOKIE_NAME))
    auth_service.logout(db, session_id, user_id, ip_hash)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(out)
    return out


@router.get("/me", response_model=SessionOut)
def me(ctx: SessionContext = Depends(get_session_context), db: Session = Depends(get_db)) -> SessionOut:
    """Signed in? Locked? The app's first call on every load."""
    return _session_out(db, ctx.user, ctx.session_id)


@router.post("/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(ctx: SessionContext = Depends(get_session_context)) -> Response:
    auth_service.lock(ctx.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pin/verify", response_model=SessionOut)
def verify_pin(body: PinRequest, ctx: SessionContext = Depends(get_session_context),
               db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> SessionOut:
    auth_service.unlock_with_pin(db, ctx.user, ctx.session_id, body.pin, ip_hash)
    return _session_out(db, ctx.user, ctx.session_id)


@router.post("/unlock", response_model=SessionOut)
def unlock_with_password(body: PasswordRequest, ctx: SessionContext = Depends(get_session_context),
                         db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> SessionOut:
    auth_service.unlock_with_password(db, ctx.user, ctx.session_id, body.password, ip_hash)
    return _session_out(db, ctx.user, ctx.session_id)


@router.post("/pin", response_model=SessionOut)
def set_pin(body: SetPinRequest, ctx: UnlockedContext = Depends(get_unlocked_context),
            db: Session = Depends(get_db), ip_hash: str = Depends(get_ip_hash)) -> SessionOut:
    auth_service.set_pin(db, ctx.user, ctx.cipher, body.pin, body.current_password, ip_hash)
    return _session_out(db, ctx.user, ctx.session_id)


@router.post("/recover", response_model=SessionOut)
def recover(body: RecoverRequest, response: Response, db: Session = Depends(get_db),
            ip_hash: str = Depends(get_ip_hash)) -> SessionOut:
    issued = recovery_service.recover(db, phrase=body.phrase, new_password=body.new_password, ip_hash=ip_hash)
    set_session_cookies(response, issued)
    return _session_out(db, db.get(User, issued.user_id), issued.session_id)
