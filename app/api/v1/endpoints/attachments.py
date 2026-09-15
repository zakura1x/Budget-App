"""
Receipts (TXN-15). The file travels as the raw request body - no multipart
parser on the server - with its name in an `X-Filename` header (URL-encoded),
never in the URL, which IIS logs. GET returns it decrypted with no-store, for
display only.
"""

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.v1.schemas.data import AttachmentOut
from app.core.config import settings
from app.core.deps import UnlockedContext, get_unlocked_context
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.services import attachment_service

router = APIRouter(tags=["attachments"])


@router.post("/transactions/{transaction_id}/attachment", response_model=AttachmentOut,
             status_code=status.HTTP_201_CREATED)
async def upload(
    transaction_id: int,
    request: Request,
    x_filename: str = Header(default="receipt.jpg", max_length=300),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> AttachmentOut:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.MAX_UPLOAD_SIZE:
        raise ValidationException(f"A receipt is at most {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB")
    content = await request.body()
    view = await run_in_threadpool(attachment_service.attach, db, ctx.cipher, transaction_id, unquote(x_filename), content)
    return AttachmentOut.model_validate(view)


@router.get("/attachments/{attachment_id}")
def download(
    attachment_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> Response:
    view, content = attachment_service.read(db, ctx.cipher, attachment_id)
    return Response(content, media_type=view.mime,
                    headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.delete("/transactions/{transaction_id}/attachment", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    transaction_id: int,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> Response:
    attachment_service.remove(db, ctx.cipher, transaction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
