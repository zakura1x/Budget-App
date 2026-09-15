"""
budget_app_import_service - bring a backup from the "Budget" phone app into
this one (DAT-21, 2026-09-15).

That app exports one .xlsx (`_Manifest.format_id = com.budget.portable-xlsx`)
with a sheet per kind of thing. What becomes what:

    Accounts             account_type 0 -> credit card, 1 -> bank (debit);
                         "not in assets" -> savings, off cash on hand
    Categories +         categories and their sub-categories, archived ones
      Subcategories      archived again once their history is in
    Records              expense / income; a refund or reimbursement is income
                         in "Refunds"; a record with no account goes to one
                         "Unassigned (Budget App)" cash account
    AccountTransactions  transfer -> one transfer (its out leg); fee ->
                         expense in "Fees"; balance_adjustment -> NOT imported
    Loans + LoanRecords  one Lent / Borrowed account per person (ACC-31); a
                         record paid from or into an account is a transfer
                         with it; a record with no account only moves that
                         person's balance

TODAY'S BALANCES ARE TYPED, NOT DERIVED. That app's balance adjustments and
account-less loan records do not add up to its own balances under any one
rule (checked against its screens), so the history is imported as it is and
each account's opening balance is set so today's balance is exactly what the
user types - the same thing ACC-28's "fix the opening balance" does. A
person's loan is prefilled with what they still owe, which the file does get
right. Balance adjustments are never written: only a balance edit may create
one (ACC-29).

Preview writes nothing. The run creates missing accounts and categories
(matched by name, so a second import reuses them), writes every transaction
in one commit through transaction_service.import_entries - skipping what is
already recorded, as the CSV import does (DAT-05) - then sets the openings
and archives in one more commit.

The file is read in memory and never stored. It is untrusted XML inside a
zip: sizes are capped before anything is inflated, and a document carrying a
DOCTYPE (the doorway to entity expansion) is refused.
"""

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from sqlalchemy.orm import Session

from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import AppException, BusinessRuleException, ValidationException
from app.db.repositories.account_repository import AccountRepository
from app.db.repositories.category_repository import CategoryRepository
from app.services import account_service, audit_service, category_service, transaction_service

FORMAT_ID = "com.budget.portable-xlsx"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_ROWS = 50_000
NOTE_MAX = 280
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

UNASSIGNED_KEY = "unassigned"
UNASSIGNED_NAME = "Unassigned (Budget App)"
REFUNDS = "Refunds"
FEES = "Fees"
DEFAULT_ACCOUNT_COLOUR = "#4A90D9"
LOAN_COLOUR = "#C86FB0"
OWED_TYPES = ("credit", "borrowed")

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# A category's name, loosely, to one of this app's icons. Anything else is a tag.
_ICON_WORDS = (
    ("grocer", "cart"), ("food", "restaurant"), ("drink", "coffee"), ("coffee", "coffee"), ("car", "car"),
    ("transport", "car"), ("gas", "fuel"), ("fuel", "fuel"), ("travel", "plane"), ("shop", "bag"),
    ("health", "heart"), ("date", "heart"), ("bill", "bolt"), ("home", "home"), ("sport", "play"),
    ("salary", "wallet"), ("freelance", "briefcase"), ("invest", "chart"), ("trade", "chart"),
    ("self", "star"), ("gift", "gift"), ("pet", "pet"), ("phone", "phone"), ("school", "book"),
    ("cash", "cash"), ("fee", "ticket"), ("refund", "undo"),
)


class BudgetAppFormatError(ValidationException):
    code = "IMPORT_FILE_INVALID"
    title = "File Not Readable"


# ------------------------------------------------------------------ shapes


@dataclass
class _Account:
    key: str
    name: str
    type: str
    subtype: Optional[str]
    colour: str
    icon: str
    counts: bool
    credit: Dict[str, Any] = field(default_factory=dict)
    suggested: Optional[Decimal] = None  # a loan: what is still owed, as the user would type it
    archive_after: bool = False


