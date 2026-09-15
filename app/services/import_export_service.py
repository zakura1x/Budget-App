"""
import_export_service - transactions as CSV, out and in (DAT-01..05, DAT-11).

CSV EXPORT IS THE ONE DELIBERATE OPENING IN THE ENCRYPTION BOUNDARY (DAT-02,
DAT-18). The file is plaintext, built in memory from the working set and
streamed straight to the browser - never written to the server's disk - and
every export is audited. Backups never open the boundary at all.

ONE ROW PER SPLIT (DAT-11). A ₱3,500 receipt split ₱2,800 / ₱700 is two rows
sharing `txn_id`, numbered by `split_index`; `amount` is the whole transaction
on both, `split_amount` the part. So an export re-imports identically - and
the row count is not the transaction count, which the export screen says.

A cell a spreadsheet would run as a formula (=, +, -, @) is written with a
leading apostrophe, and the apostrophe is removed again on import.

IMPORT is two steps, and the first writes nothing: `preview` parses, maps the
columns, finds every account, category and tag by name, validates each
transaction exactly as the add sheet would, and flags duplicates of what is
already recorded (same day, type, amount, account and merchant). `run_import`
refuses a file with any problem, skips duplicates by default, and writes the
rest in one commit.

A CSV from anywhere else works through `mapping` (our field -> its column)
and `date_format`. Without a type column, a negative amount is spending and a
positive one income.
"""

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import AppException, BusinessRuleException, ValidationException
from app.core.utils.money import money
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.db.repositories.tag_repository import TagRepository
from app.services import audit_service, transaction_service

