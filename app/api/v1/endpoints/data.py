"""
/data - transactions as CSV (DAT-01..05, DAT-11).

GET /data/transactions.csv is plaintext on purpose - the one deliberate
opening in the encryption boundary. It is built in memory and streamed, never
staged on disk, and audited. The screen that calls it says so before the
download starts.
"""

import base64
import binascii
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.schemas.data import (
    BudgetAppImportIn,
    BudgetAppPreviewOut,
    BudgetAppResultOut,
    ImportIn,
    ImportPreviewOut,
    ImportResultOut,
)
from app.core.deps import UnlockedContext, get_unlocked_context
from app.core.exceptions import ValidationException
from app.db.session import get_db
from app.services import budget_app_import_service, import_export_service

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/transactions.csv")
def export_transactions(
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    # Built before the response starts: the session closes with the request, the lines do not need it.
    lines, count = import_export_service.export_csv(db, ctx.cipher, date_from=date_from, date_to=date_to)
    filename = f"budget-transactions-{date.today():%Y-%m-%d}.csv"
    return StreamingResponse(
        iter(lines), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
                 "X-Transaction-Count": str(count)},
    )


@router.post("/import/preview", response_model=ImportPreviewOut)
def preview_import(
    body: ImportIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ImportPreviewOut:
    result = import_export_service.preview(db, ctx.cipher, body.csv, mapping=body.mapping, date_format=body.date_format)
    return ImportPreviewOut.model_validate(result)


@router.post("/import", response_model=ImportResultOut)
def run_import(
    body: ImportIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> ImportResultOut:
    result = import_export_service.run_import(
        db, ctx.cipher, body.csv, mapping=body.mapping, date_format=body.date_format,
        skip_duplicates=body.skip_duplicates,
    )
    return ImportResultOut.model_validate(result)


def _file(body: BudgetAppImportIn) -> bytes:
    try:
        return base64.b64decode(body.file, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationException("The file did not arrive intact - choose it again") from None


@router.post("/import/budget-app/preview", response_model=BudgetAppPreviewOut)
def preview_budget_app(
    body: BudgetAppImportIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> BudgetAppPreviewOut:
    """DAT-21. What the Budget app's backup would become - writes nothing."""
    return BudgetAppPreviewOut.model_validate(budget_app_import_service.preview(db, ctx.cipher, _file(body)))


@router.post("/import/budget-app", response_model=BudgetAppResultOut)
def run_budget_app(
    body: BudgetAppImportIn,
    ctx: UnlockedContext = Depends(get_unlocked_context),
    db: Session = Depends(get_db),
) -> BudgetAppResultOut:
    result = budget_app_import_service.run_import(db, ctx.cipher, _file(body), body.balances)
    return BudgetAppResultOut.model_validate(result)