@dataclass
class _Category:
    kind: str
    name: str
    parent: Optional[str]  # the parent's name, for a sub-category
    colour: str
    icon: str
    archive_after: bool = False

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.kind, (self.parent or "").casefold(), self.name.casefold())


@dataclass
class _Entry:
    txn_date: date
    type: str  # expense | income | transfer
    amount: Decimal
    account: str  # an _Account key
    counter: Optional[str] = None
    category: Optional[Tuple[str, str, str]] = None  # a _Category key
    notes: Optional[str] = None


@dataclass
class _Plan:
    exported_at: Optional[str]
    app_version: Optional[str]
    accounts: List[_Account]
    categories: List[_Category]
    entries: List[_Entry]
    adjustments_folded: int
    loan_records_folded: int
    unassigned: int
    skipped: int


@dataclass(frozen=True)
class PreviewAccount:
    key: str
    name: str
    type: str
    subtype: Optional[str]
    exists: bool
    history: Decimal  # what the imported history adds to the balance
    suggested: Optional[Decimal]
    owed: bool  # the balance is typed as an amount owed (a card, a loan)
    archived: bool
    transactions: int


@dataclass(frozen=True)
class BudgetAppPreview:
    exported_at: Optional[str]
    app_version: Optional[str]
    first_date: Optional[date]
    last_date: Optional[date]
    accounts: List[PreviewAccount]
    categories_new: int
    categories_existing: int
    transactions: int
    ready: int
    duplicates: int
    adjustments_folded: int
    loan_records_folded: int
    unassigned: int
    skipped: int


@dataclass(frozen=True)
class BudgetAppResult:
    accounts_created: int
    categories_created: int
    transactions: int
    skipped_duplicates: int
    archived: int


# ---------------------------------------------------------------- the file


def read_workbook(content: bytes) -> Dict[str, List[Dict[str, str]]]:
    """Every sheet as a list of {header: text}. Cells stay text; amounts become Decimal later, never float."""
    if len(content) > MAX_FILE_BYTES:
        raise BudgetAppFormatError(f"A file to import is at most {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise BudgetAppFormatError("That is not an Excel (.xlsx) file") from None
    with archive:
        infos = {info.filename: info for info in archive.infolist()}
        if sum(info.file_size for info in infos.values()) > MAX_UNCOMPRESSED_BYTES:
            raise BudgetAppFormatError("This file is too large to import")

        def parse(name: str) -> ET.Element:
            if name not in infos:
                raise BudgetAppFormatError("That is not a Budget App backup")
            data = archive.read(name)
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise BudgetAppFormatError("That file is not a plain spreadsheet")
            try:
                return ET.fromstring(data)
            except ET.ParseError:
                raise BudgetAppFormatError("That spreadsheet is damaged") from None

        shared: List[str] = []
        if "xl/sharedStrings.xml" in infos:
            for item in parse("xl/sharedStrings.xml").findall(f"{{{_MAIN}}}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{{{_MAIN}}}t")))

        targets = {rel.get("Id"): rel.get("Target") or "" for rel in parse("xl/_rels/workbook.xml.rels")}
        sheets_node = parse("xl/workbook.xml").find(f"{{{_MAIN}}}sheets")
        workbook: Dict[str, List[Dict[str, str]]] = {}
        for sheet in list(sheets_node) if sheets_node is not None else []:
            target = targets.get(sheet.get(f"{{{_REL}}}id"), "").lstrip("/")
            path = target if target.startswith("xl/") else f"xl/{target}"
            workbook[sheet.get("name", "")] = _rows(parse(path), shared)
    manifest = {row.get("key", ""): row.get("value", "") for row in workbook.get("_Manifest", [])}
    if manifest.get("format_id") != FORMAT_ID:
        raise BudgetAppFormatError("That is not a backup from the Budget app")
    return workbook