COLUMNS: Tuple[str, ...] = (
    "txn_id", "split_index", "date", "type", "account", "counter_account", "amount", "split_amount",
    "category", "parent_category", "merchant", "notes", "split_note", "tags",
)
REQUIRED = ("date", "amount", "account")
DATE_FORMATS = {"YYYY-MM-DD": "%Y-%m-%d", "MM/DD/YYYY": "%m/%d/%Y", "DD/MM/YYYY": "%d/%m/%Y"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
MAX_ROWS = 10000
MAX_CSV_CHARS = 5_000_000
PREVIEW_ENTRIES = 50


@dataclass(frozen=True)
class Issue:
    line: int
    message: str


@dataclass(frozen=True)
class PlannedEntry:
    line: int
    txn_date: date
    type: str
    amount: Decimal
    account: str
    merchant: Optional[str]
    duplicate: bool


@dataclass(frozen=True)
class ImportPreview:
    rows: int
    transactions: int
    ready: int  # would be imported with duplicates skipped
    duplicates: int
    errors: List[Issue]
    headers: List[str]
    mapping: Dict[str, str]
    entries: List[PlannedEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped_duplicates: int


@dataclass
class _Plan:
    line: int
    payload: Dict[str, Any]
    key: tuple
    account: str
    duplicate: bool = False


# ------------------------------------------------------------------ export


def export_csv(
    db: Session, cipher: UserCipher, *, date_from: Optional[date] = None, date_to: Optional[date] = None
) -> Tuple[List[str], int]:
    """(lines, transaction count). Lines end in CRLF; the first carries a BOM so Excel reads UTF-8."""
    accounts = {r.id: r.data for r in AccountRepository(db, cipher).list(include_deleted=True)}
    categories = {r.id: r.data for r in CategoryRepository(db, cipher).list(include_deleted=True)}
    tags = {r.id: r.data for r in TagRepository(db, cipher).list(include_deleted=True)}

    views = [
        v for v in transaction_service.views(db, cipher)
        if not (v.type == "transfer" and v.direction == "in")  # a transfer is one entry, its out leg
        and (date_from is None or v.txn_date >= date_from)
        and (date_to is None or v.txn_date <= date_to)
    ]
    views.sort(key=lambda v: (v.txn_date, v.id))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    lines: List[str] = []

    def emit(cells: Sequence[Any]) -> None:
        writer.writerow(cells)
        lines.append(buffer.getvalue())
        buffer.seek(0)
        buffer.truncate()

    emit(COLUMNS)
    lines[0] = "﻿" + lines[0]
    for view in views:
        account = _name(accounts, view.account_id)
        counter = _name(accounts, view.counter_account_id)
        tag_names = "; ".join(_name(tags, t) for t in view.tag_ids)
        for index, split in enumerate(view.splits, start=1):
            category = categories.get(split.category_id) if split.category_id is not None else None
            parent = categories.get(category.get("parent_id")) if category and category.get("parent_id") else None
            emit([
                view.id, index, view.txn_date.isoformat(), view.type, _cell(account), _cell(counter),
                str(view.amount), str(split.amount), _cell((category or {}).get("name", "")),
                _cell((parent or {}).get("name", "")), _cell(view.merchant or ""), _cell(view.notes or ""),
                _cell(split.note or ""), _cell(tag_names),
            ])

    # Plaintext has just left the boundary: that is worth a line in the audit trail.
    audit_service.record(
        db, audit_service.EXPORT, user_id=cipher.user_id, entity="transactions", cipher=cipher,
        detail={"transactions": len(views), "rows": len(lines) - 1,
                "from": date_from.isoformat() if date_from else None, "to": date_to.isoformat() if date_to else None},
    )
    db.commit()
    return lines, len(views)


# ------------------------------------------------------------------ import


def preview(
    db: Session,
    cipher: UserCipher,
    text: str,
    *,
    mapping: Optional[Mapping[str, str]] = None,
    date_format: str = "YYYY-MM-DD",
) -> ImportPreview:
    headers, resolved, rows = _read(text, mapping or {})
    plans, issues = _plan(db, cipher, rows, resolved, date_format)
    _mark_duplicates(db, cipher, plans)
    duplicates = sum(1 for p in plans if p.duplicate)
    groups = len({row.get("txn_id") or f"line:{line}" for line, row in rows})
    return ImportPreview(
        rows=len(rows),
        transactions=groups,
        ready=len(plans) - duplicates,
        duplicates=duplicates,
        errors=issues,
        headers=headers,
        mapping=resolved,
        entries=[
            PlannedEntry(p.line, date.fromisoformat(p.payload["txn_date"]), p.payload["type"],
                         Decimal(p.payload["amount"]), p.account, p.payload.get("merchant"), p.duplicate)
            for p in plans[:PREVIEW_ENTRIES]
        ],
    )


def run_import(
    db: Session,
    cipher: UserCipher,
    text: str,
    *,
    mapping: Optional[Mapping[str, str]] = None,
    date_format: str = "YYYY-MM-DD",
    skip_duplicates: bool = True,
) -> ImportResult:
    _, resolved, rows = _read(text, mapping or {})
    plans, issues = _plan(db, cipher, rows, resolved, date_format)
    if issues:
        raise BusinessRuleException(
            f"{len(issues)} row{'s' if len(issues) != 1 else ''} {'have' if len(issues) != 1 else 'has'} "
            "problems - nothing was imported. Fix them and preview again.",
            extra={"errors": len(issues)},
        )
    _mark_duplicates(db, cipher, plans)
    chosen = [p for p in plans if not (skip_duplicates and p.duplicate)]
    created = transaction_service.import_entries(db, cipher, [p.payload for p in chosen]) if chosen else 0
    return ImportResult(created=created, skipped_duplicates=len(plans) - len(chosen))


# ---------------------------------------------------------------- internals


def _read(text: str, mapping: Mapping[str, str]) -> Tuple[List[str], Dict[str, str], List[Tuple[int, Dict[str, str]]]]:
    if len(text) > MAX_CSV_CHARS:
        raise ValidationException("A CSV to import is at most 5 MB")
    unknown = set(mapping) - set(COLUMNS)
    if unknown:
        raise ValidationException(f"Not a field this app imports: {', '.join(sorted(unknown))}")

    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        raise ValidationException("The file is empty") from None
    except csv.Error:
        raise ValidationException("That file is not a readable CSV") from None

    normalised: Dict[str, int] = {}
    for index, header in enumerate(headers):
        normalised.setdefault(_normal(header), index)
    positions: Dict[str, int] = {}
    for name in COLUMNS:
        chosen = mapping.get(name)
        if chosen:
            if chosen not in headers:
                raise ValidationException(f"There is no column called {chosen}")
            positions[name] = headers.index(chosen)
        elif _normal(name) in normalised:
            positions[name] = normalised[_normal(name)]
    missing = [name for name in REQUIRED if name not in positions]
    if missing:
        raise ValidationException(f"Choose the column that holds: {', '.join(missing)}")

    rows: List[Tuple[int, Dict[str, str]]] = []
    try:
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            rows.append((reader.line_num, {
                name: _uncell(cells[i]) if i < len(cells) else "" for name, i in positions.items()
            }))
            if len(rows) > MAX_ROWS:
                raise ValidationException(f"At most {MAX_ROWS} rows in one import")
    except csv.Error:
        raise ValidationException("That file is not a readable CSV") from None
    return headers, {name: headers[i] for name, i in positions.items()}, rows


def _plan(db, cipher, rows, resolved, date_format) -> Tuple[List[_Plan], List[Issue]]:
    if date_format not in DATE_FORMATS:
        raise ValidationException(f"date_format must be one of: {', '.join(DATE_FORMATS)}")
    accounts = {str(r.data.get("name", "")).casefold(): (r.id, str(r.data.get("name", "")))
                for r in AccountRepository(db, cipher).list()}
    categories = CategoryRepository(db, cipher).list()
    tags = {str(r.data.get("name", "")).casefold(): r.id for r in TagRepository(db, cipher).list()}

    groups: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
    for line, row in rows:
        groups.setdefault(row.get("txn_id") or f"line:{line}", []).append((line, row))

    plans: List[_Plan] = []
    issues: List[Issue] = []
    for members in groups.values():
        line, first = members[0]
        try:
            payload = _payload(first, members, accounts, categories, tags, date_format)
            transaction_service.validate_entry(db, cipher, payload)
        except (AppException, ValueError) as exc:
            issues.append(Issue(line, (getattr(exc, "detail", None) or str(exc))))
            continue
        account_name = next(name for cid, name in accounts.values() if cid == payload["account_id"])
        key = (payload["txn_date"], payload["type"], Decimal(payload["amount"]), payload["account_id"],
               (payload.get("merchant") or "").casefold())
        plans.append(_Plan(line, payload, key, account_name))
    return plans, issues


def _payload(first, members, accounts, categories, tags, date_format) -> Dict[str, Any]:
    for name in REQUIRED:
        if not first.get(name):
            raise ValueError(f"Missing {name}")
    when = _date(first["date"], date_format)
    signed = _money(first["amount"])
    kind = (first.get("type") or "").strip().lower()
    if kind == "adjustment":
        raise ValueError("Balance adjustments are not imported - set the account's balance instead")
    if not kind:
        kind = "expense" if signed < 0 else "income"
    if kind not in ("expense", "income", "transfer"):
        raise ValueError(f"Unknown type {first.get('type')}")
    amount = abs(signed)
    payload: Dict[str, Any] = {
        "type": kind, "txn_date": when.isoformat(), "amount": str(amount),
        "account_id": _account(accounts, first["account"]), "notes": first.get("notes") or None,
    }
    if kind == "transfer":
        payload["counter_account_id"] = _account(accounts, first.get("counter_account") or "")
        return payload

    payload["merchant"] = first.get("merchant") or None
    splits = []
    for _, row in members:
        raw = row.get("split_amount") or (row.get("amount") if len(members) == 1 else "")
        if not raw:
            raise ValueError("Each row of a split needs a split_amount")
        splits.append({
            "category_id": _category(categories, row.get("category") or "", row.get("parent_category") or "", kind),
            "amount": str(abs(_money(raw))),
            "note": row.get("split_note") or None,
        })
    payload["splits"] = splits
    names = [n.strip() for n in re.split(r"[;,]", first.get("tags") or "") if n.strip()]
    payload["tag_ids"] = []
    for name in names:
        if name.casefold() not in tags:
            raise ValueError(f"No tag called {name}")
        payload["tag_ids"].append(tags[name.casefold()])
    return payload


def _mark_duplicates(db: Session, cipher: UserCipher, plans: List[_Plan]) -> None:
    """DAT-05. Each existing transaction can stand for one row of the file - two identical coffees stay two."""
    existing: Counter = Counter()
    for view in transaction_service.views(db, cipher):
        if view.type == "transfer" and view.direction != "out":
            continue
        existing[(view.txn_date.isoformat(), view.type, view.amount, view.account_id,
                  (view.merchant or "").casefold())] += 1
    for plan in plans:
        if existing[plan.key] > 0:
            plan.duplicate = True
            existing[plan.key] -= 1


def _account(accounts, name: str) -> int:
    found = accounts.get(name.strip().casefold())
    if found is None:
        raise ValueError(f"No account called {name}" if name else "Missing account")
    return found[0]


def _category(records, name: str, parent: str, kind: str) -> int:
    if not name:
        raise ValueError("Missing category")
    by_id = {r.id: r.data for r in records}
    matches = [
        r.id for r in records
        if r.data.get("kind") == kind and str(r.data.get("name", "")).casefold() == name.casefold()
        and (not parent or str((by_id.get(r.data.get("parent_id")) or {}).get("name", "")).casefold() == parent.casefold())
    ]
    if not matches:
        where = f" under {parent}" if parent else ""
        raise ValueError(f"No {kind} category called {name}{where}")
    if len(matches) > 1:
        raise ValueError(f"More than one {kind} category is called {name} - add a parent_category column")
    return matches[0]


def _date(value: str, date_format: str) -> date:
    try:
        return datetime.strptime(value.strip(), DATE_FORMATS[date_format]).date()
    except ValueError:
        raise ValueError(f"Dates in this file should look like {date_format}") from None


def _money(value: str) -> Decimal:
    text = value.strip().replace("₱", "").replace(",", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    amount = money(text)  # ValueError for anything that is not an amount - never via float
    return -amount if negative else amount


def _name(records: Mapping[int, Mapping[str, Any]], record_id: Optional[int]) -> str:
    if record_id is None:
        return ""
    return str((records.get(record_id) or {}).get("name", ""))


def _cell(value: str) -> str:
    return f"'{value}" if value and value.startswith(FORMULA_START) else value


def _uncell(value: str) -> str:
    text = value.strip()
    return text[1:] if len(text) > 1 and text[0] == "'" and text[1] in FORMULA_START else text


def _normal(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.casefold())
