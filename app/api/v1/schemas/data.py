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


class BudgetAppImportIn(BaseModel):
    """DAT-21. The Budget app's .xlsx as base64 in the body - never in a URL, never saved - and today's balances."""

    file: str = Field(min_length=1, max_length=14_000_000)
    # An _Account key -> today's balance as the user reads it: an amount OWED on a card or a loan.
    balances: Dict[str, Money] = {}


class BudgetAppAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    type: str
    subtype: Optional[str] = None
    exists: bool
    history: Money
    suggested: Optional[Money] = None
    owed: bool
    archived: bool
    transactions: int


class BudgetAppPreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exported_at: Optional[str] = None
    app_version: Optional[str] = None
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    accounts: List[BudgetAppAccountOut]
    categories_new: int
    categories_existing: int
    transactions: int
    ready: int
    duplicates: int
    adjustments_folded: int
    loan_records_folded: int
    unassigned: int
    skipped: int


class BudgetAppResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accounts_created: int
    categories_created: int
    transactions: int
    skipped_duplicates: int
    archived: int


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    filename: str
    mime: str
    size: int