def _rows(root: ET.Element, shared: Sequence[str]) -> List[Dict[str, str]]:
    data = root.find(f"{{{_MAIN}}}sheetData")
    grid: List[List[str]] = []
    for row in data.findall(f"{{{_MAIN}}}row") if data is not None else []:
        values: Dict[int, str] = {}
        for cell in row.findall(f"{{{_MAIN}}}c"):
            kind = cell.get("t")
            value = cell.find(f"{{{_MAIN}}}v")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{{{_MAIN}}}t"))
            elif value is None or value.text is None:
                text = ""
            elif kind == "s":
                index = int(value.text)
                text = shared[index] if 0 <= index < len(shared) else ""
            else:
                text = value.text
            values[_column(cell.get("r", "A1"), len(values))] = text.strip()
        grid.append([values.get(i, "") for i in range(max(values) + 1)] if values else [])
        if len(grid) > MAX_ROWS:
            raise BudgetAppFormatError(f"At most {MAX_ROWS} rows in one sheet")
    if not grid:
        return []
    header = grid[0]
    return [dict(zip(header, cells + [""] * (len(header) - len(cells)))) for cells in grid[1:] if any(cells)]


def _column(reference: str, fallback: int) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        return fallback
    number = 0
    for char in letters.group(0):
        number = number * 26 + ord(char) - 64
    return number - 1


# ----------------------------------------------------------------- the plan


