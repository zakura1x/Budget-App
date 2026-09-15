"""Request and response shapes for /backups, /data and receipts (DAT-01..17, TXN-15)."""

from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import Money

DateFormat = Literal["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"]
RestoreMode = Literal["fresh", "merge", "verify"]


class BackupInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    created_at: datetime
    size: int
    rows: int
    attachments: int


class BackupListOut(BaseModel):
    backups: List[BackupInfoOut]
    latest_at: Optional[datetime] = None
    automatic: bool  # DAT-08 is running in this process
    debounce_minutes: int
    interval_hours: int
    retention_days: int


class UploadOut(BaseModel):
    upload_id: str
    created_at: datetime
    rows: int
    attachments: int
    same_account: bool  # False -> only scripts/restore.py on the server can restore it


class RestoreIn(BaseModel):
    """Restore a backup kept on the server (`name`) or one just uploaded (`upload_id`)."""

    name: Optional[str] = Field(default=None, max_length=64)
    upload_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    mode: RestoreMode = "verify"


class TableReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table: str
    in_backup: int
    restored: int
    skipped: int


class DifferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table: str
    only_in_backup: int
    only_in_live: int


class RestoreReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mode: RestoreMode
    tables: List[TableReportOut]
    attachments: int
    missing_files: int
    unresolved: List[str]
    differences: List[DifferenceOut]
    ok: bool


class ImportIn(BaseModel):
    csv: str = Field(max_length=5_000_000)
    mapping: Dict[str, str] = {}  # our field -> the file's column
    date_format: DateFormat = "YYYY-MM-DD"
    skip_duplicates: bool = True


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line: int
    message: str


class PlannedEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line: int
    txn_date: date
    type: str
    amount: Money
    account: str
    merchant: Optional[str] = None
    duplicate: bool


class ImportPreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rows: int
    transactions: int
    ready: int
    duplicates: int
    errors: List[IssueOut]
    headers: List[str]
    mapping: Dict[str, str]
    entries: List[PlannedEntryOut]


class ImportResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created: int
    skipped_duplicates: int


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    filename: str
    mime: str
    size: int
