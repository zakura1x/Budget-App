"""
/backups - the full encrypted backup, from a button (SEC-13, DAT-06..16).

    GET  /backups                   the list, newest first, and how automatic backup runs
    POST /backups                   back up now
    GET  /backups/{name}/download   the .budgetbak itself - still ciphertext
    POST /backups/upload            a .budgetbak from this device, as the raw request
                                    body; checked and held for an hour
    POST /backups/restore           fresh | merge | verify, from a kept backup or an upload

The master key opens only the signed-in account's own backups here
(restore_service.unlock_source). Anyone else's file - or a backup going onto a
new server - is restored by the server owner with scripts/restore.py.
"""

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.schemas.data import BackupInfoOut, BackupListOut, RestoreIn, RestoreReportOut, UploadOut
from app.core.config import settings
from app.core.crypto.keyring import get_master_keyring
from app.core.deps import UnlockedContext, get_unlocked_context
from app.core.exceptions import ValidationException
from app.db.repositories.user_repository import UserRepository
from app.db.session import get_db
from app.services import audit_service
from app.services.backup_service import bundle, restore_service
from app.services.backup_service.scheduler import get_scheduler

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", response_model=BackupListOut)
def list_backups(ctx: UnlockedContext = Depends(get_unlocked_context)) -> BackupListOut:
    backups = bundle.list_backups(ctx.cipher.user_id)
    return BackupListOut(
        backups=[BackupInfoOut.model_validate(b) for b in backups],
        latest_at=backups[0].created_at if backups else None,
        automatic=get_scheduler().enabled,
        debounce_minutes=settings.BACKUP_DEBOUNCE_MINUTES,
        interval_hours=settings.BACKUP_INTERVAL_HOURS,
        retention_days=settings.BACKUP_RETENTION_DAYS,
    )


@router.post("", response_model=BackupInfoOut, status_code=status.HTTP_201_CREATED)
def back_up_now(ctx: UnlockedContext = Depends(get_unlocked_context), db: Session = Depends(get_db)) -> BackupInfoOut:
    info = bundle.write_backup(db, ctx.cipher.user_id)
    audit_service.record(db, audit_service.BACKUP, user_id=ctx.cipher.user_id, entity="backups", cipher=ctx.cipher,
                         detail={"name": info.name, "rows": info.rows, "attachments": info.attachments})
    db.commit()
    return BackupInfoOut.model_validate(info)


@router.get("/{name}/download")
def download(name: str, ctx: UnlockedContext = Depends(get_unlocked_context)) -> FileResponse:
    path = bundle.path_for(ctx.cipher.user_id, name)
    return FileResponse(path, media_type="application/octet-stream", filename=name,
                        headers={"Cache-Control": "no-store"})


@router.post("/upload", response_model=UploadOut)
async def upload(
    request: Request,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> UploadOut:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > bundle.MAX_UPLOAD_BYTES:
        raise ValidationException(f"A backup to restore is at most {bundle.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    content = await request.body()
    upload_id, found = await run_in_threadpool(bundle.save_upload, ctx.cipher.user_id, content)
    user = UserRepository(db).get(ctx.cipher.user_id)
    same = found.user_id == ctx.cipher.user_id and found.keys.get("email_bidx") == getattr(user, "email_bidx", None)
    return UploadOut(upload_id=upload_id, created_at=found.created_at, rows=found.rows,
                     attachments=found.attachments, same_account=same)


@router.post("/restore", response_model=RestoreReportOut)
def restore(
    body: RestoreIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> RestoreReportOut:
    if (body.name is None) == (body.upload_id is None):
        raise ValidationException("Choose one backup: a kept one by name, or an uploaded file")
    user_id = ctx.cipher.user_id
    found = bundle.read_bundle(bundle.path_for(user_id, body.name)) if body.name else bundle.load_upload(user_id, body.upload_id)
    user = UserRepository(db).get(user_id)
    source = restore_service.unlock_source(found, keyring=get_master_keyring(), owner=(user_id, user.email_bidx))
    report = restore_service.restore(db, found, ctx.cipher, source, mode=body.mode)
    if body.upload_id and body.mode != "verify":
        bundle.discard_upload(user_id, body.upload_id)
    return RestoreReportOut.model_validate(report)