def build_plan(workbook: Mapping[str, List[Dict[str, str]]]) -> _Plan:
    """The file as this app's accounts, categories and entries - pure, no database."""
    manifest = {row.get("key", ""): row.get("value", "") for row in workbook.get("_Manifest", [])}

    accounts: Dict[str, _Account] = {}
    taken: set = set()
    for row in workbook.get("Accounts", []):
        key = row.get("source_uid", "")
        name = _name(row.get("name"), account_service.NAME_MAX)
        if not key or not name:
            continue
        if row.get("account_type") == "0":
            closing = _day(row.get("statement_day")) or 1
            due = _day(row.get("bill_day"))
            if due is None or due == closing:
                due = (closing + 13) % 28 + 1
            limit = _amount(row.get("credit_limit"))
            account = _Account(key, name, "credit", "credit-card", _colour(row.get("color_hex"), DEFAULT_ACCOUNT_COLOUR),
                               "credit-card", True, {"statement_closing_day": closing, "payment_due_day": due,
                                                     "credit_limit": str(limit) if limit and limit > 0 else None})
        elif row.get("in_assets") == "0":
            account = _Account(key, name, "savings", "savings", _colour(row.get("color_hex"), DEFAULT_ACCOUNT_COLOUR),
                               "piggy-bank", False)
        else:
            account = _Account(key, name, "debit", "bank", _colour(row.get("color_hex"), DEFAULT_ACCOUNT_COLOUR),
                               "bank", True)
        account.archive_after = row.get("status", "0") not in ("", "0")
        accounts[key] = account
        taken.add(name.casefold())

    categories: Dict[Tuple[str, str, str], _Category] = {}
    by_uid: Dict[str, _Category] = {}
    for row in workbook.get("Categories", []):
        name = _name(row.get("name"), category_service.NAME_MAX)
        if not name:
            continue
        category = _Category("income" if row.get("is_income") == "1" else "expense", name, None,
                             _colour(row.get("color_hex"), "#8E8E93"), _icon(name),
                             archive_after=row.get("status", "0") not in ("", "0"))
        categories.setdefault(category.key, category)
        by_uid[row.get("source_uid", "")] = categories[category.key]
    sub_by_uid: Dict[str, _Category] = {}
    for row in workbook.get("Subcategories", []):
        parent = by_uid.get(row.get("category_id", ""))
        name = _name(row.get("name"), category_service.NAME_MAX)
        if parent is None or not name:
            continue
        child = _Category(parent.kind, name, parent.name, parent.colour, parent.icon)
        categories.setdefault(child.key, child)
        sub_by_uid[row.get("source_uid", "")] = categories[child.key]

    def need(kind: str, name: str) -> Tuple[str, str, str]:
        category = categories.setdefault((kind, "", name.casefold()), _Category(kind, name, None, "#8E8E93", _icon(name)))
        return category.key

    def unassigned() -> str:
        if UNASSIGNED_KEY not in accounts:
            accounts[UNASSIGNED_KEY] = _Account(UNASSIGNED_KEY, UNASSIGNED_NAME, "cash", "cash", "#6E7B8B", "cash", False)
        return UNASSIGNED_KEY

    entries: List[_Entry] = []
    skipped = unassigned_count = 0

    for row in workbook.get("Records", []):
        amount = _amount(row.get("system_amount") or row.get("Price"))
        when = _local_date(row.get("Date"), row.get("occurred_at_utc"))
        kind = row.get("record_type", "")
        if amount is None or amount <= 0 or when is None or kind not in ("expense", "income", "refund", "reimbursement"):
            skipped += 1
            continue
        account = row.get("account_id", "")
        if account not in accounts:
            account = unassigned()
            unassigned_count += 1
        parent = by_uid.get(row.get("category_id", ""))
        child = sub_by_uid.get(row.get("subcategory_id", ""))
        note = row.get("note") or row.get("Note") or None
        if kind in ("refund", "reimbursement"):
            label = " › ".join(n for n in (parent.name if parent else row.get("Category"), child.name if child else None) if n)
            entries.append(_Entry(when, "income", amount, account, category=need("income", REFUNDS),
                                  notes=_note(f"{kind.capitalize()} · {label}" + (f" · {note}" if note else ""))))
            continue
        chosen = child or parent
        if chosen is None or chosen.kind != kind:
            chosen_key = need(kind, row.get("Category") or "Uncategorised")
        else:
            chosen_key = chosen.key
        entries.append(_Entry(when, kind, amount, account, category=chosen_key, notes=_note(note)))

    legs = {row.get("source_uid", ""): row for row in workbook.get("AccountTransactions", [])}
    adjustments = 0
    for row in legs.values():
        kind = row.get("entry_type", "")
        amount = _amount(row.get("system_amount") or row.get("Price"))
        when = _local_date(row.get("Date"), row.get("occurred_at_utc"))
        if kind == "balance_adjustment":
            adjustments += 1
            continue
        if amount is None or amount <= 0 or when is None:
            skipped += 1
            continue
        if kind == "transfer":
            if row.get("is_income") == "1":
                continue  # the in leg - its out leg carries the transfer
            source, target = row.get("account_id", ""), row.get("counterpart_account_id", "")
            if source not in accounts or target not in accounts or source == target:
                skipped += 1
                continue
            entries.append(_Entry(when, "transfer", amount, source, counter=target, notes=_note(row.get("note"))))
        elif kind == "fee":
            source = row.get("account_id", "")
            if source not in accounts:
                skipped += 1
                continue
            entries.append(_Entry(when, "expense", amount, source, category=need("expense", FEES),
                                  notes=_note(f"Fee · {row.get('From', '')} → {row.get('To', '')}")))
        else:
            skipped += 1

    folded = 0
    loan_rows = workbook.get("LoanRecords", [])
    for row in workbook.get("Loans", []):
        uid = row.get("source_uid", "")
        person = _name(row.get("Counterparty") or row.get("nick_name") or row.get("target"), account_service.NAME_MAX - 7)
        if not uid or not person:
            continue
        lent = row.get("loan_type") == "0"
        name = person if person.casefold() not in taken else f"{person} (loan)"
        taken.add(name.casefold())
        key = f"loan:{uid}"
        outstanding = _amount(row.get("amount")) or ZERO

        def move(increase: bool, amount: Decimal, account: str, when: date, note: Optional[str]) -> None:
            # Lent: more lent leaves your account; paid back comes into it. Borrowed: the other way round.
            out_of_account = increase == lent
            source, target = (account, key) if out_of_account else (key, account)
            entries.append(_Entry(when, "transfer", amount, source, counter=target, notes=_note(note)))

        opening_when = _local_date(row.get("Happening Date"), row.get("loan_date_utc"))
        if outstanding > 0 and row.get("account_id") in accounts and opening_when:
            move(True, outstanding, row["account_id"], opening_when, row.get("note"))
        for record in loan_rows:
            if record.get("loan_id") != uid:
                continue
            amount = _amount(record.get("amount"))
            when = _local_date(record.get("Date"), record.get("occurred_at_utc"))
            if amount is None or amount <= 0 or when is None:
                skipped += 1
                continue
            increase = record.get("Type") in ("Lend", "Borrow")
            outstanding += amount if increase else -amount
            if record.get("account_id") in accounts:
                move(increase, amount, record["account_id"], when, record.get("note"))
            else:
                folded += 1
        accounts[key] = _Account(key, name, "lent" if lent else "borrowed", "lent" if lent else "borrowed", LOAN_COLOUR,
                                 "hand-coin" if lent else "hand-owe", False, suggested=outstanding.quantize(CENT),
                                 archive_after=outstanding == 0)

    entries.sort(key=lambda e: (e.txn_date, e.type, e.amount))
    return _Plan(
        exported_at=manifest.get("exported_at_utc") or None,
        app_version=manifest.get("app_version") or None,
        accounts=list(accounts.values()),
        categories=sorted(categories.values(), key=lambda c: (c.parent is not None, c.kind, c.name.casefold())),
        entries=entries,
        adjustments_folded=adjustments,
        loan_records_folded=folded,
        unassigned=unassigned_count,
        skipped=skipped,
    )


def _history(plan: _Plan) -> Tuple[Dict[str, Decimal], Counter]:
    change: Dict[str, Decimal] = {a.key: ZERO for a in plan.accounts}
    count: Counter = Counter()
    for entry in plan.entries:
        sign = -1 if entry.type in ("expense", "transfer") else 1
        change[entry.account] += sign * entry.amount
        count[entry.account] += 1
        if entry.counter:
            change[entry.counter] += entry.amount
            count[entry.counter] += 1
    return change, count


# ----------------------------------------------------------------- preview


def preview(db: Session, cipher: UserCipher, content: bytes) -> BudgetAppPreview:
    plan = build_plan(read_workbook(content))
    existing_accounts = _existing_accounts(db, cipher)
    existing_categories = _existing_categories(db, cipher)
    change, count = _history(plan)

    account_ids = {a.key: existing_accounts.get(a.name.casefold()) for a in plan.accounts}
    category_ids = {c.key: existing_categories.get(c.key) for c in plan.categories}
    payloads = _payloads(plan, account_ids, category_ids)
    duplicates = _duplicates(db, cipher, payloads)
    dates = [e.txn_date for e in plan.entries]
    return BudgetAppPreview(
        exported_at=plan.exported_at,
        app_version=plan.app_version,
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        accounts=[
            PreviewAccount(a.key, a.name, a.type, a.subtype, account_ids[a.key] is not None, change[a.key].quantize(CENT),
                           a.suggested, a.type in OWED_TYPES, a.archive_after, count[a.key])
            for a in plan.accounts
        ],
        categories_new=sum(1 for v in category_ids.values() if v is None),
        categories_existing=sum(1 for v in category_ids.values() if v is not None),
        transactions=len(plan.entries),
        ready=len(plan.entries) - sum(duplicates),
        duplicates=sum(duplicates),
        adjustments_folded=plan.adjustments_folded,
        loan_records_folded=plan.loan_records_folded,
        unassigned=plan.unassigned,
        skipped=plan.skipped,
    )


# --------------------------------------------------------------------- run


def run_import(db: Session, cipher: UserCipher, content: bytes, balances: Mapping[str, Any]) -> BudgetAppResult:
    plan = build_plan(read_workbook(content))
    typed: Dict[str, Decimal] = {}
    missing = []
    for account in plan.accounts:
        value = _amount(balances.get(account.key)) if balances.get(account.key) is not None else None
        if value is None:
            missing.append(account.name)
        else:
            typed[account.key] = value
    if missing:
        raise ValidationException(f"Type today's balance for: {', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}")

    # 1. Categories, parents before sub-categories, then accounts - each matched by name first.
    existing_categories = _existing_categories(db, cipher)
    created_categories = 0
    for category in plan.categories:
        if existing_categories.get(category.key) is not None:
            continue
        parent_id = None
        if category.parent:
            parent_id = existing_categories.get((category.kind, "", category.parent.casefold()))
        view = category_service.create_category(db, cipher, {
            "name": category.name, "kind": category.kind, "parent_id": parent_id,
            "icon": category.icon, "colour": category.colour,
        })
        existing_categories[category.key] = view.id
        created_categories += 1

    existing_accounts = _existing_accounts(db, cipher)
    created_accounts = 0
    for account in plan.accounts:
        if existing_accounts.get(account.name.casefold()) is not None:
            continue
        view = account_service.create_account(db, cipher, {
            "name": account.name, "type": account.type, "subtype": account.subtype, "opening_balance": "0",
            "colour": account.colour, "icon": account.icon, "counts_in_cash_on_hand": account.counts, **account.credit,
        })
        existing_accounts[account.name.casefold()] = view.id
        created_accounts += 1

    # 2. What is already recorded is skipped; the rest is checked as the add sheet would, before any is written.
    account_ids = {a.key: existing_accounts[a.name.casefold()] for a in plan.accounts}
    category_ids = {c.key: existing_categories[c.key] for c in plan.categories}
    payloads = _payloads(plan, account_ids, category_ids)
    duplicates = _duplicates(db, cipher, payloads)
    chosen = [p for p, duplicate in zip(payloads, duplicates) if not duplicate]

    # History belongs to archived categories and settled loans too. An archived one is opened for the
    # import - in the same session, so validation sees it - and closed again in step 3.
    accounts_repo = AccountRepository(db, cipher)
    categories_repo = CategoryRepository(db, cipher)
    reopened_accounts, reopened_categories = set(), set()
    for payload in chosen:
        for account_id in (payload.get("account_id"), payload.get("counter_account_id")):
            record = accounts_repo.get(account_id) if account_id else None
            if record is not None and record.data.get("archived") and account_id not in reopened_accounts:
                accounts_repo.update(account_id, {**record.data, "archived": False})
                reopened_accounts.add(account_id)
        for split in payload.get("splits") or []:
            record = categories_repo.get(split["category_id"]) if split.get("category_id") else None
            if record is not None and record.data.get("archived") and record.id not in reopened_categories:
                categories_repo.update(record.id, {**record.data, "archived": False})
                reopened_categories.add(record.id)

    problems = []
    for payload in chosen:
        try:
            transaction_service.validate_entry(db, cipher, payload)
        except (AppException, ValueError) as exc:
            problems.append(f"{payload['txn_date']}: {getattr(exc, 'detail', None) or exc}")
    if problems:
        raise BusinessRuleException(
            f"{len(problems)} entr{'ies' if len(problems) != 1 else 'y'} could not be imported - nothing was. "
            f"First: {problems[0]}",
            extra={"errors": len(problems)},
        )
    if chosen:
        transaction_service.import_entries(db, cipher, chosen)

    # 3. Today's balances, through the opening balance (ACC-28 "fix the opening"), and the archiving.
    postings = transaction_service.postings(db, cipher)
    views = {v.id: v for v in account_service.list_accounts(db, cipher, postings=postings)}
    archived = 0
    for account in plan.accounts:
        account_id = account_ids[account.key]
        record = accounts_repo.get(account_id)
        view = views.get(account_id)
        if record is None or view is None:
            continue
        target = -typed[account.key] if view.type in OWED_TYPES else typed[account.key]
        data = dict(record.data)
        if view.type != "investment":
            data["opening_balance"] = str((Decimal(str(data.get("opening_balance", "0"))) + target - view.balance).quantize(CENT))
        if (account.archive_after or account_id in reopened_accounts) and not data.get("archived"):
            data["archived"] = True
            archived += account_id not in reopened_accounts
        if data != record.data:
            accounts_repo.update(account_id, data)
    to_archive = reopened_categories | {category_ids[c.key] for c in plan.categories if c.archive_after}
    for category_id in to_archive:
        record = categories_repo.get(category_id)
        if record is not None and not record.data.get("archived"):
            categories_repo.update(record.id, {**record.data, "archived": True})
            archived += category_id not in reopened_categories
    audit_service.record(
        db, audit_service.IMPORT, user_id=cipher.user_id, entity="budget_app", cipher=cipher,
        detail={"accounts_created": created_accounts, "categories_created": created_categories,
                "transactions": len(chosen), "skipped_duplicates": len(payloads) - len(chosen)},
    )
    db.commit()
    return BudgetAppResult(created_accounts, created_categories, len(chosen), len(payloads) - len(chosen), archived)


# ---------------------------------------------------------------- internals


def _payloads(plan: _Plan, account_ids: Mapping[str, Optional[int]],
              category_ids: Mapping[Tuple[str, str, str], Optional[int]]) -> List[Dict[str, Any]]:
    payloads = []
    for entry in plan.entries:
        payload: Dict[str, Any] = {
            "type": entry.type, "txn_date": entry.txn_date.isoformat(), "amount": str(entry.amount),
            "account_id": account_ids.get(entry.account), "notes": entry.notes,
        }
        if entry.type == "transfer":
            payload["counter_account_id"] = account_ids.get(entry.counter or "")
        else:
            payload["merchant"] = None
            payload["tag_ids"] = []
            payload["splits"] = [{"category_id": category_ids.get(entry.category) if entry.category else None,
                                  "amount": str(entry.amount), "note": None}]
        payloads.append(payload)
    return payloads


def _duplicates(db: Session, cipher: UserCipher, payloads: Sequence[Mapping[str, Any]]) -> List[bool]:
    """DAT-05, as the CSV import counts them: each recorded entry can stand for one row - two coffees stay two."""
    existing: Counter = Counter()
    for view in transaction_service.views(db, cipher):
        if view.type == "transfer" and view.direction != "out":
            continue
        existing[(view.txn_date.isoformat(), view.type, view.amount, view.account_id, view.counter_account_id
                  if view.type == "transfer" else None)] += 1
    flags = []
    for payload in payloads:
        if payload["account_id"] is None:
            flags.append(False)
            continue
        key = (payload["txn_date"], payload["type"], Decimal(payload["amount"]), payload["account_id"],
               payload.get("counter_account_id") if payload["type"] == "transfer" else None)
        if existing[key] > 0:
            existing[key] -= 1
            flags.append(True)
        else:
            flags.append(False)
    return flags


def _existing_accounts(db: Session, cipher: UserCipher) -> Dict[str, int]:
    return {str(r.data.get("name", "")).casefold(): r.id for r in AccountRepository(db, cipher).list()}


def _existing_categories(db: Session, cipher: UserCipher) -> Dict[Tuple[str, str, str], Optional[int]]:
    records = CategoryRepository(db, cipher).list()
    names = {r.id: str(r.data.get("name", "")) for r in records}
    found: Dict[Tuple[str, str, str], Optional[int]] = {}
    for record in records:
        parent = names.get(record.data.get("parent_id")) if record.data.get("parent_id") else ""
        found[(str(record.data.get("kind", "expense")), (parent or "").casefold(),
               str(record.data.get("name", "")).casefold())] = record.id
    return found


def _amount(value: Any) -> Optional[Decimal]:
    text = str(value if value is not None else "").strip().replace(",", "").replace("₱", "")
    if not text:
        return None
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)  # "257.0299999999988" -> 257.03, never via float
    except InvalidOperation:
        return None


def _local_date(shown: Optional[str], utc: Optional[str]) -> Optional[date]:
    """The date as the phone showed it - "2026-09-15" or "Sep 14, 2026 at 10:38" - else the UTC day."""
    text = (shown or "").strip()
    for pattern in ("%Y-%m-%d", "%b %d, %Y at %H:%M"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat((utc or "")[:10])
    except ValueError:
        return None


def _day(value: Any) -> Optional[int]:
    try:
        day = int(str(value or "").strip())
    except ValueError:
        return None
    return day if 1 <= day <= 31 else None


def _colour(value: Any, default: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", text) and text not in ("000000", "FFFFFF", "ffffff"):
        return f"#{text.upper()}"
    return default


def _icon(name: str) -> str:
    lowered = name.casefold()
    return next((icon for word, icon in _ICON_WORDS if word in lowered), "tag")


def _name(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _note(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text[:NOTE_MAX] or None
